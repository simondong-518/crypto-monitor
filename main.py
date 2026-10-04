# -*- coding: utf-8 -*-
import sys
import io
# 强制整个程序用UTF-8编码，解决Windows下中文乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import json
import time
import re
# 统一资金换算：亿/万/千
def fmt_money(v):
    """统一资金单位：亿 / 万 / 元。负号统一放在 $ 前面（原来正数是 $x 万、负数是 -$x 万，看着别扭）。

    修正点：门槛原来写成 >= 1e8 亿 / >= 1e4 万 / else 千，
    所以 5 万以下会显示成"$50.0千"（应该显示"元"）。
    """
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 100000000:
        return f"{sign}${a/100000000:.2f}亿"
    if a >= 10000:
        return f"{sign}${a/10000:.1f}万"
    return f"{sign}${a:.0f}"
from datetime import datetime
from config import *
from api import get_kline, get_trades, get_ls, get_btc_chg, check_events, get_flow_1h
from indicators import get_indicator, get_daily_trend
from strategy import calc_score, get_signal, last_signal
from notifier import send_wx, beep
from alert_state import AlertState, stable_alert_key
from news import get_latest_news
pushed_news = set()
from backtest import backtest, daily_backtest, last_result as last_backtest_result

# ============================================================
# 报警状态：**冷却制**替代原来的"每个信号最多推 3 次"
#
# 原来那一套（pushed[key] < MAX_PUSH_PER_SIGNAL）的问题是：一个止损/跑路信号
# 推满 3 次后**当天彻底哑掉**，屏幕上完全看不出来；为了绕开它又在下面加了 4 处
# "方向反转清空计数""创新高清零"之类的补丁，逻辑越叠越难推理。
# 现在：首次必报；条件仍在则每过 ALERT_COOLDOWN_MIN 分钟重报，**不设上限**。
# ============================================================
state = AlertState(ALERT_STATE_FILE, ALERT_COOLDOWN_MIN)


def should_alert(key):
    """值无关的稳定 key → 判断该不该上报（判定与提交分开，方便先算清楚）。"""
    return state.should_report(key)


def mark_alert(key):
    state.mark(key)
    save_pushed()          # 顺带落盘，进程被杀也不丢冷却状态


def alert_reason(key):
    return state.why(key)

# 加载推送记录
pushed_file = "pushed.json"
try:
    with open(pushed_file, "r") as f:
        pushed = json.load(f)
except:
    pushed = {}

# 记录每个币上一轮的方向状态，用于信号反转时自动清空计数
LAST_FLOW_DIR = {}  # 1=流入，-1=流出，0=中性
LAST_RSI_STATE = {} # over=超买，under=超卖，normal=中性
# 记录每个币当天最大的15分钟资金流入/流出，突破历史极值时自动重置计数
MAX_FLOW_IN_15M = {}
MAX_FLOW_OUT_15M = {}

# 瀛樻渶杩戜竴娆″洖娴嬬粨鏋?
last_backtest_result = ""

def save_pushed():
    with open(pushed_file, "w") as f:
        json.dump(pushed, f)

def analyze_trades(trades):
    buy_v = sell_v = 0
    for t in trades:
        v = float(t['amount']) * float(t['price'])
        if t['side'] == 'buy': buy_v += v
        else: sell_v += v
    return {"buy_volume": buy_v, "sell_volume": sell_v, "net_inflow": buy_v - sell_v}

# 动态更新当日有效高低点
def update_daily_extreme(pair, df, avg_vol):
    today = datetime.now().strftime("%Y-%m-%d")
    if DAILY_EXTREME["date"] != today:
        DAILY_EXTREME["date"] = today
        DAILY_EXTREME["high"] = {}
        DAILY_EXTREME["low"] = {}
    row = df.iloc[-1]
    open_p = row['open']
    close_p = row['close']
    high_p = row['high']
    low_p = row['low']
    vol_p = row['volume']
    body = abs(close_p - open_p)
    upper_shadow = high_p - max(open_p, close_p)
    lower_shadow = min(open_p, close_p) - low_p
    coin = pair.replace("_USDT", "")
    # 初始化
    if coin not in DAILY_EXTREME["high"]:
        DAILY_EXTREME["high"][coin] = close_p
    if coin not in DAILY_EXTREME["low"]:
        DAILY_EXTREME["low"][coin] = close_p
    # 更新有效高点：长上影插针不算，用收盘价；正常收盘新高就更新
    # 注：原来这里在"创新高/创新低"时会遍历 pushed 清空该币的止盈/低吸计数。
    # 那是为了绕开"最多推 3 次"的哑火问题；现在由 alert_state 的冷却制统一处理，
    # 这些清空动作已无必要（删掉后 key 的语义更单纯，也更容易验证）。
    if upper_shadow > body*2:
        # 长上影，是压力位，用收盘价当有效高点
        if close_p > DAILY_EXTREME["high"][coin]:
            DAILY_EXTREME["high"][coin] = close_p
    else:
        if close_p > DAILY_EXTREME["high"][coin]:
            DAILY_EXTREME["high"][coin] = close_p
    # 更新有效低点：缩量长下影不算，放量下影是真底，用收盘价
    if lower_shadow > body*2:
        if vol_p < avg_vol*0.5:
            # 缩量假插针，忽略
            pass
        else:
            # 放量真底，用收盘价当有效低点
            if close_p < DAILY_EXTREME["low"][coin]:
                DAILY_EXTREME["low"][coin] = close_p
    else:
        if close_p < DAILY_EXTREME["low"][coin]:
            DAILY_EXTREME["low"][coin] = close_p
    return DAILY_EXTREME["high"][coin], DAILY_EXTREME["low"][coin]

