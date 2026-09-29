import json
import os
import time
import re
from datetime import datetime
from config import *
from api import get_kline, get_trades, get_ls, get_btc_chg, check_events
from indicators import get_indicator, get_daily_trend
from strategy import calc_score, get_signal, last_signal
from notifier import send_wx
from news import get_latest_news
pushed_news = set()
from backtest import backtest, daily_backtest, last_result as last_backtest_result

# 加载推送记录（只保留当天，key 形如 "2026-09-29|SUI_今日大跌"）
# 历史坑：key 不带日期 + 状态文件入库 → 昨天顶到上限的告警今天继续被压掉，且界面没有任何提示
pushed_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pushed.json")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def load_pushed():
    try:
        with open(pushed_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    prefix = _today() + "|"
    kept = {k: v for k, v in raw.items() if k.startswith(prefix)}
    dropped = len(raw) - len(kept)
    if dropped:
        print(f"[状态] 丢弃 {dropped} 条非当天推送计数（只保留 {prefix}*）")
    return kept


pushed = load_pushed()

# 存最近一次回测结果
# 注意：下一行是历史遗留的影子变量（P0-5），它遮蔽了上面 import 进来的 backtest.last_result，
# 导致回测结果永远进不了推送。回测整块已跳过，本轮不动它，仅修掉乱码注释。
last_backtest_result = ""


def save_pushed():
    with open(pushed_file, "w", encoding="utf-8") as f:
        json.dump(pushed, f, ensure_ascii=False)

def analyze_trades(trades):
    buy_v = sell_v = 0
    for t in trades:
        v = float(t['amount']) * float(t['price'])
        if t['side'] == 'buy': buy_v += v
        else: sell_v += v
    return {"buy_volume": buy_v, "sell_volume": sell_v, "net_inflow": buy_v - sell_v}


def day_chg_alerts(day_chg, trend_up, vol_enough, threshold):
    """涨跌幅相关提醒。抽成纯函数：可单测，也为将来的规则命中统计（N11）铺路。"""
    out = []
    big = f"今日{'大涨' if day_chg > 0 else '大跌'}{day_chg:.1f}%"
    if abs(day_chg) >= 5:
        out.append(big)
        if day_chg > 0 and day_chg >= HIGH_CHG_THRESHOLD:
            # 补做4（原提交 c67713c 声称的功能，实际一行没写）：涨太多不再喊拿住
            out.append("，涨幅过大，高位止盈落袋")
        elif trend_up and day_chg > 0:
            out.append("，趋势启动，拿住")
    elif abs(day_chg) >= threshold and vol_enough:
        out.append(big)
    return out


def monitor_once():
    btc_chg = get_btc_chg()
    # BTC暴跌>3%避险提醒
    if btc_chg < -3:
        send_wx("⚠️ BTC暴跌预警", f"BTC今日跌{btc_chg:.1f}%，所有币大概率跟跌，别抄底，手里有币逢高减仓")
    # 自定义到价提醒
    for alert_pair, (take_profit, stop_loss) in PRICE_ALERT.items():
        coin = alert_pair.replace("_USDT","")
        try:
            ind = get_indicator(alert_pair, "15m")
            price = ind['close']
            key_tp = f"{_today()}|{coin}_止盈{take_profit}"
            key_sl = f"{_today()}|{coin}_止损{stop_loss}"
            if price >= take_profit and pushed.get(key_tp, 0) < MAX_PUSH_PER_SIGNAL:
                pushed[key_tp] = pushed.get(key_tp,0)+1
                send_wx(f"✅ {coin}到止盈价！", f"现价{price}，到你设置的止盈价{take_profit}，可以卖出止盈了")
                beep()
            if price <= stop_loss and pushed.get(key_sl, 0) < MAX_PUSH_PER_SIGNAL:
                pushed[key_sl] = pushed.get(key_sl,0)+1
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
            ls = get_ls(pair)
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
            current_signal, reverse_alert = get_signal(coin, b_score, s_score, ind_s, ind_l)
            # 生成提醒
            alerts = []
            threshold = CHG_THRESHOLD.get(coin, CHG_THRESHOLD['default'])
            # 涨跌幅提醒必须伴随成交量>1.2倍平均量
            avg_vol = ind_s['df']['vol'].rolling(20).mean().iloc[-1]
            cur_vol = ind_s['df']['vol'].iloc[-1]
            vol_enough = cur_vol > avg_vol * 1.2
            alerts.extend(day_chg_alerts(ind_s['day_chg'], ind_s['trend_up'], vol_enough, threshold))
            ma20 = ind_s['df']['close'].rolling(20).mean().iloc[-1]
            prev_close = ind_s['df']['close'].iloc[-2]
            if prev_close > ma20 and ind_s['close'] < ma20 and ind_s['trend_up']:
                alerts.append("⚠️ 跌破MA20，止盈落袋")
            if reverse_alert:
                alerts.append(reverse_alert)
            if (ind_s['rsi']>80 or ind_l['rsi']>80):
                row1 = ind_s['df'].iloc[-1]
                row2 = ind_s['df'].iloc[-2]
                body1 = abs(row1['close'] - row1['open'])
                upper1 = row1['high'] - max(row1['open'], row1['close'])
                body2 = abs(row2['close'] - row2['open'])
                upper2 = row2['high'] - max(row2['open'], row2['close'])
                if upper1>body1*1.5 and upper2>body2*1.5:
                    alerts.append("RSI极度超买+连续长上影")
            if alerts:
                alert_str = ''.join(alerts)
                stable_alert = re.sub(r'\d+\.?\d*%', '%', alert_str)
                key = f"{_today()}|{coin}_{stable_alert}"
                if pushed.get(key, 0) < MAX_PUSH_PER_SIGNAL:
                    pushed[key] = pushed.get(key, 0) + 1
                    alerts_all.append((coin, alerts))
            # 生成报告表
            sync = "同步上涨" if ind_s['day_chg']*btc_chg>0 else "背离"
            lines.append(f"## {coin}/USDT ${ind_s['close']} ({ind_s['day_chg']:+.2f}%, {sync})")
            lines.append("")
            lines.append("| 指标 | 数值 | 判断 |")
            lines.append("|------|------|------|")
            trend_emoji = "🟢" if ind_s['trend_up'] else "🔴"
            trend_judge = "大趋势向上" if ind_s['trend_up'] else "大趋势向下"
            lines.append(f"| 趋势 | {trend_emoji} {'上涨' if ind_s['trend_up'] else '下跌'}(MA20) | {trend_judge} |")
            space = (ind_s['boll_u'] - ind_s['close'])/ind_s['close']*100
            lines.append(f"| 支撑/压力 | 支撑{ind_s['boll_l']:.4f} / 压力{ind_s['boll_u']:.4f} | 离压力{space:.1f}% |")
            rsi_judge = []
            if ind_s['rsi']<30: rsi_judge.append("15m超卖")
            elif ind_s['rsi']>70: rsi_judge.append("15m超买")
            else: rsi_judge.append("15m中性")
            if ind_l['rsi']<30: rsi_judge.append("1h超卖")
            elif ind_l['rsi']>70: rsi_judge.append("1h超买")
            else: rsi_judge.append("1h中性")
            lines.append(f"| RSI | 15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f} | {', '.join(rsi_judge)} |")
            # 1h趋势
            l_space = (ind_l['boll_u'] - ind_l['close'])/ind_l['close']*100
            lines.append(f"| 1h趋势 | BOLL上轨{ind_l['boll_u']:.4f} | 离上轨{l_space:.1f}%，{'上涨' if ind_l['trend_up'] else '下跌'} |")
            flow_judge = "明显流入" if flow['net_inflow']>1000 else ("明显流出" if flow['net_inflow']<-1000 else "平衡")
            lines.append(f"| 资金流向 | ${flow['net_inflow']:.0f} | {flow_judge} |")
            lines.append(f"| 大户多空比 | {top_ratio:.2f} | {'偏空' if top_ratio<0.7 else '偏多' if top_ratio>1.3 else '平衡'} |")
            s_emoji = "🟢" if current_signal=="买入" else ("🔴" if current_signal=="卖出" else "⚪")
            lines.append(f"| 15m信号 | {s_emoji} {current_signal} | 买{b_score:.1f}/卖{s_score:.1f} |")
            # 建议
            stop_loss = ind_s['boll_l']
            take_profit = ind_s['boll_u']
            daily_judge = "日线向上" if daily_up else "日线向下"
            if current_signal == "买入":
                # 仓位建议：日线向上买3成，日线向下买1成
                if daily_up:
                    pos = "3成仓"
                else:
                    pos = "1成轻仓"
                hold_advice = f"可以买入{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"
                empty_advice = f"可以建仓{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"
            elif current_signal == "卖出":
                hold_advice = "全部止盈/止损卖出"
                empty_advice = "别买，等回调"
            else:
                hold_advice = "持有观望，不动"
                empty_advice = "观望，等明确信号"
            lines.append("")
            lines.append(f"**结论**: {trend_judge}，资金{flow_judge}，{daily_judge}")
            lines.append(f"**持仓建议**: {hold_advice}")
            lines.append(f"**空仓建议**: {empty_advice}")
            lines.append("")
        except Exception as e:
            print(f"{coin}出错: {e}")
            continue
    if alerts_all:
        alert_lines = ["", f"## 🔔 新信号({len(alerts_all)}个币))", ""]
        for c, a in alerts_all:
            alert_lines.append(f"- **{c}**: {', '.join(a)}")
        alert_lines.append("")
        lines = lines[:3] + alert_lines + lines[3:]
    desp = "\n".join(lines)
    # 加上最近4小时回测结果
    if last_backtest_result:
        desp += "\n\n| 最近4h回测 | 详情 | |\n|------|------|------|\n" + last_backtest_result
    print(desp)
    if alerts_all:
        title = f"📈 K线监测- {datetime.now().strftime('%m-%d %H:%M')}"
        send_wx(title, desp)
        save_pushed()
        beep()

if __name__ == "__main__":
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
            # 每天0点自动清空推送记录
            if now_day != last_day:
                # 新的一天：清掉旧日期前缀的计数（新 key 带新日期，不会再命中旧 key）
                for stale in [k for k in pushed if not k.startswith(_today() + "|")]:
                    pushed.pop(stale, None)
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
            print(f"主循环出错: {e}")
        time.sleep(CHECK_INTERVAL)
