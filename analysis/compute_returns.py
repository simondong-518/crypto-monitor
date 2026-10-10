# -*- coding: utf-8 -*-
"""测算"信号之后真实涨跌" —— 用 5m K 线算每个信号的前向收益。

产物：returns.csv / summary.txt / preview.html（自包含，双击可看）
"""
import io
import os
import csv
import json
import bisect
import time
import calendar
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "信号导出_20261010")
LOCAL_OFFSET = 8 * 3600
HORIZONS = [("1h", 3600), ("4h", 4 * 3600), ("24h", 24 * 3600)]
FEE_SIDE = 0.001          # 单边 0.1%（Gate 现货标准 taker）
FEE_RT = FEE_SIDE * 2     # 往返 0.2%

BUY_KW = r"低吸|买入分|V型反弹|真底|趋势转多|金叉|多头排列|开口向上|支撑|流入|进场"
SELL_KW = r"高抛|卖出分|见顶回落|真高|移动止盈|死叉|空头|抛压|流出|跑路"


def to_unix(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M:%S")) - LOCAL_OFFSET


def op_of(text, direction):
    import re
    if re.search(BUY_KW, text):
        return "买入"
    if re.search(SELL_KW, text):
        return "卖出"
    return "观望"


def load_candles():
    data = {}
    for f in os.listdir(OUT):
        if f.startswith("candles_") and f.endswith(".json"):
            coin = f[len("candles_"):-len(".json")]
            rows = json.load(io.open(os.path.join(OUT, f), encoding="utf-8"))
            ts = [int(r[0]) for r in rows]
            close = [float(r[2]) for r in rows]
            data[coin] = (ts, close)
    return data


def price_at(ts_list, px_list, target, tol=900):
    """返回 target 时刻(或之前最近一根)的价格；偏差超过 tol 秒则视为无数据。"""
    i = bisect.bisect_right(ts_list, target) - 1
    if i < 0:
        return None
    if target - ts_list[i] > tol:
        return None
    return px_list[i]


def main():
    candles = load_candles()
    print("已加载 K 线:", {k: len(v[0]) for k, v in candles.items()})

    rows = list(csv.DictReader(io.open(os.path.join(OUT, "signals.csv"),
                                       encoding="utf-8-sig")))
    recs = []
    for r in rows:
        coin = r["币种"]
        if coin not in candles:
            continue
        ts_list, px_list = candles[coin]
        t0 = to_unix(r["时间"])
        entry = price_at(ts_list, px_list, t0)
        if entry is None or entry <= 0:
            continue
        op = op_of(r["信号原文"], r["方向"])
        rec = dict(r)
        rec["操作"] = op
        rec["入场价"] = entry
        rec["_t0"] = t0
        rec["_entry"] = entry
        for name, sec in HORIZONS:
            p = price_at(ts_list, px_list, t0 + sec)
            if p is None:
                rec["+%s%%" % name] = ""
            else:
                raw = (p - entry) / entry * 100.0
                # 方向收益：买入=做多，卖出=做空，观望=按原始涨跌
                if op == "卖出":
                    rec["+%s%%" % name] = round(-raw, 3)
                else:
                    rec["+%s%%" % name] = round(raw, 3)
        recs.append(rec)

    # ── 导出明细 ──
    fields = ["时间", "币种", "类别", "操作", "方向", "报告级",
              "入场价", "+1h%", "+4h%", "+24h%", "信号原文"]
    with io.open(os.path.join(OUT, "returns.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)

    def agg(rs, key):
        vals = [r[key] for r in rs if r.get(key) not in ("", None)]
        if not vals:
            return None
        n = len(vals)
        win = sum(1 for v in vals if v > 0)
        avg = sum(vals) / n
        return dict(n=n, win=win, winrate=100.0 * win / n, avg=avg,
                    net=avg - FEE_RT * 100)

    def fmt(a):
        if not a:
            return "     n/a"
        return "n=%4d  方向对=%5.1f%%  平均=%+7.3f%%  扣费后=%+7.3f%%" % (
            a["n"], a["winrate"], a["avg"], a["net"])

    L = []
    L.append("历史信号 · 真实前向收益（5m K 线实测）")
    L.append("=" * 64)
    L.append("信号条数: %d（有行情可比对）" % len(recs))
    L.append("手续费假设: 单边 %.1f%% → 往返 %.1f%%" % (FEE_SIDE * 100, FEE_RT * 100))
    L.append("方向收益定义: 买入信号按做多算，卖出信号按做空算，观望按原始涨跌")
    L.append("")
    L.append("── 总体 ──")
    for name, _ in HORIZONS:
        L.append("  %-4s %s" % (name, fmt(agg(recs, "+%s%%" % name))))
    L.append("")
    L.append("── 按操作 ──")
    for op in ["买入", "卖出", "观望"]:
        sub = [r for r in recs if r["操作"] == op]
        if not sub:
            continue
        L.append("  【%s】共 %d 条" % (op, len(sub)))
        for name, _ in HORIZONS:
            L.append("     %-4s %s" % (name, fmt(agg(sub, "+%s%%" % name))))
    L.append("")
    L.append("── 按类别（4h 视角）──")
    for cat, _ in Counter(r["类别"] for r in recs).most_common():
        sub = [r for r in recs if r["类别"] == cat]
        L.append("  %-22s %s" % (cat, fmt(agg(sub, "+4h%"))))
    L.append("")
    L.append("── 按币种（4h 视角）──")
    for coin, _ in Counter(r["币种"] for r in recs).most_common():
        sub = [r for r in recs if r["币种"] == coin]
        L.append("  %-6s %s" % (coin, fmt(agg(sub, "+4h%"))))

    txt = "\n".join(L)
    io.open(os.path.join(OUT, "summary.txt"), "w", encoding="utf-8").write(txt)
    print(txt)

    build_html(recs, agg)
    print("\n产物目录:", OUT)


def build_html(recs, agg):
    def esc(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    cats = [c for c, _ in Counter(r["类别"] for r in recs).most_common()]
    cat_rows = []
    for c in cats:
        sub = [r for r in recs if r["类别"] == c]
        a = agg(sub, "+4h%")
        if not a:
            continue
        cls = "pos" if a["net"] > 0 else "neg"
        cat_rows.append(
            "<tr><td>%s</td><td>%d</td><td>%.1f%%</td>"
            "<td class='%s'>%+.3f%%</td><td class='%s'>%+.3f%%</td></tr>"
            % (esc(c), a["n"], a["winrate"], cls, a["avg"], cls, a["net"]))

    op_rows = []
    for op in ["买入", "卖出", "观望"]:
        sub = [r for r in recs if r["操作"] == op]
        a = agg(sub, "+4h%")
        if not a:
            continue
        cls = "pos" if a["net"] > 0 else "neg"
        op_rows.append(
            "<tr><td>%s</td><td>%d</td><td>%.1f%%</td>"
            "<td class='%s'>%+.3f%%</td><td class='%s'>%+.3f%%</td></tr>"
            % (op, a["n"], a["winrate"], cls, a["avg"], cls, a["net"]))

    detail = []
    for r in recs[-400:]:
        v = r.get("+4h%", "")
        cls = "pos" if (v != "" and float(v) > 0) else ("neg" if v != "" else "")
        detail.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%.6g</td><td class='%s'>%s</td><td>%s</td></tr>"
            % (esc(r["时间"]), r["币种"], esc(r["类别"]), r["操作"],
               r["入场价"], cls, (v if v != "" else "-"), esc(r["信号原文"][:70])))

    ov = []
    for name, _ in HORIZONS:
        a = agg(recs, "+%s%%" % name)
        cls = "pos" if a["net"] > 0 else "neg"
        ov.append("<div class='card'><div class='k'>%s</div><div class='v %s'>%+.3f%%</div>"
                  "<div class='s'>方向对 %.0f%% · n=%d · 扣费后 %+.3f%%</div></div>"
                  % (name, cls, a["avg"], a["winrate"], a["n"], a["net"]))

    html = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>历史信号 · 真实收益</title><style>
:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--line:#21262d;--pos:#3fb950;--neg:#f85149;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.6 -apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;padding:24px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:26px 0 8px;color:var(--acc)}
.sub{color:var(--mut);font-size:12px;margin-bottom:18px}
.cards{display:flex;gap:12px;flex-wrap:wrap}
.card{background:#161b22;border:1px solid var(--line);border-radius:10px;padding:14px 18px;min-width:170px}
.card .k{color:var(--mut);font-size:12px}.card .v{font-size:24px;font-weight:600;margin:2px 0}
.card .s{color:var(--mut);font-size:11px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:500;position:sticky;top:0;background:var(--bg)}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.wrap{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:10px}
.note{background:#161b22;border-left:3px solid var(--acc);padding:10px 14px;
border-radius:6px;color:var(--mut);font-size:12px;margin:16px 0}
</style></head><body>
<h1>历史信号 · 真实收益测算</h1>
<div class="sub">数据源 alerts.log（推送留痕）· 行情 Gate.io 5m K 线实测 ·
手续费假设 单边 0.1%（往返 0.2%）· 买入按做多、卖出按做空</div>
<div class="cards">@@CARDS@@</div>
<div class="note">方向对 = 该信号方向与后续涨跌一致的比例（50% 即抛硬币）。
"扣费后" = 平均方向收益 − 0.2% 往返手续费。</div>
<h2>按操作类型</h2>
<table><tr><th>操作</th><th>条数</th><th>方向对</th><th>平均收益(4h)</th><th>扣费后(4h)</th></tr>@@OP@@</table>
<h2>按信号类别（4h）</h2>
<table><tr><th>类别</th><th>条数</th><th>方向对</th><th>平均收益</th><th>扣费后</th></tr>@@CAT@@</table>
<h2>最近 400 条明细</h2>
<div class="wrap"><table>
<tr><th>时间</th><th>币</th><th>类别</th><th>操作</th><th>入场价</th><th>+4h</th><th>信号</th></tr>
@@DETAIL@@</table></div></body></html>"""
    html = (html.replace("@@CARDS@@", "".join(ov))
                .replace("@@OP@@", "".join(op_rows))
                .replace("@@CAT@@", "".join(cat_rows))
                .replace("@@DETAIL@@", "".join(detail)))
    io.open(os.path.join(OUT, "preview.html"), "w", encoding="utf-8").write(html)


if __name__ == "__main__":
    main()
