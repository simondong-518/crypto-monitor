"""主监控循环。

2026-09-29 本版落地：
  P1-1  指标算在「最后一根已收盘 bar」，只有现价/当日涨跌幅用实时价（见 indicators.py）
  P1-3  大户多空比改「按币自身滚动分位数」打分（见 ls_percentile.py）
  P1-7  评估/报警判定/报告渲染全部收拢到 evaluate.py 单一入口
  P1-12 到价提醒改状态式：首次必报，之后按冷却反复提醒，永不"当天永久沉默"；并提示价位过期
  N12   移动止盈（当天最高点回撤）补做
  通知  通道可插拔（控制台/文件/Server酱/钉钉），通道失败不影响"要不要报警"的判断

用户定调（2026-09-29）：只要触发规则就该上报；额度是额度问题，不影响业务主线。
"""
import os
import time
from datetime import datetime

from config import *                                    # noqa: F403
from api import get_btc_chg, check_events
from notifier import notify, beep, get_channels
from alert_state import AlertState
from ls_percentile import LSPercentile
from evaluate import evaluate_coin, build_alerts, render_coin_report
from backtest import backtest, daily_backtest
from news import get_latest_news                          # P2-7：死代码，下一批清理
import panel                                              # 只读 H5 面板（展示层）
pushed_news = set()                                       # P2-7：死代码，下一批清理

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "alert_state.json")       # 报警冷却状态（本机私有，已 gitignore）
LS_FILE = os.path.join(HERE, LS_HISTORY_FILE)             # noqa: F405  多空比滚动样本

state = AlertState(STATE_FILE)
ls_state = LSPercentile(LS_FILE)

# P0-5：历史遗留的影子变量，遮蔽了 backtest.last_result。回测整块已跳过，
# 这里保留原样 —— 已知这套回测的买入条件是个空集（见 backtest.py），
# 修好之前不把它的结果塞进推送，免得误导。
last_backtest_result = ""


def run_alert(key, title, body, cooldown=None):
    """统一出口：判冷却 → 上报 → 记账。返回 (是否上报, 原因)。

    通道失败不影响"该不该报"的判断；返回值只用于展示/计数，判定逻辑不变。
    """
    cd = float(ALERT_COOLDOWN_MIN if cooldown is None else cooldown)   # noqa: F405
    should, why = state.check(key, cd)
    if not should:
        print(f"[冷却] {title} —— {why}")
        return False, why
    state.mark(key)
    print(f"[报警] {title} —— {why}")
    notify(title, body)
    return True, why


def monitor_once():
    t0 = time.time()
    panel_coins, panel_alerts, panel_errors = [], [], []      # 面板数据（只读视图，不参与判定）
    btc_chg = get_btc_chg()

    # BTC 暴跌避险（全局规则）
    if btc_chg < -3:
        title, body = "⚠️ BTC暴跌预警", f"BTC今日跌{btc_chg:.1f}%，所有币大概率跟跌，别抄底，手里有币逢高减仓"
        ok, why = run_alert("BTC暴跌避险", title, body)
        panel_alerts.append({"t": datetime.now().strftime("%H:%M:%S"), "coin": "BTC",
                             "title": title, "body": body, "fired": ok, "why": why})

    # 监测列表 = 常规币 + 到价提醒里单独配置的币（可能不在常规列表里）
    pairs = list(dict.fromkeys(list(CURRENCY_PAIRS) + list(PRICE_ALERT.keys())))   # noqa: F405
    lines = [
        "# 📈 K线监测报告",
        f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"口径：指标=最后一根已收盘bar，价格=实时｜报警冷却 {ALERT_COOLDOWN_MIN} 分钟",   # noqa: F405
        "",
    ]

    n_fired = 0
    for pair in pairs:
        try:
            res = evaluate_coin(pair, ls_state)
        except Exception as e:
            # 不静默跳过：把币种和原因打出来（原来只是 print(f"{coin}出错") 然后自己都不知道跳了谁）
            msg = f"[跳过] {pair} 评估失败：{type(e).__name__}: {e}"
            print(msg)
            panel_errors.append(msg)
            continue
        res["btc_chg"] = btc_chg
        fired = []
        for key, title, body in build_alerts(res):
            ok, why = run_alert(key, title, body)
            if ok:
                n_fired += 1
            fired.append({"key": key, "title": title, "body": body, "fired": ok, "why": why})
            panel_alerts.append({"t": datetime.now().strftime("%H:%M:%S"), "coin": res["coin"],
                                 "title": title, "body": body, "fired": ok, "why": why})
        lines.extend(render_coin_report(res))
        panel_coins.append(panel.coin_view(res, fired))

    desp = "\n".join(lines)
    if last_backtest_result:
        desp += "\n\n| 最近4h回测 | 详情 | |\n|------|------|------|\n" + last_backtest_result
    print(desp)

    state.save()
    ls_state.save()
    if n_fired:
        beep()
    # 刷新面板缓存（面板挂了/关掉都不影响上面任何一步）
    panel.publish(coins=panel_coins, alerts=panel_alerts, errors=panel_errors,
                  duration=time.time() - t0, btc_chg=btc_chg)
    return n_fired


if __name__ == "__main__":
    print(f"启动模块化监测系统{VERSION} {VERSION_DATE}")      # noqa: F405
    print(f"通知通道：{', '.join(c.name for c in get_channels())}")
    print(f"报警冷却：{ALERT_COOLDOWN_MIN} 分钟（首次触发必报，持续条件按此间隔重报）")   # noqa: F405
    panel.start()                                             # 只读 H5 面板；起不来不影响监控
    last_backtest_ts = time.time()
    last_day = datetime.now().day
    monitor_once()
    while True:
        try:
            now_ts = time.time()
            now_hour = datetime.now().hour
            now_min = datetime.now().minute
            now_day = datetime.now().day
            if now_day != last_day:
                n = state.prune()
                state.save()
                print(f"[状态] 跨天：清掉 {n} 条旧日期报警记录")
                last_day = now_day
            check_events()
            monitor_once()
            if now_ts - last_backtest_ts > BACKTEST_INTERVAL:      # noqa: F405
                backtest()
                last_backtest_ts = now_ts
            if now_hour == 23 and now_min >= 50:
                daily_backtest()
        except Exception as e:
            print(f"主循环出错: {type(e).__name__}: {e}")
        time.sleep(CHECK_INTERVAL)                                  # noqa: F405
