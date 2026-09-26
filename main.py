import json
import time
import re
from datetime import datetime
from config import *
from api import get_kline, get_trades, get_ls, get_btc_chg, check_events
from indicators import get_indicator, get_daily_trend
from strategy import calc_score, get_signal, last_signal
from notifier import send_wx, beep
from backtest import backtest, daily_backtest, last_result as last_backtest_result

# 鍔犺浇鎺ㄩ€佽褰?
pushed_file = "pushed.json"
try:
    with open(pushed_file, "r") as f:
        pushed = json.load(f)
except:
    pushed = {}

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

def monitor_once():
    btc_chg = get_btc_chg()
    # BTC鏆磋穼>3%閬块櫓鎻愰啋
    if btc_chg < -3:
        send_wx("鈿狅笍 BTC鏆磋穼閬块櫓", f"BTC浠婃棩璺寋btc_chg:.1f}%锛屾墍鏈夊竵澶ф鐜囪窡璺岋紝鍒妱搴曪紝鎵嬮噷鏈夊竵閫㈤珮鍑忎粨")
    # 鑷畾涔夊埌浠锋彁閱?
    for alert_pair, (take_profit, stop_loss) in PRICE_ALERT.items():
        coin = alert_pair.replace("_USDT","")
        try:
            ind = get_indicator(alert_pair, "15m")
            price = ind['close']
            key_tp = f"{coin}_姝㈢泩浠穥take_profit}"
            key_sl = f"{coin}_姝㈡崯浠穥stop_loss}"
            if price >= take_profit and pushed.get(key_tp, 0) < MAX_PUSH_PER_SIGNAL:
                pushed[key_tp] = pushed.get(key_tp,0)+1
                send_wx(f"鉁?{coin}鍒版鐩堜环锛?, f"鐜颁环{price}锛屽埌浣犺缃殑姝㈢泩浠穥take_profit}锛屽彲浠ュ崠鍑烘鐩堜簡")
                beep()
            if price <= stop_loss and pushed.get(key_sl, 0) < MAX_PUSH_PER_SIGNAL:
                pushed[key_sl] = pushed.get(key_sl,0)+1
                send_wx(f"鈿狅笍 {coin}鍒版鎹熶环锛?, f"鐜颁环{price}锛屽埌浣犺缃殑姝㈡崯浠穥stop_loss}锛屾敞鎰忛闄?)
                beep()
        except: pass
    alerts_all = []
    lines = ["# 馃搳 K绾跨洃娴嬫姤鍛?, f"鏃堕棿锛歿datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
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
            # 鎵撳垎
            b_score, s_score = calc_score(ind_s, ind_l, flow, top_ratio, ind_s['df'])
            # 鏃ョ嚎澶ц秼鍔胯繃婊わ細鏃ョ嚎鍚戜笅锛屼拱鍒嗗噺1.5
            if not daily_up:
                b_score -= 1.5
            # 4灏忔椂澶ц秼鍔胯繃婊?
            ind_4h = get_indicator(pair, "4h")
            if not ind_4h['trend_up']:
                b_score -= 1
            current_signal, reverse_alert = get_signal(coin, b_score, s_score, ind_s, ind_l)
            # 鐢熸垚鎻愰啋
            alerts = []
            threshold = CHG_THRESHOLD.get(coin, CHG_THRESHOLD['default'])
            # 娑ㄨ穼骞呮彁閱掑繀椤讳即闅忔垚浜ら噺>1.5鍊嶅钩鍧囬噺
            avg_vol = ind_s['df']['vol'].rolling(20).mean().iloc[-1]
            cur_vol = ind_s['df']['vol'].iloc[-1]
            vol_enough = cur_vol > avg_vol * 1.5
            if abs(ind_s['day_chg']) >= 5:
                alerts.append(f"浠婃棩{'澶ф定' if ind_s['day_chg']>0 else '澶ц穼'}{ind_s['day_chg']:.1f}%")
                if ind_s['trend_up'] and ind_s['day_chg']>0:
                    alerts.append("锛岃秼鍔垮惎鍔紝鎷夸綇")
            elif abs(ind_s['day_chg']) >= threshold and vol_enough:
                alerts.append(f"浠婃棩{'澶ф定' if ind_s['day_chg']>0 else '澶ц穼'}{ind_s['day_chg']:.1f}%")
            ma20 = ind_s['df']['close'].rolling(20).mean().iloc[-1]
            prev_close = ind_s['df']['close'].iloc[-2]
            if prev_close > ma20 and ind_s['close'] < ma20 and ind_s['trend_up']:
                alerts.append("鈿狅笍 璺岀牬MA20锛屾鐩堣惤琚?)
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
                    alerts.append("RSI鏋佸害瓒呬拱+杩炵画闀夸笂褰?)
            if alerts:
                alert_str = ''.join(alerts)
                stable_alert = re.sub(r'\d+\.?\d*%', '%', alert_str)
                key = f"{coin}_{stable_alert}"
                if pushed.get(key, 0) < MAX_PUSH_PER_SIGNAL:
                    pushed[key] = pushed.get(key, 0) + 1
                    alerts_all.append((coin, alerts))
            # 鐢熸垚鎶ュ憡琛?
            sync = "鍚屾涓婃定" if ind_s['day_chg']*btc_chg>0 else "鑳岀"
            lines.append(f"## {coin}/USDT ${ind_s['close']} ({ind_s['day_chg']:+.2f}%, {sync})")
            lines.append("")
            lines.append("| 鎸囨爣 | 鏁板€?| 鍒ゆ柇 |")
            lines.append("|------|------|------|")
            trend_emoji = "馃煝" if ind_s['trend_up'] else "馃敶"
            trend_judge = "澶ц秼鍔垮悜涓? if ind_s['trend_up'] else "澶ц秼鍔垮悜涓?
            lines.append(f"| 瓒嬪娍 | {trend_emoji} {'涓婃定' if ind_s['trend_up'] else '涓嬭穼'}(MA20) | {trend_judge} |")
            space = (ind_s['boll_u'] - ind_s['close'])/ind_s['close']*100
            lines.append(f"| 鏀拺/鍘嬪姏 | 鏀拺{ind_s['boll_l']:.4f} / 鍘嬪姏{ind_s['boll_u']:.4f} | 绂诲帇鍔泏space:.1f}% |")
            rsi_judge = []
            if ind_s['rsi']<30: rsi_judge.append("15m瓒呭崠")
            elif ind_s['rsi']>70: rsi_judge.append("15m瓒呬拱")
            else: rsi_judge.append("15m涓€?)
            if ind_l['rsi']<30: rsi_judge.append("1h瓒呭崠")
            elif ind_l['rsi']>70: rsi_judge.append("1h瓒呬拱")
            else: rsi_judge.append("1h涓€?)
            lines.append(f"| RSI | 15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f} | {', '.join(rsi_judge)} |")
            flow_judge = "鏄庢樉娴佸叆" if flow['net_inflow']>1000 else ("鏄庢樉娴佸嚭" if flow['net_inflow']<-1000 else "骞宠　")
            lines.append(f"| 璧勯噾娴佸悜 | ${flow['net_inflow']:.0f} | {flow_judge} |")
            lines.append(f"| 澶ф埛澶氱┖姣?| {top_ratio:.2f} | {'鍋忕┖' if top_ratio<0.7 else '鍋忓' if top_ratio>1.3 else '骞宠　'} |")
            s_emoji = "馃煝" if current_signal=="涔板叆" else ("馃敶" if current_signal=="鍗栧嚭" else "鈿?)
            lines.append(f"| 15m淇″彿 | {s_emoji} {current_signal} | 涔皗b_score:.1f}/鍗杮s_score:.1f} |")
            # 寤鸿
            stop_loss = ind_s['boll_l']
            take_profit = ind_s['boll_u']
            daily_judge = "鏃ョ嚎鍚戜笂" if daily_up else "鏃ョ嚎鍚戜笅"
            if current_signal == "涔板叆":
                # 浠撲綅寤鸿锛氭棩绾垮悜涓婁拱3鎴愶紝鏃ョ嚎鍚戜笅涔?鎴?
                if daily_up:
                    pos = "3鎴愪粨"
                else:
                    pos = "1鎴愯交浠?
                hold_advice = f"鍙互涔板叆锛寋pos}锛屾鎹焮stop_loss:.4f}锛屾鐩坽take_profit:.4f}"
                empty_advice = f"鍙互寤轰粨锛寋pos}锛屾鎹焮stop_loss:.4f}锛屾鐩坽take_profit:.4f}"
            elif current_signal == "鍗栧嚭":
                hold_advice = "鍏ㄩ儴姝㈢泩/姝㈡崯鍗栧嚭"
                empty_advice = "鍒拱锛岀瓑鍥炶皟"
            else:
                hold_advice = "鎸佹湁瑙傛湜锛屼笉鍔?
                empty_advice = "瑙傛湜锛岀瓑鏄庣‘淇″彿"
            lines.append("")
            lines.append(f"**缁撹**: {trend_judge}锛岃祫閲憑flow_judge}锛寋daily_judge}")
            lines.append(f"**鎸佷粨寤鸿**: {hold_advice}")
            lines.append(f"**绌轰粨寤鸿**: {empty_advice}")
            lines.append("")
        except Exception as e:
            print(f"{coin}鍑洪敊: {e}")
            continue
    if alerts_all:
        alert_lines = ["", f"## 馃毃 鏂颁俊鍙?({len(alerts_all)}涓竵)", ""]
        for c, a in alerts_all:
            alert_lines.append(f"- **{c}**: {', '.join(a)}")
        alert_lines.append("")
        lines = lines[:3] + alert_lines + lines[3:]
    desp = "\n".join(lines)
    # 鍔犱笂鏈€杩?灏忔椂鍥炴祴缁撴灉
    if last_backtest_result:
        desp += "\n\n| 鏈€杩?h鍥炴祴 | 璇︽儏 | |\n|------|------|------|\n" + last_backtest_result
    print(desp)
    if alerts_all:
        title = f"馃搳 K绾跨洃娴?- {datetime.now().strftime('%m-%d %H:%M')}"
        send_wx(title, desp)
        save_pushed()
        beep()

if __name__ == "__main__":
    print(f"鍚姩妯″潡鍖栫洃娴嬬郴缁?{VERSION} {VERSION_DATE}")
    last_backtest_ts = time.time()
    last_day = datetime.now().day
    monitor_once()
    while True:
        try:
            now_ts = time.time()
            now_hour = datetime.now().hour
            now_min = datetime.now().minute
            now_day = datetime.now().day
            # 姣忓ぉ0鐐硅嚜鍔ㄦ竻绌烘帹閫佽褰?
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
            print(f"涓诲惊鐜嚭閿? {e}")
        time.sleep(CHECK_INTERVAL)
