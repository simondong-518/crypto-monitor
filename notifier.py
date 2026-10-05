import requests
import time
import json
import os

# ==============================================
# 推送通道：飞书为主，**失败必须看得见**，且不依赖网络的通道永远兜底
#
# 为什么要这么改（原来三个问题）：
#   1) requests.post(...) 不看返回值 → 飞书返回 code!=0（限流/被拒）时也算成功，
#      pushed.json 的计数照 +1 → 报警永久丢失且没人知道
#   2) 只有一条通道 → 飞书一挂，报警全丢
#   3) webhook 明文写在代码里 → 已公开，请务必重置并从环境变量/本地配置读
# ==============================================

# 飞书机器人 webhook：优先读环境变量，其次 config_local.py（不进仓库），最后才是这里的默认空值
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
try:
    from config_local import FEISHU_WEBHOOK as _FW   # 本机私有配置（.gitignore 里已排除）
    if _FW:
        FEISHU_WEBHOOK = _FW
except Exception:
    pass

NOTIFY_FILE = os.environ.get("NOTIFY_FILE", "alerts.log")   # 本地留痕，永远可用
NOTIFY_CONSOLE = True                                        # 控制台提示，永远可用


def _feishu(title, desp):
    """返回 (是否成功, 原因)。成功判据 = HTTP 200 且返回体 code == 0。"""
    if not FEISHU_WEBHOOK:
        return False, "未配置 FEISHU_WEBHOOK（环境变量或 config_local.py）"
    data = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": [[{"tag": "text", "text": desp}]]
                }
            }
        }
    }
    last = ""
    for attempt in (1, 2):
        try:
            r = requests.post(FEISHU_WEBHOOK, json=data, timeout=10)
            body = {}
            try:
                body = r.json()
            except Exception:
                body = {}
            code = body.get("code", body.get("StatusCode", None))
            if r.status_code == 200 and code in (0, None):
                return True, "ok"
            last = f"HTTP {r.status_code} code={code} msg={body.get('msg', r.text[:120])}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(1)
    return False, last


def send_wx(title, desp):
    """所有通道都试一遍；**只要有一条成功就算送达**，失败原因全部打印出来。

    ★ 全局推送开关（push_switch）：
      关闭时 **只**跳过"对外通道"（飞书/钉钉等），
      控制台与 alerts.log 文件留痕**照常** —— 这样关着的时候报了什么，
      事后翻文件还能看到，不会凭空丢失。
      开关是服务端状态，所有浏览器/手机共享同一个（与折叠记忆不同）。
    """
    from push_switch import is_enabled as _push_on, get_state as _push_state

    results = []
    push_on = True
    try:
        push_on = _push_on()
    except Exception as e:
        # 开关读不出来时**按"停"处理**（安全方向），并如实说明
        push_on = False
        results.append(("开关", False, f"读取失败，按停止处理：{type(e).__name__}: {e}"))

    # 1) 控制台（不依赖网络）—— 不受开关影响
    if NOTIFY_CONSOLE:
        print(f"[通知] {title}\n{desp}", flush=True)
        results.append(("控制台", True, "ok"))

    # 2) 文件留痕（不依赖网络）—— 不受开关影响
    try:
        with open(NOTIFY_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n{title}\n{desp}\n")
        results.append(("文件", True, NOTIFY_FILE))
    except Exception as e:
        results.append(("文件", False, f"{type(e).__name__}: {e}"))

    # 3) 对外通道 —— 开关关闭时跳过
    if not push_on:
        st = {}
        try:
            st = _push_state()
        except Exception:
            pass
        why = f"推送开关已停止（{st.get('changed_at') or '默认'}）"
        if NOTIFY_CONSOLE:
            print(f"[通知] ⏸ {why} —— 仅记入 {NOTIFY_FILE}，未发飞书", flush=True)
        try:
            bump_suppressed()
        except Exception:
            pass
        return any(ok for _n, ok, _w in results)

    ok, why = _feishu(title, desp)
    results.append(("飞书", ok, why))

    for name, ok, why in results:
        flag = "✅" if ok else "❌"
        print(f"[通知] {flag} {name}: {why}", flush=True)

    if not any(ok for _n, ok, _w in results):
        print("[通知] ⚠️ 所有通道都失败了 —— 报警已写入文件，但没人收到", flush=True)
    return any(ok for _n, ok, _w in results)


def beep():
    """Windows 才有 winsound；其它平台静默跳过（原来会让程序 NameError/报错）。"""
    try:
        import winsound
        for i in range(3):
            winsound.Beep(1000 + i * 200, 300)
    except Exception:
        pass


# ── 被开关拦下的报警计数（仅用于页面提示"关着的时候有几条没发出去"）──
_SUPPRESSED = {"n": 0, "since": None}

def bump_suppressed():
    if _SUPPRESSED["since"] is None:
        _SUPPRESSED["since"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _SUPPRESSED["n"] += 1

def suppressed_count():
    return dict(_SUPPRESSED)

def reset_suppressed():
    _SUPPRESSED["n"] = 0
    _SUPPRESSED["since"] = None


# ============================================================
# 通道清单：给面板/自检用。
# **只返回名字与"是否启用"，绝不含 webhook / key 等任何值。**
# ============================================================
def get_channels():
    """返回当前可用通道（名字 + 是否启用）。顺序即实际发送顺序。

    注意 `enabled` 的含义是"**配置可用**"，不代表现在真的会发 ——
    真发不发由全局推送开关决定（见 push_switch）。
    页面要同时显示"配置可用"和"开关状态"，两者独立。
    """
    import os as _os
    fw = FEISHU_WEBHOOK or _os.environ.get("FEISHU_WEBHOOK", "")
    return [
        {"name": "控制台", "enabled": True},
        {"name": "文件留痕", "enabled": bool(NOTIFY_FILE)},
        {"name": "飞书", "enabled": bool(fw)},
    ]


def key_usage():
    """API key 轮换的用量摘要（**只有指纹，绝不含 key 原文**）。"""
    try:
        import gate_keys
        return {"n": gate_keys.count(),
                "status": gate_keys.status(),
                "stats": gate_keys.stats()}
    except Exception as e:
        return {"n": 0, "status": f"不可用：{type(e).__name__}", "stats": {}}
