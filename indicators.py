import pandas as pd
import time
from api import get_kline

# 2026-09-26 指标模块：所有技术指标计算
def calc_boll(closes, n=20):
    mid = closes.rolling(n).mean()
    std = closes.rolling(n).std()
    return mid, mid + 2*std, mid - 2*std

def calc_rsi(closes, n=14):
    delta = closes.diff()
    gain = delta.where(delta>0, 0).rolling(n).mean()
    loss = -delta.where(delta<0, 0).rolling(n).mean()
    return 100 - 100/(1 + gain/loss)

def calc_macd(closes):
    ef = closes.ewm(span=12).mean()
    es = closes.ewm(span=26).mean()
    dif = ef - es
    dea = dif.ewm(span=9).mean()
    return dif, dea

def calc_kdj(h, l, c, n=9):
    ln = l.rolling(n).min()
    hn = h.rolling(n).max()
    rsv = ((c-ln)/(hn-ln)*100).fillna(50)
    k = rsv.ewm(com=2).mean()
    d = k.ewm(com=2).mean()
    j = 3*k - 2*d
    return k, d, j

def get_indicator(pair, interval):
    data = get_kline(pair, interval, 100)
    df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
    for col in ['close','high','low','open','vol']:
        df[col] = df[col].astype(float)
    mid, upper, lower = calc_boll(df['close'])
    rsi = calc_rsi(df['close'])
    # 算当天0点涨幅（GATE K线ts是秒级）
    today = time.strftime("%Y-%m-%d", time.localtime())
    midnight = int(time.mktime(time.strptime(today, "%Y-%m-%d")))
    day_open = None
    for k in data:
        if int(k[0]) >= midnight:
            day_open = float(k[5])
            break
    if not day_open:
        day_chg = 0
    else:
        now = df['close'].iloc[-1]
        day_chg = (now - day_open)/day_open*100
    # 趋势判断：收盘价在MA20上方
    ma20 = df['close'].rolling(20).mean().iloc[-1]
    trend_up = now > ma20
    return {
        'close': now,
        'boll_m': mid.iloc[-1],
        'boll_u': upper.iloc[-1],
        'boll_l': lower.iloc[-1],
        'rsi': rsi.iloc[-1],
        'day_chg': day_chg,
        'trend_up': trend_up,
        'df': df
    }

# 2026-09-26 加日线大趋势判断
def get_daily_trend(pair):
    data = get_kline(pair, "1d", 100)
    df = pd.DataFrame(data, columns=['ts','turnover','close','high','low','open','vol','wc'])
    df['close'] = df['close'].astype(float)
    ma20 = df['close'].rolling(20).mean().iloc[-1]
    close = df['close'].iloc[-1]
    return close > ma20  # True=日线大趋势向上
