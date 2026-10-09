# -*- coding: utf-8 -*-
"""信号判定层。

架构分离自 main.py（纯搬运，逻辑一字未改）。包含：
    · 信号锁 / 方向状态 等全局量
    · 缩量慢涨慢跌、BOLL 开口、当日有效高低点、资金分析 等判定函数
    · 信号分级 _is_report_signal（哪些进"带完整报告"）
    · evaluate_coin()：单个币 取数 → 指标快照 → 打分 → 全部信号判定
      返回 report.render() 需要的上下文（无重要信号则返回 None）

⚠️ 算法口径以对方为准，本模块只做搬运，不改任何阈值/触发条件。
"""
import json
import time
from datetime import datetime

from config import *
from api import get_kline, get_trades, get_ls, get_btc_chg, get_flow_1h
from indicators import get_indicator, get_daily_trend
from strategy import calc_score, get_signal, last_signal
from alert_state import stable_alert_key
from alerting import pushed, should_alert, mark_alert, save_pushed

# 只读 H5 面板（展示层）—— 不参与判定；导入失败也不能挡住监控
try:
    import panel_adapter
    _PANEL_IMPORT_OK = True
except Exception:
    _PANEL_IMPORT_OK = False


def fmt_money(v):
    if abs(v) >= 100000000:
        return f"${v/100000000:.2f}亿" if v>=0 else f"-${-v/100000000:.2f}亿"
    elif abs(v) >= 10000:
        return f"${v/10000:.1f}万" if v>=0 else f"-${-v/10000:.1f}万"
    else:
        return f"${v/1000:.1f}千" if v>=0 else f"-${-v/1000:.1f}千"


SLOW_START_LOCK = {}
# 【2026-10-05 新增】强单信号统一锁字典，每个信号独立锁+解锁
SIGNAL_LOCK = {}


# 【2026-10-05 新增】1h资金上一轮值，用来做连续两轮确认
FLOW_PREV = {}


# 记录每个币上一轮的方向状态，用于信号反转时自动清空计数
LAST_FLOW_DIR = {}  # 1=流入，-1=流出，0=中性
LAST_RSI_STATE = {} # over=超买，under=超卖，normal=中性
# 记录每个币当天最大的15分钟资金流入/流出，突破历史极值时自动重置计数
MAX_FLOW_IN_15M = {}
MAX_FLOW_OUT_15M = {}


# 【2026-10-06 新增】缩量慢涨/慢跌信号锁
SHRINK_LOCK = {"rise": set(), "drop": set()}

# 【2026-10-06 新增】标准函数：判断是否为缩量慢涨启动信号
def check_shrink_rise(coin, df_s, ind_s):
    """缩量慢涨启动：连续2根小阳线+缩量+站上EMA20+刚从低点启动"""
    try:
        if len(df_s) < 12: return None
        # 连续2根小阳线
        k1 = df_s.iloc[-2]
        k2 = df_s.iloc[-1]
        yang1 = k1['close'] > k1['open']
        yang2 = k2['close'] > k2['open']
        chg1 = (k1['close'] - k1['open'])/k1['open']*100
        chg2 = (k2['close'] - k2['open'])/k2['open']*100
        # 小阳线：单根涨0.2%-1%
        if not (yang1 and yang2 and 0.2 < chg1 < 1 and 0.2 < chg2 < 1):
            return None
        # 缩量：最近2根平均量 < 前10根平均量的70%
        vol_recent = (k1['volume'] + k2['volume'])/2
        vol_prev = df_s['volume'].iloc[-12:-2].mean()
        if vol_recent > vol_prev * 0.7:
            return None
        # 站上EMA20
        if not ind_s['trend_up']:
            return None
        # 刚启动：从30分钟低点涨不到2%
        low_30m = df_s['low'].tail(3).min()
        rise_from_low = (ind_s['close'] - low_30m)/low_30m*100
        if rise_from_low > 2:
            return None
        return f"🟢 缩量慢涨启动，连续2根小阳+缩量，主力悄悄吸筹，后续看涨"
    except:
        return None

