# -*- coding: utf-8 -*-
"""公正检验：信号发出后 4 小时（16根15分钟K线）价格到底怎么走？

不用任何止盈止损 —— 只看"买了之后涨没涨"，这是最诚实的检验。
"""
import sys, os
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

import pandas as pd
from api import get_kline
from indicators import calc_rsi, calc_boll
from config import CURRENCY_PAIRS, FEE_RATE

print("═══ 公正检验：信号后 4 小时的真实收益（无任何止盈止损）═══")
print("   手续费往返 %.2f%%\n" % (FEE_RATE*2*100))

rows = []
for pair in CURRENCY_PAIRS:
    coin = pair.replace("_USDT", "")
    data = get_kline(pair, "15m", 1000)
    if len(data) < 200: continue
    df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
    for col in ['close','high','low','open','vol']:
        df[col] = df[col].astype(float)

    rets = []
    for i in range(50, len(df)-16):
        window = df.iloc[:i+1]
        close = window['close']
        price = close.iloc[-1]
        boll_m, boll_u, boll_l = calc_boll(close)
        rsi = calc_rsi(close).iloc[-1]

        if (price <= boll_l.iloc[-1]*1.005) and (rsi < 30):        # 买入信号
            fwd = (df.iloc[i+16]['close'] - price)/price - FEE_RATE*2
            rets.append(fwd)
        elif (price >= boll_u.iloc[-1]*0.995) and (rsi > 70):      # 卖出信号（做空/回避）
            fwd = (price - df.iloc[i+16]['close'])/price - FEE_RATE*2
            rets.append(fwd)

    if rets:
        n = len(rets)
        wins = sum(1 for r in rets if r > 0)
        avg = sum(rets)/n
        rows.append((coin, n, wins/n*100, avg*100,
                     sorted(rets)[n//2]*100,
                     sum(1 for r in rets if r > 0.01)/n*100))

print("  %-6s %5s %9s %11s %11s %12s" % ("币种", "笔数", "胜率", "平均收益", "中位收益", "涨超1%占比"))
print("  " + "-"*60)
for coin, n, wr, avg, med, big in rows:
    print("  %-6s %5d %8.0f%% %10.3f%% %10.3f%% %11.0f%%" % (coin, n, wr, avg, med, big))

tn = sum(r[1] for r in rows)
tw = sum(r[1]*r[2]/100 for r in rows)
tavg = sum(r[1]*r[3] for r in rows)/tn
print("  " + "-"*60)
print("  %-6s %5d %8.0f%% %10.3f%%" % ("合计", tn, tw/tn*100, tavg))
print()
print("  → 这就是\"不含任何止盈止损幻想\"的真实胜率")
