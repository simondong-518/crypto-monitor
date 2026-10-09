# _refactor —— 架构分离（一次性搬运工具）

把 `main.py`（1471 行，信号规则全部内联在巨型 `monitor_once()` 里）
**逐字搬运**成四个独立模块：

| 产物 | 来源切片 |
|---|---|
| `alerting.py` | `pushed.json` 持久化 + `AlertState` + `should_alert` / `mark_alert` / `save_pushed` |
| `signals.py` | `fmt_money`、各类锁字典、缩量慢涨/慢跌、`analyze_trades`、`update_daily_extreme`、`_boll_open_up`、`_is_report_signal`、**`evaluate_coin()`（原 `monitor_once()` 的主体）** |
| `report.py` | 原 `monitor_once()` 尾段的"全方位分析"渲染 → `render(rep)` |
| `pushing.py` | 市场级提醒（BTC避险/新闻/价格）+ 板块联动 + 分级推送 → `dispatch()` |
| `main.py` | 只剩框架层（119 行）：主循环 / 面板接线 / 入口 |

## 用法

```bash
python _refactor/extract.py --dry     # 只看切片边界与自由变量（不写文件）
python _refactor/extract.py --write   # 真正写文件（自动备份 main.py）
```

`extract.py` 按**标记行**定位边界并逐条断言，切片**原样搬运**（只统一缩进），
所以"行为等价"是可证明的 —— 见仓库根的 `verify_refactor.py`。

## 注意

- 它读的是**原始** `main.py`。重新跑之前，先恢复备份：
  `cp _refactor/main.py.bak_* main.py`（备份被 `.gitignore` 的 `*.bak_*` 排除，
  克隆下来没有这个文件时，可从 git 历史取分离前的那一版）。
- 切片边界变了要同步改 `extract.py` 里的 `find(...)` 标记；
  标记找不到会直接报错，不会静默切错。
