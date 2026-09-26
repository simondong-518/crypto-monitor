import pandas as pd
from api import get_kline
from indicators import calc_rsi
from notifier import send_wx
from config import CURRENCY_PAIRS

# 2026-09-26 回测模块：4小时回测，自动调参
last_result = ""
def backtest():
    global last_result
    print("开始4小时回测")
    results = []
    for pair in CURRENCY_PAIRS:
        coin = pair.replace("_USDT","")
        data = get_kline(pair, "15m", 1000)
        if len(data) < 100: continue
        df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
        for col in ['close','high','low','open','vol']:
            df[col] = df[col].astype(float)
        win = 0
        total = 0
        for i in range(30, len(df)-10):
            window = df.iloc[:i+1]
            boll_m = window['close'].rolling(20).mean().iloc[-1]
            boll_u = boll_m + 2*window['close'].rolling(20).std().iloc[-1]
            boll_l = boll_m - 2*window['close'].rolling(20).std().iloc[-1]
            rsi = calc_rsi(window['close']).iloc[-1]
            price = window.iloc[-1]['close']
            future_price = df.iloc[i+8]['close']
            row1 = window.iloc[-1]
            row2 = window.iloc[-2]
            body1 = abs(row1['close'] - row1['open'])
            upper1 = row1['high'] - max(row1['open'], row1['close'])
            body2 = abs(row2['close'] - row2['open'])
            upper2 = row2['high'] - max(row2['open'], row2['close'])
            two_upper = upper1 > body1*1.5 and upper2 > body2*1.5
            # 卖出信号
            if price >= boll_u*0.995 and rsi>70 and two_upper:
                total +=1
                if future_price < price: win +=1
            # 买入信号
            if price <= boll_l*1.005 and rsi<30 and price>boll_m:
                total +=1
                if future_price > price: win +=1
        if total>0:
            win_rate = win/total*100
            results.append(f"{coin}: 胜率{win_rate:.0f}% ({win}/{total})")
            if win_rate < 40 and total > 10:
                results.append(f"  ⚠️ 胜率过低，建议自动调参RSI阈值+5")
    if results:
        desp = "## 4小时回测结果\n" + "\n".join(results)
        last_result = "| 最近4h回测胜率 | " + " / ".join(results) + " |"
        send_wx("📊 策略回测", desp)

def daily_backtest():
    print("开始每日全天回测")
    backtest()
