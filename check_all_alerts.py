import sys
sys.path.insert(0, 'crypto_monitor')
from api import get_kline, get_trades, get_ls, get_flow_1h
from indicators import get_indicator, get_daily_trend
from strategy import calc_score
from config import CURRENCY_PAIRS, TRAILING_STOP, BUY_SCORE_THRESHOLD

rows = []
for pair in CURRENCY_PAIRS:
    coin = pair.replace("_USDT","")
    try:
        ind_s = get_indicator(pair, "15m")
        price = ind_s['close']
        day_chg = ind_s['day_chg']
        # 1h资金
        flow_1h = get_flow_1h(pair)
        # 15m资金
        trades = get_trades(pair)
        buy_v = sell_v = 0
        for t in trades:
            v = float(t['amount']) * float(t['price'])
            if t['side'] == 'buy': buy_v += v
            else: sell_v += v
        flow_15 = buy_v - sell_v
        # 简单提示
        alerts = []
        if ind_s['rsi'] >75: alerts.append("RSI超买")
        if ind_s['rsi'] <25: alerts.append("RSI超卖")
        if flow_15 >8000: alerts.append("🟢15m资金流入")
        if flow_15 < -8000: alerts.append("🔴15m资金流出")
        alert_text = "、".join(alerts) if alerts else "无"
        # 格式化
        # 自动换算资金单位：亿/万/千
        def fmt_money(v):
            if abs(v) >= 100000000:
                return f"${v/100000000:.2f}亿" if v>=0 else f"-${-v/100000000:.2f}亿"
            elif abs(v) >= 10000:
                return f"${v/10000:.1f}万" if v>=0 else f"-${-v/10000:.1f}万"
            else:
                return f"${v/1000:.1f}千" if v>=0 else f"-${-v/1000:.1f}千"
        flow1h_text = fmt_money(flow_1h)
        flow15_text = fmt_money(flow_15)
        chg_text = f"{day_chg:+.2f}%"
        rows.append([coin, f"{price:.4f}", chg_text, flow1h_text, flow15_text, alert_text])
    except Exception as e:
        rows.append([coin, "ERR", "-", "-", "-", "❌错"])

# 输出表格
print("📊 全币种盯盘总览:\n")
print(f"| {'币种':<6} | {'现价':<8} | {'今日涨跌':<8} | {'1h资金':<10} | {'15m资金':<10} | {'提示':<20} |")
print("|--------|----------|----------|------------|------------|----------------------|")
for r in rows:
    print(f"| {r[0]:<6} | {r[1]:<8} | {r[2]:<8} | {r[3]:<10} | {r[4]:<10} | {r[5]:<20} |")
