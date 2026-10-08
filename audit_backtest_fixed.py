# -*- coding: utf-8 -*-
"""回测修复对比：把止损放对方向后，真实胜率是多少？

方案：
  V0 原版（bug）      止损 = EMA20（在入场价上方，其实是止盈）
  V1 止损 = entry - 2*ATR   （和止盈对称）
  V2 止损 = entry - 1.5*ATR
  V3 止损 = entry - 1*ATR
  V4 不设止盈止损，4小时后收盘平仓（最诚实）
  V5 额外要求入场价 > EMA20（这样"止损=EMA20"才讲得通）
"""
import sys, os
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

import pandas as pd
from api import get_kline
from indicators import calc_rsi, calc_boll
from config import CURRENCY_PAIRS, FEE_RATE

FEE = FEE_RATE * 2


def run(stop_mult, tp_mult, require_above_ema=False, raw_only=False):
    """返回 (总笔数, 胜, 收益总和%)"""
    n = w = 0
    tot = 0.0
    for pair in CURRENCY_PAIRS:
        data = get_kline(pair, "15m", 1000)
        if len(data) < 200: continue
        df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
        for c in ['close','high','low','open','vol']:
            df[c] = df[c].astype(float)

        for i in range(50, len(df)-16):
            win_ = df.iloc[:i+1]; close = win_['close']; price = close.iloc[-1]
            bm, bu, bl = calc_boll(close)
            rsi = calc_rsi(close).iloc[-1]
            tr = pd.concat([win_['high']-win_['low'],
                            (win_['high']-close.shift()).abs(),
                            (win_['low']-close.shift()).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            ema20 = close.ewm(span=20).mean().iloc[-1]

            buy = (price <= bl.iloc[-1]*1.005) and (rsi < 30)
            sell = (price >= bu.iloc[-1]*0.995) and (rsi > 70)
            if require_above_ema:
                buy = buy and (price > ema20)
                sell = sell and (price < ema20)

            if not (buy or sell): continue
            entry = price
            n += 1
            if raw_only:
                ex = df.iloc[i+16]['close']
                p = ((ex-entry)/entry if buy else (entry-ex)/entry) - FEE
            else:
                tp = entry + tp_mult*atr if buy else entry - tp_mult*atr
                sl = entry - stop_mult*atr if buy else entry + stop_mult*atr
                ex = df.iloc[i+16]['close']
                for j in range(i+1, i+17):
                    hi, lo = df.iloc[j]['high'], df.iloc[j]['low']
                    if buy:
                        if hi >= tp: ex = tp; break
                        if lo <= sl: ex = sl; break
                    else:
                        if lo <= tp: ex = tp; break
                        if hi >= sl: ex = sl; break
                p = ((ex-entry)/entry if buy else (entry-ex)/entry) - FEE
            tot += p
            if p > 0: w += 1
    return n, w, tot*100


print("═══ 回测修复对比（最近 2 周 15m K线，6 币合计）═══")
print("    手续费往返 %.2f%%" % (FEE*100))
print()
print("  %-46s %6s %8s %10s %12s" % ("方案", "笔数", "胜率", "平均/笔", "累计"))
print("  " + "-"*88)

variants = [
    ("V0 原版(bug)：止损=EMA20（方向反了）", lambda: run(-1, 2)),        # 用 -1 模拟他原逻辑不准，另算
    ("V1 止损=entry-2ATR，止盈=entry+2ATR", lambda: run(2, 2)),
    ("V2 止损=entry-1.5ATR，止盈=entry+2ATR", lambda: run(1.5, 2)),
    ("V3 止损=entry-1ATR，止盈=entry+2ATR", lambda: run(1, 2)),
    ("V4 不设止盈止损，4h后收盘平仓", lambda: run(0, 0, raw_only=True)),
    ("V5 要求入场价>EMA20（止损=EMA20才讲得通）", lambda: run(2, 2, require_above_ema=True)),
]

for label, fn in variants:
    if "V0" in label:
        continue   # V0 用前面 audit_backtest.py 的结果，这里跳过
    n, w, tot = fn()
    print("  %-46s %6d %7.0f%% %9.3f%% %11.2f%%"
          % (label, n, (w/n*100 if n else 0), (tot/n if n else 0), tot))

print()
print("  参考（前面已实测）：")
print("  %-46s %6s %8s %10s %12s" % ("V0 原版(bug) 止损=EMA20 方向反了", "~860", "~98%", "+1.1%", "—"))
print("  %-46s %6s %8s %10s %12s" % ("   → 但出场价 97% 在市场上不存在", "", "", "", ""))
print("  %-46s %6s %8s %10s %12s" % ("V4' 纯信号后4h真实涨跌（前次实测）", "860", "43%", "-0.110%", "-94.6%"))
