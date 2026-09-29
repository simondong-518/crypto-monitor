"""单一判定入口（P1-7）：main.py 与所有 check_*.py 必须调用这里，不允许各算一套。

为什么：
  原来 check_all_alerts.py 在提交信息里自称"和 main.py 完全一致"，实际它只看"买分/卖分 ≥3.5"
  就打印 ✅买/✅卖；而 main.py 的**推送**根本不看分数（看的是涨跌幅 / 跌破MA20 / 信号反转 / 长上影）。
  拿它去查"为什么没提醒"，会得到错误答案；两个口径还会各自漂移。
  所以：评估、报警判定、报告渲染，全部收拢到本模块。

口径（P1-1）：
  · 指标类（RSI/BOLL/MACD/KDJ/趋势/量能/形态）→ 最后一根**已收盘** bar
  · 价格类（现价、当日涨跌幅、到价提醒）→ **实时**价
  报告里必须同时出现「已收盘 bar 的收盘时间」，否则看不出这个数是哪根 K 线的。

用法：
    from evaluate import evaluate_coin, build_alerts, render_coin_report
    res = evaluate_coin("SUI_USDT", ls_state)
    for key, title, body in build_alerts(res):   # 所有"该不该报"的判断都在这里
        ...
"""
import re
import time
from datetime import datetime

import config
from api import get_ls, get_trades
from indicators import get_indicator, get_daily_trend
from strategy import calc_score, get_signal


def fnum(x, default=None):
    try:
        v = float(x)
        return v
    except (TypeError, ValueError):
        return default


def analyze_trades(trades):
    buy_v = sell_v = 0.0
    if not isinstance(trades, list):
        return {"buy_volume": 0.0, "sell_volume": 0.0, "net_inflow": 0.0, "n": 0}
    for t in trades:
        try:
            v = float(t['amount']) * float(t['price'])
        except (KeyError, TypeError, ValueError):
            continue
        if t.get('side') == 'buy':
            buy_v += v
        else:
            sell_v += v
    return {"buy_volume": buy_v, "sell_volume": sell_v,
            "net_inflow": buy_v - sell_v, "n": len(trades)}


def day_high(df):
    """当天最高价（从 K 线 ts 列取，重启不丢；原补丁脚本用内存字典，重启就丢）"""
    if df is None or 'ts' not in df:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        mask = df['ts'].map(
            lambda s: time.strftime("%Y-%m-%d", time.localtime(int(float(s)))) == today)
        if not mask.any():
            return None
        return float(df.loc[mask, 'high'].max())
    except Exception:
        return None


def evaluate_coin(pair, ls_state=None):
    """单币完整评估。抛出的异常由调用方按"跳过并打印原因"处理（不静默吞掉）。"""
    coin = pair.replace("_USDT", "")
    ind_s = get_indicator(pair, "15m")
    ind_l = get_indicator(pair, "1h")
    ind_4h = get_indicator(pair, "4h")
    daily_up = get_daily_trend(pair)
    flow = analyze_trades(get_trades(pair))

    raw = get_ls(pair)
    rec = raw[-1] if isinstance(raw, list) and raw else {}
    ls_account = fnum(rec.get('top_lsr_account'))
    ls_size = fnum(rec.get('top_lsr_size'))
    ls_pct = None
    ls_n = 0
    if ls_state is not None:
        metric = str(getattr(config, "LS_METRIC", "top_lsr_account"))
        value = ls_size if metric == "top_lsr_size" else ls_account
        if value is not None:
            ls_pct, ls_n = ls_state.sample(coin, value)

    b, s = calc_score(ind_s, ind_l, flow, ls_pct, ind_s['df'])
    if not daily_up:
        b -= 1.5
    if not ind_4h['trend_up']:
        b -= 1
    signal, reverse_alert = get_signal(coin, b, s, ind_s, ind_l)

    return {
        "pair": pair, "coin": coin,
        "ind_s": ind_s, "ind_l": ind_l, "ind_4h": ind_4h,
        "daily_up": daily_up, "flow": flow,
        "ls_account": ls_account, "ls_size": ls_size, "ls_pct": ls_pct, "ls_n": ls_n,
        "b_score": b, "s_score": s,
        "signal": signal, "reverse_alert": reverse_alert,
    }


def day_chg_verdict(day_chg, trend_up, vol_ok, threshold):
    """涨跌幅是否报警 + 附加说明。纯函数，便于单测（原来这段内联在 main.monitor_once 里）。

    规则（沿用原意）：
      · |涨幅| ≥5% 直接报（不看量）
      · 阈值~5% 之间需要**已收盘 bar** 的量能达标 —— P1-1 修正口径后这个门槛才可达
      · 涨到 HIGH_CHG_THRESHOLD 以上不再喊"拿住"，改提示高位止盈（补做4）
    """
    if abs(day_chg) >= 5 or (abs(day_chg) >= threshold and vol_ok):
        if day_chg > 0 and day_chg >= float(getattr(config, "HIGH_CHG_THRESHOLD", 10.0)):
            return True, f"涨幅已达 {day_chg:.1f}%，涨幅过大 —— 高位止盈落袋，不追"
        if trend_up and day_chg > 0:
            return True, "趋势启动，拿住"
        return True, None
    return False, None


