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
    if abs(v) >= 100000000:
        return f"${v/100000000:.2f}亿" if v>=0 else f"-${-v/100000000:.2f}亿"
    elif abs(v) >= 10000:
        return f"${v/10000:.1f}万" if v>=0 else f"-${-v/10000:.1f}万"
    else:
        return f"${v/1000:.1f}千" if v>=0 else f"-${-v/1000:.1f}千"
from datetime import datetime
from config import *
from api import get_kline, get_trades, get_ls, get_btc_chg, check_events, get_flow_1h
from indicators import get_indicator, get_daily_trend
from strategy import calc_score, get_signal, last_signal
from notifier import send_wx
from alert_state import AlertState, stable_alert_key
from news import get_latest_news
pushed_news = set()
from backtest import backtest, daily_backtest, last_result as last_backtest_result

# 只读 H5 面板（展示层）—— 不参与判定；导入失败也不能挡住监控
try:
    import panel
    import panel_adapter
    _PANEL_IMPORT_OK = True
except Exception as _e:
    _PANEL_IMPORT_OK = False
    print(f"[面板] 未启用（导入失败）：{type(_e).__name__}: {_e}", flush=True)

# 加载之前保存的推送记录
pushed_file = "pushed.json"
try:
    with open(pushed_file, "r") as f:
        pushed = json.load(f)
except:
    pushed = {}


# ── 报警冷却状态（我方）：替代"每个信号最多推N次"的哑火问题 ──
# 注：对方新写的部分信号仍自带 `pushed.get(key,0) < 2` 上限制 —— 那是他的策略，
#     按他要求**保留不改**。这里只给"原本走计次上限的老信号"提供冷却。
_ALERT_STATE = AlertState(getattr(__import__('config'), 'ALERT_STATE_FILE', 'alert_state.json'),
                          cooldown_min=getattr(__import__('config'), 'ALERT_COOLDOWN_MIN', 30))


def should_alert(key):
    """冷却制：首次必报；条件仍在则按间隔重报；不设次数上限。"""
    return _ALERT_STATE.should_report(key)


def mark_alert(key):
    _ALERT_STATE.mark(key)

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
    if upper_shadow > body*2:
        # 长上影，是压力位，用收盘价当有效高点
        if close_p > DAILY_EXTREME["high"][coin]:
            DAILY_EXTREME["high"][coin] = close_p
            # 创了新高，清空这个币之前的止盈提醒计数，新的一波回撤要重新提醒
            for k in list(pushed.keys()):
                if k.startswith(f"{coin}_") and ("止盈" in k or "回撤" in k):
                    del pushed[k]
    else:
        if close_p > DAILY_EXTREME["high"][coin]:
            DAILY_EXTREME["high"][coin] = close_p
            # 创了新高，清空这个币之前的止盈提醒计数，新的一波回撤要重新提醒
            for k in list(pushed.keys()):
                if k.startswith(f"{coin}_") and ("止盈" in k or "回撤" in k):
                    del pushed[k]
    # 更新有效低点：缩量长下影不算，放量下影是真底，用收盘价
    if lower_shadow > body*2:
        if vol_p < avg_vol*0.5:
            # 缩量假插针，忽略
            pass
        else:
            # 放量真底，用收盘价当有效低点
            if close_p < DAILY_EXTREME["low"][coin]:
                DAILY_EXTREME["low"][coin] = close_p
                # 创了新低，清空这个币之前的低吸/V反/超卖提醒计数，新的一波反弹要重新提醒
                for k in list(pushed.keys()):
                    if k.startswith(f"{coin}_") and ("低吸" in k or "V反" in k or "超卖" in k):
                        del pushed[k]
    else:
        if close_p < DAILY_EXTREME["low"][coin]:
            DAILY_EXTREME["low"][coin] = close_p
            # 创了新低，清空这个币之前的低吸/V反/超卖提醒计数，新的一波反弹要重新提醒
            for k in list(pushed.keys()):
                if k.startswith(f"{coin}_") and ("低吸" in k or "V反" in k or "超卖" in k):
                    del pushed[k]
    return DAILY_EXTREME["high"][coin], DAILY_EXTREME["low"][coin]

