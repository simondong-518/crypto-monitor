"""缓存自检：省了多少请求 + **判定结果有没有被改** 。

用法： <解释器> verify_cache.py
"""
import collections
import io
import re
import sys
import time

sys.path.insert(0, r'M:\hermes\workspace\dev\crypto-monitor-v3')
import os
os.chdir(r'M:\hermes\workspace\dev\crypto-monitor-v3')

import requests

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


# ── 1) 配置层 ───────────────────────────────────────────────
import config
import kline_cache

check("缓存默认开启", config.CACHE_ENABLED is True)
check("★ 15m 不在缓存表里（对方口径必须实时）",
      "15m" not in (config.CACHE_TTL or {}), str(list((config.CACHE_TTL or {}).keys())))
check("15m 的 TTL 为 0（= 不缓存）", kline_cache.ttl_for("15m") == 0)
check("1h / 4h / 1d 都有缓存", all(kline_cache.ttl_for(k) > 0 for k in ("1h", "4h", "1d")))

# ── 2) K 线起点对齐（跨整点自动失效）────────────────────────
import datetime as _dt
probe = _dt.datetime(2026, 10, 5, 14, 37, 12).timestamp()
check("1h 起点 = 整点", kline_cache.bar_start("1h", probe) % 3600 == 0)
check("15m 起点落在 0/15/30/45",
      (kline_cache.bar_start("15m", probe) % 900) == 0)
check("日线起点 = 当天 0 点（UTC）",
      kline_cache.bar_start("1d", probe) % 86400 == 0)
# 同一根 K 线内 key 相同，跨到下一根 key 就变
a = kline_cache.bar_start("1h", probe)
b = kline_cache.bar_start("1h", probe + 60)          # 同小时内
c = kline_cache.bar_start("1h", probe + 3600)        # 下一小时
check("同一根 K 线内 key 稳定", a == b)
check("跨整点 key 变化 → 自动重拉", a != c)

# ── 3) 失败不缓存 ───────────────────────────────────────────
kline_cache.clear()
calls = {"n": 0}


def failing():
    calls["n"] += 1
    return None


kline_cache.get_or_fetch(("t", 1), 300, failing)
kline_cache.get_or_fetch(("t", 1), 300, failing)
check("取数失败不写缓存（下次仍会重试）", calls["n"] == 2, f"实际调用 {calls['n']} 次")

# ── 4) 缓存命中 ─────────────────────────────────────────────
kline_cache.clear()
calls["n"] = 0


def ok_data():
    calls["n"] += 1
    return [1, 2, 3]


kline_cache.get_or_fetch(("t", 2), 300, ok_data)
kline_cache.get_or_fetch(("t", 2), 300, ok_data)
kline_cache.get_or_fetch(("t", 2), 300, ok_data)
check("成功数据被复用（3 次请求只取 1 次）", calls["n"] == 1, f"实际 {calls['n']} 次")

# ── 5) 关掉缓存 → 回到全实时 ────────────────────────────────
config.CACHE_ENABLED = False
kline_cache.clear()
calls["n"] = 0
for _ in range(3):
    kline_cache.get_or_fetch(("t", 3), 300, ok_data)
check("关掉缓存后每次都真取", calls["n"] == 3, f"实际 {calls['n']} 次")
config.CACHE_ENABLED = True

# ── 6) 实跑两轮，数请求 ═════════════════════════════════════
hits = collections.Counter()
_orig = requests.get


def spy(url, **kw):
    u = str(url)
    u = re.sub(r'contract=[A-Z0-9_]+', 'contract=<P>', u)
    u = re.sub(r'currency_pair=[A-Z0-9_]+', 'currency_pair=<P>', u)
    u = re.sub(r'limit=\d+', 'limit=N', u)
    hits[u.split('/api/v4/')[-1]] += 1
    return _orig(url, **kw)


import api
requests.get = spy
api.requests = requests
import main
import notifier
notifier.NOTIFY_CONSOLE = False
try:
    notifier.FEISHU_WEBHOOK = ""
except Exception:
    pass

print("  实跑第 1 轮（冷缓存）…")
t0 = time.time()
main.monitor_once()
r1 = sum(hits.values())
hits.clear()
print("  实跑第 2 轮（热缓存）…")
main.monitor_once()
r2 = sum(hits.values())
dt = time.time() - t0

