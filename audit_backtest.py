# -*- coding: utf-8 -*-
"""审计对方的回测：为什么胜率能到 100%？

方法：完全照搬他 backtest.py 的逻辑，但加插桩，把每笔交易的
      entry / stop_loss / take_profit / 实际出场原因 打出来。
"""
import sys, os, io
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

import pandas as pd
from api import get_kline
from indicators import calc_rsi, calc_boll
from config import CURRENCY_PAIRS, FEE_RATE

print("FEE_RATE = %s  (往返手续费 = %.4f%%)" % (FEE_RATE, FEE_RATE * 2 * 100))
print()

for pair in CURRENCY_PAIRS:
    coin = pair.replace("_USDT", "")
    data = get_kline(pair, "15m", 1000)
    if len(data) < 200:
        print("%-6s 数据不足" % coin)
        continue
    df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
    for col in ['close','high','low','open','vol']:
        df[col] = df[col].astype(float)

    win = total = 0
    tp_hit = sl_hit = timeout = 0
    sl_above_entry_buy = 0      # ★ 买入时"止损"竟在入场价之上 = 其实是止盈
    sl_below_entry_sell = 0     # ★ 卖出时"止损"竟在入场价之下
    profits = []
    sl_gap_pct = []             # (stop_loss - entry)/entry 的百分比

    for i in range(50, len(df)-16):
        window = df.iloc[:i+1]
        close = window['close']
        price = close.iloc[-1]
        boll_m, boll_u, boll_l = calc_boll(close)
        rsi = calc_rsi(close).iloc[-1]
        tr = pd.concat([window['high']-window['low'],
                        (window['high']-close.shift()).abs(),
                        (window['low']-close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        ema20 = close.ewm(span=20).mean().iloc[-1]

        buy_signal = (price <= boll_l.iloc[-1]*1.005) and (rsi < 30)
        sell_signal = (price >= boll_u.iloc[-1]*0.995) and (rsi > 70)

        if buy_signal:
            total += 1
            entry = price
            take_profit = entry + atr*2
            stop_loss = ema20
            exit_price = df.iloc[i+16]['close']
            reason = "timeout"
            for j in range(i+1, i+17):
                fh, fl = df.iloc[j]['high'], df.iloc[j]['low']
                if fh >= take_profit:
                    exit_price = take_profit; reason = "TP"; break
                if fl <= stop_loss:
                    exit_price = stop_loss; reason = "SL"; break
            profit = (exit_price - entry)/entry - FEE_RATE*2
            profits.append(profit)
            if reason == "TP": tp_hit += 1
            elif reason == "SL": sl_hit += 1
            else: timeout += 1
            if stop_loss > entry:
                sl_above_entry_buy += 1
                sl_gap_pct.append((stop_loss-entry)/entry*100)
            if profit > 0: win += 1

        elif sell_signal:
            total += 1
            entry = price
            take_profit = entry - atr*2
            stop_loss = ema20
            exit_price = df.iloc[i+16]['close']
            reason = "timeout"
            for j in range(i+1, i+17):
                fh, fl = df.iloc[j]['high'], df.iloc[j]['low']
                if fl <= take_profit:
                    exit_price = take_profit; reason = "TP"; break
                if fh >= stop_loss:
                    exit_price = stop_loss; reason = "SL"; break
            profit = (entry - exit_price)/entry - FEE_RATE*2
            profits.append(profit)
            if reason == "TP": tp_hit += 1
            elif reason == "SL": sl_hit += 1
            else: timeout += 1
            if stop_loss < entry:
                sl_below_entry_sell += 1
                sl_gap_pct.append((entry-stop_loss)/entry*100)
            if profit > 0: win += 1

    if total:
        print("══ %-5s 信号 %3d 笔 → 胜率 %.0f%% (%d/%d)" % (coin, total, win/total*100, win, total))
        print("     出场原因: 止盈TP=%d  止损SL=%d  超时=%d" % (tp_hit, sl_hit, timeout))
        print("     ★ 买/卖方向搞反的笔数: 买入时SL在入场价之上=%d, 卖出时SL在入场价之下=%d"
              % (sl_above_entry_buy, sl_below_entry_sell))
        if sl_gap_pct:
            print("     ★ 所谓\"止损\"相对入场的平均偏离: %+.2f%%（正值=其实是盈利出场）"
                  % (sum(sl_gap_pct)/len(sl_gap_pct)))
        print("     平均每笔收益: %+.3f%%  中位数: %+.3f%%"
              % (sum(profits)/len(profits)*100,
                 sorted(profits)[len(profits)//2]*100))
        print()
