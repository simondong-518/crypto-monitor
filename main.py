# -*- coding: utf-8 -*-
import sys
import io
# 强制整个程序用UTF-8编码，解决Windows下中文乱码
# line_buffering=True：让 print 逐行落盘。否则重定向到文件时是块缓冲，
# 日志会滞后很久才出现（排障时看不到实时输出）。仅影响输出时机，不改任何逻辑。
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
import json
import time
import re
# 统一资金换算：亿/万/千
from datetime import datetime
from config import *
from api import get_kline, get_trades, get_ls, get_btc_chg, check_events, get_flow_1h
from indicators import get_indicator, get_daily_trend
from strategy import calc_score, get_signal, last_signal
from notifier import send_wx
from alert_state import AlertState, stable_alert_key
from news import get_latest_news

# ── 分层模块（架构分离：指标/信号/报告/推送/冷却 各自独立，便于修改）──
from alerting import pushed, should_alert, mark_alert, save_pushed
from signals import (SLOW_START_LOCK, SIGNAL_LOCK, FLOW_PREV,
                     LAST_FLOW_DIR, LAST_RSI_STATE,
                     MAX_FLOW_IN_15M, MAX_FLOW_OUT_15M, SHRINK_LOCK,
                     fmt_money, check_shrink_rise, check_shrink_drop,
                     analyze_trades, update_daily_extreme, _boll_open_up,
                     _is_report_signal, evaluate_coin, _REPORT_KEYWORDS)
from alert_state import stable_alert_key
import report
import pushing
import siglog
from backtest import backtest, daily_backtest, last_result as last_backtest_result

# 只读 H5 面板（展示层）—— 不参与判定；导入失败也不能挡住监控
try:
    import panel
    import panel_adapter
    _PANEL_IMPORT_OK = True
except Exception as _e:
    _PANEL_IMPORT_OK = False
    print(f"[面板] 未启用（导入失败）：{type(_e).__name__}: {_e}", flush=True)

#回测结果全局变量
last_backtest_result = ""


def monitor_once():
    """一轮监测：市场级提醒 → 逐币判定 → 分级推送 → 面板发布。"""
    siglog.round_start()          # 给本轮所有记录一个统一轮次号（工具层）
    _round_t0 = time.time()      # 面板"上一轮耗时"用（纯展示）
    panel_coins = []             # 面板：本轮各币只读视图
    btc_chg = get_btc_chg()
    pushing.check_market_notices(btc_chg)

    alerts_all = []
    coin_chg = {}  # 2026-10-07 新增：存所有币今日涨跌幅，用于板块联动判断
    lines = ["# 📈 K线监测报告", f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    for pair in CURRENCY_PAIRS:
        coin = pair.replace("_USDT", "")
        rep = evaluate_coin(pair, coin, btc_chg, alerts_all, lines, coin_chg, panel_coins)
        if rep is not None:
            lines.extend(report.render(rep))

    pushing.dispatch(alerts_all, lines, coin_chg, last_backtest_result)

    if alerts_all:
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
