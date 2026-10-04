import sys
sys.path.insert(0, 'crypto_monitor')
from api import get_kline, get_trades, get_ls, get_btc_chg, get_flow_1h, get_big_order, get_funding_rate, get_orderbook
from indicators import get_indicator, get_daily_trend

pair = sys.argv[1] if len(sys.argv)>1 else "SUI_USDT"
coin = pair.replace("_USDT","")
ind_5m = get_indicator(pair, "5m")
ind_s = get_indicator(pair, "15m")
ind_l = get_indicator(pair, "1h")
ind_4h = get_indicator(pair, "4h")
daily_up = get_daily_trend(pair)
trades = get_trades(pair)
buy_v = sell_v = 0
for t in trades:
    v = float(t['amount']) * float(t['price'])
    if t['side'] == 'buy': buy_v += v
    else: sell_v += v
flow = buy_v - sell_v
flow_1h = get_flow_1h(pair)
big_buy, big_sell = get_big_order(pair)
big_flow = big_buy - big_sell
taker_ratio = buy_v/sell_v if sell_v>0 else 1
try:
    ls_ratio = float(get_ls(pair)[-1]['top_lsr_account'])
except:
    ls_ratio = 1
try:
    ls_ratio_liq = float(get_ls(pair)[-1]['top_lsr_liq'])
except:
    ls_ratio_liq = 1
fund_rate, fund_change = get_funding_rate(pair)
buy1, sell1, bid_total, ask_total = get_orderbook(pair)

price = ind_s['close']
today_chg = ind_s['day_chg']
# 连续上影线统计
upper_count = 0
for i in range(-5,0):
    row = ind_s['df'].iloc[i]
    body = abs(row['close'] - row['open'])
    upper = row['high'] - max(row['open'], row['close'])
    if body>0 and upper > body*2:
        upper_count +=1

# 当日高低点（只算今天0点之后的）
import time
today = time.strftime("%Y-%m-%d", time.localtime())
midnight = int(time.mktime(time.strptime(today, "%Y-%m-%d")))
df = ind_s['df']
df['ts'] = df['t'].astype(int)
today_df = df[df['ts'] >= midnight]
today_high = today_df['high'].max()
today_low = today_df['low'].min()
rise_low = (price - today_low)/today_low*100
drawdown_high = (today_high - price)/today_high*100
from config import TRAILING_STOP
trail_thr = TRAILING_STOP.get(pair, 0.035)*100
btc_chg = get_btc_chg()

# 计算ATR波动率（14周期）
import pandas as pd
high = df['high']
low = df['low']
close = df['close']
tr = pd.concat([high-low, abs(high-close.shift()), abs(low-close.shift())], axis=1).max(axis=1)
atr = tr.rolling(14).mean().iloc[-1]
atr_pct = atr/price*100

# 计算涨跌概率打分
bull_score = 50  # 基准50%
# 4h趋势加分
if ind_4h['trend_up']:
    bull_score += 10
else:
    bull_score -= 10
# 15m MACD信号
if ind_s['macd_gold']:
    bull_score += 8
elif ind_s['macd_dead']:
    bull_score -= 8
# 15m KDJ信号
if ind_s['k_gold']:
    bull_score += 7
elif ind_s['k_dead']:
    bull_score -= 7
# 5分钟超短信号
if ind_5m['trend_up']:
    bull_score += 5
else:
    bull_score -=5
if ind_5m['macd_gold']:
    bull_score += 3
elif ind_5m['macd_dead']:
    bull_score -=3
# RSI位置
if ind_s['rsi'] < 35:
    bull_score += 8  # 超卖反弹
elif ind_s['rsi'] > 70:
    bull_score -= 8  # 超买回落
# 1小时资金流向
if flow_1h > 10000:
    bull_score += 10
elif flow_1h < -10000:
    bull_score -= 10
# 大单流向
if big_flow > 50000:
    bull_score += 8