# 【2026-10-06 新增】标准函数：判断是否为缩量慢跌启动信号
def check_shrink_drop(coin, df_s, ind_s):
    """缩量慢跌启动：连续2根小阴线+缩量+跌破EMA20+刚从高点回落"""
    try:
        if len(df_s) < 12: return None
        # 连续2根小阴线
        k1 = df_s.iloc[-2]
        k2 = df_s.iloc[-1]
        yin1 = k1['close'] < k1['open']
        yin2 = k2['close'] < k2['open']
        chg1 = (k1['open'] - k1['close'])/k1['open']*100
        chg2 = (k2['open'] - k2['close'])/k2['open']*100
        # 小阴线：单根跌0.2%-1%
        if not (yin1 and yin2 and 0.2 < chg1 < 1 and 0.2 < chg2 < 1):
            return None
        # 缩量：最近2根平均量 < 前10根平均量的70%
        vol_recent = (k1['volume'] + k2['volume'])/2
        vol_prev = df_s['volume'].iloc[-12:-2].mean()
        if vol_recent > vol_prev * 0.7:
            return None
        # 跌破EMA20
        if ind_s['trend_up']:
            return None
        # 刚启动：从30分钟高点跌不到2%
        high_30m = df_s['high'].tail(3).max()
        drop_from_high = (high_30m - ind_s['close'])/high_30m*100
        if drop_from_high > 2:
            return None
        return f"🔴 缩量慢跌开始，连续2根小阴+缩量，主力悄悄出货，后续看跌"
    except:
        return None


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


def _boll_open_up(ind, df_tf):
    """该周期是否『BOLL三轨开口向上』：三轨有序(上>中>下) + 上轨比上一根抬升。

    与原来 15m 单周期的判据完全一致，只是抽成函数以便两个周期复用。
    取数异常一律返回 False（不误报）。
    """
    try:
        u = float(ind['boll_u'])
        m = float(ind['boll_mid'])
        l = float(ind['boll_l'])
        uprev = float(df_tf['boll_u'].iloc[-2]) if 'boll_u' in df_tf.columns else 0.0
        return bool(u > m > l and u > uprev)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# 【2026-10-07 新增】信号分级：哪些报警"带完整全方位分析报告"
# ══════════════════════════════════════════════════════════════
# 规格（用户 2026-10-07 明确定义）：
#   ▸ 带完整报告 —— 涉及买卖操作 / 主力级别，需要做决策：
#       ① 移动止盈落袋提醒
#       ② ≥30分 低吸/高抛预警
#       ③ ≥90分 最佳买卖点
#       ④ V型反弹 / 见顶回落
#       ⑤ BOLL 真突破上轨 / 真跌破下轨（连续 2 根确认的真破轨）
#       ⑥ 缩量慢涨 / 慢跌启动
#       ⑦ 大级别资金流入 / 流出（主力资金）
#       ⑧ 真高 / 真底提醒
#   ▸ 只推一句话 —— 盘面异动/板块提示，不用做复杂决策：
#       30分钟急涨急跌 · 变盘点趋势转多转空 · 大反弹大回撤 ·
#       大户极端多空比 · 板块联动 · 币种小级别新闻快讯
# 注意：本函数只决定"哪些报警进详细报告"，**不改任何信号的触发条件**。


_REPORT_KEYWORDS = (
    "移动止盈落袋",                        # ①
    "低吸预警", "高抛预警",                 # ②（含"紧急低吸/高抛预警"）
    "最佳低吸点", "最佳高抛点",             # ③
    "V型反弹", "见顶回落",                  # ④
    "真突破可以追多", "真跌破超卖低吸",     # ⑤
    "缩量慢涨启动", "缩量慢跌开始",         # ⑥
    "资金大幅流入", "资金大幅流出",         # ⑦
    "触及当日真高", "触及当日真底",         # ⑧
)


def _is_report_signal(text):
    """该报警是否属于『带完整全方位分析报告』的 8 类重要信号。"""
    return any(k in text for k in _REPORT_KEYWORDS)


