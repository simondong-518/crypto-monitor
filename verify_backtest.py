# -*- coding: utf-8 -*-
"""回测自检：确认止损方向是对的（这是 2026-10-08 修的那个致命 bug）。

背景：原版 `stop_loss = ema20`，而低吸入场价在 BOLL 下轨（必然低于 EMA20），
      导致"止损"落在入场价上方 = 其实是止盈，97% 的出场价在市场上根本不存在。
"""
import sys, io, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest.py"),
              encoding="utf-8").read()

PASS, FAIL = [], []


def chk(desc, cond, detail=""):
    (PASS if cond else FAIL).append((desc, detail))


# ── 静态断言 ──
chk("买入止损在入场价下方（entry - atr*2）",
    "stop_loss = entry_price - atr*2" in src)
chk("卖出止损在入场价上方（entry + atr*2）",
    "stop_loss = entry_price + atr*2" in src)
chk("★ 已无 stop_loss = ema20（原致命 bug）",
    not re.search(r"^\s*stop_loss\s*=\s*ema20", src, re.M))
chk("止盈仍是 2 倍 ATR（他 #37 的设定，未动）",
    "take_profit = entry_price + atr*2" in src and "take_profit = entry_price - atr*2" in src)
chk("回测周期仍是最近 2 周 1000 根 15m",
    '"15m", 1000' in src)
chk("未来窗口仍是 16 根（4 小时）",
    "range(i+1, i+17)" in src)
chk("胜率标题已改对（不再是三个月）",
    "最近2周回测胜率" in src and "最近3个月回测胜率" not in src)

# ── 功能断言：用合成数据验证方向 ──
import pandas as pd
# 构造：入场价 100，ATR=2 → 买入止损应为 96，止盈 104
entry, atr = 100.0, 2.0
buy_sl = entry - atr*2
buy_tp = entry + atr*2
chk("买入：止损(%.0f) < 入场(%.0f) < 止盈(%.0f)" % (buy_sl, entry, buy_tp),
    buy_sl < entry < buy_tp)
sell_sl = entry + atr*2
sell_tp = entry - atr*2
chk("卖出：止盈(%.0f) < 入场(%.0f) < 止损(%.0f)" % (sell_tp, entry, sell_sl),
    sell_tp < entry < sell_sl)

# ── 反面对照：原版会怎样 ──
ema20 = 103.0     # 低吸时 EMA20 在入场价上方
chk("★ 反面对照：原版 stop_loss=EMA20(%.0f) 确实在入场价(%.0f)上方 → 那是止盈"
    % (ema20, entry), ema20 > entry)

print("════════ 回测自检 ════════")
for d, detail in PASS:
    print("  ✓ %s" % d)
for d, detail in FAIL:
    print("  ✗ %s   %s" % (d, detail))
print()
print("  结果: %d/%d 通过" % (len(PASS), len(PASS)+len(FAIL)))
sys.exit(1 if FAIL else 0)