elif big_flow < -50000:
    bull_score -= 8
# 大户多空比
if ls_ratio > 1.2:
    bull_score += 8
elif ls_ratio < 0.7:
    bull_score -= 8
# 日线趋势
if daily_up:
    bull_score += 7
else:
    bull_score -= 7
# BTC联动
if btc_chg > 1:
    bull_score += 7
elif btc_chg < -1:
    bull_score -= 7
# Taker情绪
if taker_ratio < 0.7:
    bull_score += 5  # 散户恐慌割肉，底部
elif taker_ratio > 1.5:
    bull_score -= 5  # 散户追高，顶部
# 资金费率变化
if fund_change > 0.0001:
    bull_score -= 3  # 资金费率上升，多头拥挤
elif fund_change < -0.0001:
    bull_score += 3  # 资金费率下降，空头拥挤
# 盘口深度
if bid_total > ask_total * 1.2:
    bull_score += 4  # 下面托单厚，跌不下去
elif ask_total > bid_total * 1.2:
    bull_score -= 4  # 上面压单厚，涨不上去
# 成交量趋势：最近3根量比之前大
vol_recent = df['volume'].iloc[-3:].mean()
vol_prev = df['volume'].iloc[-6:-3].mean()
if price > df['close'].iloc[-3] and vol_recent > vol_prev*1.2:
    bull_score += 5  # 放量上涨
elif price < df['close'].iloc[-3] and vol_recent > vol_prev*1.2:
    bull_score -= 5  # 放量下跌

# 限制概率在10-90之间
bull_score = max(10, min(90, bull_score))
bear_score = 100 - bull_score

print(f"{coin}/USDT 预测分析:")
print()
print("| 维度 | 数值 | 判断 |")
print("|------|------|------|")
print(f"| 现价 | ${price:.4f} | 今日 {today_chg:+.2f}% |")
print(f"| 当日高低点 | 低{today_low:.4f} / 高{today_high:.4f} | 从0点开盘至今的极值 |")
print(f"| 当前位置 | 从低点反弹{rise_low:.1f}% / 从高点回撤{drawdown_high:.1f}% | 今日高低点区间内 |")
print(f"| 移动止盈 | 阈值{trail_thr:.1f}% | 还差{trail_thr - drawdown_high:.1f}%触发提醒 |")
trend_emoji = "🟢" if ind_s['trend_up'] else "🔴"
trend_text = "上涨" if ind_s['trend_up'] else "下跌"
trend_judge = "15分钟站上MA20" if ind_s['trend_up'] else "15分钟跌破MA20"
print(f"| 趋势 | {trend_emoji} {trend_text} | {trend_judge} |")
print(f"| RSI | 15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f} | 中性 |")
space_up = (ind_s['boll_u'] - price)/price*100
space_down = (price - ind_s['boll_l'])/price*100
print(f"| BOLL 上轨 | {ind_s['boll_u']:.4f} | 还有{space_up:.1f}%空间 |")
print(f"| BOLL 下轨 | {ind_s['boll_l']:.4f} | 还有{space_down:.1f}%空间 |")
# 统一资金换算：亿/万/千
def fmt_money(v):
    if abs(v) >= 100000000:
        return f"${v/100000000:.2f}亿" if v>=0 else f"-${-v/100000000:.2f}亿"
    elif abs(v) >= 10000:
        return f"${v/10000:.1f}万" if v>=0 else f"-${-v/10000:.1f}万"
    else:
        return f"${v/1000:.1f}千" if v>=0 else f"-${-v/1000:.1f}千"
if flow >=0:
    flow_text = f"净流入{fmt_money(flow)}"
else:
    flow_text = f"净流出{fmt_money(-flow)}"
flow_judge = "主力在进" if flow>1000 else "主力在跑" if flow<-1000 else "平衡"
print(f"| 现货资金(瞬时) | {flow_text} | {flow_judge} |")
if flow_1h >=0:
    flow1h_text = f"净流入{fmt_money(flow_1h)}"