def build_alerts(res):
    """所有"该不该报"的判断都在这一个函数里。

    返回 [(稳定 key, 标题, 正文), ...]。key 不含日期（AlertState 会自己加日期前缀），
    也不含具体数字（同一类告警要能被冷却机制识别为"同一件事"）。
    """
    out = []
    coin = res["coin"]
    ind_s, ind_l = res["ind_s"], res["ind_l"]
    price = ind_s['price']

    # 1) 涨跌幅：>=5% 直接报；2%~5% 需要已收盘 bar 的量能达标（P1-1 修正后这个门槛才可达）
    threshold = config.CHG_THRESHOLD.get(coin, config.CHG_THRESHOLD['default'])
    vol_ok = ind_s['vol_ratio'] > float(getattr(config, "VOL_ENOUGH_MULT", 1.2))
    day_chg = ind_s['day_chg']
    fire, note = day_chg_verdict(day_chg, ind_s['trend_up'], vol_ok, threshold)
    if fire:
        word = "大涨" if day_chg > 0 else "大跌"
        body = (f"{coin} 今日{word} {day_chg:+.2f}%\n"
                f"现价 {price:.6g}｜已收盘bar {ind_s['close']:.6g}"
                f"（{ind_s['bar_time']}）｜量能 {ind_s['vol_ratio']:.2f}× 均量")
        if note:
            body += "\n" + note
        out.append((f"{coin}_涨跌幅", f"{'📈' if day_chg>0 else '📉'} {coin} {word} {day_chg:+.1f}%", body))

    # 2) 跌破 MA20（止盈落袋）
    if ind_s['prev_close'] > ind_s['ma20'] and ind_s['close'] < ind_s['ma20'] and ind_s['trend_up']:
        out.append((f"{coin}_跌破MA20", f"⚠️ {coin} 跌破MA20",
                    f"{coin} 已收盘bar {ind_s['close']:.6g} 跌破 MA20 {ind_s['ma20']:.6g}"
                    f"（{ind_s['bar_time']}），止盈落袋"))

    # 3) 信号反转
    if res["reverse_alert"]:
        out.append((f"{coin}_信号反转", f"🔄 {coin} 信号反转",
                    f"{coin} {res['reverse_alert']}\n现价 {price:.6g}"
                    f"｜买分 {res['b_score']:.1f} / 卖分 {res['s_score']:.1f}"))

    # 4) RSI 极度超买 + 连续长上影（已收盘 bar 的形态）
    if ind_s['rsi'] > 80 or ind_l['rsi'] > 80:
        b1, u1, _ = ind_s['shadows'][0]
        b2, u2, _ = ind_s['shadows'][1]
        if u1 > b1 * 1.5 and u2 > b2 * 1.5:
            out.append((f"{coin}_超买长上影", f"⚠️ {coin} RSI极度超买+连续长上影",
                        f"{coin} 15m RSI {ind_s['rsi']:.1f} / 1h RSI {ind_l['rsi']:.1f}，"
                        f"最近两根已收盘 bar 都是长上影，注意回落"))

    # 5) 移动止盈（补做 N12）
    dh = day_high(ind_s['df'])
    if dh:
        dd = (dh - price) / dh * 100
        need_trend = bool(getattr(config, "TRAILING_REQUIRE_TREND_UP", True))
        if dd >= float(getattr(config, "TRAILING_DRAWDOWN_PCT", 3.0)) and (ind_s['trend_up'] or not need_trend):
            out.append((f"{coin}_移动止盈", f"⚠️ {coin} 从今日最高回撤 {dd:.1f}%",
                        f"{coin} 今日最高 {dh:.6g}，现价 {price:.6g}，"
                        f"回撤 {dd:.1f}%（阈值 {config.TRAILING_DRAWDOWN_PCT}%），移动止盈落袋"))

    # 6) 到价提醒（止盈/止损）：用实时价
    if res["pair"] in config.PRICE_ALERT:
        tp, sl = config.PRICE_ALERT[res["pair"]]
        if price >= tp:
            out.append((f"{coin}_止盈{tp}", f"✅ {coin} 到止盈价",
                        f"现价 {price:.6g}，到你设置的止盈价 {tp}，可以卖出止盈了"))
        if price <= sl:
            below = (sl - price) / sl * 100
            out.append((f"{coin}_止损{sl}", f"⚠️ {coin} 到止损价 {sl}",
                        f"现价 {price:.6g}，已跌破止损价 {sl} 达 {below:.1f}%，注意风险"))
        set_day = getattr(config, "PRICE_ALERT_SET", {}).get(res["pair"])
        if set_day:
            try:
                age = (datetime.now() - datetime.strptime(set_day, "%Y-%m-%d")).days
            except ValueError:
                age = None
            if age is not None and age >= int(getattr(config, "PRICE_ALERT_STALE_DAYS", 14)):
                out.append((f"{coin}_价位复核{set_day}", f"⏰ {coin} 的止盈止损线该复核了",
                            f"当前止盈 {tp} / 止损 {sl} 是 {set_day} 设的，已经 {age} 天。"
                            f"现价 {price:.6g}。建议按最新行情重设 config.PRICE_ALERT"))

    return out