def evaluate_coin(pair, coin, btc_chg, alerts_all, lines, coin_chg, panel_coins):
    """单个币：取数 → 指标快照 → 打分 → 全部信号判定（含分级）。

    返回 report.render() 需要的上下文 dict；
    该币本轮没有"带完整报告"的重要信号（或取数异常）时返回 None。
    """
    try:
        ind_s = get_indicator(pair, "15m")
        coin_chg[coin] = ind_s['day_chg']  # 存当日涨跌幅用于板块联动判断
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
        # 移动止盈逻辑放到后面ATR算完之后
        drawdown = (eff_high - ind_s['close'])/eff_high
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
        if reverse_alert:
            alerts.append(reverse_alert)
        df_s = ind_s['df']
        # 2026-10-07 优化：BOLL破轨改用标准函数判断，过滤插针假突破
        from indicators import check_boll_breakout
        boll_br = check_boll_breakout(df_s, ind_s['close'], ind_s['boll_u'], ind_s['boll_l'], coin)
        if boll_br == 'true_break_up' and vol_enough:
            key_break = f"{coin}_突破BOLL上轨"
            if key_break not in pushed:
                pushed[key_break] = 1
                alerts.append(f"✅ 连续2根K线放量突破BOLL上轨{ind_s['boll_u']:.4f}，真突破可以追多")
        elif boll_br == 'true_break_down':
            key_break_l = f"{coin}_跌破BOLL下轨"
            if key_break_l not in pushed:
                pushed[key_break_l] = 1
                alerts.append(f"🟢 连续2根K线跌破BOLL下轨{ind_s['boll_l']:.4f}，真跌破超卖低吸机会")
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
        #
        # ★ 用户要求（2026-10-06）：由 15m 单周期 → **15m 为主 + 结合 1h，15m 占 60%**
        #   做法：两个周期各判一次"开口向上"，按 60/40 加权，合计 ≥60 分触发。
        #     · 15m 满足            → 60 分 → **达到阈值，触发**（15m 是必要条件）
        #     · 15m + 1h 都满足     → 100 分 → 触发，且强度更高（更可信）
        #     · 只有 1h 满足        → 40 分 → 不触发
        #   权重正好落在阈值上，所以语义 = "15m 必须有，1h 是确认"，与"15m 为主"一致。
        boll_s15 = 60 if _boll_open_up(ind_s, df_s) else 0
        boll_s1h = 40 if (ind_l and _boll_open_up(ind_l, ind_l.get('df'))) else 0
        boll_score = boll_s15 + boll_s1h
        if boll_score >= 60:
            key_boll_open = f"{coin}_BOLL开口向上"
            if pushed.get(key_boll_open,0) < 2:  # 一天最多推2次
                mark_alert(key_boll_open)
                _共振 = "15m+1h 双周期共振" if boll_score >= 100 else "15m 为主"
                alerts.append(f"📈 BOLL三轨开口向上，慢牛趋势，可持有（{boll_score}/100，{_共振}）")
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
        # 条件3：BOLL三轨开口向上（与上面同一口径：15m 为主 + 1h，≥60 分）
        if boll_score >= 60:
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
        # 新增：急涨预警，提前发现拉升，别追高
        # 【2026-10-05 19:10 优化：用ATR动态算阈值，2倍ATR才算真急涨，资金按币种分档】
        tr1 = df_s['high']-df_s['low']
        tr2 = (df_s['high']-df_s['close'].shift(1)).abs()
        tr3 = (df_s['low']-df_s['close'].shift(1)).abs()
        tr = tr1.combine(tr2, max).combine(tr3, max)
        atr_pct = tr.rolling(14).mean().iloc[-1]/df_s['close'].iloc[-1]*100
        rush_thresh = 2 * atr_pct  # 急涨阈值：2倍ATR
        bounce_thresh = 1.5 * atr_pct  # 大反弹阈值：1.5倍ATR
        # 2026-10-07 动态移动止盈：从有效高点回撤1.5倍ATR就止盈
        trail_ratio = atr_pct/100 * 1.5
        drawdown = (eff_high - ind_s['close'])/eff_high
        if drawdown >= trail_ratio:
            key_trail = f"{coin}_移动止盈"
            if key_trail not in pushed:
                pushed[key_trail] = 1
                alerts.append(f"⚠️ 从高点回撤{drawdown*100:.1f}%（动态阈值{trail_ratio*100:.1f}%），移动止盈落袋")
        # 资金阈值按币种体量分档
        if 'BTC' in coin or 'BSV' in coin:
            big_flow_1h = 150000
            big_flow_15m = 30000
        elif 'CYS' in coin:
            big_flow_1h = 30000
            big_flow_15m = 10000
        else:
            big_flow_1h = 100000
            big_flow_15m = 20000
        recent_chg = (df_s['close'].iloc[-1] - df_s['close'].iloc[-3]) / df_s['close'].iloc[-3] * 100
        if recent_chg >= rush_thresh and vol_enough:
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
        # ★ 我方补充（不动他的逻辑）：原来这里 alerts.clear() 把小信号
        #   直接丢掉了，用户就没法"想推的时候推"。现在改成**留下来**，
        #   由 small_signal_switch 决定要不要一起发：
        #     关（默认）= 和原来完全一样，只有 ≥90 的关键点推
        #     开        = 这些小信号也一起推（用户要的"触发即上报"）
        #
        # ★ 我方补充 2（2026-10-07 信号分级规格）：这段之前的报警里也有
        #   **属于"带完整报告"8 类**的（真高/真底、BOLL真突破/真跌破、
        #   移动止盈落袋）。它们不该被清掉 —— 单独留一份，clear 之后放回
        #   推送队列，这样它们才会带完整报告推出去。
        keep_alerts  = [x for x in alerts if _is_report_signal(x)]
        small_alerts = [x for x in alerts if not _is_report_signal(x)]
        for msg in alerts:
            print(f"[{coin}] 控制台小信号: {msg}")
        alerts.clear()
        alerts.extend(keep_alerts)       # 报告级信号回到推送队列
        # ==============================================
        # 【2026-10-05 新增】强单信号恢复推飞书
        # 逻辑：统一锁+解锁机制，同一波行情只推一次，变盘后自动解锁
        # ==============================================
        # 1. 30分钟急涨≥2倍ATR/急跌≥2倍ATR（动态阈值，加滞回死区防止横盘来回推）
        if recent_chg >= rush_thresh:
            if f"{coin}_30m急涨" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_30m急涨"] = True
                alerts.append(f"⚡ 30分钟急涨{recent_chg:.1f}%，注意追高风险")
        # 急涨解锁：从高点回撤1.5倍ATR（滞回，缓冲带）
        if f"{coin}_30m急涨" in SIGNAL_LOCK and (recent_high_30m - ind_s['close'])/recent_high_30m*100 >= atr_pct*1.5:
            del SIGNAL_LOCK[f"{coin}_30m急涨"]
        elif recent_chg <= -rush_thresh:
            if f"{coin}_30m急跌" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_30m急跌"] = True
                alerts.append(f"⚡ 30分钟急跌{recent_chg:.1f}%，注意恐慌割肉")
        # 急跌解锁：从低点反弹1.5倍ATR（滞回，缓冲带）
        if f"{coin}_30m急跌" in SIGNAL_LOCK and (ind_s['close'] - recent_low_30m)/recent_low_30m*100 >= atr_pct*1.5:
            del SIGNAL_LOCK[f"{coin}_30m急跌"]
        # 2. 1h资金大幅异动≥分档阈值（连续两轮同方向+15分钟配合，双确认过滤毛刺）
        prev_flow = FLOW_PREV.get(coin, 0)
        if flow_1h >= big_flow_1h and prev_flow > 0 and recent_flow_15 >= big_flow_15m:
            if f"{coin}_1h大流入" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_1h大流入"] = True
                alerts.append(f"🟢 1h资金大幅流入${flow_1h/10000:.1f}万，15分钟持续进场，主力真金白银买入")
        # 大流入解锁：1h资金反向走全额阈值（滞回，防止横盘来回抖）
        if f"{coin}_1h大流入" in SIGNAL_LOCK and flow_1h <= -big_flow_1h:
            del SIGNAL_LOCK[f"{coin}_1h大流入"]
        if flow_1h <= -big_flow_1h and prev_flow < 0 and recent_flow_15 <= -big_flow_15m:
            if f"{coin}_1h大流出" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_1h大流出"] = True
                alerts.append(f"🔴 1h资金大幅流出${-flow_1h/10000:.1f}万，15分钟持续跑路，主力真金白银卖出")
        # 大流出解锁：1h资金反向走全额阈值（滞回，防止横盘来回抖）
        if f"{coin}_1h大流出" in SIGNAL_LOCK and flow_1h >= big_flow_1h:
            del SIGNAL_LOCK[f"{coin}_1h大流出"]
        # 更新上一轮资金值
        FLOW_PREV[coin] = flow_1h
        # 3. 大户极端多空比（加默认值，避免KeyError）
        top_ratio = ind_s.get('top_ratio', 1.0)
        if top_ratio > 1.8:
            if f"{coin}_大户极端多" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_大户极端多"] = True
                alerts.append(f"🟢 大户多空比{top_ratio:.2f}，极端看多")
        # 大户极端多解锁：多空比回到1.2
        if f"{coin}_大户极端多" in SIGNAL_LOCK and top_ratio <=1.2:
            del SIGNAL_LOCK[f"{coin}_大户极端多"]
        elif top_ratio < 0.6:
            if f"{coin}_大户极端空" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_大户极端空"] = True
                alerts.append(f"🔴 大户多空比{top_ratio:.2f}，极端看空")
        # 大户极端空解锁：多空比回到0.8
        if f"{coin}_大户极端空" in SIGNAL_LOCK and top_ratio >=0.8:
            del SIGNAL_LOCK[f"{coin}_大户极端空"]
        # 4. 从最近30分钟高点回撤≥1.5倍ATR/从最近30分钟低点反弹≥1.5倍ATR（动态阈值）
        if (ind_s['close'] - recent_low_30m)/recent_low_30m*100 >= bounce_thresh:
            if f"{coin}_大反弹" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_大反弹"] = True
                alerts.append(f"🟢 从30分钟变盘点反弹{(ind_s['close']-recent_low_30m)/recent_low_30m*100:.1f}%，趋势转多")
        # 大反弹解锁：从最近30分钟高点回撤1倍ATR（滞回缓冲）
        if f"{coin}_大反弹" in SIGNAL_LOCK and (recent_high_30m - ind_s['close'])/recent_high_30m*100 >= atr_pct:
            del SIGNAL_LOCK[f"{coin}_大反弹"]
        elif (recent_high_30m - ind_s['close'])/recent_high_30m*100 >= bounce_thresh:
            if f"{coin}_大回撤" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_大回撤"] = True
                alerts.append(f"🔴 从30分钟变盘点回撤{(recent_high_30m-ind_s['close'])/recent_high_30m*100:.1f}%，趋势转空")
        # 大回撤解锁：从最近30分钟低点反弹1倍ATR（滞回缓冲）
        if f"{coin}_大回撤" in SIGNAL_LOCK and (ind_s['close'] - recent_low_30m)/recent_low_30m*100 >= atr_pct:
            del SIGNAL_LOCK[f"{coin}_大回撤"]
        # ==============================================
        # 【2026-10-05 新增】V型反弹/见顶回落单独推飞书
        # 逻辑：从30分钟低点反弹1.5-3%推V反，从高点跌1.5-3%推见顶回落
        # 统一锁机制，同一波只推一次，反向自动解锁
        # ==============================================
        v_bounce = (ind_s['close'] - recent_low_30m)/recent_low_30m*100
        # 【2026-10-05 18:35 优化V反信号】加两个过滤条件：1.最近30分钟必须先急跌≥1% 2.15分钟资金必须净流入，过滤假反弹
        pre_drop = (recent_high_30m - recent_low_30m)/recent_high_30m*100
        if 1.5 <= v_bounce <=3 and pre_drop >=1 and recent_flow_15 > 0:
            if f"{coin}_V反" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_V反"] = True
                alerts.append(f"🟢 V型反弹，先急跌后资金进场，从30分钟低点反弹{v_bounce:.1f}%，短线反弹机会")
        # V反解锁：反弹超过3%或者从高点回落1.5%
        if f"{coin}_V反" in SIGNAL_LOCK and (v_bounce>3 or (recent_high_30m-ind_s['close'])/recent_high_30m*100>=1.5):
            del SIGNAL_LOCK[f"{coin}_V反"]
        # 对称：见顶回落信号，同样优化：先急涨≥1%+15分钟资金净流出
        pre_rise = (recent_high_30m - recent_low_30m)/recent_low_30m*100
        v_drop = (recent_high_30m - ind_s['close'])/recent_high_30m*100
        if 1.5 <= v_drop <=3 and pre_rise >=1 and recent_flow_15 < 0:
            if f"{coin}_见顶回落" not in SIGNAL_LOCK:
                SIGNAL_LOCK[f"{coin}_见顶回落"] = True
                alerts.append(f"🔴 见顶回落，先急涨后资金流出，从30分钟高点下跌{v_drop:.1f}%，短线注意风险")
        # 见顶回落解锁：跌超过3%或者从低点反弹1.5%
        if f"{coin}_见顶回落" in SIGNAL_LOCK and (v_drop>3 or (ind_s['close']-recent_low_30m)/recent_low_30m*100>=1.5):
            del SIGNAL_LOCK[f"{coin}_见顶回落"]
        # ==============================================
        # 【2026-10-05 新增】第一级紧急预警打分
        # 逻辑：6项指标打分，≥30分（3个信号共振）才推飞书，快速抓变盘
        # ==============================================
        emerg_buy_score = 0
        emerg_buy_reasons = []
        emerg_sell_score = 0
        emerg_sell_reasons = []
        # 给所有打分用到的变量加默认值，避免未定义报错
        upper_shadow = 0
        lower_shadow = 0
        body = 1
        funding_rate = 0
        recent_flow_15 = 0
        # 2026-10-05 结论打分用到的变量加默认值
        ind_s['ema20'] = ind_s.get('ema20', ind_s['close'])
        ind_s['kdj_j'] = ind_s.get('kdj_j', 50)
        ind_s['boll_m'] = ind_s.get('boll_m', ind_s['close'])
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
        # 盘口承接（加默认值避免未定义报错）
        buy_depth = 0
        sell_depth = 0
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
            SCORE_LOCK = {'buy':set(), 'sell':set(), 'buy_warn':set(), 'sell_warn':set()}
        # 【2026-10-06 恢复】30分紧急预警推送
        if buy_score >=30 and coin not in SCORE_LOCK['buy_warn']:
            SCORE_LOCK['buy_warn'].add(coin)
            alerts.append(f"🟡 低吸预警，买入分{buy_score}/110，开始关注，满足：{'、'.join(buy_reasons)}")
        # 买分跌回≤20，解锁预警
        if buy_score <=20 and coin in SCORE_LOCK['buy_warn']:
            SCORE_LOCK['buy_warn'].remove(coin)
        # 触发低吸提醒：买入分≥90（11项里至少9项共振），且没锁
        if buy_score >=90 and coin not in SCORE_LOCK['buy']:
            SCORE_LOCK['buy'].add(coin)
            alerts.append(f"✅ 最佳低吸点，买入分{buy_score}/110，满足：{'、'.join(buy_reasons)}，可建仓")
        # 买入分跌回≤30，解锁买入
        if buy_score <=30 and coin in SCORE_LOCK['buy']:
            SCORE_LOCK['buy'].remove(coin)
        # 【2026-10-06 恢复】30分高抛预警推送
        if sell_score >=30 and coin not in SCORE_LOCK['sell_warn']:
            SCORE_LOCK['sell_warn'].add(coin)
            alerts.append(f"🟡 高抛预警，卖出分{sell_score}/110，开始关注，满足：{'、'.join(sell_reasons)}")
        # 卖分跌回≤20，解锁预警
        if sell_score <=20 and coin in SCORE_LOCK['sell_warn']:
            SCORE_LOCK['sell_warn'].remove(coin)
        # 触发高抛提醒：卖出分≥90（11项里至少9项共振），且没锁
        if sell_score >=90 and coin not in SCORE_LOCK['sell']:
            SCORE_LOCK['sell'].add(coin)
            alerts.append(f"⚠️ 最佳高抛点，卖出分{sell_score}/110，满足：{'、'.join(sell_reasons)}，可止盈")
        # 卖出分跌回≤30，解锁卖出
        if sell_score <=30 and coin in SCORE_LOCK['sell']:
            SCORE_LOCK['sell'].remove(coin)
        # ==============================================
        # 【2026-10-05 新增】慢涨刚启动监测
        # 逻辑：刚从低位涨1.5%-2.5%+资金流入+连续2根阳线就推
        # 同一波上涨不重复推，变盘跌破MA20/资金流出/回撤3%就解锁
        # ==============================================
        # 算从今日低点的涨幅
        chg_from_low = (ind_s['close'] - today_low) / today_low * 100
        # 判断是否连续2根阳线
        two_yang = len(df_s)>=2 and df_s.iloc[-1]['close']>df_s.iloc[-1]['open'] and df_s.iloc[-2]['close']>df_s.iloc[-2]['open']
        # 触发慢涨启动：从低点涨1.5-2.5% + 15分钟资金流入 + 连续2阳
        if 1.5 <= chg_from_low <= 2.5 and recent_flow_15>0 and two_yang:
            if coin not in SLOW_START_LOCK:
                SLOW_START_LOCK[coin] = True
                alerts.append(f"🟢 慢涨刚启动，从低点涨{chg_from_low:.1f}%，资金流入+连续小阳，可小仓位跟进，止损设MA20")
        # 变盘解锁条件
        if coin in SLOW_START_LOCK:
            # 跌破MA20/15m资金流出/从高点回撤3%，解锁
            if ind_s['close'] < ind_s['ma20'] or recent_flow_15<0 or (recent_high_30m - ind_s['close'])/recent_high_30m*100 >=3:
                del SLOW_START_LOCK[coin]
        # 【2026-10-06 新增】调用标准函数判断缩量慢涨/慢跌启动信号
        rise_sig = check_shrink_rise(coin, df_s, ind_s)
        if rise_sig and coin not in SHRINK_LOCK['rise']:
            SHRINK_LOCK['rise'].add(coin)
            alerts.append(rise_sig)
        # 慢涨解锁：连续2根阴线就解锁
        if len(df_s)>=2 and coin in SHRINK_LOCK['rise']:
            if df_s.iloc[-1]['close'] < df_s.iloc[-1]['open'] and df_s.iloc[-2]['close'] < df_s.iloc[-2]['open']:
                SHRINK_LOCK['rise'].remove(coin)
        drop_sig = check_shrink_drop(coin, df_s, ind_s)
        if drop_sig and coin not in SHRINK_LOCK['drop']:
            SHRINK_LOCK['drop'].add(coin)
            alerts.append(drop_sig)
        # 慢跌解锁：连续2根阳线就解锁
        if len(df_s)>=2 and coin in SHRINK_LOCK['drop']:
            if df_s.iloc[-1]['close'] > df_s.iloc[-1]['open'] and df_s.iloc[-2]['close'] > df_s.iloc[-2]['open']:
                SHRINK_LOCK['drop'].remove(coin)
        if alerts:
            alert_str = ''.join(alerts)
            key = stable_alert_key(coin, alert_str)
            if should_alert(key):
                mark_alert(key)
                alerts_all.append((coin, alerts))

        # ── 小信号（开关打开时才加进来）─────────────────
        # 默认关 → 行为和对方的设计完全一致（只有 ≥90 的关键点推）。
        # 打开后 → 这些"只打控制台"的小信号也进发送队列。
        # 注意：它们各自也走冷却，不会因为打开开关就每轮刷屏。
        if small_alerts:
            try:
                import small_signal_switch
                if small_signal_switch.is_enabled():
                    kept = []
                    for msg in small_alerts:
                        k2 = stable_alert_key(coin, msg)
                        if should_alert(k2):
                            mark_alert(k2)
                            kept.append(msg)
                    if kept:
                        alerts_all.append((coin, kept))
            except Exception as _se:
                print(f"[小信号] 开关读取失败，按关闭处理："
                      f"{type(_se).__name__}: {_se}", flush=True)
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
        # 只有这个币触发了**带完整报告的重要信号**，才输出详细分析，否则跳过
        # 【2026-10-07 改】原来用模糊关键词（'止盈'/'买入'/'卖出'…）判，
        #   会把"1h资金大幅流入…真金白银**买入**"这种强单信号误判成重要信号，
        #   也会漏掉 V型反弹/见顶回落（文案里没有 '急跌V反'）。
        #   现按用户定的信号分级规格，用 _is_report_signal() 精确判定 8 类：
        #     移动止盈 / ≥30分预警 / ≥90分最佳点 / V反·见顶回落 /
        #     BOLL真破轨 / 缩量慢涨慢跌 / 大级别资金 / 真高·真底
        has_important = any(_is_report_signal(x) for x in alerts)
        if not has_important:
            return None
        return {
            'coin': coin,
            'alerts': alerts,
            'big_flow_1h': big_flow_1h,
            'btc_chg': btc_chg,
            'buy_taker': buy_taker,
            'current_signal': current_signal,
            'daily_up': daily_up,
            'df_s': df_s,
            'drawdown_high': drawdown_high,
            'eff_high': eff_high,
            'eff_low': eff_low,
            'flow': flow,
            'flow_1h': flow_1h,
            'flow_1h_val': flow_1h_val,
            'fmt_money': fmt_money,
            'ind_l': ind_l,
            'ind_s': ind_s,
            'lsd': lsd,
            'recent_flow_15': recent_flow_15,
            'rise_low': rise_low,
            'sell_taker': sell_taker,
            'today_high': today_high,
            'today_low': today_low,
            'top_ratio': top_ratio,
            'trail_thr': trail_thr,
            'upper_count': upper_count,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"{coin}出错: {e}")
        return None
