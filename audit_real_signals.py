# -*- coding: utf-8 -*-
"""用真实运行日志（alerts.log）核对：实际推出去的信号，后来涨了还是跌了？

日志格式：
    ===== 2026-10-04 21:44:22 =====
    - **SUI**: 🔴 大户多空比<0.5，极端偏空
"""
import sys, os, re, io
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

import pandas as pd
from api import get_kline
from config import CURRENCY_PAIRS, FEE_RATE

LOG = "alerts.log"
txt = io.open(LOG, encoding="utf-8", errors="ignore").read()

# 切块：每个 ===== 时间 ===== 开头
blocks = re.split(r"^===== (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) =====\s*$",
                  txt, flags=re.M)
# blocks[0] 是头部，之后 [时间, 内容, 时间, 内容, ...]
recs = []
for k in range(1, len(blocks) - 1, 2):
    ts = blocks[k]
    body = blocks[k+1]
    for m in re.finditer(r"^- \*\*([A-Z]+)\*\*: (.+)$", body, re.M):
        recs.append((ts, m.group(1), m.group(2).strip()))

print("═══ 真实日志里的信号 ═══")
print("  总条数: %d" % len(recs))
if recs:
    print("  时间范围: %s → %s" % (recs[0][0], recs[-1][0]))
print()

# 分类统计
from collections import Counter
kinds = Counter()
for ts, coin, sig in recs:
    if "真高" in sig or "真底" in sig: kinds["真高/真底"] += 1
    elif "资金大幅流入" in sig or "资金大幅流出" in sig: kinds["大资金"] += 1
    elif "V型反弹" in sig or "见顶回落" in sig: kinds["V反/见顶"] += 1
    elif "低吸" in sig or "高抛" in sig: kinds["低吸/高抛"] += 1
    elif "缩量慢涨" in sig or "缩量慢跌" in sig: kinds["缩量"] += 1
    elif "移动止盈" in sig: kinds["移动止盈"] += 1
    elif "急涨" in sig or "急跌" in sig: kinds["30分急涨急跌"] += 1
    elif "变盘点" in sig: kinds["变盘点"] += 1
    elif "大户多空比" in sig: kinds["大户多空比"] += 1
    elif "BOLL" in sig or "突破" in sig or "跌破" in sig: kinds["BOLL"] += 1
    elif "板块" in sig: kinds["板块联动"] += 1
    else: kinds["其他"] += 1

print("  按类型:")
for k, v in kinds.most_common():
    print("    %-16s %d" % (k, v))
print()

# 取 K 线，算每个信号后 4 小时的真实涨跌
print("═══ 每个信号后 4 小时的真实涨跌 ═══")
print("    （日志时间是本地时间 UTC+8，K线是 UTC，做换算）")
print()
KL = {}
for pair in CURRENCY_PAIRS:
    coin = pair.replace("_USDT", "")
    d = get_kline(pair, "15m", 1000)
    if len(d) < 200: continue
    df = pd.DataFrame(d, columns=['ts','turnover','close','high','low','open','vol','wc'])
    df['close'] = df['close'].astype(float)
    df['dt'] = pd.to_datetime(df['ts'].astype("int64"), unit='s')   # UTC
    KL[coin] = df.set_index('dt').sort_index()

ok = 0
res = []
for ts, coin, sig in recs:
    if coin not in KL: continue
    t = pd.Timestamp(ts) - pd.Timedelta(hours=8)       # 本地 → UTC
    df = KL[coin]
    idx = df.index.searchsorted(t)
    if idx >= len(df) - 16 or idx < 1: continue
    entry = df['close'].iloc[idx]
    exit_ = df['close'].iloc[idx+16]
    raw = (exit_ - entry)/entry*100
    # 方向：看多类信号按涨算，看空类按跌算
    bearish = any(k in sig for k in ["看空", "流出", "见顶", "高抛", "慢跌", "真高", "回撤", "跑路"])
    good = (raw < 0) if bearish else (raw > 0)
    res.append((coin, raw, good, bearish, sig[:38]))

if res:
    n = len(res)
    hit = sum(1 for r in res if r[2])
    print("  可比对样本: %d 笔（有K线覆盖的）" % n)
    print("  方向猜对（看多则涨/看空则跌）: %d 笔 = %.0f%%" % (hit, hit/n*100))
    print("  平均 4 小时涨跌: %+.3f%%" % (sum(r[1] for r in res)/n))
    print("  扣手续费后看多的平均收益: %+.3f%%" % (sum(r[1] for r in res)/n - FEE_RATE*2*100))
    print()
    print("  样例（最近 10 条）:")
    for c, raw, good, bear, s in res[-10:]:
        print("    %-5s %+7.2f%%  %s  %s" % (c, raw, "✓" if good else "✗", s))
else:
    print("  （日志时间超出K线覆盖范围，无法比对）")
