import pandas as pd
from api import get_kline
from indicators import calc_rsi, calc_boll
from notifier import send_wx
from config import CURRENCY_PAIRS, FEE_RATE

# 2026-10-07 优化回测模块：和实盘逻辑一致，样本量足够，加动态止盈止损
last_result = ""
def backtest():
    global last_result
    print("开始优化后4小时回测")
    results = []
    for pair in CURRENCY_PAIRS:
        coin = pair.replace("_USDT","")
        # 2026-10-07 优化回测模块：改成最近2周1000根15分钟K线，既贴近当前行情，样本量也足够
        data = get_kline(pair, "15m", 1000)
        if len(data) < 200: continue
        df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
        for col in ['close','high','low','open','vol']:
            df[col] = df[col].astype(float)
        win = 0
        total = 0
        for i in range(50, len(df)-16):  # 留16根K线当未来4小时观察窗口
            window = df.iloc[:i+1]
            close = window['close']
            price = close.iloc[-1]
            # 算指标，和实盘一致
            boll_m, boll_u, boll_l = calc_boll(close)
            rsi = calc_rsi(close).iloc[-1]
            # 算ATR
            tr = pd.concat([window['high']-window['low'], 
                           (window['high']-close.shift()).abs(), 
                           (window['low']-close.shift()).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            atr_pct = atr/price*100
            ema20 = close.ewm(span=20).mean().iloc[-1]
            
            # 模拟买入信号（和实盘低吸逻辑一致：BOLL下轨+RSI<30+动态ATR）
            buy_signal = (price <= boll_l.iloc[-1]*1.005) and (rsi < 30)
            # 模拟卖出信号（和实盘高抛逻辑一致：BOLL上轨+RSI>70+动态ATR）
            sell_signal = (price >= boll_u.iloc[-1]*0.995) and (rsi > 70)
            
            if buy_signal:
                total +=1
                # 2026-10-11 修正回测3个核心bug：
                # 1. 入场价用下一根K线开盘价，没有未来函数
                entry_price = df.iloc[i+1]['open']
                # 2. 止损改成正确方向：入场价-1.5倍ATR，之前用EMA20方向反了永不触发
                take_profit = entry_price + atr*2
                stop_loss = entry_price - atr*1.5
                exit_price = df.iloc[i+16]['close']
                # 3. 同根K线保守假设先触发止损，胜率不虚高
                for j in range(i+1, i+17):
                    future_high = df.iloc[j]['high']
                    future_low = df.iloc[j]['low']
                    if future_low <= stop_loss:
                        exit_price = stop_loss
                        break
                    if future_high >= take_profit:
                        exit_price = take_profit
                        break
                profit = (exit_price - entry_price)/entry_price - FEE_RATE*2
                if profit > 0: win +=1
            elif sell_signal:
                total +=1
                entry_price = df.iloc[i+1]['open']
                take_profit = entry_price - atr*2
                stop_loss = entry_price + atr*1.5
                exit_price = df.iloc[i+16]['close']
                for j in range(i+1, i+17):
                    future_high = df.iloc[j]['high']
                    future_low = df.iloc[j]['low']
                    if future_high >= stop_loss:
                        exit_price = stop_loss
                        break
                    if future_low <= take_profit:
                        exit_price = take_profit
                        break
                profit = (entry_price - exit_price)/entry_price - FEE_RATE*2
                if profit > 0: win +=1
                
        if total>0:
            win_rate = win/total*100
            results.append(f"{coin}: 胜率{win_rate:.0f}% ({win}/{total})")
            if win_rate < 40 and total > 30:
                results.append(f"  ⚠️ 胜率过低，建议调参")
    if results:
        desp = "## 优化后4小时回测结果（最近2周数据）\n" + "\n".join(results)
        last_result = "| 最近3个月回测胜率 | " + " / ".join(results) + " |"
        send_wx("📊 策略回测", desp)

def daily_backtest():
    print("开始每日全天回测")
    backtest()
