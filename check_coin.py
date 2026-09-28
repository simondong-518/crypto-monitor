import sys
sys.path.insert(0, 'crypto_monitor')
from api import get_kline, get_trades, get_ls
from indicators import get_indicator, get_daily_trend
from strategy import calc_score
from config import CHG_THRESHOLD

pair = sys.argv[1] if len(sys.argv)>1 else "SUI_USDT"
coin = pair.replace("_USDT","")
thr = CHG_THRESHOLD.get(coin, CHG_THRESHOLD['default'])
ind_s = get_indicator(pair, "15m")
ind_l = get_indicator(pair, "1h")
daily_up = get_daily_trend(pair)
trades = get_trades(pair)
buy_v = sell_v = 0
for t in trades:
    v = float(t['amount']) * float(t['price'])
    if t['side'] == 'buy': buy_v += v
    else: sell_v += v
flow = {'net_inflow': buy_v - sell_v}
ls = get_ls(pair)
try:
    ls_ratio = float(ls[-1]['top_lsr_account'])
except:
    ls_ratio = 1
b, s = calc_score(ind_s, ind_l, flow, ls_ratio, ind_s['df'])
if not daily_up:
    b -= 1.5
print(f"【{coin}】")
print(f"现价: {ind_s['close']}")
print(f"今日涨幅: {ind_s['day_chg']:.2f}% (阈值{thr}%)")
print(f"日线趋势: {'向上' if daily_up else '向下'}")
print(f"买分: {b}, 卖分: {s} (阈值3.5)")
avg_vol = ind_s['df']['vol'].rolling(20).mean().iloc[-1]
cur_vol = ind_s['df']['vol'].iloc[-1]
print(f"当前成交量: {cur_vol:.2f}, 1.5倍平均量: {avg_vol*1.5:.2f}, 够吗: {'够' if cur_vol>avg_vol*1.5 else '不够'}")
