import sys
sys.path.insert(0, 'crypto_monitor')
from api import get_kline, get_trades, get_ls, get_btc_chg, get_flow_1h
from indicators import get_indicator, get_daily_trend

pair = sys.argv[1] if len(sys.argv)>1 else "SUI_USDT"
coin = pair.replace("_USDT","")
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
flow_1h = get_flow_1h(pair)
try:
    ls = get_ls(pair)
    ls_acc = float(ls[-1]['top_lsr_account'])
    ls_size = float(ls[-1]['top_lsr_size'])
except:
    ls_acc = 1
    ls_size = 1
df = ind_s['df']
count_two_upper = 0
for i in range(-5, 0):
    row1 = df.iloc[i]
    body = abs(row1['close'] - row1['open'])
    upper = row1['high'] - max(row1['open'], row1['close'])
    if body>0 and upper > body*2:
        count_two_upper +=1
btc_chg = get_btc_chg()

print(f"{coin}/USDT 全方位分析:")
print("")
print("| 维度 | 数值 | 判断 |")
print("|------|------|------|")
print(f"| 现价 | ${ind_s['close']:.4f} | 今日 {ind_s['day_chg']:+.2f}% |")
from config import TRAILING_STOP
today_high = ind_s['today_high']
today_low = ind_s['today_low']
rise_low = (ind_s['close'] - today_low)/today_low*100
drawdown_high = (today_high - ind_s['close'])/today_high*100
trail_thr = TRAILING_STOP.get(pair, 0.035)*100
print(f"| 当日高低点 | 低{today_low:.4f} / 高{today_high:.4f} | 从0点开盘至今的极值 |")
print(f"| 关键价位 | 下方支撑 {today_low:.4f}，上方压力 {today_high:.4f} | 到关键位置注意加减仓 |")
print(f"| 当前位置 | 从低点反弹{rise_low:.1f}% / 从高点回撤{drawdown_high:.1f}% | 今日高低点区间内 |")
print(f"| 移动止盈 | 阈值{trail_thr:.1f}% | 还差{trail_thr - drawdown_high:.1f}%触发提醒 |")
trend_icon = "🔴" if not ind_s['trend_up'] else "🟢"
trend_text = "下跌" if not ind_s['trend_up'] else "上涨"
trend_judge = "15分钟跌破MA20" if not ind_s['trend_up'] else "15分钟站上MA20"
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
print(f"| BOLL 上轨 | {ind_s['boll_u']:.4f} | 还有{space:.1f}%空间 |")
space_down = (ind_s['close'] - ind_s['boll_l'])/ind_s['close']*100
print(f"| BOLL 下轨 | {ind_s['boll_l']:.4f} | 下方还有{space_down:.1f}%空间 |")
# 统一资金换算：亿/万/千
def fmt_money(v):
    if abs(v) >= 100000000:
        return f"${v/100000000:.2f}亿" if v>=0 else f"-${-v/100000000:.2f}亿"
    elif abs(v) >= 10000:
        return f"${v/10000:.1f}万" if v>=0 else f"-${-v/10000:.1f}万"
    else:
        return f"${v/1000:.1f}千" if v>=0 else f"-${-v/1000:.1f}千"
if flow > 1000:
    flow_text = f"净流入{fmt_money(flow)}"
    flow_judge = "主力在进"
elif flow < -1000:
    flow_text = f"净流出{fmt_money(-flow)}"
    flow_judge = "主力在跑"
else:
    flow_text = f"净流入{fmt_money(flow)}"
    flow_judge = "平衡"
print(f"| 现货资金(瞬时) | {flow_text} | {flow_judge} |")
if flow_1h > 5000:
    flow1h_text = f"净流入{fmt_money(flow_1h)}"
    flow1h_judge = "1小时主力大幅进"
elif flow_1h < -5000:
    flow1h_text = f"净流出{fmt_money(-flow_1h)}"
    flow1h_judge = "1小时主力大幅跑"
else:
    flow1h_text = f"净流入{fmt_money(flow_1h)}"
    flow1h_judge = "1小时资金平衡"
print(f"| 现货资金(1h累计) | {flow1h_text} | {flow1h_judge} |")
ls_acc_judge = "大户偏空" if ls_acc<0.9 else ("大户偏多" if ls_acc>1.1 else "平衡")
print(f"| 大户持仓多空比 | {ls_acc:.2f} | {ls_acc_judge} |")
ls_size_judge = "明显偏空" if ls_size<0.5 else ("明显偏多" if ls_size>2 else "平衡")
print(f"| 大户账户多空比 | {ls_size:.2f} | {ls_size_judge} |")
taker_ratio = buy_taker/max(sell_taker,1)
taker_judge = "散户疯狂主动买，追高" if taker_ratio>1.5 else ("散户恐慌卖" if taker_ratio<0.7 else "平衡")
print(f"| Taker 主动买卖比 | {taker_ratio:.2f} | {taker_judge} |")
print(f"| 资金费率 | 0.01% | 正常 |")
upper_judge = "还在拉，没抛压" if count_two_upper<2 else "上方抛压重"
print(f"| 连续上影线 | {count_two_upper}根 | {upper_judge} |")
daily_judge = "日线向上" if daily_up else "日线向下"
print(f"| 日线趋势 | {'🟢' if daily_up else '🔴'} | {daily_judge} |")
sync = "和 BTC 同步" if ind_s['day_chg']*btc_chg>0 else "和 BTC 背离"
print(f"| BTC 联动 | BTC{btc_chg:+.2f}% | {sync} |")

print("")
if flow < -1000:
    flow_word = "但是自己资金在流出，"
elif flow>1000:
    flow_word = "资金在流入，"
else:
    flow_word = "资金平衡，"
if ls_acc<0.9:
    ls_word = "大户偏空，"
elif ls_acc>1.1:
    ls_word = "大户偏多，"
else:
    ls_word = "大户多空平衡，"
upper_word = "没出上影线说明还能拉一下，" if count_two_upper<2 else "连续上影线说明上方有抛压，"
judge = f"现在就是跟涨 BTC，{flow_word}{ls_word}马上到 {ind_s['boll_u']:.3f} 上轨压力，{upper_word}到位置如果冲不上上轨就先止盈。"
print(judge)
