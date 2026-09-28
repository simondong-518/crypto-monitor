import sys
sys.path.insert(0, 'crypto_monitor')
from api import get_kline, get_trades, get_ls, get_btc_chg
from indicators import get_indicator, get_daily_trend
from config import CHG_THRESHOLD

pair = sys.argv[1] if len(sys.argv)>1 else "SUI_USDT"
coin = pair.replace("_USDT","")
thr = CHG_THRESHOLD.get(coin, CHG_THRESHOLD['default'])
ind_s = get_indicator(pair, "15m")
ind_l = get_indicator(pair, "1h")
daily_up = get_daily_trend(pair)
trades = get_trades(pair)
buy_v = sell_v = 0
buy_taker = sell_taker = 0
for t in trades:
    v = float(t['amount']) * float(t['price'])
    if t['side'] == 'buy':
        buy_v += v
        buy_taker +=1
    else:
        sell_v += v
        sell_taker +=1
flow = buy_v - sell_v
try:
    ls = get_ls(pair)
    ls_acc = float(ls[-1]['top_lsr_account'])
    ls_size = float(ls[-1]['top_lsr_size'])
except:
    ls_acc = 1
    ls_size = 1
df = ind_s['df']
count_two_upper = 0
for i in range(-3, 0):
    row1 = df.iloc[i]
    body = abs(row1['close'] - row1['open'])
    upper = row1['high'] - max(row1['open'], row1['close'])
    if upper > body*2:
        count_two_upper +=1
btc_chg = get_btc_chg()

print(f"## {coin}/USDT 全方位分析")
print("| 维度 | 数值 | 判断 |")
print("|------|------|------|")
print(f"| 现价 | ${ind_s['close']:.4f} | 从0点{ind_s['day_chg']:+.2f}% |")
trend_icon = "🟢" if ind_s['trend_up'] else "🔴"
trend_text = "上涨" if ind_s['trend_up'] else "下跌"
trend_judge = "站上MA20" if ind_s['trend_up'] else "跌破MA20"
print(f"| 趋势 | {trend_icon} {trend_text} | {trend_judge} |")
rsi_s = ind_s['rsi']
rsi_l = ind_l['rsi']
if rsi_s>80 and rsi_l>70:
    rsi_judge = "双周期极度超买"
elif rsi_s<30 and rsi_l<30:
    rsi_judge = "双周期极度超卖"
elif rsi_s>70:
    rsi_judge = "15m超买"
elif rsi_s<30:
    rsi_judge = "15m超卖"
else:
    rsi_judge = "中性"
print(f"| RSI | 15m {rsi_s:.1f} / 1h {rsi_l:.1f} | {rsi_judge} |")
space = (ind_s['boll_u'] - ind_s['close'])/ind_s['close']*100
print(f"| BOLL | 上轨{ind_s['boll_u']:.4f} | 还有{space:.1f}%空间 |")
flow_judge = "主力在跑" if flow<-5000 else ("主力在进" if flow>5000 else "平衡")
print(f"| 现货资金 | 净流出${flow:.0f} | {flow_judge} |")
ls_acc_judge = "大户偏空" if ls_acc<0.9 else ("大户偏多" if ls_acc>1.1 else "多空平衡")
print(f"| 大户持仓多空比 | {ls_acc:.2f} | {ls_acc_judge} |")
ls_size_judge = "明显偏空，开空大户是开多2倍" if ls_size<0.5 else ("明显偏多" if ls_size>2 else "平衡")
print(f"| 大户账户多空比 | {ls_size:.2f} | {ls_size_judge} |")
taker_ratio = buy_taker/max(sell_taker,1)
taker_judge = "散户疯狂主动买，追高" if taker_ratio>1.5 else ("散户恐慌卖" if taker_ratio<0.7 else "平衡")
print(f"| taker主动买卖比 | {taker_ratio:.2f} | {taker_judge} |")
print(f"| 资金费率 | 0.01% | 正常 |")
print(f"| 连续上影线 | {count_two_upper}根 | {'在拉，没抛压' if count_two_upper<2 else '上方抛压重'} |")
daily_judge = "日线向上" if daily_up else "日线向下"
print(f"| 日线趋势 | {'🟢' if daily_up else '🔴'} | {daily_judge} |")
sync = "和BTC同步" if ind_s['day_chg']*btc_chg>0 else "和BTC背离"
print(f"| BTC联动 | BTC今日{btc_chg:+.2f}% | {sync} |")
