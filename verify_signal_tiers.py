# -*- coding: utf-8 -*-
"""信号分级自检 —— 验证 main._is_report_signal 与用户 2026-10-07 定的规格一致。

规格：
  ▸ 带完整全方位分析报告（8 类）：移动止盈 / ≥30分预警 / ≥90分最佳点 /
    V反·见顶回落 / BOLL真破轨 / 缩量慢涨慢跌 / 大级别资金 / 真高·真底
  ▸ 只推一句话（6 类）：30分钟急涨急跌 / 变盘点转多转空 / 大反弹大回撤 /
    大户极端多空比 / 板块联动 / 币种小级别新闻快讯

用法： python verify_signal_tiers.py
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main

# 注意：main.py L5 已经把 sys.stdout 重包成 utf-8 了。
# 这里**不要再包一次** —— 再包会让 main 那层包装失去引用被 GC，
# 而 TextIOWrapper.__del__ 会关掉底层 buffer，导致后续 print 报
# "I/O operation on closed file"。

PASS, FAIL = [], []


def chk(desc, text, want):
    got = main._is_report_signal(text)
    (PASS if got == want else FAIL).append((desc, text, want, got))


# ══════ 一、带完整报告（8 类）══════
chk("① 移动止盈落袋", "⚠️ 从高点回撤3.2%（动态阈值2.8%），移动止盈落袋", True)
chk("② 紧急低吸预警", "⚡ 紧急低吸预警，45/60分，满足：RSI超卖、BOLL下轨，反弹在即", True)
chk("② 紧急高抛预警", "⚠️ 紧急高抛预警，40/60分，满足：RSI超买，回调在即", True)
chk("② 低吸预警(≥30)", "🟡 低吸预警，买入分35/110，开始关注，满足：KDJ超卖", True)
chk("② 高抛预警(≥30)", "🟡 高抛预警，卖出分38/110，开始关注，满足：RSI超买", True)
chk("③ 最佳低吸点(≥90)", "✅ 最佳低吸点，买入分95/110，满足：…，可建仓", True)
chk("③ 最佳高抛点(≥90)", "⚠️ 最佳高抛点，卖出分92/110，满足：…，可止盈", True)
chk("④ V型反弹", "🟢 V型反弹，先急跌后资金进场，从30分钟低点反弹2.1%，短线反弹机会", True)
chk("④ 见顶回落", "🔴 见顶回落，先急涨后资金流出，从30分钟高点下跌1.8%，短线注意风险", True)
chk("⑤ BOLL真突破上轨", "✅ 连续2根K线放量突破BOLL上轨0.1234，真突破可以追多", True)
chk("⑤ BOLL真跌破下轨", "🟢 连续2根K线跌破BOLL下轨0.1000，真跌破超卖低吸机会", True)
chk("⑥ 缩量慢涨启动", "🟢 缩量慢涨启动，连续2根小阳+缩量，主力悄悄吸筹，后续看涨", True)
chk("⑥ 缩量慢跌开始", "🔴 缩量慢跌开始，连续2根小阴+缩量，主力悄悄出货，后续看跌", True)
chk("⑦ 大级别资金流入", "🟢 1h资金大幅流入$35.2万，15分钟持续进场，主力真金白银买入", True)
chk("⑦ 大级别资金流出", "🔴 1h资金大幅流出$12.0万，15分钟持续跑路，主力真金白银卖出", True)
chk("⑧ 真高提醒", "🔴 触及当日真高，主力出货，注意止盈落袋", True)
chk("⑧ 真底提醒", "🟢 触及当日真底，主力接盘，关注买入机会", True)

# ══════ 二、只推一句话（6 类）══════
chk("· 30分钟急涨", "⚡ 30分钟急涨2.4%，注意追高风险", False)
chk("· 30分钟急跌", "⚡ 30分钟急跌2.1%，注意恐慌割肉", False)
chk("· 变盘点趋势转多", "🟢 从30分钟变盘点反弹1.7%，趋势转多", False)
chk("· 变盘点趋势转空", "🔴 从30分钟变盘点回撤1.9%，趋势转空", False)
chk("· 大户极端看多", "🟢 大户多空比1.95，极端看多", False)
chk("· 大户极端看空", "🔴 大户多空比0.55，极端看空", False)
chk("· 板块联动", "- 🌐 AI板块联动下跌：SUI/WLD/CYS中3个跌超1%，板块回调注意风险", False)

# ══════ 三、不得误判的回归用例 ══════
# 旧代码用 '止盈' 当关键词 → "跌破MA20，止盈落袋" 被误判成重要信号（实际是小信号）
chk("回归·跌破MA20止盈落袋(应非报告)", "⚠️ 跌破MA20，止盈落袋", False)
# 旧代码 '高抛'/'买入' 等模糊词会误命中这些普通文案
chk("回归·缩量上涨别追高(应非报告)", "⚠️ 缩量上涨，别追高", False)
chk("回归·1h资金净流入(小信号版,应非报告)", "🟢 1h资金净流入$12.3万，主力大幅进场", False)
chk("回归·1h累计流出(应非报告)", "⚠️ 1h累计流出$52.0万，持续跑路，注意风险", False)
chk("回归·假突破上轨(应非报告)", "⚠️ 假突破上轨跌回，别追多", False)
chk("回归·假跌破下轨(应非报告)", "🟢 假跌破下轨涨回，别恐慌割肉", False)
chk("回归·BOLL三轨开口向上(应非报告)", "📈 BOLL三轨开口向上，慢牛趋势，可持有（100/100，15m+1h 双周期共振）", False)
chk("回归·KDJ超买(应非报告)", "⚠️ KDJ J值105超买，短线别追高", False)
chk("回归·RSI超卖长下影(应非报告)", "🟢 RSI超卖+第一根长下影，超卖低吸机会", False)
chk("回归·EMA金叉(应非报告)", "🟢 EMA金叉，短线多头启动", False)
chk("回归·突破前高(应非报告)", "🚀 突破前高0.5%，正在创新高", False)

# ══════ 四、用真实代码里的文案全量回归 ══════
import re
_here = os.path.dirname(os.path.abspath(__file__))
SRC_FILES = ["main.py", "signals.py", "report.py", "pushing.py", "alerting.py"]
src = ""
for _f in SRC_FILES:
    try:
        src += io.open(os.path.join(_here, _f), encoding="utf-8").read() + "\n"
    except OSError:
        pass
texts = re.findall(r'alerts\.append\(f?"([^"]{4,120})', src)
# 去掉 f-string 占位符，留文字骨架
cleaned = sorted({re.sub(r"\{[^}]*\}", "X", t) for t in texts})
n_report = sum(1 for t in cleaned if main._is_report_signal(t))
print("════════ 真实代码文案全量扫描 ════════")
print("  alerts.append 文案种类: %d（去重后）" % len(cleaned))
print("  其中判定为『带完整报告』: %d" % n_report)
print()
print("  ▸ 带报告的：")
for t in cleaned:
    if main._is_report_signal(t):
        print("      %s" % t[:66])
print()
print("  ▸ 只推一句话的：")
for t in cleaned:
    if not main._is_report_signal(t):
        print("      %s" % t[:66])
print()

# ══════ 五、静态断言：接线必须一直在 ══════
print("════════ 静态断言 ════════")
_static = []


def sassert(desc, cond):
    _static.append((desc, bool(cond)))


sassert("_is_report_signal 已定义", "def _is_report_signal(" in src)
sassert("_REPORT_KEYWORDS 已定义", "_REPORT_KEYWORDS = (" in src)
sassert("has_important 用 _is_report_signal",
        "has_important = any(_is_report_signal(x) for x in alerts)" in src)
sassert("旧的模糊关键词表已移除",
        "'急跌V反' in x" not in src and "'超卖下轨' in x" not in src)
sassert("keep_alerts 分流存在",
        "keep_alerts  = [x for x in alerts if _is_report_signal(x)]" in src)
sassert("报告级信号 clear 后放回推送队列",
        "alerts.extend(keep_alerts)" in src)
sassert("小信号开关仍在（未被动过）",
        "small_signal_switch" in src)
sassert("小信号=非报告级",
        "small_alerts = [x for x in alerts if not _is_report_signal(x)]" in src)

for d, ok in _static:
    print("  %s %s" % ("✓" if ok else "✗", d))
_static_fail = [d for d, ok in _static if not ok]
print()

# ══════ 六、分流行为测试（模拟 monitor_once 的 clear 前后）══════
print("════════ 分流行为测试 ════════")
_flow = []


def fchk(desc, cond):
    _flow.append((desc, bool(cond)))


# 模拟一个币这一轮产生的报警（混合报告级 + 小信号）
_round_alerts = [
    "🔴 触及当日真高，主力出货，注意止盈落袋",              # ⑧ 报告级
    "✅ 连续2根K线放量突破BOLL上轨0.12，真突破可以追多",     # ⑤ 报告级
    "⚠️ 从高点回撤3.1%（动态阈值2.6%），移动止盈落袋",       # ① 报告级
    "📈 BOLL三轨开口向上，慢牛趋势，可持有（100/100）",       # 小信号
    "⚠️ 缩量上涨，别追高",                                  # 小信号
    "⚠️ KDJ J值105超买，短线别追高",                        # 小信号
]
keep = [x for x in _round_alerts if main._is_report_signal(x)]
small = [x for x in _round_alerts if not main._is_report_signal(x)]
fchk("报告级信号被留住 = 3 条", len(keep) == 3)
fchk("小信号 = 3 条", len(small) == 3)
fchk("真高进了报告级", any("真高" in x for x in keep))
fchk("BOLL真突破进了报告级", any("真突破" in x for x in keep))
fchk("移动止盈进了报告级", any("移动止盈" in x for x in keep))
fchk("BOLL三轨开口没进报告级", not any("三轨开口" in x for x in keep))
fchk("KDJ超买没进报告级", not any("KDJ" in x for x in keep))
fchk("两类无重叠", not (set(keep) & set(small)))
fchk("两类合起来 = 原始", sorted(keep + small) == sorted(_round_alerts))

# 强单信号（一句话那批）不应进报告
_strong = [
    "⚡ 30分钟急涨2.4%，注意追高风险",
    "🟢 大户多空比1.95，极端看多",
    "🟢 从30分钟变盘点反弹1.7%，趋势转多",
]
fchk("强单信号全部不进详细报告", not any(main._is_report_signal(x) for x in _strong))

for d, ok in _flow:
    print("  %s %s" % ("✓" if ok else "✗", d))
_flow_fail = [d for d, ok in _flow if not ok]
print()

print("════════ 断言结果 ════════")
for d, t, w, g in FAIL:
    print("  ✗ %-34s 期望=%s 实际=%s  ← %s" % (d, w, g, t[:44]))
for d in _static_fail:
    print("  ✗ 静态断言失败: %s" % d)
for d in _flow_fail:
    print("  ✗ 分流测试失败: %s" % d)
total = len(PASS) + len(FAIL) + len(_static) + len(_flow)
npass = len(PASS) + (len(_static) - len(_static_fail)) + (len(_flow) - len(_flow_fail))
print("  结果: %d/%d 通过" % (npass, total))
sys.exit(1 if (FAIL or _static_fail or _flow_fail) else 0)
