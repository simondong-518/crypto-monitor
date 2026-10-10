# -*- coding: utf-8 -*-
"""把结构化信号日志（signal_logs/*.jsonl）导出成 CSV / 汇总。

用法：
    python analysis/export_siglog.py                 # 导出全部
    python analysis/export_siglog.py --days 2        # 只导最近 2 天
    python analysis/export_siglog.py --out D:\\某处   # 指定输出目录

与 export_signals.py 的区别：
    · export_signals.py 解析的是 alerts.log —— **只有推送留痕**，
      受总闸/分级/冷却过滤，看不到"没被推的信号"和"没触发信号的币"
    · 本脚本读的是 siglog —— **每轮每个币一行**，是全量快照
"""
import io
import os
import re
import csv
import json
import glob
import argparse
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG_DIR = os.path.join(ROOT, "signal_logs")

FIELDS = ["ts", "round", "coin", "pair", "close", "day_chg",
          "rsi15", "rsi1h", "kdj_j", "macd",
          "boll_u", "boll_m", "boll_l", "ma20",
          "trend15", "trend1h", "vol_ratio",
          "net_inflow", "score_buy", "score_sell",
          "signal", "report", "n_alerts", "alerts", "error"]

CN = {"ts": "时间", "round": "轮次", "coin": "币种", "pair": "交易对",
      "close": "现价", "day_chg": "今日涨跌%", "rsi15": "RSI15m", "rsi1h": "RSI1h",
      "kdj_j": "KDJ_J", "macd": "MACD", "boll_u": "BOLL上轨", "boll_m": "BOLL中轨",
      "boll_l": "BOLL下轨", "ma20": "MA20", "trend15": "15m趋势向上",
      "trend1h": "1h趋势向上", "vol_ratio": "量能比", "net_inflow": "瞬时净流入",
      "score_buy": "买入分", "score_sell": "卖出分",
      "signal": "综合信号", "report": "报告级", "n_alerts": "信号条数",
      "alerts": "触发的信号", "error": "错误"}


def load(days=None):
    files = sorted(glob.glob(os.path.join(LOG_DIR, "*.jsonl")))
    if days:
        files = files[-days:]
    recs = []
    for p in files:
        for line in io.open(p, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    return files, recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = args.out or os.path.join(HERE, "信号导出_%s" % __import__("time").strftime("%Y%m%d"))
    os.makedirs(out, exist_ok=True)

    files, recs = load(args.days)
    if not recs:
        print("signal_logs/ 里还没有数据（服务跑起来之后才会有）")
        print("目录:", LOG_DIR)
        return

    for r in recs:
        a = r.get("alerts") or []
        r["n_alerts"] = len(a)
        r["alerts"] = " | ".join(a)

    recs.sort(key=lambda r: (r.get("ts") or "", r.get("coin") or ""))

    with io.open(os.path.join(out, "siglog_all.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerow({CN.get(k, k): k for k in FIELDS})   # 中文表头行
        for r in recs:
            w.writerow({CN.get(k, k): r.get(k, "") for k in FIELDS})

    fired = [r for r in recs if r["n_alerts"]]
    with io.open(os.path.join(out, "siglog_alerts_only.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in fired:
            w.writerow({CN.get(k, k): r.get(k, "") for k in FIELDS})

    L = []
    L.append("结构化信号日志导出")
    L.append("=" * 60)
    L.append("文件: %s" % ", ".join(os.path.basename(p) for p in files))
    L.append("总记录: %d 行（每轮每个币一行）" % len(recs))
    L.append("时间跨度: %s → %s" % (recs[0]["ts"], recs[-1]["ts"]))
    L.append("轮次数: %d" % len(set(r.get("round") for r in recs)))
    L.append("")
    L.append("── 每币记录数（应当基本相等 = 每轮都记）──")
    for k, v in Counter(r.get("coin") for r in recs).most_common():
        L.append("  %-6s %6d" % (k, v))
    L.append("")
    L.append("── 有信号 vs 无信号 ──")
    L.append("  触发了信号: %d 行 (%.1f%%)" % (len(fired), 100.0 * len(fired) / len(recs)))
    L.append("  无任何信号: %d 行 (%.1f%%)" % (len(recs) - len(fired),
                                              100.0 * (len(recs) - len(fired)) / len(recs)))
    L.append("")
    L.append("── 报告级（会带完整报告推送）──")
    rep = [r for r in recs if r.get("report")]
    L.append("  %d 行 (%.2f%%)" % (len(rep), 100.0 * len(rep) / len(recs)))
    L.append("")
    L.append("── 触发的信号文案 Top 25 ──")
    c = Counter()
    for r in fired:
        for a in (r["alerts"] or "").split(" | "):
            if a:
                c[re.sub(r"[0-9][0-9.,]*", "N", a)] += 1
    for k, v in c.most_common(25):
        L.append("  %6d  %s" % (v, k[:70]))
    L.append("")
    L.append("── 买入分分布（综合打分）──")
    sb = [r["score_buy"] for r in recs if isinstance(r.get("score_buy"), (int, float))]
    if sb:
        L.append("  n=%d  最大=%.0f  平均=%.1f  ≥30 的占比=%.1f%%  ≥90 的占比=%.2f%%"
                 % (len(sb), max(sb), sum(sb) / len(sb),
                    100.0 * sum(1 for x in sb if x >= 30) / len(sb),
                    100.0 * sum(1 for x in sb if x >= 90) / len(sb)))
    errs = [r for r in recs if r.get("error")]
    L.append("")
    L.append("── 该币本轮评估失败（缺口可见）──")
    L.append("  %d 行" % len(errs))
    for k, v in Counter(r["error"].split(":")[0] for r in errs).most_common():
        L.append("  %-20s %d" % (k, v))

    txt = "\n".join(L)
    io.open(os.path.join(out, "summary.txt"), "w", encoding="utf-8").write(txt)
    print(txt)
    print("\n产物目录:", out)


if __name__ == "__main__":
    main()
