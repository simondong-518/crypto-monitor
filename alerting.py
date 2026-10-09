# -*- coding: utf-8 -*-
"""报警冷却 / 去重 / 推送记录持久化。

架构分离自 main.py（纯搬运，逻辑一字未改）：
    · pushed.json 的加载与保存
    · 冷却状态 AlertState + should_alert / mark_alert
"""
import json
from alert_state import AlertState


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


def save_pushed():
    with open(pushed_file, "w") as f:
        json.dump(pushed, f)
