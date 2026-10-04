# -*- coding: utf-8 -*-
"""报警状态层：**冷却制**，替代原来的"每个信号最多推 3 次"。

原来那套 `if pushed.get(key,0) < MAX_PUSH_PER_SIGNAL` 的问题（实盘真出过）：
  一个止损/跑路信号推满 3 次后，**当天彻底哑掉**，而屏幕上完全看不出来。
  为了绕开它，main.py 里又加了 4 处"方向反转清空计数""创新高清零""突破当天最大流入清零"……
  补丁叠补丁，逻辑已经很难推理。

冷却制只有两条规则：
  1) 首次触发**必报**；
  2) 条件仍在时，**每过 ALERT_COOLDOWN_MIN 分钟重报一次，不设上限**。
     （依据："只要触发规则就该上报；额度不够是额度问题，不影响业务主线"）

key 必须是**值无关**的稳定 key（如 `SUI_主力大幅出`，绝不要 `SUI_大涨3.42%`），
否则每次数字一变就是新 key，冷却永远匹配不上 → 等于没有冷却。
`assert_stable_key()` 就是用来在自检里抓这件事的。
"""
from __future__ import annotations

import json
import os
import re
import time

DEFAULT_COOLDOWN_MIN = 30
STATE_FILE = "alert_state.json"


class AlertState:
    def __init__(self, path=STATE_FILE, cooldown_min=DEFAULT_COOLDOWN_MIN):
        self.path = path
        self.cooldown = max(0, int(cooldown_min)) * 60
        self._fired = {}          # key -> 上次上报时间戳
        self._load()

    # ── 持久化：只保留当天，避免文件无限长大 ──
    def _today(self):
        return time.strftime("%Y-%m-%d")

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
        # 只认"今天这一份"。昨天及更早的整份丢弃 —— 不用时间戳回溯过滤：
        # 那种写法（v >= now-86400）会把"时间戳比现在早一天以上"的记录误杀，
        # 一旦有人用假时间/时钟回拨就会静默清空冷却状态（自己踩过）。
        if isinstance(raw, dict) and raw.get("_date") == self._today():
            fired = raw.get("fired") or {}
            self._fired = {k: float(v) for k, v in fired.items()
                           if isinstance(v, (int, float)) and v > 0}
        else:
            self._fired = {}

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"_date": self._today(), "fired": self._fired}, f,
                          ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"[状态] 保存失败：{type(e).__name__}: {e}", flush=True)

    # ── 判定 ──
    def should_report(self, key, now=None):
        """该不该上报；**不修改状态**（判定与提交分开，方便先算清楚再决定）。"""
        now = time.time() if now is None else now
        last = self._fired.get(key)
        return last is None or (now - last) >= self.cooldown

    def mark(self, key, now=None):
        """记录一次上报，并**立刻落盘**。

        为什么必须落盘：进程重启（计划任务每天重启、手动重跑）后如果状态丢了，
        同一个报警会被当成"首次触发"**重复推送** —— 冷却就形同虚设。
        这里每上报一条就写一次，条目很少（每天几十条），开销可忽略。
        """
        self._fired[key] = time.time() if now is None else now
        self.save()

    def why(self, key, now=None):
        """给报告用的原因：首次触发 / 冷却中（还剩 N 分钟）"""
        now = time.time() if now is None else now
        last = self._fired.get(key)
        if last is None:
            return "首次触发"
        left = self.cooldown - (now - last)
        if left <= 0:
            return "冷却结束，重新上报"
        return f"冷却中（还剩 {left / 60:.0f} 分钟）"

    def seen(self, key):
        return key in self._fired

    def clear(self):
        self._fired.clear()

    def keys(self):
        return list(self._fired)


# ============================================================ 稳定 key
# 报警文本里**不该**带具体数字：带了就每轮都变，冷却永远命中不了。
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


def stable_alert_key(coin, kind):
    """生成值无关的稳定 key：`SUI_主力大幅出`。

    kind 里若混进了数字/百分比，会被抹掉并在自检里报出来
    （历史 bug：`key = f"{coin}_{整串报警文本}"` → 数字一变就换 key，等于没有冷却）。
    """
    clean = _NUM.sub("", str(kind)).replace("%", "").strip(" _-，。、:：")
    clean = re.sub(r"\s+", "", clean)
    return f"{coin}_{clean}"


def assert_stable_key(key):
    """自检用：key 里不该再有数字/百分号。"""
    return not _NUM.search(str(key)) and "%" not in str(key)
