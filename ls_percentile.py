"""大户多空比打分：按「币自己的滚动分位数」而不是固定 1.0 阈值（P1-3 / D1 决策）。

为什么改：
  原规则是 `top_lsr_account > 1 → 买分 +1` / `< 1 → 卖分 +1`。
  实测 6 个币的 account 口径全部落在 0.48~0.67（**全都 <1**）：
    · ">1 加买分"这一支**一次都拿不到** —— 规则等于不存在
    · "<1 加卖分"近乎恒真 —— 买卖分被结构性拉开，这就是"怎么永远看不到买入信号"的一部分
  同时 `top_lsr_size`（持仓量口径）有区分度（0.66~1.05），所以用它做**展示**。

方案（D1）：两个口径都展示；打分用**币自身的滚动分位数**，高分位算多、低分位算空。

数据来源说明：Gate 没有历史多空比接口（/futures/usdt/contract_stats 只有当前值），
  所以历史只能自己攒。预热期（样本不足）**返回 None 不加分，绝不猜**。

配置见 config.py：LS_WINDOW / LS_MIN_SAMPLES / LS_BUY_PCT / LS_SELL_PCT / LS_SCORE_MODE
"""
import json
from pathlib import Path

import config


class LSPercentile:
    """滚动采样 + 分位数。样本文件是本机私有状态（已 gitignore）。"""

    def __init__(self, path):
        self.path = Path(path)
        self.hist = self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        return {k: [float(x) for x in v] for k, v in raw.items() if isinstance(v, list)}

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.hist, f)

    def sample(self, coin, value):
        """记一个样本，返回 (分位数 0~100 或 None, 样本数)"""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None, 0
        d = self.hist.setdefault(coin, [])
        d.append(v)
        cap = int(getattr(config, "LS_WINDOW", 720))
        if len(d) > cap:
            del d[:len(d) - cap]
        n = len(d)
        if n < int(getattr(config, "LS_MIN_SAMPLES", 60)):
            return None, n
        below = sum(1 for x in d if x < v)
        return below / (n - 1) * 100.0, n

    def score(self, coin, value):
        """返回 (买分增量, 卖分增量, 说明)。预热期返回 0,0 并说明原因。"""
        pct, n = self.sample(coin, value)
        need = int(getattr(config, "LS_MIN_SAMPLES", 60))
        if pct is None:
            return 0.0, 0.0, f"样本不足（{n}/{need}），本币多空比暂不加分"
        hi = float(getattr(config, "LS_BUY_PCT", 80.0))
        lo = float(getattr(config, "LS_SELL_PCT", 20.0))
        if pct >= hi:
            b, s = 1.0, 0.0
        elif pct <= lo:
            b, s = 0.0, 1.0
        else:
            b, s = 0.0, 0.0
        mode = str(getattr(config, "LS_SCORE_MODE", "momentum"))
        if mode == "contrarian":
            b, s = s, b
        return b, s, f"分位 {pct:.0f}%（n={n}，模式 {mode}）"


def pick(value_account, value_size):
    """打分用的口径由 config.LS_METRIC 决定；两个口径都会展示。"""
    metric = str(getattr(config, "LS_METRIC", "top_lsr_account"))
    return value_size if metric == "top_lsr_size" else value_account