print()
print("  ┌──────────────────────────────────────────────")
print(f"  │ 第 1 轮（冷）  {r1:>3} 请求")
print(f"  │ 第 2 轮（热）  {r2:>3} 请求   ← 稳定状态就是这个数")
print(f"  │ 原实现         50 请求/轮")
print(f"  │ 省了        {50 - r2:>3} 请求/轮 （{(1-r2/50)*100:.0f}%）")
print(f"  │ 折合每分钟  {r2:.0f} 请求/分钟（原 110）")
print("  └──────────────────────────────────────────────")
print()
print("  第 2 轮明细：")
for k, v in hits.most_common():
    print(f"    {v:>3} 次  {k}")

check("热轮请求数明显下降（≤ 35）", r2 <= 35, f"实际 {r2}")
check("★ 15m K 线仍是每币每轮 1 次（实时不变）",
      hits.get("spot/candlesticks?currency_pair=<P>&interval=15m&limit=N", 0)
      == len(main.CURRENCY_PAIRS),
      f"实际 {hits.get('spot/candlesticks?currency_pair=<P>&interval=15m&limit=N', 0)} 次")

# ── 7) ★ 等价性：缓存不改变任何判定值 ───────────────────────
#     做法：抓**同一份原始数据**，一条路直接算、一条路经缓存算，要求逐位相同。
#     （不能"跑两次实拉再比" —— 15m 用的是正在走的那根，
#       两次请求之间行情本身就在动，那样比永远比不出结论。）
print()
print("  等价性对比（同一份数据：直接算 vs 经缓存算）…")

import pandas as pd
from indicators import calc_boll, calc_rsi

snap = {p: main.get_kline(p, "15m", 100) for p in main.CURRENCY_PAIRS}


def digest(data):
    df = pd.DataFrame(data, columns=['t', 'volume', 'close', 'high', 'low',
                                     'open', 'amount', 'is_contract'])
    df['close'] = df['close'].astype(float)
    closes = df['close']
    return (round(float(closes.iloc[-1]), 10),
            round(float(calc_rsi(closes).iloc[-1]), 10),
            round(float(calc_boll(closes)[1].iloc[-1]), 10),
            round(float(closes.iloc[0]), 10))


config.CACHE_ENABLED = False
kline_cache.clear()
direct = {p: digest(snap[p]) for p in main.CURRENCY_PAIRS}

config.CACHE_ENABLED = True
kline_cache.clear()
for p in main.CURRENCY_PAIRS:                       # 先填充
    kline_cache.get_or_fetch(("eq", p), 600, lambda q=p: snap[q])
cached = {p: digest(kline_cache.get_or_fetch(("eq", p), 600, lambda q=p: snap[q]))
          for p in main.CURRENCY_PAIRS}

bad = [p for p in main.CURRENCY_PAIRS if direct[p] != cached.get(p)]
check("★ 同一份数据经缓存处理，结果逐位相同", not bad, f"不一致: {bad}")

# ── 8) 已收盘 K 线：缓存内容 == 现拉内容 ────────────────────
#     只比已收盘的（最后一根正在走，本来就每秒在变）
config.CACHE_ENABLED = True
kline_cache.clear()
fresh = {p: main.get_kline(p, "1h", 100) for p in main.CURRENCY_PAIRS}
config.CACHE_ENABLED = False
mismatch = []
for p in main.CURRENCY_PAIRS:
    live = main.get_kline(p, "1h", 100)
    if fresh[p][:-1] != live[:-1]:
        mismatch.append(p)
check("★ 1h 已收盘 K 线：缓存与现拉逐位相同", not mismatch, f"不一致: {mismatch}")
config.CACHE_ENABLED = True


# ── 输出 ────────────────────────────────────────────────────
print()
w = max(len(n) for n, _o, _x in results)
fails = 0
for n, o, d in results:
    if not o:
        fails += 1
    print(f"    {'PASS' if o else 'FAIL'}  {n}" + (f"   [{d}]" if (d and not o) else ""))
print()
print(f"  结果: {len(results)-fails}/{len(results)} 通过")
sys.exit(1 if fails else 0)