def monitor_once():
    btc_chg = get_btc_chg()
    # BTC暴跌>3%避险提醒
    if btc_chg < -3:
        key_btc = "BTC_暴跌预警"
        if should_alert(key_btc):
            mark_alert(key_btc)
            send_wx("⚠️ BTC暴跌预警", f"BTC今日跌{btc_chg:.1f}%，所有币大概率跟跌，别抄底，手里有币逢高减仓")
    # BTC跌>1%温和风险提示
    elif btc_chg < -1:
        key_btc = "BTC_温和风险提示"
        if should_alert(key_btc):
            mark_alert(key_btc)
            send_wx("⚠️ BTC风险提示", f"BTC今日跌{btc_chg:.1f}%，小币可能补跌，注意仓位")
    # 新闻提醒：宏观事件/单币新闻单独推，不参与打分
    coin_news, macro_news = get_latest_news()
    for n in macro_news:
        if n not in pushed_news:
            pushed_news.add(n)
            send_wx("📰 宏观事件提醒", n)
    for n in coin_news:
        if n not in pushed_news:
            pushed_news.add(n)
            send_wx("📰 币圈新闻", n)
    # 自定义到价提醒
    for alert_pair, (take_profit, stop_loss) in PRICE_ALERT.items():
        coin = alert_pair.replace("_USDT","")
        try:
            ind = get_indicator(alert_pair, "15m")
            price = ind['close']
            key_tp = f"{coin}_到止盈价"
            key_sl = f"{coin}_到止损价"
            if price >= take_profit and should_alert(key_tp):
                mark_alert(key_tp)
                send_wx(f"✅ {coin}到止盈价！", f"现价{price}，到你设置的止盈价{take_profit}，可以卖出止盈了")
                beep()
            if price <= stop_loss and should_alert(key_sl):
                mark_alert(key_sl)
                send_wx(f"⚠️ {coin}到止损价！", f"现价{price}，到你设置的止损价{stop_loss}，注意风险")
                beep()
        except: pass
    alerts_all = []
    lines = ["# 📈 K线监测报告", f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    for pair in CURRENCY_PAIRS:
        coin = pair.replace("_USDT", "")
        try:
            ind_s = get_indicator(pair, "15m")
            ind_l = get_indicator(pair, "1h")
            daily_up = get_daily_trend(pair)
            trades = get_trades(pair)
            flow = analyze_trades(trades)
            # 计算1h累计资金
            flow_1h = get_flow_1h(pair)
            # 注：原来这里有 4 段"方向反转/创新高就清空计数"的补丁（约 60 行），
            # 目的是绕开"每个信号最多推 3 次"导致的哑火。现在由 alert_state 的
            # **冷却制**统一负责（首次必报、按间隔重报、不设上限），这 4 段补丁已无必要，
            # 删掉后行为更可预期、代码少一半。
            cur_flow_dir = 1 if flow_1h > 50000 else (-1 if flow_1h < -50000 else 0)
            LAST_FLOW_DIR[coin] = cur_flow_dir
            # RSI 状态仅用于报告展示
            cur_rsi = ind_s['rsi']
            if cur_rsi >= 75:
                cur_rsi_state = "over"
            elif cur_rsi <= 25:
                cur_rsi_state = "under"
            else:
                cur_rsi_state = "normal"
            LAST_RSI_STATE[coin] = cur_rsi_state
            # 计算taker买卖笔数
            buy_taker = sum(1 for t in trades if t['side']=='buy')
            sell_taker = sum(1 for t in trades if t['side']=='sell')
            ls = get_ls(pair)
            # 兼容get_ls返回列表或字典的情况
            if isinstance(ls, dict):
                ls = ls.get('data', [])
            lsd = ls[-1] if ls else {'top_lsr_account': 1}
            top_ratio = float(lsd['top_lsr_account'])
            # 打分
            b_score, s_score = calc_score(ind_s, ind_l, flow, top_ratio, ind_s['df'])
            # 日线大趋势过滤：日线向下，买分减1.5
            if not daily_up:
                b_score -= 1.5
            # 4小时大趋势过滤
            ind_4h = get_indicator(pair, "4h")
            if not ind_4h['trend_up']:
                b_score -= 1
            current_signal = get_signal(b_score, s_score)
            reverse_alert = ""
            # 生成提醒
            alerts = []
            threshold = CHG_THRESHOLD.get(coin, CHG_THRESHOLD['default'])
            # 涨跌幅提醒必须伴随成交量>1.2倍平均量
            avg_vol = ind_s['df']['volume'].rolling(20).mean().iloc[-1]
            cur_vol = ind_s['df']['volume'].iloc[-1]
            vol_enough = cur_vol > avg_vol * 1.2
            # 更新动态有效高低点
            eff_high, eff_low = update_daily_extreme(pair, ind_s['df'], avg_vol)
            # 高点提醒：碰到当日有效高点+长上影+资金流出+大户偏空
            row1 = ind_s['df'].iloc[-1]
            body1 = abs(row1['close'] - row1['open'])
            upper1 = row1['high'] - max(row1['open'], row1['close'])
            day_chg_from_low = (ind_s['close'] - eff_low)/eff_low*100
            if upper1 > body1*2 and abs(ind_s['close'] - eff_high)/eff_high < 0.001 \
                and flow['net_inflow'] < -1000 and top_ratio < 0.7 and day_chg_from_low >=5:
                key_high = f"{coin}_当日高点"
                if should_alert(key_high):
                    mark_alert(key_high)
                    alerts.append("🔴 触及当日真高，主力出货，注意止盈落袋")
            # 低点提醒：碰到当日有效低点+放量长下影+资金流入+大户不偏空
            lower1 = min(row1['open'], row1['close']) - row1['low']
            day_chg_from_high = (eff_high - ind_s['close'])/eff_high*100
            if lower1 > body1*2 and cur_vol >= avg_vol*1 and abs(ind_s['close'] - eff_low)/eff_low <0.001 \
                and flow['net_inflow'] > 1000 and top_ratio > 0.7 and day_chg_from_high >=3:
                key_low = f"{coin}_当日低点"
                if should_alert(key_low):
                    mark_alert(key_low)
                    alerts.append("🟢 触及当日真底，主力接盘，关注买入机会")
            # 动态移动止盈：从有效高点回撤到阈值
            trail_ratio = TRAILING_STOP.get(pair, 0.035)
            drawdown = (eff_high - ind_s['close'])/eff_high
            if drawdown >= trail_ratio:
                key_trail = f"{coin}_移动止盈"
                if should_alert(key_trail):
                    mark_alert(key_trail)
                    alerts.append(f"⚠️ 从高点回撤{drawdown*100:.1f}%，移动止盈落袋")
            if abs(ind_s['day_chg']) >= 5:
                alerts.append(f"今日{'大涨' if ind_s['day_chg']>0 else '大跌'}{ind_s['day_chg']:.1f}%")
                if ind_s['trend_up'] and ind_s['day_chg']>0:
                    alerts.append("，趋势启动，拿住")
            elif abs(ind_s['day_chg']) >= threshold and vol_enough:
                alerts.append(f"今日{'大涨' if ind_s['day_chg']>0 else '大跌'}{ind_s['day_chg']:.1f}%")
            # 缩量上涨提醒
            if ind_s['day_chg']>=3 and not vol_enough:
                alerts.append("⚠️ 缩量上涨，别追高")
            ma20 = ind_s['df']['close'].rolling(20).mean().iloc[-1]
            prev_close = ind_s['df']['close'].iloc[-2]
            if prev_close > ma20 and ind_s['close'] < ma20 and ind_s['trend_up']:
                alerts.append("⚠️ 跌破MA20，止盈落袋")
            # EMA金叉死叉提醒
            if ind_s['golden_cross']:
                key_gold = f"{coin}_EMA金叉"
                if should_alert(key_gold):
                    mark_alert(key_gold)
                    alerts.append("🟢 EMA金叉，短线多头启动")
            if ind_s['dead_cross']:
                key_dead = f"{coin}_EMA死叉"
                if should_alert(key_dead):
                    mark_alert(key_dead)
                    alerts.append("🔴 EMA死叉，短线空头启动")
            # 新增：突破BOLL上轨提醒
            if ind_s['close'] > ind_s['boll_u'] and vol_enough:
                key_break = f"{coin}_突破BOLL上轨"
                if should_alert(key_break):
                    mark_alert(key_break)
                    alerts.append(f"✅ 放量突破BOLL上轨{ind_s['boll_u']:.4f}，可以追多")
            if reverse_alert:
                alerts.append(reverse_alert)
            # 新增：跌破BOLL下轨超卖提醒
            if ind_s['close'] < ind_s['boll_l']:
                key_break_l = f"{coin}_跌破BOLL下轨"
                if should_alert(key_break_l):
                    mark_alert(key_break_l)
                    alerts.append(f"🟢 跌破BOLL下轨{ind_s['boll_l']:.4f}，超卖低吸机会")
            # 假突破上轨提醒：上根在上方，本根跌回上轨里面
            df_s = ind_s['df']
            prev_close = df_s.iloc[-2]['close']
            if prev_close > ind_s['boll_u'] and ind_s['close'] < ind_s['boll_u']:
                key_fake_up = f"{coin}_假突破上轨"
                if should_alert(key_fake_up):
                    mark_alert(key_fake_up)
                    alerts.append(f"⚠️ 假突破上轨跌回，别追多")
            # 假跌破下轨提醒：上根在下方，本根涨回下轨里面
            if prev_close < ind_s['boll_l'] and ind_s['close'] > ind_s['boll_l']:
                key_fake_down = f"{coin}_假跌破下轨"
                if should_alert(key_fake_down):
                    mark_alert(key_fake_down)
                    alerts.append(f"🟢 假跌破下轨涨回，别恐慌割肉")
            # 新增：资金大幅异动提醒
            if flow_1h > 100000:
                key_flow = f"{coin}_主力大幅进"
                if should_alert(key_flow):
                    mark_alert(key_flow)
                    alerts.append(f"🟢 1h资金净流入{fmt_money(flow_1h)}，主力大幅进场")
            elif flow_1h < -100000:
                key_flow = f"{coin}_主力大幅出"
                if should_alert(key_flow):
                    mark_alert(key_flow)
                    alerts.append(f"🔴 1h资金净流出{fmt_money(-flow_1h)}，主力大幅跑路")
            # 持续流出提醒：1h流出超50万，就算推过3次也再提醒
            if flow_1h < -500000:
                key_persist = f"{coin}_持续流出风险"
                if should_alert(key_persist):
                    mark_alert(key_persist)
                    alerts.append(f"⚠️ 1h累计流出{fmt_money(-flow_1h)}，持续跑路，注意风险")
            # 新增：大户极端多空比提醒
            try:
                ls_ratio = float(ls[-1]['top_lsr_account'])
            except:
                ls_ratio = 1
            if ls_ratio < 0.5:
                key_ls = f"{coin}_大户极空"
                if should_alert(key_ls):
                    mark_alert(key_ls)
                    alerts.append("🔴 大户多空比<0.5，极端偏空")
            elif ls_ratio > 2:
                key_ls = f"{coin}_大户极多"
                if should_alert(key_ls):
                    mark_alert(key_ls)
                    alerts.append("🟢 大户多空比>2，极端偏多")
            # 新增：突破前高/前低0.5%就提前提醒，不等涨/跌2%
            df_s = ind_s['df']
            today_high = ind_s['today_high']
            today_low = ind_s['today_low']
            key_new_high = f"{coin}_提前突破前高"
            if ind_s['close'] > today_high*1.005 and should_alert(key_new_high):
                mark_alert(key_new_high)
                alerts.append(f"🚀 突破前高0.5%，正在创新高")
            key_new_low = f"{coin}_提前跌破前低"
            if ind_s['close'] < today_low*0.995 and should_alert(key_new_low):
                mark_alert(key_new_low)
                alerts.append(f"🔻 跌破前低0.5%，正在创新低")
            # 新增：15分钟资金流斜率，提前发现主力进场/跑路
            recent_flow_15 = flow['net_inflow']
            key_fast_flow = f"{coin}_资金突然加速"
            # 大方向判断：避免和1h大方向矛盾
            big_out_direction = flow_1h < -50000
            big_in_direction = flow_1h > 50000
            # 分币种+分量级设基础阈值
            vol_ratio = ind_s['vol_now'] / ind_s['vol_ma'] if ind_s['vol_ma']>0 else 1
            if coin == 'BTC':
                base_in_thr = 30000 if vol_ratio >=1.2 else 100000
                base_out_thr = base_in_thr
            elif coin == 'CYS':
                base_in_thr = 3000 if vol_ratio >=1.2 else 10000
                base_out_thr = base_in_thr
            else:
                base_in_thr = 15000 if vol_ratio >=1.2 else 30000
                base_out_thr = base_in_thr
            # 按BOLL趋势动态调阈值
            close = ind_s['close']
            boll_u = ind_s['boll_u']
            boll_m = ind_s['boll_mid']
            boll_l = ind_s['boll_l']
            # 下降趋势：三轨向下+价在中轨下，阈值翻倍
            if boll_l < boll_m < boll_u and close < boll_m:   # 修：上轨>中轨>下轨；原来写反了，条件永远为假
                base_in_thr *= 2
            # 接近上轨：流入阈值提高别追高，流出阈值降低逃顶
            if (boll_u - close)/close < 0.005:
                base_in_thr *= 1.5
                base_out_thr *= 0.7
            # 接近下轨：流出阈值提高别割底，流入阈值降低抓低吸
            if (close - boll_l)/close < 0.005:
                base_out_thr *= 1.5
                base_in_thr *= 0.7
            fast_thr = max(base_in_thr, base_out_thr)
            # 连续2轮确认，防单笔毛刺
            global FAST_FLOW_CONFIRM
            if 'FAST_FLOW_CONFIRM' not in globals():
                FAST_FLOW_CONFIRM = {}
            cur_confirm_key = f"{coin}_in" if recent_flow_15>0 else f"{coin}_out"
            prev_confirm = FAST_FLOW_CONFIRM.get(cur_confirm_key, 0)
            FAST_FLOW_CONFIRM[cur_confirm_key] = 1 if abs(recent_flow_15) > fast_thr else 0
            confirm_pass = prev_confirm == 1
            # 流入和流出用各自阈值判断
            in_trigger = recent_flow_15 > base_in_thr and not big_out_direction
            out_trigger = recent_flow_15 < -base_out_thr and not big_in_direction
            if in_trigger and confirm_pass:
                prev_max_in = MAX_FLOW_IN_15M.get(coin, 0)
                if recent_flow_15 > prev_max_in:
                    # 突破当天最大流入，自动清空计数重新提醒
                    MAX_FLOW_IN_15M[coin] = recent_flow_15
                    if key_fast_flow in pushed:
                        del pushed[key_fast_flow]
                if should_alert(key_fast_flow):
                    mark_alert(key_fast_flow)
                    alerts.append(f"⚡ 最近15分钟资金流入{fmt_money(recent_flow_15)}，主力突然进场")
            elif out_trigger and confirm_pass:
                prev_max_out = MAX_FLOW_OUT_15M.get(coin, 0)
                cur_out_abs = -recent_flow_15
                if cur_out_abs > prev_max_out:
                    # 突破当天最大流出，自动清空计数重新提醒
                    MAX_FLOW_OUT_15M[coin] = cur_out_abs
                    if key_fast_flow in pushed:
                        del pushed[key_fast_flow]
                if should_alert(key_fast_flow):
                    mark_alert(key_fast_flow)
                    alerts.append(f"⚡ 最近15分钟资金流出{fmt_money(cur_out_abs)}，主力突然跑路")
            # 新增：急涨预警，提前发现拉升，别追高（30分钟内涨≥2%就提醒）
            recent_chg = (df_s['close'].iloc[-1] - df_s['close'].iloc[-3]) / df_s['close'].iloc[-3] * 100
            if recent_chg >= 2 and vol_enough:
                key_rush = f"{coin}_急涨预警"
                if should_alert(key_rush):
                    mark_alert(key_rush)
                    alerts.append(f"⚡ 最近30分钟急涨{recent_chg:.1f}%，别追高")
            elif recent_chg <= -2 and vol_enough:
                key_drop = f"{coin}_急跌预警"
                if should_alert(key_drop):
                    mark_alert(key_drop)
                    alerts.append(f"⚡ 最近30分钟急跌{-recent_chg:.1f}%，别恐慌割肉")
            # 新增：RSI超买+第一根上影就提醒，不等连续2根
            if ind_s['rsi'] >=75:
                row1 = df_s.iloc[-1]
                body1 = abs(row1['close'] - row1['open'])
                upper1 = row1['high'] - max(row1['open'], row1['close'])
                if upper1 > body1*1.5:
                    key_upper = f"{coin}_上影预警"
                    if should_alert(key_upper):
                        mark_alert(key_upper)
                        alerts.append("⚠️ RSI超买+第一根长上影，上方抛压出来了")
            # 对称：RSI超卖+第一根下影就提醒低吸
            if ind_s['rsi'] <=25:
                row1 = df_s.iloc[-1]
                body1 = abs(row1['close'] - row1['open'])
                lower1 = min(row1['open'], row1['close']) - row1['low']
                if lower1 > body1*1.5:
                    key_lower = f"{coin}_下影预警"
                    if should_alert(key_lower):
                        mark_alert(key_lower)
                        alerts.append("🟢 RSI超卖+第一根长下影，超卖低吸机会")
            # KDJ J值极端提醒
            if ind_s['kdj_overbought']:
                key_kdj_over = f"{coin}_KDJ超买"
                if should_alert(key_kdj_over):
                    mark_alert(key_kdj_over)
                    alerts.append(f"⚠️ KDJ J值{ind_s['kdj_j']:.0f}超买，短线别追高")
            if ind_s['kdj_oversold']:
                key_kdj_under = f"{coin}_KDJ超卖"
                if should_alert(key_kdj_under):
                    mark_alert(key_kdj_under)
                    alerts.append(f"🟢 KDJ J值{ind_s['kdj_j']:.0f}超卖，短线有反弹需求")
            # 新增：实时触底反弹预警，不等K线收线，从30分钟最低点反弹1.5%就提醒，超过3%就不提醒
            recent_low_30m = df_s['low'].tail(2).min()
            bounce_from_low = (ind_s['close'] - recent_low_30m) / recent_low_30m * 100
            if 1.5 <= bounce_from_low <= 3:
                key_bounce = f"{coin}_实时触底反弹"
                if should_alert(key_bounce):
                    mark_alert(key_bounce)
                    alerts.append(f"🟢 从30分钟最低点反弹{bounce_from_low:.1f}%，V反初现")
            # 对称：实时见顶回落预警，从30分钟最高点跌1.5%-3%就提醒，超过3%就不提醒
            recent_high_30m = df_s['high'].tail(2).max()
            drop_from_high = (recent_high_30m - ind_s['close']) / recent_high_30m * 100
            if 1.5 <= drop_from_high <= 3:
                key_drop_top = f"{coin}_实时见顶回落"
                if should_alert(key_drop_top):
                    mark_alert(key_drop_top)
                    alerts.append(f"🔴 从30分钟最高点回落{drop_from_high:.1f}%，见顶信号")
            if alerts:
                alert_str = ''.join(alerts)
                # ★ 修 P0-1：原来 key = f"{coin}_{整串报警文本}"（再用正则抹掉百分比）——
                #   1) 任一条目增删都产生新 key；2) 不同含义的报警会撞成同一个 key。
                #   现在：**每条报警各自一个值无关的稳定 key**，逐条走冷却判定。
                fired_this_round = []
                for one in alerts:
                    akey = stable_alert_key(coin, one)
                    if should_alert(akey):
                        mark_alert(akey)
                        fired_this_round.append(one)
                if fired_this_round:
                    alerts_all.append((coin, fired_this_round))
            # 生成标准报告表格（和full_analysis格式完全一致）
            df_s = ind_s['df']
            today_high = ind_s['today_high']
            today_low = ind_s['today_low']
            rise_low = (ind_s['close'] - today_low)/today_low*100
            drawdown_high = (today_high - ind_s['close'])/today_high*100
            trail_thr = TRAILING_STOP.get(pair, 0.035)*100
            flow_1h_val = get_flow_1h(pair)
            upper_count = 0
            for i in range(-5,0):
                row = df_s.iloc[i]
                body = abs(row['close'] - row['open'])
                upper = row['high'] - max(row['open'], row['close'])
                if body>0 and upper > body*2:
                    upper_count +=1
            # 只有这个币触发了重要操作信号，才输出详细分析，否则跳过
            has_important = any(('止盈' in x or '买入' in x or '卖出' in x or '高抛' in x or '急跌V反' in x or '超卖下轨' in x or '突破BOLL上轨' in x or '真高' in x or '真底' in x) for x in alerts)
            if not has_important:
                continue
            lines.append(f"## {coin}/USDT 全方位分析:")
            lines.append("")
            lines.append(f"- **现价**: ${ind_s['close']:.4f}，今日 {ind_s['day_chg']:+.2f}%")
            lines.append(f"- **当日高低点**: 低{today_low:.4f} / 高{today_high:.4f}")
            lines.append(f"- **当前位置**: 从低点反弹{rise_low:.1f}% / 从高点回撤{drawdown_high:.1f}%")
            lines.append(f"- **移动止盈**: 阈值{trail_thr:.1f}%，还差{trail_thr - drawdown_high:.1f}%触发")
            trend_emoji = "🟢" if ind_s['trend_up'] else "🔴"
            trend_text = "上涨" if ind_s['trend_up'] else "下跌"
            trend_judge = "15分钟站上MA20" if ind_s['trend_up'] else "15分钟跌破MA20"
            lines.append(f"- **趋势**: {trend_emoji} {trend_text}（{trend_judge}）")
            lines.append(f"- **RSI**: 15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f}（中性）")
            space_up = (ind_s['boll_u'] - ind_s['close'])/ind_s['close']*100
            lines.append(f"- **BOLL上轨**: {ind_s['boll_u']:.4f}，还有{space_up:.1f}%空间")
            net_flow = flow['net_inflow']
            if net_flow >=0:
                flow_text = f"净流入{fmt_money(net_flow)}"
            else:
                flow_text = f"净流出{fmt_money(-net_flow)}"
            flow_judge = "主力在进" if net_flow>1000 else "主力在跑" if net_flow<-1000 else "平衡"
            lines.append(f"- **现货资金(瞬时)**: {flow_text}（{flow_judge}）")
            if flow_1h_val >=0:
                flow1h_text = f"净流入{fmt_money(flow_1h_val)}"
            else:
                flow1h_text = f"净流出{fmt_money(-flow_1h_val)}"
            flow1h_judge = "1小时主力大幅进" if flow_1h_val>10000 else "1小时主力大幅跑" if flow_1h_val<-10000 else "1小时平衡"
            lines.append(f"- **现货资金(1h累计)**: {flow1h_text}（{flow1h_judge}）")
            ls_acc_judge = "大户偏空" if top_ratio<0.9 else "大户偏多" if top_ratio>1.1 else "平衡"
            lines.append(f"- **大户持仓多空比**: {top_ratio:.2f}（{ls_acc_judge}）")
            # ★ 修字段名：原来是 lsd.get('top_lsr_liq') —— 接口返回的字段叫 **top_lsr_size**，
            #   取不到就永远落到兜底 1.0，于是"大户账户多空比 1.00（平衡）"是假的。
            ls_size_ratio = float(lsd.get('top_lsr_size', 1.0) or 1.0)
            ls_size_judge = "明显偏空" if ls_size_ratio<0.5 else "明显偏多" if ls_size_ratio>2 else "平衡"
            lines.append(f"- **大户持仓量多空比**: {ls_size_ratio:.2f}（{ls_size_judge}）")
            taker_ratio = buy_taker/max(sell_taker,1)
            taker_judge = "散户疯狂主动买，追高" if taker_ratio>1.5 else "散户恐慌卖" if taker_ratio<0.7 else "平衡"
            lines.append(f"- **Taker主动买卖比**: {taker_ratio:.2f}（{taker_judge}）")
            # ★ 修假数据：原来硬编码 "- **资金费率**: 0.01%（正常）" —— 而 api.get_funding_rate()
            #   是个恒返回 (0.001, 0) 的占位实现，也就是说这一行**永远是假的**。
            #   要么接入真实来源，要么如实标注"未接入"，不要给假数字。
            lines.append("- **资金费率**: 未接入（暂无数据源，请勿参考）")
            upper_judge = "还在拉，没抛压" if upper_count<2 else "上方抛压重"
            lines.append(f"- **连续上影线**: {upper_count}根（{upper_judge}）")
            daily_text = "🟢" if daily_up else "🔴"
            daily_judge = "日线向上" if daily_up else "日线向下"
            lines.append(f"- **日线趋势**: {daily_text} {daily_judge}")
            sync_text = "和BTC同步" if ind_s['day_chg']*btc_chg>0 else "和BTC背离"
            lines.append(f"- **BTC联动**: BTC{btc_chg:+.2f}%（{sync_text}）")
            # 加关键支撑压力位
            lines.append(f"- **关键价位**: 下方支撑{today_low:.4f}，上方压力{today_high:.4f}")
            # 寤鸿
            stop_loss = ind_s['boll_l']
            take_profit = ind_s['boll_u']
            daily_judge = "日线向上" if daily_up else "日线向下"
            if current_signal == "买入":
                # 仓位建议：日线向上买3成，日线向下买1成
                if daily_up:
                    pos = "3鎴愪粨"
                else:
                    pos = "1成轻仓"
                hold_advice = f"可以买入{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"
                empty_advice = f"可以建仓{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"
            elif current_signal == "卖出":
                hold_advice = "全部止盈/止损卖出"
                empty_advice = "别买，等回调"
            else:
                # 综合所有策略维度判断建议，直接给最终唯一结论
                sell_score = 0
                buy_score = 0
                # 最高权重：触止盈线
                if any('止盈' in a for a in alerts):
                    sell_score += 10
                # 次高权重：主力大幅进/出
                if any('主力大幅出' in a or '主力大幅跑路' in a for a in alerts):
                    sell_score += 8
                if any('主力大幅进' in a or '主力大幅进场' in a for a in alerts):
                    buy_score += 8
                # 中等权重：大户极端/BOLL破轨，分位置反向判断
                dist_high = abs(ind_s['close'] - eff_high)/eff_high*100
                dist_low = abs(ind_s['close'] - eff_low)/eff_low*100
                # 大户极空<0.5：低位就是轧空看涨，高位才是真看跌
                if any('大户极空' in a for a in alerts):
                    if dist_low < 2:
                        buy_score += 5
                    else:
                        sell_score += 5
                # 大户极多>2：高位就是多头挤兑看跌，低位才是真看涨
                if any('大户极多' in a for a in alerts):
                    if dist_high < 2:
                        sell_score += 5
                    else:
                        buy_score += 5
                if any('超卖下轨' in a for a in alerts):
                    buy_score += 5
                if dist_high < 1:
                    sell_score += 3
                if dist_low < 1:
                    buy_score += 3
                # RSI辅助
                if ind_s['rsi'] < 20 and any('急跌V反' in a for a in alerts):
                    buy_score += 2
                if ind_s['rsi'] > 80 and any('连续上影' in a for a in alerts):
                    sell_score += 2
                # 低权重信号
                if any('连续上影' in a for a in alerts):
                    sell_score += 2
                if any('急跌V反' in a for a in alerts):
                    buy_score += 2
                # 直接给最终唯一结论
                if sell_score >= buy_score and sell_score >=5:
                    hold_advice = "现在优先逢高减仓"
                    empty_advice = "现在别接盘，等回调"
                elif buy_score > sell_score and buy_score >=5:
                    hold_advice = "现在可以持有，别割肉"
                    empty_advice = "现在可以小仓低吸"
                else:
                    hold_advice = "持有观望，不动"
                    empty_advice = "观望，等明确信号"
            lines.append("")
            lines.append(f"**📌 结论**: {trend_judge}，资金{flow_judge}，{daily_judge}")
            lines.append(f"**💼 持仓建议**: {hold_advice}")
            lines.append(f"**👀 空仓建议**: {empty_advice}")
            lines.append("")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"{coin}出错: {e}")
            continue
    if alerts_all:
        alert_lines = ["", f"## 🔔 新信号({len(alerts_all)}个币))", ""]
        need_detail = False
        for c, a in alerts_all:
            alert_lines.append(f"- **{c}**: {', '.join(a)}")
            # 判断有没有需要详细报告的重要操作信号
            if any(('止盈' in x or '买入' in x or '卖出' in x or '高抛' in x or '急跌V反' in x or '超卖下轨' in x or '突破BOLL上轨' in x or '真高' in x or '真底' in x) for x in a):
                need_detail = True
        alert_lines.append("")
        # 只有有重要信号才带详细报告，否则只推简短信号
        if need_detail:
            lines = lines[:3] + alert_lines + lines[3:]
            desp = "\n".join(lines)
        else:
            desp = "\n".join(alert_lines)
        # 加上最近4小时回测结果
        if last_backtest_result and need_detail:
            desp += "\n\n**最近4h回测**:\n" + last_backtest_result
        print(desp)
        if need_detail:
            title = f"🚨 重要操作提醒 - {datetime.now().strftime('%m-%d %H:%M')}"
        else:
            title = f"📈 K线监测 - {datetime.now().strftime('%m-%d %H:%M')}"
        send_wx(title, desp)
        save_pushed()
        # beep()