else:
    flow1h_text = f"净流出{fmt_money(-flow_1h)}"
flow1h_judge = "1小时主力大幅进" if flow_1h>10000 else "1小时主力大幅跑" if flow_1h<-10000 else "1小时平衡"
print(f"| 现货资金(1h累计) | {flow1h_text} | {flow1h_judge} |")
if big_flow >=0:
    big_text = f"净流入{fmt_money(big_flow)}"
else:
    big_text = f"净流出{fmt_money(-big_flow)}"
big_judge = "大资金在进" if big_flow>50000 else "大资金在跑" if big_flow<-50000 else "无明显大单"
print(f"| 大单资金(>10万) | {big_text} | {big_judge} |")
if ls_ratio < 0.7:
    ls_judge = "大户偏空"
elif ls_ratio >1.3:
    ls_judge = "大户偏多"
else:
    ls_judge = "平衡"
print(f"| 大户持仓多空比 | {ls_ratio:.2f} | {ls_judge} |")
if ls_ratio_liq <0.7:
    ls_liq_judge = "大户偏空"
elif ls_ratio_liq>1.3:
    ls_liq_judge = "大户偏多"
else:
    ls_liq_judge = "平衡"
print(f"| 大户账户多空比 | {ls_ratio_liq:.2f} | {ls_liq_judge} |")
taker_judge = "散户疯狂主动买，追高" if taker_ratio>1.5 else "散户恐慌割肉" if taker_ratio<0.7 else "平衡"
print(f"| Taker 主动买卖比 | {taker_ratio:.2f} | {taker_judge} |")
print(f"| 波动率(ATR) | {atr_pct:.1f}% | 正常波动" if atr_pct<5 else f"| 波动率(ATR) | {atr_pct:.1f}% | 剧烈波动 |")
fund_pct = fund_rate*100
if fund_change > 0.0001:
    fund_judge = "费率上升，多头拥挤"
elif fund_change < -0.0001:
    fund_judge = "费率下降，空头拥挤"
else:
    fund_judge = "费率正常"
print(f"| 资金费率 | {fund_pct:.3f}% | {fund_judge} |")
depth_ratio = bid_total/ask_total if ask_total>0 else 1
if depth_ratio > 1.2:
    depth_judge = "买盘厚，跌不动"
elif depth_ratio < 0.8:
    depth_judge = "卖盘厚，涨不动"
else:
    depth_judge = "盘口平衡"
print(f"| 盘口深度 | 买{bid_total/1000:.0f}k / 卖{ask_total/1000:.0f}k | {depth_judge} |")
print(f"| 连续上影线 | {upper_count}根 | 还在拉，没抛压" if upper_count==0 else f"| 连续上影线 | {upper_count}根 | 上方抛压重 |")
daily_text = "🟢" if daily_up else "🔴"
daily_judge = "日线向上" if daily_up else "日线向下"
print(f"| 日线趋势 | {daily_text} | {daily_judge} |")
sync_text = "和 BTC 同步" if today_chg*btc_chg>0 else "和 BTC 背离"
print(f"| BTC 联动 | BTC{btc_chg:+.2f}% | {sync_text} |")
print(f"| 未来4小时概率 | 涨{bull_score}% / 跌{bear_score}% | 量化打分结果 |")
print()
# 专家判断
if bull_score > 65:
    judge = "强多，大概率继续上涨，可持有或逢低买入"
elif bull_score > 55:
    judge = "偏多，震荡向上为主，可持有"
elif bear_score > 65:
    judge = "强空，大概率继续下跌，建议止盈或观望"
elif bear_score > 55:
    judge = "偏空，震荡向下为主，建议减仓"
else:
    judge = "震荡，方向不明，观望为主"
print(f"未来4小时判断：{judge}。下方支撑{today_low:.4f}，上方压力{today_high:.4f}，到压力位先止盈，到支撑位可低吸。")
