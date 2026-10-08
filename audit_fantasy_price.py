# -*- coding: utf-8 -*-
"""讲清楚 bug：回测「出场」时用了一个市场上根本不存在的价格。

买入信号 -> entry 约等于 BOLL 下轨 -> 他设 stop_loss = EMA20（在下轨上方）
-> 循环第一根 K 线就判定 future_low <= stop_loss 成立
-> 于是按 stop_loss(=EMA20) 出场，那个价格比当时的市价高 2~3%
-> 但那一根 K 线根本没到过那个价 -> 卖在了不存在的价格上 -> 凭空赚 2~3%
"""
import sys, os
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

import pandas as pd
from api import get_kline
from indicators import calc_rsi, calc_boll
from config import FEE_RATE

print("=== 实测：所谓「止损出场」的价格，市场真的到过吗？ ===")
print()

grand_total = grand_fantasy = 0

for pair in ["SUI_USDT", "BTC_USDT", "DOGE_USDT"]:
    coin = pair.replace("_USDT", "")
    data = get_kline(pair, "15m", 1000)
    df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
    for c in ['close','high','low','open','vol']:
        df[c] = df[c].astype(float)

    tot = fantasy = 0
    samples = []
    for i in range(50, len(df)-16):
        w = df.iloc[:i+1]; close = w['close']; price = close.iloc[-1]
        bm, bu, bl = calc_boll(close)
        rsi = calc_rsi(close).iloc[-1]
        tr = pd.concat([w['high']-w['low'], (w['high']-close.shift()).abs(),
                        (w['low']-close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        ema20 = close.ewm(span=20).mean().iloc[-1]

        if (price <= bl.iloc[-1]*1.005) and (rsi < 30):     # 买入信号
            tot += 1
            entry = price; sl = ema20
            for j in range(i+1, i+17):
                if df.iloc[j]['high'] >= entry + atr*2:
                    break
                if df.iloc[j]['low'] <= sl:
                    lo, hi = df.iloc[j]['low'], df.iloc[j]['high']
                    if not (lo <= sl <= hi):
                        fantasy += 1
                        if len(samples) < 3:
                            samples.append((entry, sl, lo, hi, j-i))
                    break

    grand_total += tot
    grand_fantasy += fantasy
    print("  -- %s（%d 笔买入信号）--" % (coin, tot))
    print("     按不存在的价格出场的: %d 笔 = %.0f%%" % (fantasy, (fantasy/tot*100 if tot else 0)))
    for entry, sl, lo, hi, gap in samples:
        print("       入场 %.4f -> 声称在 %.4f 出场" % (entry, sl))
        print("          但那根K线真实区间是 [%.4f, %.4f]，%.4f 根本没出现过" % (lo, hi, sl))
        print("          凭空多赚 %.2f%%（等于穿越回去挂了个更高价的卖单）"
              % ((sl-entry)/entry*100))
    print()

print("  ====== 合计 ======")
print("  买入信号 %d 笔，其中 %d 笔（%.0f%%）是按市场上没出现过的价格出场的"
      % (grand_total, grand_fantasy, (grand_fantasy/grand_total*100 if grand_total else 0)))
print()
print("  -> 不是「低吸买在不存在的价格」，而是")
print("     「卖出卖在了不存在的价格」—— 比当时市价高 2~3%，凭空赚出来的。")
