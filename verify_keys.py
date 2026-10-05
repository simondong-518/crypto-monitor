"""API Key 轮换自检。

用法： <解释器> verify_keys.py
"""
import sys, os, hashlib, hmac
sys.path.insert(0, r'M:\hermes\workspace\dev\crypto-monitor-v3')
os.chdir(r'M:\hermes\workspace\dev\crypto-monitor-v3')

import config, gate_keys

results = []
def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))

# ── 1) 没填 key 时：行为必须和以前完全一样 ──────────────────
config.GATE_API_KEYS = []
config.GATE_SIGNED_PATHS = []
check("没填 key 时不启用轮换", gate_keys.count() == 0)
check("没填 key 时 pick() 返回空（= 匿名请求）",
      gate_keys.pick("spot/trades") == (None, None))
check("没填 key 时不产生任何签名头",
      gate_keys.sign_headers("spot/trades") == {})

# ── 2) 填了 key 但没标记签名路径 → 仍然匿名（行为不变）───────
config.GATE_API_KEYS = [("k1", "s1"), ("k2", "s2"), ("k3", "s3")]
config.GATE_SIGNED_PATHS = []
check("填了 key 但未标记签名路径时，仍是匿名",
      gate_keys.pick("spot/trades") == (None, None))

# ── 3) 标记了签名路径 → 按 key 轮换 ─────────────────────────
config.GATE_SIGNED_PATHS = ["spot/trades"]
picked = [gate_keys.pick("spot/trades")[0] for _ in range(6)]
check("按路径启用后返回 key", all(picked), str(picked))
check("★ 轮换均匀（3 个 key 转 6 次 = 每个 2 次）",
      picked.count("k1") == 2 and picked.count("k2") == 2 and picked.count("k3") == 2,
      str(picked))
check("轮换是循环的（第 1 次 == 第 4 次）", picked[0] == picked[3], str(picked))
check("未标记的路径仍匿名（只分摊指定路径）",
      gate_keys.pick("spot/candlesticks") == (None, None))

# ── 4) 签名头格式（Gate v4）─────────────────────────────────
config.GATE_SIGNED_PATHS = []
h = gate_keys.sign_headers("spot/trades", key="k1", secret="s1")
check("签名头含 KEY / Timestamp / SIGN",
      all(k in h for k in ("KEY", "Timestamp", "SIGN")), str(sorted(h)))
check("Timestamp 是秒（10 位）", len(h["Timestamp"]) == 10, h["Timestamp"])
check("SIGN 是 HMAC-SHA512（128 hex）",
      len(h["SIGN"]) == 128 and all(c in "0123456789abcdef" for c in h["SIGN"]),
      f"len={len(h['SIGN'])}")
check("★ 签名头里不含 secret", "s1" not in str(h.values()), str(h))

# 手工复算一遍，确认签名算法正确
ts = h["Timestamp"]
body_hash = hashlib.sha512(b"").hexdigest()
msg = f"GET\nspot/trades\n\n{body_hash}\n{ts}"
want = hmac.new(b"s1", msg.encode(), hashlib.sha512).hexdigest()
check("签名可被独立复算（算法一致）", want == h["SIGN"])

# ── 5) 一个 key 也能用（退化为单一）─────────────────────────
config.GATE_API_KEYS = [("only1", "sec1")]
config.GATE_SIGNED_PATHS = ["spot/trades"]
ones = [gate_keys.pick("spot/trades")[0] for _ in range(4)]
check("只填 1 个 key 时正常工作（不影响运行）", set(ones) == {"only1"}, str(ones))

# ── 6) 两种写法都支持 ───────────────────────────────────────
config.GATE_API_KEYS = ["a:aa", "b:bb"]
check("支持 \"KEY:SECRET\" 字符串写法", gate_keys.count() == 2, str(gate_keys.keys()))
config.GATE_API_KEYS = [("a", "aa"), "b:bb"]
check("支持元组与字符串混写", gate_keys.count() == 2)

# ── 7) 指纹不泄露 key ───────────────────────────────────────
config.GATE_API_KEYS = [("MYSUPERSECRETKEY", "zz")]
fp = gate_keys._fingerprint("MYSUPERSECRETKEY")
check("★ 指纹不含原文（日志/页面安全）",
      "MYSUPERSECRETKEY" not in fp and len(fp) == 8, fp)

# ── 8) 用量统计只记指纹 ─────────────────────────────────────
config.GATE_API_KEYS = [("k1", "s1")]
gate_keys.note_use("spot/trades", key="k1")
gate_keys.note_use("spot/trades", key=None)
gate_keys.note_use("spot/trades", key="k1", throttled=True)
st = gate_keys.stats()
keyed = [k for k in st if k != "anonymous"]
check("统计里有匿名与按 key 两类", "anonymous" in st and keyed, str(list(st.keys())))
check("★ 统计里没有 key 原文",
      not any("k1" == k for k in st), str(list(st.keys())))
check("限流次数被记下", st[keyed[0]]["throttled"] == 1, str(st[keyed[0]]))

# ── 输出 ────────────────────────────────────────────────────
print()
n_fail = 0
for n, o, d in results:
    if not o:
        n_fail += 1
    print(f"  {'PASS' if o else 'FAIL'}  {n}" + (f"   [{d}]" if (d and not o) else ""))
print()
print(f"  结果: {len(results)-n_fail}/{len(results)} 通过")
print()
print("  当前配置:", gate_keys.status())
sys.exit(1 if n_fail else 0)
