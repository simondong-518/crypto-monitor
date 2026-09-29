# 2026-09-26 策略模块：打分和信号判断
# 2026-09-29 P1-1/P1-3：
#   · 所有「形态」判断改用最近两根**已收盘** bar（ind_s['shadows']），不再用 iloc[-1]/[-2]
#     —— iloc[-1] 是形成中的 bar，形态会在盘中反复变化
#   · 量能用 ind_s['vol_ratio']（已收盘 bar 的量能比）
#   · 大户多空比不再用固定 1.0 阈值，改用语币自身的滚动分位数 ls_pct（0~100 或 None）
from config import BUY_SCORE_THRESHOLD, SELL_SCORE_THRESHOLD, LS_BUY_PCT, LS_SELL_PCT

# 记录每个币上次信号状态，用于信号反转提醒
last_signal = {}

def calc_score(ind_s, ind_l, flow, ls_pct, df):
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
    boll_width = (ind_s['boll_u'] - ind_s['boll_l']) / ind_s['boll_m']
    vol_ratio = ind_s['vol_ratio']        # 已收盘 bar 的量能比（P1-1）
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
        # 收口+放量突破上轨=启动上涨，加买分
        if boll_width < 0.03 and vol_ratio > 1.5:
            buy +=1.5
        elif not ind_s['trend_up']:
            sell += 1.5
        else:
            # 上涨碰上轨：连续上影才加卖分（用最近两根**已收盘** bar）
            body1, upper1, _ = ind_s['shadows'][0]
            body2, upper2, _ = ind_s['shadows'][1]
            two_upper = upper1 > body1*2 and upper2 > body2*2
            if two_upper:
                sell += 1.5
            else:
                buy += 0.5
    # 连续3根阳线/阴线（补做2/3：原补丁脚本 fix_score.py / add_down3.py 的目标逻辑）
    # 用「已收盘」的3根 df.iloc[-4:-1]，排除形成中的 bar —— 原脚本用 df.tail(3) 会把未收盘 bar 算进去
    last3 = df.iloc[-4:-1]
    if len(last3) == 3:
        if (last3['close'] > last3['open']).all() and close > ind_s['boll_m']:
            buy += 1.5
        if (last3['close'] < last3['open']).all() and close < ind_s['boll_m']:
            sell += 1.5
    # 连续2根长下影+跌到下轨+从最低点反弹1-3%：卖分减2，加买分
    body1, _, lower1 = ind_s['shadows'][0]
    body2, _, lower2 = ind_s['shadows'][1]
    two_lower = lower1 > body1*2 and lower2 > body2*2
    recent_low = min(float(df['low'].iloc[-2]), float(df['low'].iloc[-3]))   # 最近两根已收盘 bar
    rebound_pct = (close - recent_low)/recent_low*100
    rebound_ok = 1 <= rebound_pct <=3
    if two_lower and close <= ind_s['boll_l']*1.01 and rebound_ok:
        sell -= 2
        buy +=1
    # RSI规则（双周期共振）
    # 上涨途中不随便喊卖：只有连续2根长上影才加RSI卖分
    body1, upper1, _ = ind_s['shadows'][0]
    body2, upper2, _ = ind_s['shadows'][1]
    two_upper = upper1 > body1*2 and upper2 > body2*2 and ind_s['boll_all_up']
    # 15m RSI
    if ind_s['rsi'] <30: buy +=1
    elif ind_s['rsi']>80 and two_upper: sell +=1.5
    elif ind_s['rsi']>70 and two_upper: sell +=1
    # 1h RSI共振
    if ind_l['rsi'] <30: buy +=1
    elif ind_l['rsi']>80 and two_upper: sell +=1.5
    elif ind_l['rsi']>70 and two_upper: sell +=1
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
    # 大户多空比（P1-3）：按币自身滚动分位数打分，阈值与方向都在 config 里
    # 原来是写死的 >1 加买分 / <1 加卖分 —— 实测 6 个币的 account 口径全在 0.48~0.67，
    # 所以"加买分"那一支**一次都拿不到**，"加卖分"近乎恒真。预热期 ls_pct=None，不加分。
    if ls_pct is not None:
        if ls_pct >= LS_BUY_PCT:
            buy += 1
        elif ls_pct <= LS_SELL_PCT:
            sell += 1
    # 资金持续流出时，就算到下轨也不抄底：买分减1
    if flow['net_inflow'] < -1000 and close <= ind_s['boll_l']*1.01:
        buy -= 1
    # BOLL收口如果没突破，降权
    if boll_width < 0.03 and close < ind_s['boll_u']*0.99:
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
