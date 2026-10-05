"""API Key 轮换 —— 用多个 key 分摊请求，规避单 key 限流。

背景
    现在一轮 6 个币打 50 次请求，60 秒一轮 ≈ 110 请求/分钟，
    对方反馈被 Gate 限流了。

思路
    申请 2~3 个 Gate API key，**轮换使用**。每个 key 各自有自己的限流额度，
    3 个 key 相当于额度×3，单 key 的压力降到 1/3。

    比"做缓存 / 自己撮合数据"简单得多，也不用改任何判定逻辑 ——
    只改"这次请求用哪个 key"，数据本身一个字都不变。

怎么用
    1. 去 Gate 申请 2~3 个 key（只读权限就够，本项目不下单）。
    2. 填进 config_local.py（**已被 .gitignore 排除，不会进仓库**）：

           GATE_API_KEYS = [
               ("key1...", "secret1..."),
               ("key2...", "secret2..."),
               ("key3...", "secret3..."),
           ]

       只填一个也可以 —— 那就退化成现在的行为，不影响运行。

    3. 什么都不用改，代码自动轮换。

★ 重要：为什么现在填了 key 也不会"更糟"
    目前所有请求打的都是 **公开接口**（spot/trades、candlesticks、
    futures/usdt/contract_stats），Gate 对公开接口按 **IP** 限流，key 帮不上忙。
    所以本模块的设计是：

      · 请求默认**不带签名**（和现在完全一样）；
      · 只有当你把某个端点标记为"需要签名"时（GATE_SIGNED_PATHS），
        才按该路径挑一个 key 签名 —— 这样你以后要接签名接口（或某个公开接口
        也开始认 key 配额）时，改配置就行，不用改代码；
      · 同时记录每个 key 的**用量与限流次数**，页面上能看到，
        这样你能判断"到底该申请几个 key"。

    （Gate 对**认证**请求的额度通常显著高于匿名，且按 key 计。
      等你 key 填进来、并且确认真实额度后，可以把需要的路径加进
      GATE_SIGNED_PATHS，额度立刻就分摊开了。）
"""
import hashlib
import hmac
import json
import threading
import time

_LOCK = threading.Lock()
_rr = {"idx": 0}                 # 轮询指针
_stats = {}                       # key 指纹 -> {"used": n, "throttled": n, "last": ts}


def _cfg(name, default):
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default


def keys():
    """读配置里的 key 列表。支持三种写法：

        GATE_API_KEYS = ["32位hexkey1", "32位hexkey2"]      # ★ Gate 新版 key（无 secret）
        GATE_API_KEYS = [("KEY","SECRET"), ...]              # 老式 key+secret
        GATE_API_KEYS = ["KEY:SECRET", ...]

    只填一对也完全没问题。

    ★ 关于 Gate 的两种 key（实测确认过）：
      · 32 位纯 hex（如 ddf4f609…）＝ **新版 key，没有独立的 secret**，
        签名时把 key 本身当 HMAC 的密钥用（Gate 的 APIv4 就是这么设计的）。
      · key + secret 两段式是老写法，也继续支持。
    """
    raw = _cfg("GATE_API_KEYS", []) or []
    out = []
    try:
        for it in raw:
            if isinstance(it, (list, tuple)) and len(it) >= 2:
                k, s = str(it[0]).strip(), str(it[1]).strip()
                if k:
                    out.append((k, s))
            elif isinstance(it, str) and it.strip():
                if ":" in it:
                    k, s = it.split(":", 1)
                    if k.strip():
                        out.append((k.strip(), s.strip()))
                else:
                    # 单段字符串 → 新版 key：secret 就是它自己
                    out.append((it.strip(), it.strip()))
    except Exception:
        pass
    return out


def count():
    return len(keys())


def enabled():
    """有 key 且允许用于签名，才算启用。"""
    return bool(_cfg("GATE_USE_KEYS", True)) and count() > 0


def _fingerprint(k):
    """key 的短指纹 —— 用于日志/页面显示，**绝不暴露 key 本身**。"""
    try:
        return hashlib.sha256(k.encode()).hexdigest()[:8]
    except Exception:
        return "????????"


def needs_sign(path):
    """该路径是否需要签名？由配置的 GATE_SIGNED_PATHS 决定。

    目前默认为空 —— 也就是**所有请求都走匿名**，和改造之前一模一样，
    不会因为填了 key 而突然开始签名（避免引入新变量）。
    """
    pats = _cfg("GATE_SIGNED_PATHS", []) or []
    p = str(path or "")
    for x in pats:
        if x and str(x) in p:
            return True
    return False


def pick(path):
    """按轮询挑一个 key（返回 (key, secret)）；没有 key 返回 (None, None)。

    轮询而不是随机：随机会让某个 key 偶然被连打，
    轮询能保证额度被均匀分摊 —— 这正是要的效果。
    """
    if not needs_sign(path):
        return None, None
    ks = keys()
    if not ks or not _cfg("GATE_USE_KEYS", True):
        return None, None
    with _LOCK:
        i = _rr["idx"] % len(ks)
        _rr["idx"] = (i + 1) % max(len(ks), 1)
    return ks[i]


def sign_headers(path, query="", body="", key=None, secret=None):
    """生成 Gate 要求的签名头。

    Gate v4 签名 = HMAC-SHA512(secret, f"{method}\\n{path}\\n{query}\\n{sha512(body)}\\n{ts}")
    时间戳单位是**秒**（13 位是毫秒，Gate 用秒）。
    """
    if key is None or secret is None:
        key, secret = pick(path)
    if not key or not secret:
        return {}
    ts = str(int(time.time()))
    body_hash = hashlib.sha512((body or "").encode()).hexdigest()
    msg = f"GET\n{path}\n{query or ''}\n{body_hash}\n{ts}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha512).hexdigest()
    return {"KEY": key, "Timestamp": ts, "SIGN": sig}


def note_use(path, key=None, throttled=False):
    """记一次用量（只统计，不参与逻辑）。key=None 表示匿名请求。"""
    fp = _fingerprint(key) if key else "anonymous"
    with _LOCK:
        st = _stats.setdefault(fp, {"used": 0, "throttled": 0, "last": None})
        st["used"] += 1
        st["last"] = time.strftime("%H:%M:%S")
        if throttled:
            st["throttled"] += 1


def stats():
    """给页面/自检看的用量摘要（**只有指纹，没有 key**）。"""
    with _LOCK:
        return {k: dict(v) for k, v in _stats.items()}


def status():
    """一句话状态，给日志和页面用。"""
    n = count()
    if n == 0:
        return "未配置 key（匿名请求；如需分摊限流请填 GATE_API_KEYS）"
    signed = _cfg("GATE_SIGNED_PATHS", []) or []
    tail = ("签名路径: " + ", ".join(map(str, signed))) if signed else \
           "签名路径未启用（当前全部匿名，填 GATE_SIGNED_PATHS 后按 key 分摊额度）"
    return f"已配置 {n} 个 key，轮换启用；{tail}"
