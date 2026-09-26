import requests
import time
from config import BASE

# 2026-09-26 API模块：所有GATE接口请求，带超时重试
def get_kline(pair, interval, limit=100):
    for i in range(3):
        try:
            r = requests.get(f"{BASE}/spot/candlesticks", params={"currency_pair": pair, "interval": interval, "limit": limit}, timeout=15)
            return r.json()
        except:
            time.sleep(2)
    return []

def get_trades(pair, limit=100):
    for i in range(3):
        try:
            r = requests.get(f"{BASE}/spot/trades", params={"currency_pair": pair, "limit": limit}, timeout=15)
            return r.json()
        except:
            time.sleep(2)
    return []

def get_ls(pair):
    try:
        r = requests.get(f"{BASE}/futures/usdt/contract_stats", params={"contract": pair, "limit": 10}, timeout=10)
        return r.json()
    except: return None

def get_btc_chg():
    # 修复：算BTC当天涨幅
    data = get_kline("BTC_USDT", "15m", 500)
    import pandas as pd
    import time
    df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
    df['close'] = df['close'].astype(float)
    today = time.strftime("%Y-%m-%d", time.localtime())
    midnight = int(time.mktime(time.strptime(today, "%Y-%m-%d")))*1000
    day_open = None
    for k in data:
        if int(k[0]) >= midnight:
            day_open = float(k[5])
            break
    if not day_open:
        return 0
    now = df['close'].iloc[-1]
    return (now - day_open)/day_open*100

# 事件监控：检查新公告
last_announce_ts = 0
def check_events():
    global last_announce_ts
    from notifier import send_wx
    try:
        r = requests.get(f"{BASE}/spot/time", timeout=10)
        now_ts = r.json()['server_time']
        r2 = requests.get(f"{BASE}/announcements", params={"type": "new_listing"}, timeout=10)
        anns = r2.json()
        new_anns = []
        for a in anns[:5]:
            if int(a['date']) > last_announce_ts:
                new_anns.append(a['title'])
        if new_anns:
            send_wx("📢 重大事件", "新上币/公告：\n" + "\n".join(new_anns))
        last_announce_ts = now_ts
    except: pass