if __name__ == "__main__":
    print(f"启动模块化监测系统{VERSION} {VERSION_DATE}", flush=True)   # flush：重定向到文件时也要立刻可见
    # 打印单轮成本，避免"看着像没动"（实测单轮 30 秒左右）
    print(f"[启动] 监测 {len(CURRENCY_PAIRS)} 个币，{CHECK_INTERVAL} 秒一轮；"
          f"一轮要给每个币拉 15m/1h/4h K线与逐笔成交，通常 20-40 秒，属正常。", flush=True)
    print(f"[启动] 报警冷却 {ALERT_COOLDOWN_MIN} 分钟（首次必报，条件仍在则按间隔重报，不设上限）", flush=True)
    print(f"[启动] 推送通道：控制台 + {NOTIFY_FILE} 留痕 + 飞书（未配 FEISHU_WEBHOOK 时飞书自动跳过）", flush=True)

    last_backtest_ts = time.time()
    last_day = datetime.now().day
    monitor_once()
    while True:
        try:
            now_ts = time.time()
            now_hour = datetime.now().hour
            now_min = datetime.now().minute
            now_day = datetime.now().day
            # 每天0点自动清空推送记录
            if now_day != last_day:
                pushed.clear()
                save_pushed()
                last_day = now_day
            check_events()
            monitor_once()
            if now_ts - last_backtest_ts > BACKTEST_INTERVAL:
                backtest()
                last_backtest_ts = now_ts
            if now_hour == 23 and now_min >= 50:
                daily_backtest()
        except Exception as e:
            print(f"主循环出错: {e}", flush=True)
        time.sleep(CHECK_INTERVAL)


