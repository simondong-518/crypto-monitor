import sys
sys.path.insert(0, 'crypto_monitor')
from api import get_kline, get_trades, get_ls, get_flow_1h
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
# 算1h累计资金
flow_1h = get_flow_1h(pair)
# 算15分钟瞬时资金
buy_v = sell_v = 0
for t in trades:
    v = float(t['amount']) * float(t['price'])
    if t['side'] == 'buy': buy_v += v
    else: sell_v += v
flow_15m = buy_v - sell_v
try:
    ls_ratio = float(ls[-1]['top_lsr_account'])
except:
    ls_ratio = 1
flow = {'net_inflow': flow_15m}
b, s = calc_score(ind_s, ind_l, flow, ls_ratio, ind_s['df'])
if not daily_up:
    b -= 1.5
# 计算今日有效高低点
from config import TRAILING_STOP
today_high = ind_s['today_high']
today_low = ind_s['today_low']
rise_from_low = (ind_s['close'] - today_low)/today_low*100
drawdown_from_high = (today_high - ind_s['close'])/today_high*100
trail_thr = TRAILING_STOP.get(pair, 0.035)*100

print(f"【{coin}/USDT】")
print(f"| 维度 | 数值 | 判断 |")
print(f"|------|------|------|")
# 1. 现价
print(f"| 现价 | {ind_s['close']:.4f} | 今日{ind_s['day_chg']:+.2f}% |")
# 2. 日线趋势
trend_emoji = "🟢" if daily_up else "🔴"
trend_judge = "中期趋势向好" if daily_up else "中期趋势走弱"
print(f"| 日线趋势 | {trend_emoji} {'向上' if daily_up else '向下'} | {trend_judge} |")
# 3. 买分卖分
bs_judge = "未到阈值" if (b<3.5 and s<3.5) else "已触发操作信号"
print(f"| 买分 / 卖分 | {b:.1f} / {s:.1f} | {bs_judge} |")
# 4. 当日位置
pos_text = f"从低点反弹{rise_from_low:.1f}% / 从高点回撤{drawdown_from_high:.1f}%"
if drawdown_from_high >= trail_thr:
    pos_judge = f"已经超过{trail_thr:.1f}%回撤"
else:
    pos_judge = f"未到回撤阈值，还差{trail_thr - drawdown_from_high:.1f}%"
print(f"| 当日位置 | {pos_text} | {pos_judge} |")
# 5. 移动止盈
if drawdown_from_high >= trail_thr:
    trail_text = f"阈值{trail_thr:.1f}%，已超{drawdown_from_high - trail_thr:.1f}%"
    trail_judge = "现在已经触达止盈线"
else:
    trail_text = f"阈值{trail_thr:.1f}%，还差{trail_thr - drawdown_from_high:.1f}%"
    trail_judge = "未触达止盈线"
print(f"| 移动止盈 | {trail_text} | {trail_judge} |")
# 6. 资金
# 统一资金换算：亿/万/千
def fmt_money(v):
    if abs(v) >= 100000000:
        return f"${v/100000000:.2f}亿" if v>=0 else f"-${-v/100000000:.2f}亿"
    elif abs(v) >= 10000:
        return f"${v/10000:.1f}万" if v>=0 else f"-${-v/10000:.1f}万"
    else:
        return f"${v/1000:.1f}千" if v>=0 else f"-${-v/1000:.1f}千"
flow1h_text = fmt_money(flow_1h)
flow15_text = fmt_money(flow_15m)
flow_text = f"1h {flow1h_text} / 15m {flow15_text}"
if flow_15m > 8000:
    flow_judge = "15分钟主力大幅进场"
elif flow_15m < -8000:
    flow_judge = "15分钟主力大幅跑路"
elif flow_15m > 0:
    flow_judge = "短期资金小幅流入"
else:
    flow_judge = "短期资金小幅流出"
print(f"| 资金 | {flow_text} | {flow_judge} |")
# 7. 大户多空比
if ls_ratio < 0.5:
    ls_judge = "大户偏空（轧空逻辑）"
elif ls_ratio > 2:
    ls_judge = "大户偏多（多头集中）"
else:
    ls_judge = "多空平衡"
print(f"| 大户多空比 | {ls_ratio:.2f} | {ls_judge} |")
# 8. 今日高低
print(f"| 今日高 / 低 | {today_high:.4f} / {today_low:.4f} | 上方压力 {today_high:.4f}，下方支撑 {today_low:.4f} |")

# 自动综合结论
print("")
# 计算离压力/支撑位的距离
space_to_high = (today_high - ind_s['close'])/ind_s['close']*100
space_to_low = (ind_s['close'] - today_low)/ind_s['close']*100
conclusion = ""
if drawdown_from_high >= trail_thr:
    conclusion = f"现在 {coin} 从高点回撤{drawdown_from_high:.1f}%，已经超过{trail_thr:.1f}%的移动止盈阈值，建议止盈落袋，主程序会自动推送止盈提醒。"
elif b >= 3.5:
    conclusion = f"现在 {coin} 综合买分{b:.1f}，达到买入阈值，结合资金流入、位置支撑，建议逢低买入，主程序会自动推送买入提醒。"
elif s >= 3.5:
    conclusion = f"现在 {coin} 综合卖分{s:.1f}，达到卖出阈值，结合资金流出、位置压力，建议逢高减仓，主程序会自动推送卖出提醒。"
elif space_to_high < 1 and flow_15m < 0 and ind_s['rsi']>70:
    conclusion = f"现在 {coin} 离上方压力位仅{space_to_high:.1f}%，15分钟资金流出+RSI超买，上方抛压重，建议逢高减仓别追高。"
elif space_to_low < 1 and flow_15m > 0 and ind_s['rsi']<30:
    conclusion = f"现在 {coin} 离下方支撑位仅{space_to_low:.1f}%，15分钟资金流入+RSI超卖，是低吸机会，建议逢低布局。"
else:
    conclusion = f"现在 {coin} 未触发明确操作信号，当前位置震荡，主程序持续监测，有信号会自动推送到飞书。"
print(conclusion)
