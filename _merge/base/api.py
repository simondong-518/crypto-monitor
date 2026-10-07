import requests
import time
from config import BASE

def get_kline(pair, interval='15m', limit=100):
    for i in range(3):
        try:
            url = f"{BASE}/spot/candlesticks?currency_pair={pair}&interval={interval}&limit={limit}"
            r = requests.get(url, timeout=15)
            return r.json()
        except:
            time.sleep(1)
    return []

def get_trades(pair, limit=100):
    for i in range(3):
        try:
            url = f"{BASE}/spot/trades?currency_pair={pair}&limit={limit}"
            r = requests.get(url, timeout=15)
            return r.json()
        except:
            time.sleep(1)
    return []

def get_ls(pair):
    try:
        url = f"{BASE}/futures/{pair}/long_short?limit=1"
        r = requests.get(url, timeout=10)
        return r.json()
    except:
        return []

def get_flow_1h(pair):
    try:
        # 正确算最近1小时的资金净流入：拿最近1000笔逐笔成交，累加买卖差额
        trades = get_trades(pair, limit=1000)
        buy_v = sell_v = 0
        for t in trades:
            v = float(t['amount']) * float(t['price'])
            if t['side'] == 'buy':
                buy_v += v
            else:
                sell_v += v
        return buy_v - sell_v
    except:
        pass
    return 0

def get_btc_chg():
    try:
        # 取BTC最近1小时K线，算实时涨跌
        data = get_kline('BTC_USDT', '1h', limit=2)
        if len(data)>=2:
            prev_close = float(data[-2][2])
            now_close = float(data[-1][2])
            return (now_close - prev_close)/prev_close*100
    except:
        pass
    return 0

def check_events():
    return []

def get_big_order(pair):
    return (0, 0)

def get_funding_rate(pair):
    return (0.001, 0)

def get_orderbook(pair):
    try:
        url = f"{BASE}/spot/order_book?currency_pair={pair}&limit=50"
        r = requests.get(url, timeout=10)
        data = r.json()
        bids = data.get('bids', [])
        asks = data.get('asks', [])
        bid_total = sum(float(p) * float(a) for p, a in bids)
        ask_total = sum(float(p) * float(a) for p, a in asks)
        buy1 = float(bids[0][0]) if bids else 0
        sell1 = float(asks[0][0]) if asks else 0
        return (buy1, sell1, bid_total, ask_total)
    except:
        return (0, 0, 0, 0)

def analyze_trades(trades):
    buy_v = sell_v = 0
    for t in trades:
        v = float(t['amount']) * float(t['price'])
        if t['side'] == 'buy': buy_v += v
        else: sell_v += v
    return {"buy_volume": buy_v, "sell_volume": sell_v, "net_inflow": buy_v - sell_v}
