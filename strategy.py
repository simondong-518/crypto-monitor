# 2026-09-26 策略模块：打分和信号判断
from config import BUY_SCORE_THRESHOLD, SELL_SCORE_THRESHOLD

# 记录每个币上次信号状态，用于信号反转提醒
last_signal = {}

def calc_score(ind_s, ind_l, flow, top_ratio, df):
    buy = sell = 0
    close = ind_s['close']
    # BOLL三线向上判断
    boll_up_trend = False
    upper = ind_s['boll_u']
    if len(df)>=2:
        prev_upper = df['close'].rolling(20).mean().iloc[-2] + 2*df['close'].rolling(20).std().iloc[-2]
        if upper > prev_upper:
            boll_up_trend = True
    # 4小时趋势过滤
    if not ind_s['trend_up']:
        sell += 0.5
    # BOLL规则
    if close <= ind_s['boll_l']*1.005:
        if ind_s['trend_up']:
            # 上涨碰下轨：4h向上加1.5，4h向下加0.75
            if ind_l['trend_up']:
                buy += 1.5
            else:
                buy += 0.75
        else:
            # 下跌碰下轨：不买不卖
            pass
    if close >= ind_s['boll_u']*0.995:
        if not ind_s['trend_up']:
            sell += 1.5
        else:
            # 上涨碰上轨：连续上影才加卖分
            row1 = df.iloc[-1]
            row2 = df.iloc[-2]
            body1 = abs(row1['close'] - row1['open'])
            upper1 = row1['high'] - max(row1['open'], row1['close'])
            body2 = abs(row2['close'] - row2['open'])
            upper2 = row2['high'] - max(row2['open'], row2['close'])
            two_upper = upper1 > body1*1.5 and upper2 > body2*1.5
            if two_upper:
                sell += 1.5
            else:
                buy += 0.5
    # 连续2根长下影+跌到下轨：卖分减2，不割在支撑位
    row1 = df.iloc[-1]
    row2 = df.iloc[-2]
    body1 = abs(row1['close'] - row1['open'])
    lower1 = min(row1['open'], row1['close']) - row1['low']
    body2 = abs(row2['close'] - row2['open'])
    lower2 = min(row2['open'], row2['close']) - row2['low']
    two_lower = lower1 > body1*1.5 and lower2 > body2*1.5
    if two_lower and close <= ind_s['boll_l']*1.01:
        sell -= 2
    # RSI规则（双周期共振）
    # 15m RSI
    if ind_s['rsi'] <30: buy +=1
    elif ind_s['rsi']>80: sell +=1.5
    elif ind_s['rsi']>70: sell +=1
    # 1h RSI共振
    if ind_l['rsi'] <30: buy +=1
    elif ind_l['rsi']>80: sell +=1.5
    elif ind_l['rsi']>70: sell +=1
    # 资金规则
    if flow['net_inflow'] > 1000: buy +=1
    if flow['net_inflow'] < -1000: sell +=1
    # MACD金叉/死叉
    if ind_s['macd_gold']: buy +=1
    if ind_s['macd_dead']: sell +=1
    # KDJ打分
    if ind_s['kdj_j'] < 0: buy +=1
    if ind_s['kdj_j'] > 100: sell +=1
    if ind_s['k_gold']: buy +=0.5
    if ind_s['k_dead']: sell +=0.5
    # 大户多空比：阈值改成>1.1买，<0.9卖
    if top_ratio < 0.9: sell +=1
    if top_ratio > 1.1: buy +=1
    # 资金持续流出时，就算到下轨也不抄底：买分减1
    if flow['net_inflow'] < -1000 and close <= ind_s['boll_l']*1.01:
        buy -= 1
    # BOLL收口降权
    boll_width = (ind_s['boll_u'] - ind_s['boll_l']) / ind_s['boll_m']
    if boll_width < 0.03:
        buy -=1
        sell -=1
    return buy, sell

def get_signal(coin, b_score, s_score, ind_s, ind_l):
    # 双周期共振才出信号：15m和1h方向一致
    s_buy = ind_s['rsi'] < 45 and ind_s['close'] > ind_s['boll_m']*0.99
    l_buy = ind_l['rsi'] < 45 and ind_l['close'] > ind_l['boll_m']*0.99
    s_sell = ind_s['rsi'] > 55 and ind_s['close'] < ind_s['boll_m']*1.01
    l_sell = ind_l['rsi'] > 55 and ind_l['close'] < ind_l['boll_m']*1.01
    # 判断当前信号：必须双周期共振
    current = "观望"
    if b_score >= BUY_SCORE_THRESHOLD and s_buy and l_buy:
        current = "买入"
    if s_score >= SELL_SCORE_THRESHOLD and s_sell and l_sell:
        current = "卖出"
    # 信号反转提醒
    reverse_alert = None
    if coin in last_signal and last_signal[coin] != current and current != "观望":
        reverse_alert = f"信号反转：{last_signal[coin]}→{current}"
    last_signal[coin] = current
    return current, reverse_alert