def _advice(res):
    """持仓/空仓建议。这里比较的信号值来自 strategy.get_signal 的返回值本身，
    不再手写中文字面量 —— P0-1 那种"字面量对不上、分支永不命中"的 bug 从结构上不可能再犯。"""
    ind_s = res["ind_s"]
    stop_loss, take_profit = ind_s['boll_l'], ind_s['boll_u']
    pos = "3成仓" if res["daily_up"] else "1成轻仓"
    signal = res["signal"]
    if signal == "买入":
        return (f"可以买入{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}",
                f"可以建仓{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}")
    if signal == "卖出":
        return ("全部止盈/止损卖出", "别买，等回调")
    return ("持有观望，不动", "观望，等明确信号")


def render_coin_report(res):
    """单币报告块（markdown 行列表）。口径：指标=已收盘 bar，价格=实时。"""
    ind_s, ind_l, flow = res["ind_s"], res["ind_l"], res["flow"]
    coin, price = res["coin"], ind_s['price']
    trend_judge = "大趋势向上" if ind_s['trend_up'] else "大趋势向下"
    flow_judge = ("明显流入" if flow['net_inflow'] > 1000
                  else "明显流出" if flow['net_inflow'] < -1000 else "平衡")
    rsi_judge = []
    rsi_judge.append("15m超卖" if ind_s['rsi'] < 30 else "15m超买" if ind_s['rsi'] > 70 else "15m中性")
    rsi_judge.append("1h超卖" if ind_l['rsi'] < 30 else "1h超买" if ind_l['rsi'] > 70 else "1h中性")
    sync = "同步上涨" if ind_s['day_chg'] * res.get("btc_chg", 0) > 0 else "背离"
    s_emoji = {"买入": "🟢", "卖出": "🔴"}.get(res["signal"], "⚪")
    hold_advice, empty_advice = _advice(res)
    l_space = (ind_l['boll_u'] - ind_l['close']) / ind_l['close'] * 100
    space = (ind_s['boll_u'] - price) / price * 100

    lo_pct = float(getattr(config, "LS_BUY_PCT", 80.0))
    se_pct = float(getattr(config, "LS_SELL_PCT", 20.0))
    if res["ls_pct"] is None:
        ls_judge = f"分位 —（预热中 {res['ls_n']}/{getattr(config,'LS_MIN_SAMPLES',60)}）"
    else:
        ls_judge = (f"分位 {res['ls_pct']:.0f}%"
                    + ("偏多" if res["ls_pct"] >= lo_pct else "偏空" if res["ls_pct"] <= se_pct else "平衡"))
    fmt = lambda v: "—" if v is None else f"{v:.2f}"   # noqa: E731

    return [
        f"## {coin}/USDT ${price:g} ({ind_s['day_chg']:+.2f}%, {sync})",
        "",
        f"> 指标口径：最后一根**已收盘** bar（{ind_s['bar_time']}）｜价格：实时",
        "",
        "| 指标 | 数值 | 判断 |",
        "|------|------|------|",
        f"| 趋势 | {'🟢' if ind_s['trend_up'] else '🔴'} "
        f"{'上涨' if ind_s['trend_up'] else '下跌'}(MA20 {ind_s['ma20']:.4g}) | {trend_judge} |",
        f"| 支撑/压力 | 支撑{ind_s['boll_l']:.4f} / 压力{ind_s['boll_u']:.4f} | 离压力{space:.1f}% |",
        f"| RSI | 15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f} | {', '.join(rsi_judge)} |",
        f"| 1h趋势 | BOLL上轨{ind_l['boll_u']:.4f} | 离上轨{l_space:.1f}%，"
        f"{'上涨' if ind_l['trend_up'] else '下跌'} |",
        f"| 资金流向 | ${flow['net_inflow']:.0f} | {flow_judge} |",
        f"| 量能 | {ind_s['vol_ratio']:.2f}× 均量 | "
        f"{'放量' if ind_s['vol_ratio'] > 1.2 else '缩量'} |",
        f"| 大户持仓多空比 | {fmt(res['ls_size'])} | size 口径（仅展示） |",
        f"| 大户账户多空比 | {fmt(res['ls_account'])} | {ls_judge}（打分口径 {config.LS_METRIC}） |",
        f"| 15m信号 | {s_emoji} {res['signal']} | 买{res['b_score']:.1f}/卖{res['s_score']:.1f} |",
        "",
        f"**结论**: {trend_judge}，资金{flow_judge}，"
        f"{'日线向上' if res['daily_up'] else '日线向下'}",
        f"**持仓建议**: {hold_advice}",
        f"**空仓建议**: {empty_advice}",
        "",
    ]
