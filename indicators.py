"""指标模块：所有技术指标计算。

2026-09-29 P1-1 修正口径（本次最重要的根因修复）：
  **所有指标一律算在「最后一根已收盘 bar」上（df.iloc[-2]）**，
  只有「实时价」和「当日涨跌幅」用形成中的 bar（df.iloc[-1]）。
  原因：原来一律用 iloc[-1]，也就是拿一根刚开盘 1 分钟、还在形成的 bar 去算量能和指标：
    实测同一时刻（2026-09-29 09:30:08）—— 形成中 bar 的量是均量的 0.00~0.11 倍，
    而同一批币的已收盘 bar 是 1.34~13.98 倍。也就是说 `量 > 1.2 倍均量` 这个门槛
    **结构性不可达**，不是噪声问题；同理 MACD/KDJ 的交叉信号会在活 bar 上反复闪烁。
  代价与要求：报告里的「价（实时）」和「指标（已收盘 bar）」不再是同一根 bar，
    所以报告必须打印**该 bar 的收盘时间**（bar_time），否则没人看得懂这个数是哪根 K 线的。
"""
import time

import pandas as pd

from api import get_kline

CLOSED = -2          # 最后一根已收盘 bar 的下标；df.iloc[-1] 是形成中的 bar
MIN_BARS = 25        # 需要至少这么多个 bar：MA20 要 20，boll_all_up 还要往前看 3 根


def fmt_ts(ts):
    """Gate 的 ts 是秒级字符串/数字 → 'YYYY-MM-DD HH:MM'"""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(float(ts))))
    except Exception:
        return "?"


def calc_boll(closes, n=20):
    mid = closes.rolling(n).mean()
    std = closes.rolling(n).std()
    return mid, mid + 2*std, mid - 2*std


def calc_rsi(closes, n=14):
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(n).mean()
    loss = -delta.where(delta < 0, 0).rolling(n).mean()
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
    rsv = ((c - ln)/(hn - ln)*100).fillna(50)
    k = rsv.ewm(com=2).mean()
    d = k.ewm(com=2).mean()
    j = 3*k - 2*d
    return k, d, j


def _frame(data):
    if not isinstance(data, list) or len(data) < MIN_BARS:
        raise RuntimeError(
            f"K线数据异常：期望 ≥{MIN_BARS} 根，实际 "
            f"{len(data) if isinstance(data, list) else type(data).__name__} 根"
            + (f"（返回体：{str(data)[:120]}）" if not isinstance(data, list) else "")
        )
    df = pd.DataFrame(data, columns=['ts', 'turnover', 'close', 'high', 'low', 'open', 'vol', 'wc'])
    for col in ['close', 'high', 'low', 'open', 'vol']:
        df[col] = df[col].astype(float)
    return df


def _day_open(data):
    """当天 0 点之后第一根 K 线的开盘价（用于算当日涨跌幅）"""
    today = time.strftime("%Y-%m-%d", time.localtime())
    midnight = int(time.mktime(time.strptime(today, "%Y-%m-%d")))
    for row in data:
        if int(float(row[0])) >= midnight:
            return float(row[5])
    return None


def _shadow(row):
    body = abs(row['close'] - row['open'])
    return (float(body),
            float(row['high'] - max(row['open'], row['close'])),
            float(min(row['open'], row['close']) - row['low']))


def get_indicator(pair, interval):
    data = get_kline(pair, interval, 100)
    df = _frame(data)

    k = len(df) + CLOSED                 # 最后一根已收盘 bar 的下标
    mid, upper, lower = calc_boll(df['close'])
    rsi = calc_rsi(df['close'])
    dif, dea = calc_macd(df['close'])
    kk, dd, jj = calc_kdj(df['high'], df['low'], df['close'])

    price = float(df['close'].iloc[-1])          # 实时价（价格类事实）
    do = _day_open(data)
    day_chg = (price - do)/do*100 if do else 0.0

    ma20 = df['close'].rolling(20).mean().iloc[k]
    vol_avg = df['vol'].rolling(20).mean().iloc[k]
    vol_now = float(df['vol'].iloc[k])
    try:
        bar_closed = str(df['wc'].iloc[k]).lower() in ("true", "1")
    except Exception:
        bar_closed = None

    return {
        # ---------- 价格类：实时 ----------
        'price': price,                    # 报告显示 / 到价提醒 / 涨跌幅 都用它
        'day_chg': day_chg,
        # ---------- 已收盘 bar 的价 ----------
        'close': float(df['close'].iloc[k]),        # 指标类比较一律用它
        'prev_close': float(df['close'].iloc[k-1]),
        'bar_time': fmt_ts(df['ts'].iloc[k]),       # 这根已收盘 bar 的收盘时间
        'bar_closed': bar_closed,                   # 期望 True；不是 True 就说明口径又错了
        # ---------- 指标（全部在 k 上） ----------
        'boll_m': float(mid.iloc[k]),
        'boll_u': float(upper.iloc[k]),
        'boll_l': float(lower.iloc[k]),
        'rsi': float(rsi.iloc[k]),
        'ma20': float(ma20),
        'trend_up': bool(df['close'].iloc[k] > ma20),
        'boll_all_up': bool(mid.iloc[k] > mid.iloc[k-3]
                            and upper.iloc[k] > upper.iloc[k-3]
                            and lower.iloc[k] > lower.iloc[k-3]),
        'macd_gold': bool(dif.iloc[k] > dea.iloc[k] and dif.iloc[k-1] <= dea.iloc[k-1]),
        'macd_dead': bool(dif.iloc[k] < dea.iloc[k] and dif.iloc[k-1] >= dea.iloc[k-1]),
        'kdj_j': float(jj.iloc[k]),
        'k_gold': bool(kk.iloc[k] > dd.iloc[k] and kk.iloc[k-1] <= dd.iloc[k-1]),
        'k_dead': bool(kk.iloc[k] < dd.iloc[k] and kk.iloc[k-1] >= dd.iloc[k-1]),
        # 量能：用已收盘 bar —— 这正是原来"量能门槛永不达标"的根因
        'vol_now': vol_now,
        'vol_avg': float(vol_avg),
        'vol_ratio': float(vol_now/vol_avg) if vol_avg else 0.0,
        # 最近两根已收盘 bar 的 (实体, 上影, 下影)：[0]=最新已收盘, [1]=前一根
        'shadows': [_shadow(df.iloc[k]), _shadow(df.iloc[k-1])],
        'df': df,
    }


def get_daily_trend(pair):
    """日线大趋势：用**最后一根已收盘日线**（今天的日线还在形成中）。True=向上。"""
    df = _frame(get_kline(pair, "1d", 100))
    k = len(df) + CLOSED
    ma20 = df['close'].rolling(20).mean().iloc[k]
    return bool(df['close'].iloc[k] > ma20)
