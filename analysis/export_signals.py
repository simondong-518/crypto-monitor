# -*- coding: utf-8 -*-
"""从 alerts.log 解析历史信号 → 分类 → 导出 CSV + 汇总。

产物全部落在 analysis/信号导出_20261010/ 下，不动任何原始数据。
"""
import io
import os
import re
import csv
from datetime import datetime
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "alerts.log")
OUT = os.path.join(HERE, "信号导出_20261010")

COINS = ["CYS", "SUI", "WLD", "BSV", "DOGE", "BTC"]

# ── 信号分类：(正则片段, 类别, 报告级?) ────────────────────────────────
# 报告级 = 用户 2026-10-07 规格里"带完整全方位分析报告"的 8 类
CATS = [
    # ── 8 类"带完整报告" ──
    (r"移动止盈",            "①移动止盈落袋",   True),
    (r"低吸预警|高抛预警",    "②≥30分低吸/高抛预警", True),
    (r"最佳|≥90|90分",       "③≥90分最佳买卖点", True),
    (r"V型反弹|见顶回落",     "④V反/见顶回落",   True),
    (r"真突破|真跌破",        "⑤BOLL真突破/真跌破", True),
    (r"缩量上涨|缩量下跌|缩量慢涨|缩量慢跌|缩量", "⑥缩量慢涨/慢跌", True),
    (r"大幅流入|大幅流出|大幅进|大幅跑|大额流入|大额流出", "⑦大级别资金", True),
    (r"真高|真底|触及当日",   "⑧真高/真底",      True),
    # ── 6 类"只发一句话" ──
    (r"急涨|急跌",           "⑨30分钟急涨/急跌", False),
    (r"变盘点|趋势转多|转空",  "⑩变盘点转多/转空", False),
    (r"大反弹|大回撤",        "⑪大反弹/大回撤",  False),
    (r"大户多空比|大户账户多空比", "⑫大户极端多空比", False),
    (r"板块联动",            "⑬板块联动",      False),
    (r"新闻|快讯",           "⑭新闻快讯",      False),
    # ── 其余（我方观察到的"盘面异动"类）──
    (r"资金流入|资金流出|净流入|净流出|进场|跑路", "其他·资金异动", False),
    (r"EMA|均线",            "其他·均线",       False),
    (r"KDJ",                 "其他·KDJ",       False),
    (r"RSI",                 "其他·RSI",       False),
    (r"上影线|下影线",        "其他·影线",       False),
    (r"MACD",                "其他·MACD",      False),
]

BULL = r"低吸|超卖|流入|进场|反弹|真底|金叉|多头排列|开口向上|缩量上涨|支撑|买"
BEAR = r"高抛|超买|流出|跑路|见顶|真高|死叉|空头|缩量下跌|抛压|跌破|卖|顶"

EMOJI = r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF]"


def classify(text):
    cat, rep = "其他·未分类", False
    for pat, c, r in CATS:
        if re.search(pat, text):
            cat, rep = c, r
            break
    if re.search(BULL, text):
        d = "偏多"
    elif re.search(BEAR, text):
        d = "偏空"
    else:
        d = "中性"
    return cat, d, rep


def parse():
    """返回 [(ts, coin, text)]"""
    rows = []
    with io.open(LOG, encoding="utf-8", errors="replace") as f:
        content = f.read()
    blocks = re.split(r"^=====\s*([0-9-]+ [0-9:]+)\s*=====\s*$",
                      content, flags=re.M)
    # blocks = [前导, ts1, body1, ts2, body2, ...]
    for i in range(1, len(blocks) - 1, 2):
        ts, body = blocks[i], blocks[i + 1]
        for m in re.finditer(r"^- \*\*([A-Z]{2,6})\*\*: (.+)$", body, flags=re.M):
            coin, rest = m.group(1), m.group(2).strip()
            if coin not in COINS:
                continue
            for part in re.split(r",\s*(?=" + EMOJI + r")", rest):
                part = part.strip().rstrip(",")
                if part:
                    rows.append((ts, coin, part))
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = parse()
    recs = []
    for ts, coin, text in rows:
        cat, d, rep = classify(text)
        recs.append({"时间": ts, "币种": coin, "类别": cat, "方向": d,
                     "报告级": "是" if rep else "否", "信号原文": text})
    recs.sort(key=lambda r: r["时间"])

    csv_path = os.path.join(OUT, "signals.csv")
    with io.open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["时间", "币种", "类别", "方向",
                                          "报告级", "信号原文"])
        w.writeheader()
        w.writerows(recs)

    buy_path = os.path.join(OUT, "buy_signals.csv")
    buys = [r for r in recs if r["方向"] == "偏多"]
    with io.open(buy_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["时间", "币种", "类别", "方向",
                                          "报告级", "信号原文"])
        w.writeheader()
        w.writerows(buys)

    # ── 汇总 ──
    L = []
    L.append("历史信号导出 · %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    L.append("数据源: alerts.log（这是推送留痕，即真正发出去的信号）")
    L.append("时间跨度: %s → %s" % (recs[0]["时间"], recs[-1]["时间"]) if recs else "空")
    L.append("信号总条数: %d" % len(recs))
    L.append("")
    L.append("── 按类别 ──")
    for k, v in Counter(r["类别"] for r in recs).most_common():
        L.append("  %-24s %5d" % (k, v))
    L.append("")
    L.append("── 按方向 ──")
    for k, v in Counter(r["方向"] for r in recs).most_common():
        L.append("  %-8s %5d" % (k, v))
    L.append("")
    L.append("── 报告级 vs 一句话 ──")
    for k, v in Counter(r["报告级"] for r in recs).most_common():
        L.append("  %-6s %5d" % (k, v))
    L.append("")
    L.append("── 按天 ──")
    byday = defaultdict(int)
    for r in recs:
        byday[r["时间"][:10]] += 1
    for k in sorted(byday):
        L.append("  %s  %5d" % (k, byday[k]))
    L.append("")
    L.append("── 偏多（买入向）信号 Top ──")
    for k, v in Counter(r["信号原文"] for r in buys).most_common(15):
        L.append("  %5d  %s" % (v, k[:60]))

    txt = "\n".join(L)
    with io.open(os.path.join(OUT, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    print("\n产物目录:", OUT)


if __name__ == "__main__":
    main()
