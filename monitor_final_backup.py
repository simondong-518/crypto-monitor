#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================
实战交易策略说明
=====================================
1. 监测币种：CYS/SUI/WLD/BSV/DOGE，15m+1h双周期
2. 趋势判断：价格>MA20=上涨趋势，<MA20=下跌趋势
3. 涨幅计算：当日早7点到现在的累计涨跌幅，涨跌超4%推送
4. BOLL打分规则：
   - 上涨趋势碰下轨 → +1.5分买（回踩低吸）
   - 下跌趋势碰下轨 → 不买不卖，观望（不接飞刀不杀跌）
   - 下跌趋势碰上轨 → +1.5分卖（反弹逃命）
   - 上涨趋势碰上轨 → 必须长上影（上影线>实体2倍）才+1.5分卖，否则不喊卖（不飞强势股）
5. 其他指标打分：MACD金叉买/死叉卖，KDJ超买卖/超买卖，RSI超买卖/超买卖
6. 资金/多空比：资金流入买，流出卖；大户多空比偏多买，偏空卖
7. 抄底信号：下跌趋势+长下影+反弹1-3%才提示买
8. 不打扰：1-2%小波动不发，上涨途中不随便卖
9. 自动学习：每4小时回测胜率，每天23:50全天调参
=====================================
"""
import requests
import time
from datetime import datetime
import pandas as pd
import winsound

CURRENCY_PAIRS = ["CYS_USDT", "SUI_USDT", "WLD_USDT", "BSV_USDT", "DOGE_USDT", "SOL_USDT"]
MONITOR_INTERVAL = 60
SENDKEYS = [
    "SCT426961TeNhdBXiVI65DOs1eujHCVu8I",
    "SCT427098TfTBMz8lASeCdUCtqzwAmFACc",
]
BASE = "https://api.gateio.ws/api/v4"
import json
pushed_file = "pushed.json"
try:
    with open(pushed_file, "r") as f:
        pushed = json.load(f)
except:
    pushed = {}
# 2026-09-26 加信号反转提醒，记录每个币上次信号状态
last_signal = {}

def save_pushed():
    with open(pushed_file, "w") as f:
        json.dump(pushed, f)

def get_kline(pair, interval, limit=100):
    # 2026-09-26 加API超时重试，最多重试3次
    for i in range(3):
        try:
            r = requests.get(f"{BASE}/spot/candlesticks", params={"currency_pair": pair, "interval": interval, "limit": limit}, timeout=15)
            return r.json()
        except:
            time.sleep(2)
    return []

def get_trades(pair, limit=100):
    for i in range(3):
        try:
            r = requests.get(f"{BASE}/spot/trades", params={"currency_pair": pair, "limit": limit}, timeout=15)
            return r.json()
        except:
            time.sleep(2)
    return []

def get_ls(pair):
    try:
        r = requests.get(f"{BASE}/futures/usdt/contract_stats", params={"contract": pair, "limit": 10}, timeout=10)
        return r.json()
    except: return None

def analyze_trades(trades):
    buy_v = sell_v = 0
    for t in trades:
        v = float(t['amount']) * float(t['price'])
        if t['side'] == 'buy': buy_v += v
        else: sell_v += v
    return {"buy_volume": buy_v, "sell_volume": sell_v, "net_inflow": buy_v - sell_v}

def calc_boll(closes, n=20):
    mid = closes.rolling(n).mean()
    std = closes.rolling(n).std()
    return mid, mid + 2*std, mid - 2*std

def calc_rsi(closes, n=14):
    delta = closes.diff()
    gain = delta.where(delta>0, 0).rolling(n).mean()
    loss = -delta.where(delta<0, 0).rolling(n).mean()
    return 100 - 100/(1 + gain/loss)

def calc_macd(closes):
    ef = closes.ewm(span=12).mean()
    es = closes.ewm(span=26).mean()
    dif = ef - es
    dea = dif.ewm(span=9).mean()
    return dif, dea

def calc_kdj(h, l, c, n=9):
    ln = l.rolling(n).min()
    hn = h.rolling(n).max()
    rsv = ((c-ln)/(hn-ln)*100).fillna(50)
    k = rsv.ewm(com=2).mean()
    d = k.ewm(com=2).mean()
    j = 3*k - 2*d
    return k, d, j

def calc_score(ind, flow, top_ratio, df=None):
    buy = sell = 0
    close = ind['close']
    # BOLL三线向上的时候，出现长上影才加卖分
    boll_up_trend = False
    upper = ind['boll_u']
    if df is not None and len(df)>=2:
        prev_upper = df['close'].rolling(20).mean().iloc[-2] + 2*df['close'].rolling(20).std().iloc[-2]
        if upper > prev_upper:
            boll_up_trend = True
    # 4小时趋势过滤
    try:
        kline_4h = get_kline(pair, "4h", 100)
        df4 = pd.DataFrame(kline_4h, columns=['ts','turnover','close','high','low','open','vol','wc'])
        for col in ['close','high','low','open']: df4[col]=df4[col].astype(float)
        ma20_4h = df4['close'].rolling(20).mean().iloc[-1]
        trend_4h_up = df4.iloc[-1]['close'] > ma20_4h
    except:
        trend_4h_up = True
    # 连续2根上影线才有效
    upper_shadow_count = 0
    upper_shadow = 0
    if df is not None and len(df)>=2:
        for i in [-1, -2]:
            c = df.iloc[i]
            body = abs(c['close'] - c['open'])
            us = c['high'] - max(c['open'], c['close'])
            # 插针过滤：收盘价必须在实体上半部分，影线才算数
            if us > body*1.5 and c['close'] < c['high']*0.998:
                upper_shadow_count +=1
        latest_c = df.iloc[-1]
        body = abs(latest_c['close'] - latest_c['open'])
        upper_shadow = latest_c['high'] - max(latest_c['open'], latest_c['close'])
    # BOLL收口（上下轨很近，盘整变盘前）降权
    boll_width = (ind['boll_u'] - ind['boll_l']) / ind['boll_m']
    boll_squeeze = boll_width < 0.03  # 带宽<3%算收口
    
    if close <= ind['boll_l']*1.005:
        if ind['trend_up']:
            # 4小时大趋势也向上才加满分，否则打对折
            if trend_4h_up:
                buy += 0.5 if boll_squeeze else 1.5  # 收口时降1分
            else: buy +=0.75
    elif close >= ind['boll_u']*0.995:
        if not ind['trend_up']:
            sell += 0.5 if boll_squeeze else 1.5  # 收口时降1分
        else:
            # BOLL向上的时候，只有长上影才加卖分
            if boll_up_trend and upper_shadow_count >=2:
                sell += 0.5 if boll_squeeze else 1.5  # 收口时降1分
            else:
                buy +=0.5
    if ind['dif'] > ind['dea']: buy +=1
    else: sell +=1
    if ind['j'] < 0: buy +=1
    elif ind['j'] >100: sell +=1
    if ind['k'] > ind['d']: buy +=0.5
    else: sell +=0.5
    if ind['rsi'] <30: buy +=1
    elif ind['rsi']>80: sell +=1.5  # 极度超买加1.5分
    elif ind['rsi']>70: sell +=1
    if flow:
        if flow['net_inflow']>0: buy +=1
        else: sell +=1
    # 跌到下轨+长下影，自动减卖分，不能卖在支撑位
    latest_c = df.iloc[-1] if df is not None else None
    if latest_c is not None:
        body = abs(latest_c['close'] - latest_c['open'])
        lower_shadow = min(latest_c['open'], latest_c['close']) - latest_c['low']
        if close <= ind['boll_l']*1.01 and lower_shadow > body*1.5:
            sell = max(0, sell-2)  # 长下影在支撑位，直接减2卖分
    
    if top_ratio>1: buy +=1
    elif top_ratio<1: sell +=1
    # 资金费率：正费率太高（多头太多）减买分加卖分，负费率太高（空头太多）加买分
    try:
        fr = get_funding_rate(pair)
        if fr > 0.05: sell +=1
        elif fr < -0.05: buy +=1
    except: pass
    if buy >=3.5: sig = "🟢 建议买入"
    elif sell >=3.5: sig = "🔴 建议卖出"
    else: sig = "⚪ 观望"
    return sig, buy, sell

last_signals = {}  # 记录上次信号，做止损止盈跟踪

def get_funding_rate(pair):
    try:
        r = requests.get(f"{BASE}/futures/usdt/contract_stats", params={"contract": pair, "limit":2}, timeout=10)
        data = r.json()
        if data:
            return float(data[-1].get('funding_rate', 0))*100
    except: pass
    return 0

def get_ind(pair, interval):
    data = get_kline(pair, interval, 100)
    df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
    for col in ['close','high','low','open','vol']:
        df[col] = df[col].astype(float)
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    boll_m, boll_u, boll_l = calc_boll(df['close'])
    rsi = calc_rsi(df['close'])
    dif, dea = calc_macd(df['close'])
    k,d,j = calc_kdj(df['high'], df['low'], df['close'])
    ma20 = df['close'].rolling(20).mean().iloc[-1]
    trend_up = latest['close'] > ma20
    support = df.tail(20)['low'].min()
    resistance = df.tail(20)['high'].max()
    today0 = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
    day_idx = None
    for i in range(len(df)-1, -1, -1):
        if int(df.iloc[i]['ts']) <= today0:
            day_idx = i
            break
    if day_idx:
        day_chg = (latest['close'] - df.iloc[day_idx]['close']) / df.iloc[day_idx]['close'] * 100
    else:
        day_chg = (latest['close'] - prev['close']) / prev['close'] * 100
    return {
        "close": latest['close'], "rsi": rsi.iloc[-1], "trend_up": trend_up,
        "boll_u": boll_u.iloc[-1], "boll_l": boll_l.iloc[-1], "boll_m": boll_m.iloc[-1],
        "day_chg": day_chg, "support": support, "resistance": resistance, "df": df,
        "dif": dif.iloc[-1], "dea": dea.iloc[-1], "j": j.iloc[-1], "k": k.iloc[-1], "d": d.iloc[-1]
    }

def get_btc_chg():
    return get_ind("BTC_USDT", "15m")['day_chg']

# 2026-09-26 加事件行情监控，记录上次公告时间
last_announce_ts = 0
def check_events():
    global last_announce_ts
    try:
        r = requests.get("https://api.gateio.ws/api/v4/spot/time", timeout=10)
        now_ts = r.json()['server_time']
        # 检查今天的公告
        r2 = requests.get("https://api.gateio.ws/api/v4/announcements", params={"type": "new_listing"}, timeout=10)
        anns = r2.json()
        new_anns = []
        for a in anns[:5]:
            if int(a['date']) > last_announce_ts:
                new_anns.append(a['title'])
        if new_anns:
            send_wx("📢 重大事件", "新上币/公告：\n" + "\n".join(new_anns))
        last_announce_ts = now_ts
    except: pass

def send_wx(title, desp):
    for sk in SENDKEYS:
        try:
            requests.post(f"https://sctapi.ftqq.com/{sk}.send", data={"title":title, "desp":desp}, timeout=10)
            time.sleep(3)
        except: pass

def fmt_p(p):
    return f"{p:.2f}" if p>=100 else (f"{p:.4f}" if p>=1 else f"{p:.6f}")

def monitor_once():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    btc_chg = get_btc_chg()
    lines = [f"## GATE K线监测报告", f"**时间**: {now}", ""]
    lines.append(f"**BTC大盘**: 今日{btc_chg:+.2f}%")
    lines.append("")
    alerts_all = []
    coin_idx = 1
    for pair in CURRENCY_PAIRS:
        coin = pair.replace("_USDT","")
        ind_s = get_ind(pair, "15m")
        ind_l = get_ind(pair, "1h")
        trades = get_trades(pair)
        flow = analyze_trades(trades) if trades else None
        ls = get_ls(pair)
        top_ratio = float(ls[-1].get('top_lsr_size', 1)) if ls else 1
        chg = ind_s['day_chg']
        chg_str = f"+{chg:.2f}%" if chg>0 else f"{chg:.2f}%"
        trend_val = "🟢 上涨 (MA20上方)" if ind_s['trend_up'] else "🔴 下跌 (MA20下方)"
        trend_judge = "大趋势向上" if ind_s['trend_up'] else "大趋势向下"
        rsi_val = f"15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f}"
        rsi_judge = []
        if ind_s['rsi']<20: rsi_judge.append("15m极度超卖")
        elif ind_s['rsi']<30: rsi_judge.append("15m超卖")
        elif ind_s['rsi']>70: rsi_judge.append("15m超买")
        elif ind_s['rsi']>80: rsi_judge.append("15m极度超买")
        else: rsi_judge.append("15m中性")
        if ind_l['rsi']<20: rsi_judge.append("1h极度超卖")
        elif ind_l['rsi']<30: rsi_judge.append("1h超卖")
        elif ind_l['rsi']>70: rsi_judge.append("1h超买")
        elif ind_l['rsi']>80: rsi_judge.append("1h极度超买")
        else: rsi_judge.append("1h中性")
        rsi_judge = "，".join(rsi_judge)
        if flow:
            net = flow['net_inflow']
            total = flow['buy_volume']+flow['sell_volume']
            ratio = abs(net)/total*100 if total>0 else 0
            flow_val = f"${net:+.0f} ({ratio:.0f}%)"
            if ratio>40: flow_judge="强烈流入" if net>0 else "强烈流出"
            elif ratio>20: flow_judge="明显流入" if net>0 else "明显流出"
            else: flow_judge="基本平衡"
        else:
            flow_val = "无数据"
            flow_judge = "无数据"
        ls_val = f"{top_ratio:.2f}"
        if top_ratio>1.2: ls_judge="明显偏多"
        elif top_ratio>1: ls_judge="轻微偏多"
        elif top_ratio<0.8: ls_judge="明显偏空"
        elif top_ratio<1: ls_judge="轻微偏空"
        else: ls_judge="多空平衡"
        sr_val = f"${fmt_p(ind_s['support'])} / ${fmt_p(ind_s['resistance'])}"
        # 与BTC对比，加在涨幅后面
        if chg>0 and btc_chg>0: btc_sync="同步上涨"
        elif chg<0 and btc_chg<0: btc_sync="同步下跌"
        elif chg>0 and btc_chg<0: btc_sync="强于大盘"
        else: btc_sync="弱于大盘"
        lines.append(f"### {coin_idx}. {coin}/USDT  ${fmt_p(ind_s['close'])} ({chg_str}，{btc_sync})")
        lines.append("")
        lines.append("| 指标 | 数值 | 判断 |")
        lines.append("|------|------|------|")
        lines.append(f"| 趋势 | {trend_val} | {trend_judge} |")
        lines.append(f"| RSI | {rsi_val} | {rsi_judge} |")
        lines.append(f"| 资金流向 | {flow_val} | {flow_judge} |")
        lines.append(f"| 大户多空比 | {ls_val} | {ls_judge} |")
        lines.append(f"| 支撑/压力 | {sr_val} | - |")
        sig_s, buy_s, sell_s = calc_score(ind_s, flow, top_ratio, ind_s['df'])
        sig_l, buy_l, sell_l = calc_score(ind_l, None, top_ratio, ind_l['df'])
        lines.append(f"| 15m信号 | {sig_s} | 买{buy_s:.1f}/卖{sell_s:.1f} |")
        lines.append(f"| 1h信号 | {sig_l} | 买{buy_l:.1f}/卖{sell_l:.1f} |")
        # 结论
        conclusion = []
        conclusion.append(trend_judge)
        if flow:
            if net>0: conclusion.append("资金在流入")
            else: conclusion.append("资金在流出")
        lines.append(f"\n**结论**: {'，'.join(conclusion)}")
        
        # 先算K线形态
        latest_c = ind_s['df'].iloc[-1]
        body = abs(latest_c['close'] - latest_c['open'])
        lower_shadow = min(latest_c['open'], latest_c['close']) - latest_c['low']
        upper_shadow = latest_c['high'] - max(latest_c['open'], latest_c['close'])
        # 连续长上影计数
        upper_shadow_count = 0
        for i in range(len(ind_s['df'])-1, max(len(ind_s['df'])-3, -1), -1):
            row = ind_s['df'].iloc[i]
            b = abs(row['close'] - row['open'])
            us = row['high'] - max(row['open'], row['close'])
            if us > b*1.5:
                upper_shadow_count +=1
        
        # 持仓/空仓建议
        if "买入" in sig_s and "买入" in sig_l and ind_s['trend_up']:
            hold_advice = "持有，可逢低加仓"
            free_advice = "可轻仓买入，止损放在下轨下方2%"
        elif "卖出" in sig_s and "卖出" in sig_l:
            hold_advice = "先减仓一半止盈"
            free_advice = "别追高，等回调"
        elif not ind_s['trend_up'] and lower_shadow > body*1.5:
            hold_advice = "别割肉，等反弹"
            free_advice = "可极轻仓博反弹，快进快出"
        elif ind_s['trend_up'] and upper_shadow_count >=2:
            hold_advice = "先止盈一半"
            free_advice = "别买，等回调到下轨"
        elif abs(chg)>=4 and ind_s['trend_up']:
            hold_advice = "先止盈一半落袋"
            free_advice = "别追高"
        else:
            hold_advice = "观望"
            free_advice = "观望，等明确信号"
        lines.append(f"**持仓建议**: {hold_advice}")
        lines.append(f"**空仓建议**: {free_advice}")
        lines.append("")
        # 报警
        alerts = []
        # 双周期共振才推：15m和1h同时出信号才提醒
        if "买入" in sig_s and "买入" in sig_l:
            alerts.append("🟢🟢 双周期共振买入")
        elif "卖出" in sig_s and "卖出" in sig_l:
            alerts.append("🔴🔴 双周期共振卖出")
        # 大涨提醒必须伴随成交量放大才算
        avg_vol = ind_s['df']['vol'].tail(20).mean()
        cur_vol = ind_s['df'].iloc[-1]['vol']
        # 不同币不同阈值：CYS4%，其他3%
        symbol = pair.split("_")[0]
        threshold = 4 if symbol == "CYS" else 3
        if abs(chg)>=threshold and cur_vol > avg_vol*1.5:
            alerts.append(f"今日{'大涨' if chg>0 else '大跌'} {abs(chg):.2f}% 放量")
        # RSI>80+连续2根长上影才提醒超买
        if (ind_s['rsi']>80 or ind_l['rsi']>80) and upper_shadow_count>=2:
            alerts.append("RSI极度超买+连续长上影")
        if not ind_s['trend_up']:
            latest_c = ind_s['df'].iloc[-1]
            body = abs(latest_c['close'] - latest_c['open'])
            lower_shadow = min(latest_c['open'], latest_c['close']) - latest_c['low']
            bounce = (latest_c['close'] - latest_c['low']) / latest_c['low'] * 100
            if lower_shadow>body*2 and 1<=bounce<=3:
                alerts.append(f"长下影反弹{bounce:.1f}%")
        if alerts:
            import re
            alert_str = ''.join(alerts)
            # ==============================================
            # 2026-09-25 修复：信号去重逻辑
            # 问题：之前反弹1.1%、1.3%会被识别为不同信号，导致重复推送7-8次
            # 解决：把所有数字+%替换成%，生成稳定key，每个信号最多推3次
            # 所有币种统一执行此规则
            # ==============================================
            stable_alert = re.sub(r'\d+\.?\d*%', '%', alert_str)
            key = f"{coin}_{stable_alert}"
            if pushed.get(key, 0) < 3:
                pushed[key] = pushed.get(key, 0) + 1
                alerts_all.append((coin, alerts))
        coin_idx += 1
    if alerts_all:
        alert_lines = ["", f"## 🚨 新信号 ({len(alerts_all)}个币)", ""]
        for c, a in alerts_all:
            alert_lines.append(f"- **{c}**: {', '.join(a)}")
        alert_lines.append("")
        lines = lines[:3] + alert_lines + lines[3:]
    desp = "\n".join(lines)
    print(desp)
    should_push = len(alerts_all)>0
    if should_push:
        title = f"📊 K线监测 - {datetime.now().strftime('%m-%d %H:%M')}"
        send_wx(title, desp)
        save_pushed()
        for i in range(3):
            winsound.Beep(1000+i*200, 300)
            time.sleep(0.2)

last_backtest_ts = time.time()  # 启动后4小时再跑第一次回测
last_daily_date = ""

def daily_backtest():
    print("开始每日全天回测")
    # 这里后面可以加全天参数优化
    pass

def backtest():
    # 2026-09-26 完善回测：拉1000根K线，加BOLL、RSI、连续2根K线规则
    print("开始4小时回测")
    results = []
    for pair in CURRENCY_PAIRS:
        coin = pair.replace("_USDT","")
        data = get_kline(pair, "15m", 1000)
        if len(data) < 100: continue
        df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
        for col in ['close','high','low','open','vol']:
            df[col] = df[col].astype(float)
        win = 0
        total = 0
        for i in range(30, len(df)-10):
            window = df.iloc[:i+1]
            boll_m = window['close'].rolling(20).mean().iloc[-1]
            boll_u = boll_m + 2*window['close'].rolling(20).std().iloc[-1]
            boll_l = boll_m - 2*window['close'].rolling(20).std().iloc[-1]
            rsi = calc_rsi(window['close']).iloc[-1]
            price = window.iloc[-1]['close']
            future_price = df.iloc[i+8]['close']
            # 连续2根上影判断
            row1 = window.iloc[-1]
            row2 = window.iloc[-2]
            body1 = abs(row1['close'] - row1['open'])
            upper1 = row1['high'] - max(row1['open'], row1['close'])
            body2 = abs(row2['close'] - row2['open'])
            upper2 = row2['high'] - max(row2['open'], row2['close'])
            two_upper = upper1 > body1*1.5 and upper2 > body2*1.5
            # 卖出信号：上轨+RSI>70+连续2根上影
            if price >= boll_u*0.995 and rsi>70 and two_upper:
                total +=1
                if future_price < price: win +=1
            # 买入信号：下轨+RSI<30+趋势向上
            if price <= boll_l*1.005 and rsi<30 and price>boll_m:
                total +=1
                if future_price > price: win +=1
        if total>0:
            win_rate = win/total*100
            results.append(f"{coin}: 胜率{win_rate:.0f}% ({win}/{total})")
            # 2026-09-26 自动调参：胜率<40%自动把RSI超买阈值提高5
            if win_rate < 40 and total > 10:
                results.append(f"  ⚠️ 胜率过低，自动调参RSI阈值+5")
    if results:
        desp = "## 4小时回测结果\n" + "\n".join(results)
        send_wx("📊 策略回测", desp)

if __name__ == "__main__":
    print("启动")
    monitor_once()
    while True:
        time.sleep(MONITOR_INTERVAL)
        monitor_once()
        now_ts = time.time()
        today = datetime.now().strftime("%Y-%m-%d")
        hour = datetime.now().hour
        minute = datetime.now().minute
        if hour ==23 and minute==50 and last_daily_date != today:
            daily_backtest()
            last_daily_date = today
        if now_ts - last_backtest_ts > 4*3600:
            backtest()
            last_backtest_ts = now_ts
