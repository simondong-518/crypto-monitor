# -*- coding: utf-8 -*-
"""公平起见：单独看高分信号（≥90 最佳买卖点）的真实表现。
对方说他"连赚好几天"，也许是靠这类少数高分信号。
"""
import sys, os, re, io
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

import pandas as pd
from api import get_kline
from config import CURRENCY_PAIRS, FEE_RATE

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
    df['dt'] = pd.to_datetime(df['ts'].astype("int64"), unit='s')
    KL[coin] = df.set_index('dt').sort_index()


def outcome(coin, ts, bearish, bars=16):
    if coin not in KL: return None
    t = pd.Timestamp(ts) - pd.Timedelta(hours=8)
    df = KL[coin]
    i = df.index.searchsorted(t)
    if i >= len(df) - bars or i < 1: return None
    e = df['close'].iloc[i]; x = df['close'].iloc[i+bars]
    raw = (x - e)/e*100
    return (-raw if bearish else raw)


def report(title, pred):
    sub = [(ts, c, s) for ts, c, s in recs if pred(s)]
    print("══ %s ══" % title)
    print("   日志条数: %d" % len(sub))
    if not sub:
        print("   （无）\n"); return
    rs = []
    for ts, c, s in sub:
        bear = any(k in s for k in ["看空","流出","见顶","高抛","慢跌","真高","回撤","跑路"])
        o = outcome(c, ts, bear)
        if o is not None: rs.append(o)
    if not rs:
        print("   （无K线覆盖）\n"); return
    n = len(rs)
    w = sum(1 for r in rs if r > 0)
    print("   可比对: %d 笔" % n)
    print("   方向对: %d 笔 = %.0f%%" % (w, w/n*100))
    print("   平均 4h 收益: %+.3f%%" % (sum(rs)/n))
    print("   扣费后: %+.3f%%" % (sum(rs)/n - FEE_RATE*2*100))
    print()


report("≥90 最佳买卖点（他最看重的）", lambda s: "最佳低吸点" in s or "最佳高抛点" in s)
report("≥30 低吸/高抛预警", lambda s: ("低吸预警" in s or "高抛预警" in s))
report("大资金信号", lambda s: "资金大幅流入" in s or "资金大幅流出" in s)
report("V型反弹 / 见顶回落", lambda s: "V型反弹" in s or "见顶回落" in s)
report("缩量慢涨 / 慢跌", lambda s: "缩量慢涨" in s or "缩量慢跌" in s)
report("移动止盈落袋", lambda s: "移动止盈" in s)
report("BOLL 真突破 / 真跌破", lambda s: "真突破" in s or "真跌破" in s)
report("真高 / 真底", lambda s: "真高" in s or "真底" in s)
