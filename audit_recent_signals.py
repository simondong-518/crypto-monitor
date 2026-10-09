# -*- coding: utf-8 -*-
"""最近 24 小时的「明确信号」清单 + 后续真实结果"""
import sys, os, re, io
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

import pandas as pd
from api import get_kline
from config import CURRENCY_PAIRS, FEE_RATE
from datetime import datetime, timedelta

FEE = FEE_RATE * 2
BEARISH_KW = ["看空","流出","见顶","高抛","慢跌","真高","回撤","跑路"]

REPORT_KW = ["移动止盈落袋","低吸预警","高抛预警","最佳低吸点","最佳高抛点",
             "V型反弹","见顶回落","真突破","真跌破","缩量慢涨","缩量慢跌",
             "资金大幅流入","资金大幅流出","真高","真底"]


def is_report(s):
    return any(k in s for k in REPORT_KW)


txt = io.open("alerts.log", encoding="utf-8", errors="ignore").read()
blocks = re.split(r"^===== (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) =====\s*$", txt, flags=re.M)
recs = []
for k in range(1, len(blocks)-1, 2):
    for m in re.finditer(r"^- \*\*([A-Z]+)\*\*: (.+)$", blocks[k+1], re.M):
        if is_report(m.group(2)):
            recs.append((blocks[k], m.group(1), m.group(2).strip()))

KL = {}
for pair in CURRENCY_PAIRS:
    coin = pair.replace("_USDT", "")
    d = get_kline(pair, "15m", 1000)
    if len(d) < 200: continue
    df = pd.DataFrame(d, columns=['ts','turnover','close','high','low','open','vol','wc'])
    for c in ['close','high','low']: df[c] = df[c].astype(float)
    df['dt'] = pd.to_datetime(df['ts'].astype("int64"), unit='s')
    KL[coin] = df.set_index('dt').sort_index()


def outcome(coin, ts):
    if coin not in KL: return None
    t = pd.Timestamp(ts) - pd.Timedelta(hours=8)
    df = KL[coin]
    i = df.index.searchsorted(t)
    if i >= len(df) - 16 or i < 1: return None
    e = df['close'].iloc[i]; x = df['close'].iloc[i+16]
    seg = df.iloc[i+1:i+17]
    return e, x, (x-e)/e*100, (seg['high'].max()-e)/e*100, (e-seg['low'].min())/e*100


last = recs[-1][0] if recs else None
print("═══ 明确信号（带报告那 8 类）时间线 ═══")
print("  日志里共 %d 条 | 最新一条: %s" % (len(recs), last))
print()

# 只保留"未来4小时窗口已经走完"的信号（否则没有结果可比）
done_rows = []
for ts, c, s in recs:
    o = outcome(c, ts)
    if o:
        done_rows.append((ts, c, s, o))
print("═══ 窗口已完成的最新 40 条明确信号 ═══")
print("  （日志共 %d 条明确信号，其中 %d 条窗口已走完）" % (len(recs), len(done_rows)))
print()
print("  %-14s %-5s %-5s %8s %9s %9s  %s" % ("时间", "币", "方向", "4h收益", "期间最高", "期间最低", "信号"))
print("  " + "-"*108)
for ts, c, s, o in done_rows[-40:]:
    e, x, mv, hi, lo = o
    bear = any(k in s for k in BEARISH_KW)
    pnl = -mv if bear else mv
    print("  %-14s %-5s %-5s %+7.2f%% %+8.2f%% %+8.2f%%  %s %s"
          % (ts[5:16], c, "看空" if bear else "看多", pnl, hi, lo,
             "✓" if pnl > 0 else "✗", s[:36]))
print()
n = len(done_rows)
w = sum(1 for _, _, s, o in done_rows
        if (-o[2] if any(k in s for k in BEARISH_KW) else o[2]) > 0)
tot = sum((-o[2] if any(k in s for k in BEARISH_KW) else o[2]) for _, _, s, o in done_rows)
print("  【这批合计】%d 笔 | 方向对 %.0f%% | 平均 %+.3f%% | 扣费后 %+.3f%%"
      % (n, w/n*100, tot/n, tot/n - FEE*100))
