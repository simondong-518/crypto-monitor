"""报警状态：记录每个告警"上次上报时间"，用**冷却**代替原来的硬性次数上限。

为什么改（2026-09-29）：
  原来用 `pushed.get(key,0) < MAX_PUSH_PER_SIGNAL`（每个信号最多 3 次）压重复，后果是：
    ① 一旦顶到上限，这个告警**当天永久沉默**，哪怕条件一直成立（BSV 止损线被压了 3 天）
    ② 状态文件被提交进仓库后，换台机器一启动就直接压制当天的告警，界面毫无提示
  用户定调："只要触发规则就该上报；额度不够是额度问题，不影响业务主线。"
  所以改成：
    · 首次触发 —— 一定上报
    · 条件持续 —— 按 ALERT_COOLDOWN_MIN 冷却后**反复**上报，永不"今天不再报"
    · key 带日期分区 —— 昨天的记录不会压制今天

冷却的用途是防刷屏（同一告警每 60 秒报一次谁都受不了），不是省额度。
"""
import json
import time
from datetime import datetime


class AlertState:
    def __init__(self, path):
        self.path = path
        self.data = self._load()          # {key: last_ts}

    @staticmethod
    def _today():
        return datetime.now().strftime("%Y-%m-%d")

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        prefix = self._today() + "|"
        kept = {k: v for k, v in raw.items() if k.startswith(prefix)}
        dropped = len(raw) - len(kept)
        if dropped:
            print(f"[状态] 丢弃 {dropped} 条非当天报警记录（只保留 {prefix}*）")
        return kept

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)

    def _key(self, key):
        return f"{self._today()}|{key}"

    def check(self, key, cooldown_min):
        """返回 (是否该上报, 原因说明)。原因用于日志，避免"到底为什么没报"靠猜。"""
        k = self._key(key)
        last = self.data.get(k)
        if last is None:
            return True, "首次触发"
        try:
            elapsed_min = (time.time() - float(last)) / 60.0
        except (TypeError, ValueError):
            return True, "历史记录格式异常，按首次触发处理"
        if elapsed_min >= cooldown_min:
            return True, f"距上次上报 {elapsed_min:.0f} 分钟（≥冷却 {cooldown_min:.0f} 分钟），重新上报"
        return False, f"冷却中（{elapsed_min:.0f}/{cooldown_min:.0f} 分钟）"

    def mark(self, key):
        self.data[self._key(key)] = time.time()

    def prune(self):
        """清掉非当天记录（跨天时调用），避免文件无限增长。"""
        prefix = self._today() + "|"
        stale = [k for k in self.data if not k.startswith(prefix)]
        for k in stale:
            self.data.pop(k, None)
        return len(stale)

    def report(self, key, cooldown_min, title, body):
        """判定 + 上报 + 记账，一步完成。返回 (是否上报了, 原因)。"""
        from notifier import notify
        should, why = self.check(key, cooldown_min)
        if should:
            self.mark(key)
            notify(title, body)
        return should, why