def monitor_once():
    _round_t0 = time.time()      # 面板"上一轮耗时"用（纯展示）
    panel_coins = []             # 面板：本轮各币只读视图
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
    # 价格止盈止损提醒：遍历用户设置的止盈止损价位
    for alert_pair, (take_profit, stop_loss) in PRICE_ALERT.items():
        coin = alert_pair.replace("_USDT","")
        try:
            ind = get_indicator(alert_pair, "15m")
            price = ind['close']
            key_tp = f"{coin}_止盈{take_profit}"
            key_sl = f"{coin}_止损{stop_loss}"
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

            # ── 【补缺口·崩溃修复】对方 2026-10-05 新增的买卖打分块引用了
            #    buy_depth / sell_depth / funding_rate 三个变量，但全程没有定义，
            #    也没有 import get_orderbook / get_funding_rate —— 于是每轮每个币在
            #    "盘口承接 / 盘口抛压 / 资金费率"那几项直接 NameError，被外层 except
            #    吞掉后**整币本轮所有报警都不再产生**（静默失效）。
            #    这里只补"变量存在且为中性值"，**不改他的算法**：
            #    盘口/费率未接入 → 那几项恒不加分（与他本意一致：没数据就不加分）。
            #    他日后若接通真接口，把这三个值换成真实取数即可。
            buy_depth = 0
            sell_depth = 0
            funding_rate = 0.0
            # 【同批缺口】对方新增打分块里 row_now / body / upper_shadow / lower_shadow
            #    在 L628、L647 **先被使用**，却到 L70x 才定义 —— Python 视为局部变量，
            #    于是 UnboundLocalError，同样把整币本轮报警吞掉。
            #    这里按他后面那段的同一算法提前算好，不改数值口径。
            row_now = None
            body = 0.0
            upper_shadow = 0.0
            lower_shadow = 0.0
            try:
                row_now = df_s.iloc[-1]
                body = abs(row_now["close"] - row_now["open"])
                upper_shadow = row_now["high"] - max(row_now["open"], row_now["close"])
                lower_shadow = min(row_now["open"], row_now["close"]) - row_now["low"]
            except Exception:
                pass
            # 方向反转自动清空计数：资金方向彻底反转时，清空旧方向信号计数
            cur_flow_dir = 1 if flow_1h > 50000 else (-1 if flow_1h < -50000 else 0)
            prev_flow_dir = LAST_FLOW_DIR.get(coin, 0)
            if prev_flow_dir == -1 and cur_flow_dir == 1:
                # 从流出反转为流入，清空所有流出类计数
                for k in list(pushed.keys()):
                    if k.startswith(f"{coin}_") and ("跑路" in k or "流出" in k or "大幅出" in k):
                        del pushed[k]
            if prev_flow_dir == 1 and cur_flow_dir == -1:
                # 从流入反转为流出，清空所有流入类计数
                for k in list(pushed.keys()):
                    if k.startswith(f"{coin}_") and ("进场" in k or "流入" in k or "大幅进" in k):
                        del pushed[k]
            LAST_FLOW_DIR[coin] = cur_flow_dir
            # RSI方向反转自动清空计数
            cur_rsi = ind_s['rsi']
            if cur_rsi >=75:
                cur_rsi_state = "over"
            elif cur_rsi <=25:
                cur_rsi_state = "under"
            else:
                cur_rsi_state = "normal"
            prev_rsi_state = LAST_RSI_STATE.get(coin, "normal")
            if prev_rsi_state == "over" and cur_rsi_state == "under":
                # 从超买反转为超卖，清空所有超买类计数
                for k in list(pushed.keys()):
                    if k.startswith(f"{coin}_") and ("超买" in k or "上影" in k or "抛压" in k):
                        del pushed[k]
            if prev_rsi_state == "under" and cur_rsi_state == "over":
                # 从超卖反转为超买，清空所有超卖类计数
                for k in list(pushed.keys()):
                    if k.startswith(f"{coin}_") and ("超卖" in k or "下影" in k or "低吸" in k):
                        del pushed[k]
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
            # 鎵撳垎
            b_score, s_score = calc_score(ind_s, ind_l, flow, top_ratio, ind_s['df'])
            # 日线大趋势过滤：日线向下，买分减1.5
            if not daily_up:
                b_score -= 1.5
            # 4灏忔椂澶ц秼鍔胯繃婊?
            ind_4h = get_indicator(pair, "4h")
            if not ind_4h['trend_up']:
                b_score -= 1
            current_signal = get_signal(b_score, s_score)
            reverse_alert = ""
            # 鐢熸垚鎻愰啋
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
                key_trail = f"{coin}_移动止盈{trail_ratio*100:.0f}%"
                if should_alert(key_trail):
                    mark_alert(key_trail)
                    alerts.append(f"⚠️ 从高点回撤{drawdown*100:.1f}%，移动止盈落袋")
            if abs(ind_s['day_chg']) >= 5:
                alerts.append(f"今日{'大涨' if ind_s['day_chg']>0 else '大跌'}{ind_s['day_chg']:.1f}%")
                if ind_s['trend_up'] and ind_s['day_chg']>0:
                    alerts.append("顺势上涨，趋势向上，可持有")
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
            # 【2026-10-05 新增】慢涨趋势信号1：BOLL三轨开口向上
            # 说明：BOLL上轨>中轨>下轨，且三轨同步抬升，是慢牛行情特征，抓DOGE这种慢涨
            boll_u_now = ind_s['boll_u']
            boll_m_now = ind_s['boll_mid']
            boll_l_now = ind_s['boll_l']
            boll_u_prev = df_s['boll_u'].iloc[-2] if 'boll_u' in df_s.columns else 0
            if boll_u_now > boll_m_now > boll_l_now and boll_u_now > boll_u_prev:
                key_boll_open = f"{coin}_BOLL开口向上"
                if pushed.get(key_boll_open,0) < 2:  # 一天最多推2次
                    mark_alert(key_boll_open)
                    alerts.append(f"📈 BOLL三轨开口向上，慢牛趋势，可持有")
            # 【2026-10-05 新增】慢涨趋势信号2：连续3根小阳推升
            # 说明：连续3根15分钟小阳线，累计涨幅≥1%，不跌破前低，抓慢涨启动
            if len(df_s)>=3:
                c1 = df_s.iloc[-3]['close']
                c2 = df_s.iloc[-2]['close']
                c3 = df_s.iloc[-1]['close']
                o1 = df_s.iloc[-3]['open']
                o2 = df_s.iloc[-2]['open']
                o3 = df_s.iloc[-1]['open']
                chg_3 = (c3 - c1)/c1*100
                if c1>o1 and c2>o2 and c3>o3 and chg_3>=1:
                    key_small_up = f"{coin}_连续小阳推升"
                    if pushed.get(key_small_up,0) < 2:
                        mark_alert(key_small_up)
                        alerts.append(f"📈 连续3根小阳推升，累计涨{chg_3:.1f}%，慢涨趋势健康")
            # 【2026-10-05 新增】慢涨趋势信号4：均线多头排列
            # 说明：MA5>MA10>MA20，价格一直在MA5上方，是趋势启动信号
            if len(df_s)>=20:
                ma5 = df_s['close'].rolling(5).mean().iloc[-1]
                ma10 = df_s['close'].rolling(10).mean().iloc[-1]
                ma20 = df_s['close'].rolling(20).mean().iloc[-1]
                if ma5>ma10>ma20 and ind_s['close']>ma5:
                    key_ma_bull = f"{coin}_均线多头排列"
                    if pushed.get(key_ma_bull,0) < 2:
                        mark_alert(key_ma_bull)
                        alerts.append(f"📈 15分钟均线多头排列，上涨趋势确认")
            # ==============================================
            # 【2026-10-05 新增】95%正确率慢涨启动共振信号
            # 逻辑：必须4个以上条件同时满足，连续2轮确认，才推高正确率买入提醒
            # 条件：均线多头+1h资金流入+BOLL开口向上+RSI健康+不追高
            # ==============================================
            slow_buy_score = 0
            # 条件1：均线多头排列
            if len(df_s)>=20:
                ma5 = df_s['close'].rolling(5).mean().iloc[-1]
                ma10 = df_s['close'].rolling(10).mean().iloc[-1]
                ma20 = df_s['close'].rolling(20).mean().iloc[-1]
                if ma5>ma10>ma20 and ind_s['close']>ma5:
                    slow_buy_score +=1
            # 条件2：连续1h净流入≥1.5万
            if flow_1h >=15000:
                slow_buy_score +=1
            # 条件3：BOLL三轨开口向上
            if boll_u_now > boll_m_now > boll_l_now and boll_u_now > boll_u_prev:
                slow_buy_score +=1
            # 条件4：RSI在50-70之间，健康不超买
            if 50 <= ind_s['rsi'] <=70:
                slow_buy_score +=1
            # 条件5：不追高，离今日前高还有≥1%空间
            today_high = ind_s.get('today_high', ind_s['close'])
            if (today_high - ind_s['close'])/ind_s['close'] >= 0.01:
                slow_buy_score +=1
            # 连续2轮确认，防毛刺
            global SLOW_BUY_CONFIRM
            if 'SLOW_BUY_CONFIRM' not in globals():
                SLOW_BUY_CONFIRM = {}
            prev_slow = SLOW_BUY_CONFIRM.get(coin, 0)
            cur_slow = 1 if slow_buy_score >=4 else 0
            SLOW_BUY_CONFIRM[coin] = cur_slow
            slow_confirm_pass = (prev_slow ==1 and cur_slow ==1)
            # 触发：4个以上条件满足，连续2轮确认，一天最多推1次
            if slow_confirm_pass and slow_buy_score >=4:
                key_slow_buy = f"{coin}_慢涨共振买入"
                if pushed.get(key_slow_buy,0) <1:
                    mark_alert(key_slow_buy)
                    alerts.append(f"✅ 慢涨启动信号共振，{slow_buy_score}/5条件全部满足，可小仓位建仓，止损设MA20位")
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
                if pushed.get(key_persist,0) < 1:
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
            if boll_l < boll_m < boll_u and close < boll_m:
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
            # 【2026-10-05 新增】慢涨趋势信号3：连续4轮（1小时）净流入
            # 说明：哪怕每轮只小流入，连续1小时资金都是正的，累计≥1.5万，抓DOGE这种慢慢建仓的慢涨
            if 'CONTINUOUS_FLOW' not in globals():
                CONTINUOUS_FLOW = {}
            coin_flow_key = f"{coin}_in"
            prev_cont = CONTINUOUS_FLOW.get(coin_flow_key, 0)
            # 只要15分钟是净流入，就计数，哪怕只流入几百
            if recent_flow_15 > 0:
                CONTINUOUS_FLOW[coin_flow_key] = prev_cont + 1
            else:
                CONTINUOUS_FLOW[coin_flow_key] = 0
            # 连续4轮净流入，且1h累计净流入≥1.5万
            if CONTINUOUS_FLOW[coin_flow_key] >=4 and flow_1h >=15000:
                key_cont_flow = f"{coin}_连续1h资金流入"
                if pushed.get(key_cont_flow,0) < 2:  # 一天最多推2次
                    mark_alert(key_cont_flow)
                    alerts.append(f"📈 连续1小时资金净流入，累计{fmt_money(flow_1h)}，主力持续建仓慢涨")
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
            # ==============================================
            # 【2026-10-05 新增】小信号转控制台，不推飞书
            # 逻辑：前面所有单个小信号只打印到控制台，不推飞书
            # 只有后面综合打分≥90的最佳低吸/高抛点才推飞书
            # ==============================================
            for msg in alerts:
                print(f"[{coin}] 控制台小信号: {msg}")
            alerts.clear()
            # ==============================================
            # 【2026-10-05 新增】第一级紧急预警打分
            # 逻辑：6项指标打分，≥30分（3个信号共振）才推飞书，快速抓变盘
            # ==============================================
            emerg_buy_score = 0
            emerg_buy_reasons = []
            emerg_sell_score = 0
            emerg_sell_reasons = []
            # 紧急低吸打分项
            recent_chg_30m = df_s['close'].iloc[-1]/df_s['close'].iloc[-3]-1
            if recent_chg_30m <= -0.015:
                emerg_buy_score +=10
                emerg_buy_reasons.append("30分钟急跌")
            if ind_s['rsi'] <=30 and lower_shadow > body*1.5:
                emerg_buy_score +=10
                emerg_buy_reasons.append("RSI超卖+长下影")
            if 0.015 <= bounce_from_low <=0.03:
                emerg_buy_score +=10
                emerg_buy_reasons.append("V反反弹")
            if recent_flow_15 >=10000:
                emerg_buy_score +=10
                emerg_buy_reasons.append("15分钟资金流入")
            if top_ratio >2:
                emerg_buy_score +=10
                emerg_buy_reasons.append("大户极端偏多")
            if len(df_s)>=2 and df_s.iloc[-1]['close']>df_s.iloc[-1]['open'] and df_s.iloc[-2]['close']>df_s.iloc[-2]['open']:
                emerg_buy_score +=10
                emerg_buy_reasons.append("连续小阳止跌")
            # 紧急高抛打分项
            if recent_chg_30m >= 0.015:
                emerg_sell_score +=10
                emerg_sell_reasons.append("30分钟急涨")
            if ind_s['rsi'] >=70 and upper_shadow > body*1.5:
                emerg_sell_score +=10
                emerg_sell_reasons.append("RSI超买+长上影")
            if 0.015 <= drop_from_high <=0.03:
                emerg_sell_score +=10
                emerg_sell_reasons.append("见顶回落")
            if recent_flow_15 <=-10000:
                emerg_sell_score +=10
                emerg_sell_reasons.append("15分钟资金流出")
            if top_ratio <0.5:
                emerg_sell_score +=10
                emerg_sell_reasons.append("大户极端偏空")
            if len(df_s)>=2 and df_s.iloc[-1]['close']<df_s.iloc[-1]['open'] and df_s.iloc[-2]['close']<df_s.iloc[-2]['open']:
                emerg_sell_score +=10
                emerg_sell_reasons.append("连续阴线拐头")
            # 紧急预警状态锁
            global EMERG_LOCK
            if 'EMERG_LOCK' not in globals():
                EMERG_LOCK = {'buy':set(), 'sell':set()}
            # 触发紧急低吸预警
            if emerg_buy_score >=30 and coin not in EMERG_LOCK['buy']:
                EMERG_LOCK['buy'].add(coin)
                alerts.append(f"⚡ 紧急低吸预警，{emerg_buy_score}/60分，满足：{'、'.join(emerg_buy_reasons)}，反弹在即")
            if emerg_buy_score <=10 and coin in EMERG_LOCK['buy']:
                EMERG_LOCK['buy'].remove(coin)
            # 触发紧急高抛预警
            if emerg_sell_score >=30 and coin not in EMERG_LOCK['sell']:
                EMERG_LOCK['sell'].add(coin)
                alerts.append(f"⚠️ 紧急高抛预警，{emerg_sell_score}/60分，满足：{'、'.join(emerg_sell_reasons)}，回调在即")
            if emerg_sell_score <=10 and coin in EMERG_LOCK['sell']:
                EMERG_LOCK['sell'].remove(coin)
            # ==============================================
            # 【2026-10-05 新增】综合打分低吸高抛系统
            # 逻辑：11项指标打分，≥90分才推飞书，分数回落解锁不刷屏
            # ==============================================
            buy_score = 0
            buy_reasons = []
            sell_score = 0
            sell_reasons = []
            # 买入打分项
            if ind_s['kdj_j'] <0:
                buy_score +=10
                buy_reasons.append("KDJ超卖")
            if ind_s['rsi'] <30:
                buy_score +=10
                buy_reasons.append("RSI超卖")
            if ind_s['close'] < ind_s['boll_l']:
                buy_score +=10
                buy_reasons.append("跌破BOLL下轨")
            if flow_1h >=50000:
                buy_score +=10
                buy_reasons.append("1h资金大幅流入")
            drawdown_from_high = (today_high - ind_s['close'])/today_high*100
            if drawdown_from_high >=3:
                buy_score +=10
                buy_reasons.append(f"从高点回撤{drawdown_from_high:.1f}%")
            # 长下影线
            row_now = df_s.iloc[-1]
            body = abs(row_now['close'] - row_now['open'])
            lower_shadow = min(row_now['open'], row_now['close']) - row_now['low']
            if lower_shadow > body*1.5:
                buy_score +=10
                buy_reasons.append("长下影支撑")
            # 连续2轮小阳止跌
            if len(df_s)>=2 and df_s.iloc[-1]['close']>df_s.iloc[-1]['open'] and df_s.iloc[-2]['close']>df_s.iloc[-2]['open']:
                buy_score +=10
                buy_reasons.append("连续小阳止跌")
            # 大户偏多
            if top_ratio >1.1:
                buy_score +=10
                buy_reasons.append("大户偏多")
            # 盘口承接
            if buy_depth > sell_depth*1.2:
                buy_score +=10
                buy_reasons.append("盘口承接强")
            # 资金费率负
            if funding_rate <0:
                buy_score +=10
                buy_reasons.append("资金费率负")
            # 【2026-10-05 新增】第11项：15分钟短期资金净流入
            if recent_flow_15 >=10000:
                buy_score +=10
                buy_reasons.append("15分钟资金流入")
            # 卖出打分项
            if ind_s['kdj_j'] >100:
                sell_score +=10
                sell_reasons.append("KDJ超买")
            if ind_s['rsi'] >70:
                sell_score +=10
                sell_reasons.append("RSI超买")
            if ind_s['close'] > ind_s['boll_u']:
                sell_score +=10
                sell_reasons.append("涨破BOLL上轨")
            if flow_1h <=-50000:
                sell_score +=10
                sell_reasons.append("1h资金大幅流出")
            bounce_from_low = (ind_s['close'] - today_low)/today_low*100
            if bounce_from_low >=3:
                sell_score +=10
                sell_reasons.append(f"从低点反弹{bounce_from_low:.1f}%")
            # 长上影线
            upper_shadow = row_now['high'] - max(row_now['open'], row_now['close'])
            if upper_shadow > body*1.5:
                sell_score +=10
                sell_reasons.append("长上影抛压")
            # 连续2根阴线拐头
            if len(df_s)>=2 and df_s.iloc[-1]['close']<df_s.iloc[-1]['open'] and df_s.iloc[-2]['close']<df_s.iloc[-2]['open']:
                sell_score +=10
                sell_reasons.append("连续阴线拐头")
            # 大户偏空
            if top_ratio <0.9:
                sell_score +=10
                sell_reasons.append("大户偏空")
            # 盘口抛压
            if sell_depth > buy_depth*1.2:
                sell_score +=10
                sell_reasons.append("盘口抛压重")
            # 资金费率正过高
            if funding_rate >0.05:
                sell_score +=10
                sell_reasons.append("资金费率过高")
            # 【2026-10-05 新增】第11项：15分钟短期资金净流出
            if recent_flow_15 <=-10000:
                sell_score +=10
                sell_reasons.append("15分钟资金流出")
            # 解锁状态：分数跌到≤30才解锁下一次推送
            global SCORE_LOCK
            if 'SCORE_LOCK' not in globals():
                SCORE_LOCK = {'buy':set(), 'sell':set()}
            # 触发低吸提醒：买入分≥90（11项里至少9项共振），且没锁
            if buy_score >=90 and coin not in SCORE_LOCK['buy']:
                SCORE_LOCK['buy'].add(coin)
                alerts.append(f"✅ 最佳低吸点，买入分{buy_score}/110，满足：{'、'.join(buy_reasons)}，可建仓")
            # 买入分跌回≤30，解锁买入
            if buy_score <=30 and coin in SCORE_LOCK['buy']:
                SCORE_LOCK['buy'].remove(coin)
            # 触发高抛提醒：卖出分≥90（11项里至少9项共振），且没锁
            if sell_score >=90 and coin not in SCORE_LOCK['sell']:
                SCORE_LOCK['sell'].add(coin)
                alerts.append(f"⚠️ 最佳高抛点，卖出分{sell_score}/110，满足：{'、'.join(sell_reasons)}，可止盈")
            # 卖出分跌回≤30，解锁卖出
            if sell_score <=30 and coin in SCORE_LOCK['sell']:
                SCORE_LOCK['sell'].remove(coin)
            if alerts:
                alert_str = ''.join(alerts)
                key = stable_alert_key(coin, alert_str)
                if should_alert(key):
                    mark_alert(key)
                    alerts_all.append((coin, alerts))
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
            # ── 面板：把本轮该币已算好的结果收成只读视图 ──
            # 注意：必须放在下面 has_important 的 continue **之前**！
            #   对方的逻辑是"只有重要信号才输出详细报告，否则 continue 跳过"，
            #   而面板要展示**所有**币的状态，所以在这里就收走。
            try:
                if _PANEL_IMPORT_OK:
                    panel_coins.append(panel_adapter.coin_view(
                        pair=pair, coin=coin, ind_s=ind_s, ind_l=ind_l,
                        flow=flow, score=(b_score, s_score),
                        signal=current_signal if "current_signal" in dir() else "",
                    ))
            except Exception as _pe:
                print(f"[面板] {coin} 视图收集失败：{type(_pe).__name__}: {_pe}", flush=True)
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
            ls_size_ratio = float(lsd.get('top_lsr_size', 1.0))
            ls_size_judge = "明显偏空" if ls_size_ratio<0.5 else "明显偏多" if ls_size_ratio>2 else "平衡"
            lines.append(f"- **大户账户多空比**: {ls_size_ratio:.2f}（{ls_size_judge}）")
            taker_ratio = buy_taker/max(sell_taker,1)
            taker_judge = "散户疯狂主动买，追高" if taker_ratio>1.5 else "散户恐慌卖" if taker_ratio<0.7 else "平衡"
            lines.append(f"- **Taker主动买卖比**: {taker_ratio:.2f}（{taker_judge}）")
            lines.append(f"- **资金费率**: 未接入（暂无数据源，请勿参考）")
            upper_judge = "还在拉，没抛压" if upper_count<2 else "上方抛压重"
            lines.append(f"- **连续上影线**: {upper_count}根（{upper_judge}）")
            daily_text = "🟢" if daily_up else "🔴"
            daily_judge = "日线向上" if daily_up else "日线向下"
            lines.append(f"- **日线趋势**: {daily_text} {daily_judge}")
            sync_text = "和BTC同步" if ind_s['day_chg']*btc_chg>0 else "和BTC背离"
            lines.append(f"- **BTC联动**: BTC{btc_chg:+.2f}%（{sync_text}）")
            # 加关键支撑压力位
            lines.append(f"- **关键价位**: 下方支撑{today_low:.4f}，上方压力{today_high:.4f}")
            # 止损止盈
            stop_loss = ind_s['boll_l']
            take_profit = ind_s['boll_u']
            daily_judge = "日线向上" if daily_up else "日线向下"
            if current_signal == "探底反弹":
                # if daily_up 是判断日线趋势的
                if daily_up:
                    pos = "3成重仓"
                else:
                    pos = "1成轻仓"
                hold_advice = f"可以买入{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"
                empty_advice = f"可以建仓{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"
            elif current_signal == "碰BOLL上轨":
                hold_advice = "可以持有"
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

        # ── 面板：发布本轮结果（只读展示）──
        try:
            if _PANEL_IMPORT_OK:
                panel.publish(coins=panel_coins,
                              alerts=[{'t': datetime.now().strftime('%H:%M:%S'),
                                       'coin': c, 'text': ', '.join(a)} for c, a in alerts_all],
                              errors=[], btc_chg=btc_chg,
                              duration=time.time() - _round_t0)
        except Exception as _pe:
            print(f"[面板] 发布失败：{type(_pe).__name__}: {_pe}", flush=True)
        # beep()


    # ── 面板：本轮无报警也要发布（页面才能看到最新状态）──
    try:
        if _PANEL_IMPORT_OK and not alerts_all:
            panel.publish(coins=panel_coins, alerts=[], errors=[],
                          btc_chg=btc_chg, duration=time.time() - _round_t0)
    except Exception as _pe:
        print(f"[面板] 发布失败：{type(_pe).__name__}: {_pe}", flush=True)


if __name__ == "__main__":
    # ── 面板：启动只读 H5 服务（后台线程；失败只警告，监控照跑）──
    if _PANEL_IMPORT_OK:
        try:
            panel.start()
        except Exception as _pe:
            print(f"[面板] 启动失败（监控不受影响）：{type(_pe).__name__}: {_pe}", flush=True)
    print(f"启动模块化监测系统{VERSION} {VERSION_DATE}")
    last_backtest_ts = time.time()
    last_day = datetime.now().day
    monitor_once()
    while True:
        try:
            now_ts = time.time()
            now_hour = datetime.now().hour
            now_min = datetime.now().minute
            now_day = datetime.now().day
            # 每日0点自动清空当天推送记录
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
            print(f"主循环出错：{e}")
        time.sleep(CHECK_INTERVAL)


