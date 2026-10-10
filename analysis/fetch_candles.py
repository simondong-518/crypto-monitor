# -*- coding: utf-8 -*-
"""拉取历史 K 线（5m）用于"信号之后真实涨跌"测算。

只读公开行情接口；结果缓存到输出目录，重跑不再联网。
"""
import io
import os
import json
import time
import calendar
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "信号导出_20261010")
os.makedirs(OUT, exist_ok=True)

COINS = ["CYS", "SUI", "WLD", "BSV", "DOGE", "BTC"]
BASE = "https://api.gateio.ws/api/v4/spot/candlesticks"

# 日志时间戳是本机时间(UTC+8)，转 unix 要减 8 小时
LOCAL_OFFSET = 8 * 3600


def local_to_unix(s):
    t = time.strptime(s, "%Y-%m-%d %H:%M:%S")
    return calendar.timegm(t) - LOCAL_OFFSET


def fetch(pair, frm, to):
    """Gate.io 单次最多 1000 个数据点 → 按窗口分页拉。"""
    rows = {}
    span = 900 * 300          # 5m K 线：900 根，留余量（API 上限 1000 点）
    cur = frm
    while cur < to:
        w_to = min(cur + span, to)
        url = ("%s?currency_pair=%s&interval=5m&from=%d&to=%d&limit=1000"
               % (BASE, pair, cur, w_to))
        req = urllib.request.Request(url, headers={"User-Agent": "crypto-monitor/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            raise RuntimeError("HTTP%d from=%d to=%d :: %s" % (e.code, cur, w_to, body))
        for row in data:
            rows[int(row[0])] = row
        cur = w_to + 300
        time.sleep(0.35)
    return [rows[k] for k in sorted(rows)]


def main():
    frm = local_to_unix("2026-10-04 00:00:00")
    to = local_to_unix("2026-10-12 00:00:00")
    print("窗口 unix: %d → %d (%.1f 天)" % (frm, to, (to - frm) / 86400.0))
    for coin in COINS:
        pair = "%s_USDT" % coin
        path = os.path.join(OUT, "candles_%s.json" % coin)
        if os.path.exists(path) and os.path.getsize(path) > 100:
            print("  %-6s 已有缓存，跳过" % coin)
            continue
        t0 = time.time()
        try:
            rows = fetch(pair, frm, to)
        except Exception as e:
            print("  %-6s 失败: %s %s" % (coin, type(e).__name__, e))
            continue
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        print("  %-6s %5d 根  %.1fs  首=%s 末=%s"
              % (coin, len(rows), time.time() - t0, rows[0][0], rows[-1][0]))
        if coin == COINS[0] and rows:
            print("     样本行:", rows[0])
    print("缓存目录:", OUT)


if __name__ == "__main__":
    main()
