import pandas as pd
import time
from api import get_kline

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
    macd = (dif - dea) * 2
    return dif, dea, macd

# 2026-10-07 新增：标准可复用函数，判断真假BOLL破轨，过滤插针假突破
# 锁机制：第一次破轨先锁，下一根K线还在外面才算真破，回来就解锁
BOLL_BREAK_LOCK = {}
def check_boll_breakout(df_s, close, boll_u, boll_l, coin):
    """
    返回值:
    'true_break_up' = 真突破上轨
    'true_break_down' = 真跌破下轨
    None = 假突破/没破轨
    """
    key_up = f"{coin}_break_up"
    key_down = f"{coin}_break_down"
    # 先判断状态解锁：如果价格回到轨道内，解锁
    if key_up in BOLL_BREAK_LOCK and close < boll_u:
        del BOLL_BREAK_LOCK[key_up]
    if key_down in BOLL_BREAK_LOCK and close > boll_l:
        del BOLL_BREAK_LOCK[key_down]
    # 第一次破上轨：先锁，不推
    if close > boll_u:
        if key_up not in BOLL_BREAK_LOCK:
            BOLL_BREAK_LOCK[key_up] = True
            return None  # 第一次破轨，等下一根确认
        else:
            return 'true_break_up'  # 连续两根在外面，真突破
    # 第一次破下轨：先锁，不推
    if close < boll_l:
        if key_down not in BOLL_BREAK_LOCK:
            BOLL_BREAK_LOCK[key_down] = True
            return None  # 第一次破轨，等下一根确认
        else:
            return 'true_break_down'  # 连续两根在外面，真跌破
    return None

def calc_kdj(df, n=9):
    low_list = df['low'].rolling(n).min()
    high_list = df['high'].rolling(n).max()
    rsv = (df['close'] - low_list) / (high_list - low_list) * 100
    k = rsv.ewm(com=2).mean()
    d = k.ewm(com=2).mean()
    j = 3*k - 2*d
    return k, d, j

def get_indicator(pair, interval='15m'):
    data = get_kline(pair, interval)
    df = pd.DataFrame(data, columns=['t', 'volume', 'close', 'high', 'low', 'open', 'amount', 'is_contract'])
    df['t'] = df['t'].astype(int)
    df['t'] = pd.to_datetime(df['t'], unit='s')
    df = df.astype({'volume': float, 'close': float, 'high': float, 'low': float, 'open': float})
    df = df.sort_values('t').reset_index(drop=True)
    closes = df['close']
    boll_mid, boll_u, boll_l = calc_boll(closes)
    rsi = calc_rsi(closes)
    dif, dea, macd = calc_macd(closes)
    k, d, j = calc_kdj(df)
    vol_ma = df['volume'].rolling(20).mean()
    # 修正bug：取今天北京时间0点之后第一根K线的开盘价作为今日开盘价
    import time
    today = time.strftime("%Y-%m-%d", time.localtime())
    # df里的t是UTC时间，北京时间0点=UTC时间前一天16点
    today_start = pd.Timestamp(today) - pd.Timedelta(hours=8)
    today_df = df[df['t'] >= today_start]
    if len(today_df) == 0:
        day_open = df.iloc[0]['open']
    else:
        day_open = today_df.iloc[0]['open']
    day_chg = (closes.iloc[-1] - day_open)/day_open*100
    # 直接在正确的today_df上算当日高低点，统一UTC+8
    if len(today_df) == 0:
        today_high = df['high'].iloc[-1]
        today_low = df['low'].iloc[-1]
    else:
        today_high = today_df['high'].max()
        today_low = today_df['low'].min()
    ma20 = closes.rolling(20).mean()
    # 加EMA12和EMA26
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    # 判断金叉死叉：当前12>26，上一根12<=26就是金叉；当前12<26，上一根12>=26就是死叉
    golden_cross = (ema12.iloc[-1] > ema26.iloc[-1]) and (ema12.iloc[-2] <= ema26.iloc[-2])
    dead_cross = (ema12.iloc[-1] < ema26.iloc[-1]) and (ema12.iloc[-2] >= ema26.iloc[-2])
    return {
        'close': closes.iloc[-1],
        'boll_mid': boll_mid.iloc[-1],
        'boll_u': boll_u.iloc[-1],
        'boll_l': boll_l.iloc[-1],
        'rsi': rsi.iloc[-1],
        'kdj_j': j.iloc[-1],
        'kdj_overbought': j.iloc[-1] >= 100,
        'kdj_oversold': j.iloc[-1] <= 0,
        'ema12': ema12.iloc[-1],
        'ema26': ema26.iloc[-1],
        'golden_cross': golden_cross,
        'dead_cross': dead_cross,
        'dif': dif.iloc[-1],
        'dea': dea.iloc[-1],
        'macd': macd.iloc[-1],
        'k': k.iloc[-1],
        'd': d.iloc[-1],
        'j': j.iloc[-1],
        'vol_now': df['volume'].iloc[-1],
        'vol_ma': vol_ma.iloc[-1],
        'vol_enough': df['volume'].iloc[-1] > vol_ma.iloc[-1]*1.2,
        'day_chg': day_chg,
        'today_high': today_high,
        'today_low': today_low,
        'ma20': ma20.iloc[-1],
        'trend_up': closes.iloc[-1] > ma20.iloc[-1],
        'df': df,
        'macd_gold': False,
        'macd_dead': False,
        'k_gold': False,
        'k_dead': False
    }

def get_daily_trend(pair):
    data = get_kline(pair, '1d')
    df = pd.DataFrame(data, columns=['t', 'volume', 'close', 'high', 'low', 'open', 'amount', 'is_contract'])
    df = df.astype({'close': float})
    closes = df['close']
    ma20 = closes.rolling(20).mean()
    return closes.iloc[-1] > ma20.iloc[-1]
