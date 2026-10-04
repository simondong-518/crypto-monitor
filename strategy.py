# 策略模块：打分和信号判断
from config import BUY_SCORE_THRESHOLD, SELL_SCORE_THRESHOLD

# 记录每个币上次信号状态，用于信号反转提醒
last_signal = {}

def calc_score(ind_s, ind_l, flow, top_ratio, df):
    buy = sell = 0
    close = ind_s['close']
    # BOLL三轨向上判断
    if close > ind_s['boll_u'] and ind_s['vol_enough']:
        buy += 2
    if close < ind_s['boll_l']:
        buy += 2
    # RSI打分
    if ind_s['rsi'] < 30:
        buy += 1
    if ind_s['rsi'] > 70:
        sell += 1
    # MACD打分
    if ind_s['dif'] > ind_s['dea'] and ind_s['macd']>0:
        buy += 0.5
    if ind_s['dif'] < ind_s['dea'] and ind_s['macd']<0:
        sell += 0.5
    # KDJ打分
    if ind_s['j'] < 20:
        buy += 0.5
    if ind_s['j'] > 80:
        sell += 0.5
    # 双周期共振
    if ind_l and ind_l['close'] > ind_l['ma20']:
        buy += 0.5
    # 资金打分
    if flow['net_inflow'] > 10000:
        buy += 1
    if flow['net_inflow'] < -10000:
        sell += 1
    # 大户多空比打分
    if top_ratio < 0.5:
        sell += 1
    if top_ratio > 2:
        buy += 1
    return buy, sell

def check_reverse(coin, current_signal):
    reverse_alert = ""
    if coin in last_signal and last_signal[coin] != current_signal:
        reverse_alert = f"信号反转: {last_signal[coin]} → {current_signal}"
    last_signal[coin] = current_signal
    return reverse_alert

def get_signal(buy, sell):
    if buy >= BUY_SCORE_THRESHOLD:
        return "买入"
    if sell >= SELL_SCORE_THRESHOLD:
        return "卖出"
    return "持有观望"
