# -*- coding: utf-8 -*-
"""报警状态/冷却自检：`python verify_alerts.py`

为什么需要它：冷却与 key 的稳定性**只有在多轮之间才看得出来**。
一次运行全是"首次触发"，看着都对；错的是"第二轮该重报却没报"或
"因为 key 带了数字，同一个信号每轮都当新信号重报"。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from alert_state import AlertState, stable_alert_key, assert_stable_key   # noqa: E402

checks = []


def ck(name, ok, extra=""):
    checks.append((name, bool(ok), str(extra)))


tmp = os.path.join(tempfile.mkdtemp(), "alert_state.json")
st = AlertState(tmp, cooldown_min=30)

# ── 1) 首次必报 ──
ck("首次触发必报", st.should_report("SUI_主力大幅出") is True)
ck("首次原因显示'首次触发'", st.why("SUI_主力大幅出") == "首次触发")
st.mark("SUI_主力大幅出", now=1000.0)

# ── 2) 冷却期内不重报 ──
ck("冷却期内（5分钟）不重报", st.should_report("SUI_主力大幅出", now=1000 + 5 * 60) is False)
ck("冷却中原因带剩余时间", "冷却中" in st.why("SUI_主力大幅出", now=1000 + 5 * 60))

# ── 3) 冷却结束后重报，且**不设次数上限** ──
ck("30 分钟后重新上报", st.should_report("SUI_主力大幅出", now=1000 + 31 * 60) is True)
t = 1000.0
for i in range(50):                       # 连续推 50 次也不该哑掉
    st.mark("SUI_主力大幅出", now=t)
    t += 31 * 60
    if not st.should_report("SUI_主力大幅出", now=t):
        ck("第 %d 次后仍能上报（无次数上限）" % (i + 2), False)
        break
else:
    ck("连续 50 次后仍能上报（无次数上限）", True, "旧版 MAX_PUSH_PER_SIGNAL=3 会在这里哑掉")

# ── 4) key 必须值无关 ──
k1 = stable_alert_key("SUI", "🟢 1h资金净流入$15.5万，主力大幅进场")
k2 = stable_alert_key("SUI", "🟢 1h资金净流入$88.2万，主力大幅进场")
ck("金额变化不影响 key（冷却能命中）", k1 == k2, f"{k1} vs {k2}")
k3 = stable_alert_key("SUI", "今日大涨5.2%")
k4 = stable_alert_key("SUI", "今日大涨3.1%")
ck("涨跌幅变化不影响 key", k3 == k4, f"{k3} vs {k4}")
ck("不同含义的报警 key 不同", stable_alert_key("SUI", "主力大幅出") !=
   stable_alert_key("SUI", "缩量上涨"), "")
ck("生成的 key 不含数字/百分号", assert_stable_key(k1) and assert_stable_key(k3), f"{k1} / {k3}")
ck("旧实现会失败：拼接整串报警文本后数字一变就换 key",
   stable_alert_key("SUI", "🔴 主力大幅跑路") != stable_alert_key("SUI", "⚠️ 缩量上涨"), "")

# ── 5) 跨进程持久化 + 只保留当天 ──
# 注意：这里必须用**当前时间**当基准。用 1000（1970）当基准的话，重新加载后
# (now - 1000) 早就超过冷确期，should_report 返回 True 是正确的 —— 那是测试用例
# 构造得不对，不是代码错（本文件第一版就踩过，记下来避免以后又改错方向）。
now0 = time.time()
st.mark("SUI_持久化", now=now0)
st.save()
st2 = AlertState(tmp, cooldown_min=30)
ck("重新加载后：冷却内的不重复报（重启不会重发）",
   AlertState(tmp, cooldown_min=30).should_report("SUI_持久化") is False,
   f"now={now0}, fired={st2._fired}")
ck("重启后仍能被识别为'冷却中'", "冷却中" in st2.why("SUI_持久化"))
import json as _json
raw = _json.load(open(tmp, encoding="utf-8"))
ck("状态文件只保留当天（不会无限长大）", raw.get("_date") == time.strftime("%Y-%m-%d"))

print("=== 报警冷却自检 ===")
bad = 0
for name, ok, extra in checks:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{extra}]" if extra and not ok else ""))
    bad += (not ok)
print(f"\n结果: {len(checks) - bad}/{len(checks)} 通过")
sys.exit(1 if bad else 0)
