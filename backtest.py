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
                # 2026-10-07 修正回测bug：止盈改成2倍ATR，之前1.5倍太近导致胜率虚高
                entry_price = price
                take_profit = entry_price + atr*2
                # ★ 我方修（2026-10-08）：原来 stop_loss = ema20。
                #   低吸信号的入场价在 BOLL 下轨，**必然低于 EMA20**，
                #   所以"止损"落在了入场价**上方** —— 那不是止损，是止盈。
                #   循环第一根 K 线就判定 future_low <= stop_loss 成立，
                #   于是按一个高于市价 2~3%、市场上根本没出现过的价格"卖出"，
                #   凭空记成盈利（实测 97% 的出场价在当根 K 线区间之外）。
                #   改：止损放到入场价下方，方向才对。
                stop_loss = entry_price - atr*2
                exit_price = df.iloc[i+16]['close']  # 4小时后收盘价
                # 遍历未来16根K线，看先触发止盈还是止损
                for j in range(i+1, i+17):
                    future_high = df.iloc[j]['high']
                    future_low = df.iloc[j]['low']
                    if future_high >= take_profit:
                        exit_price = take_profit
                        break
                    if future_low <= stop_loss:
                        exit_price = stop_loss
                        break
                profit = (exit_price - entry_price)/entry_price - FEE_RATE*2
                if profit > 0: win +=1
            elif sell_signal:
                total +=1
                entry_price = price
                take_profit = entry_price - atr*2
                # ★ 我方修（2026-10-08）：对称的同一个 bug —— 高抛入场价在 BOLL 上轨，
                #   必然高于 EMA20，所以原来的 stop_loss = ema20 落在入场价**下方**，
                #   同样是"方向反了"的假止损。改：放到入场价上方。
                stop_loss = entry_price + atr*2
                exit_price = df.iloc[i+16]['close']
                for j in range(i+1, i+17):
                    future_high = df.iloc[j]['high']
                    future_low = df.iloc[j]['low']
                    if future_low <= take_profit:
                        exit_price = take_profit
                        break
                    if future_high >= stop_loss:
                        exit_price = stop_loss
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
        last_result = "| 最近2周回测胜率 | " + " / ".join(results) + " |"
        send_wx("📊 策略回测", desp)

def daily_backtest():
    print("开始每日全天回测")
    backtest()
