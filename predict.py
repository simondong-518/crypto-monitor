import sys
sys.path.insert(0, 'crypto_monitor')
from api import get_kline, get_trades, get_ls, get_btc_chg
from indicators import get_indicator, get_daily_trend

pair = sys.argv[1] if len(sys.argv)>1 else "SUI_USDT"
coin = pair.replace("_USDT","")
ind_s = get_indicator(pair, "15m")
ind_l = get_indicator(pair, "1h")
daily_up = get_daily_trend(pair)
trades = get_trades(pair)
buy_v = sell_v = 0
for t in trades:
    v = float(t['amount']) * float(t['price'])
    if t['side'] == 'buy': buy_v += v
    else: sell_v += v
flow = buy_v - sell_v
taker_ratio = buy_v/sell_v if sell_v>0 else 1
try:
    ls_ratio = float(get_ls(pair)[-1]['top_lsr_account'])
except:
    ls_ratio = 1

price = ind_s['close']
support = ind_s['boll_l']
pressure = ind_s['boll_u']
rsi = ind_s['rsi']
rsi_l = ind_l['rsi']

print(f"## {coin}/USDT 专家级走势判断：")
print()
# 现在位置判断
if rsi_l < 30:
    pos = "超跌位置"
    rsi_state = "1h RSI已经到超卖区间，下跌动能耗尽"
elif rsi_l > 70:
    pos = "超买位置"
    rsi_state = "1h RSI已经到超买区间，上涨动能减弱"
else:
    pos = "中间位置"
    rsi_state = "RSI中性，没有极端信号"
# 散户情绪
if taker_ratio < 0.6:
    retail = "散户在恐慌割肉，是典型的底部洗盘特征"
    retail_bull = True
elif taker_ratio > 1.4:
    retail = "散户在追高接盘，是典型的顶部特征"
    retail_bull = False
else:
    retail = "散户多空平衡，没有极端情绪"
    retail_bull = None
trend_state = "大日线趋势向上，没走坏" if daily_up else "大日线趋势向下，别乱抄底"
# 资金和大户判断
if flow > 1000:
    fund = "资金明显流入，有主力在买"
elif flow < -1000:
    fund = "资金明显流出，主力在跑"
else:
    fund = "资金平衡，没有大动作"
if ls_ratio > 1.2:
    big = "大户偏多"
elif ls_ratio < 0.8:
    big = "大户偏空"
else:
    big = "大户多空平衡"

print("| 维度 | 情况 | 判断 |")
print("|------|------|------|")
print(f"| 现在位置 | {rsi_state} | {pos} |")
retail_judge = "偏多" if retail_bull==True else "偏空" if retail_bull==False else "中性"
print(f"| 散户情绪 | {retail} | {retail_judge} |")
print(f"| 资金动向 | 净流入${flow:.0f} | {fund} |")
print(f"| 大户动向 | 多空比{ls_ratio:.2f} | {big} |")
print(f"| 大趋势 | 日线 | {trend_state} |")
space_up = (pressure - price)/price*100
space_down = (price - support)/price*100
print(f"| 上方压力 | BOLL上轨 {pressure:.4f} | 还有{space_up:.1f}%空间 |")
print(f"| 下方支撑 | BOLL下轨 {support:.4f} | 还有{space_down:.1f}%空间 |")
print()
if pos == "超跌位置" and daily_up:
    advice = "现在RSI超卖，已经跌不动了，别割在最低点，拿住等反弹"
    target = f"反弹目标先看{pressure:.4f}，到这附近可以止盈"
elif pos == "超买位置" and daily_up:
    advice = "现在RSI超买，别贪，先止盈落袋"
    target = f"等回调到{support:.4f}附近再接回来"
elif not daily_up:
    advice = "大趋势向下，别抄底，持币观望"
    target = "等趋势转多再进场"
else:
    advice = "现在在中间位置，拿着不动，等方向选择"
    target = "突破上轨追多，跌破下轨止损"
print(f"| 操作建议 | {advice} | {target} |")
