# -*- coding: utf-8 -*-
"""推送编排层。

架构分离自 main.py（纯搬运，逻辑一字未改）：
    · check_market_notices()：BTC 避险 / 新闻 / 价格止盈止损（市场级提醒）
    · dispatch()：板块联动 + 信号分级 → 标题/正文 → 发送 → 落盘
"""
import time
from datetime import datetime

from config import *
from indicators import get_indicator
from news import get_latest_news
from notifier import send_wx
from alerting import pushed, should_alert, mark_alert, save_pushed
from signals import _is_report_signal

# 新闻推送全局变量
pushed_news = set()
last_news_date = ""
news_count = 0


def check_market_notices(btc_chg):
    """市场级提醒：BTC 避险 / 新闻 / 价格止盈止损。"""
    global last_news_date, news_count
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
    # 【2026-10-05 修复】一天最多推5条新闻，避免刷屏
    coin_news, macro_news = get_latest_news()
    news_count_today = 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    global last_news_date, news_count
    if not hasattr(last_news_date, 'value') or last_news_date != today_str:
        last_news_date = today_str
        news_count = 0
    for n in macro_news:
        if news_count >=5: break
        if n not in pushed_news:
            pushed_news.add(n)
            send_wx("📰 宏观事件提醒", n)
            news_count +=1
    for n in coin_news:
        if news_count >=5: break
        if n not in pushed_news:
            pushed_news.add(n)
            send_wx("📰 币圈新闻", n)
            news_count +=1
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


def dispatch(alerts_all, lines, coin_chg, last_backtest_result=""):
    """板块联动 + 信号分级推送。返回是否真的发出去了。"""
    # 2026-10-07 新增：板块联动判断
    ai_coins = ['SUI', 'WLD', 'CYS']
    main_coins = ['BTC', 'BSV', 'DOGE']
    ai_up = sum(1 for c in ai_coins if coin_chg.get(c,0) > 1)
    ai_down = sum(1 for c in ai_coins if coin_chg.get(c,0) < -1)
    main_up = sum(1 for c in main_coins if coin_chg.get(c,0) > 1)
    main_down = sum(1 for c in main_coins if coin_chg.get(c,0) < -1)
    # AI板块3个币里有2个以上同涨/同跌超过1%，加板块提醒
    if ai_up >=2:
        lines.append(f"- 🌐 AI板块联动上涨：SUI/WLD/CYS中{ai_up}个涨超1%，板块行情可持有")
    if ai_down >=2:
        lines.append(f"- 🌐 AI板块联动下跌：SUI/WLD/CYS中{ai_down}个跌超1%，板块回调注意风险")
    if main_up >=2:
        lines.append(f"- 🌐 主流币联动上涨：BTC/BSV/DOGE中{main_up}个涨超1%，大盘行情")
    if main_down >=2:
        lines.append(f"- 🌐 主流币联动下跌：BTC/BSV/DOGE中{main_down}个跌超1%，大盘回调")
    if alerts_all:
        alert_lines = ["", f"## 🔔 新信号({len(alerts_all)}个币))", ""]
        need_detail = False
        for c, a in alerts_all:
            alert_lines.append(f"- **{c}**: {', '.join(a)}")
            # 判断有没有需要详细报告的重要操作信号
            # 【2026-10-07 改】同 L1208：用统一的 _is_report_signal() 判 8 类，
            #   不再用模糊关键词（否则资金流误命中、V反/见顶漏判）。
            if any(_is_report_signal(x) for x in a):
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
