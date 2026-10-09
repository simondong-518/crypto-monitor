# -*- coding: utf-8 -*-
"""近期日志里的「明确信号」逐条核对：发出后到底成功了没有？

明确信号 = 用户规格里"带完整全方位分析报告"的 8 类：
  移动止盈落袋 / ≥30分低吸·高抛预警 / ≥90分最佳买卖点 /
  V型反弹·见顶回落 / BOLL真突破·真跌破 / 缩量慢涨·慢跌 /
  大级别资金流入·流出 / 真高·真底
"""
import sys, os, re, io
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

import pandas as pd
from api import get_kline
from config import CURRENCY_PAIRS, FEE_RATE

FEE = FEE_RATE * 2

KINDS = [
    ("① 移动止盈落袋",      lambda s: "移动止盈落袋" in s),
    ("② ≥30分低吸/高抛预警", lambda s: ("低吸预警" in s or "高抛预警" in s)),
    ("③ ≥90分最佳买卖点",    lambda s: ("最佳低吸点" in s or "最佳高抛点" in s)),
    ("④ V型反弹/见顶回落",   lambda s: ("V型反弹" in s or "见顶回落" in s)),
    ("⑤ BOLL真突破/真跌破",  lambda s: ("真突破" in s or "真跌破" in s)),
    ("⑥ 缩量慢涨/慢跌",      lambda s: ("缩量慢涨" in s or "缩量慢跌" in s)),
    ("⑦ 大级别资金流入/流出", lambda s: ("资金大幅流入" in s or "资金大幅流出" in s)),
    ("⑧ 真高/真底",          lambda s: ("真高" in s or "真底" in s)),
]
BEARISH_KW = ["看空","流出","见顶","高抛","慢跌","真高","回撤","跑路"]

txt = io.open("alerts.log", encoding="utf-8", errors="ignore").read()
blocks = re.split(r"^===== (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) =====\s*$", txt, flags=re.M)
recs = []
for k in range(1, len(blocks)-1, 2):
    for m in re.finditer(r"^- \*\*([A-Z]+)\*\*: (.+)$", blocks[k+1], re.M):
        recs.append((blocks[k], m.group(1), m.group(2).strip()))

KL = {}
for pair in CURRENCY_PAIRS:
    coin = pair.replace("_USDT", "")
    d = get_kline(pair, "15m", 1000)
    if len(d) < 200: continue
    df = pd.DataFrame(d, columns=['ts','turnover','close','high','low','open','vol','wc'])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['dt'] = pd.to_datetime(df['ts'].astype("int64"), unit='s')
    KL[coin] = df.set_index('dt').sort_index()


def look(coin, ts, bars=16):
    """返回 (入场价, bars*15分钟后的价, 期间最高, 期间最低)"""
    if coin not in KL: return None
    t = pd.Timestamp(ts) - pd.Timedelta(hours=8)
    df = KL[coin]
    i = df.index.searchsorted(t)
    if i >= len(df) - bars or i < 1: return None
    seg = df.iloc[i+1:i+1+bars]
    return (df['close'].iloc[i], df['close'].iloc[i+bars],
            seg['high'].max(), seg['low'].min())


print("═══ 日志概况 ═══")
print("  总信号条数: %d" % len(recs))
if recs: print("  时间范围: %s → %s" % (recs[0][0], recs[-1][0]))
print()

grand = []
for name, pred in KINDS:
    sub = [(ts, c, s) for ts, c, s in recs if pred(s)]
    print("─" * 78)
    print("  %s   共 %d 条" % (name, len(sub)))
    if not sub:
        print("     （4 天里没触发过）")
        continue
    rows = []
    for ts, c, s in sub:
        o = look(c, ts)
        if not o: continue
        e, x, hi, lo = o
        bear = any(k in s for k in BEARISH_KW)
        move = (x-e)/e*100                      # 价格实际涨跌
        pnl = (-move if bear else move)         # ★ 按信号方向操作的真实盈亏
        rows.append((ts, c, s, e, x, pnl, pnl > 0, bear))
    if not rows:
        print("     （无K线覆盖）"); continue
    n = len(rows)
    w = sum(1 for r in rows if r[6])
    avg = sum(r[5] for r in rows)/n
    print("     可比对 %d 笔 | 方向对 %d (%.0f%%) | 平均4h %+.3f%% | 扣费后 %+.3f%%"
          % (n, w, w/n*100, avg, avg - FEE*100))
    grand.extend(rows)
    print("     ── 逐条明细（最近 8 条，收益=按信号方向操作）──")
    for ts, c, s, e, x, raw, good, bear in rows[-8:]:
        arrow = "看多" if not bear else "看空"
        print("       %s  %-5s [%s] %+.2f%%  %s  %s"
              % (ts[5:16], c, arrow, raw, "✓" if good else "✗", s[:34]))

print()
print("═" * 78)
if grand:
    n = len(grand)
    w = sum(1 for r in grand if r[6])
    avg = sum(r[5] for r in grand)/n
    print("  【明确信号 合计】%d 笔" % n)
    print("     方向对: %d 笔 = %.0f%%" % (w, w/n*100))
    print("     平均 4h 收益: %+.3f%%   扣费后: %+.3f%%" % (avg, avg - FEE*100))
    print("     扣费后为正的比例: %.0f%%"
          % (sum(1 for r in grand if r[5] > FEE*100)/n*100))
