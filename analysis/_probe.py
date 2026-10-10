# -*- coding: utf-8 -*-
"""探测 Gate.io candlesticks 接口的正确调用方式（只读）。"""
import json
import urllib.request
import urllib.error

BASE = "https://api.gateio.ws/api/v4/spot/candlesticks"


def call(qs, label):
    url = BASE + "?" + qs
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "crypto-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        print("  [OK  ] %-46s -> %d 条" % (label, len(data)))
        if data:
            print("          样本:", data[0])
        return data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        print("  [HTTP%d] %-46s -> %s" % (e.code, label, body))
    except Exception as e:
        print("  [ERR ] %-46s -> %s %s" % (label, type(e).__name__, e))
    return None


print("=== 1) 最简调用 ===")
call("currency_pair=BTC_USDT&interval=5m&limit=3", "BTC 5m limit=3")

print("=== 2) 带 from/to（长窗口）===")
call("currency_pair=BTC_USDT&interval=5m&from=1791043200&to=1791734400&limit=1000",
     "from=1004 to=1012 limit=1000")

print("=== 3) 带 from/to（短窗口，1 天）===")
call("currency_pair=BTC_USDT&interval=5m&from=1791043200&to=1791129600&limit=1000",
     "from=1004 to=1005 limit=1000")

print("=== 4) 用 limit=1000 不带 from/to ===")
call("currency_pair=BTC_USDT&interval=5m&limit=1000", "BTC 5m limit=1000")

print("=== 5) interval=1m 带 from/to ===")
call("currency_pair=BTC_USDT&interval=1m&from=1791043200&to=1791129600&limit=1000",
     "BTC 1m from/to limit=1000")
