import sys
sys.path.insert(0, 'crypto_monitor')
from indicators import get_indicator
import time

ind = get_indicator("WLD_USDT", "15m")
df = ind['df']
today_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))*1000
df = df[df.index >= today_start]
avg_vol = df['vol'].rolling(20).mean().iloc[-1]

eff_high = df.iloc[0]['close']
eff_low = df.iloc[0]['close']

for i in range(len(df)):
    row = df.iloc[i]
    open_p = row['open']
    close_p = row['close']
    high_p = row['high']
    low_p = row['low']
    vol_p = row['vol']
    body = abs(close_p - open_p)
    upper_shadow = high_p - max(open_p, close_p)
    lower_shadow = min(open_p, close_p) - low_p
    if upper_shadow > body*2:
        if close_p > eff_high:
            eff_high = close_p
    else:
        if close_p > eff_high:
            eff_high = close_p
    if lower_shadow > body*2:
        if vol_p >= avg_vol*1:
            if close_p < eff_low:
                eff_low = close_p
    else:
        if close_p < eff_low:
            eff_low = close_p

print(f"WLD今天K线最高: {df['high'].max():.4f}")
print(f"WLD今天K线最低: {df['low'].min():.4f}")
print(f"过滤插针后有效高点: {eff_high:.4f}")
print(f"过滤插针后有效低点: {eff_low:.4f}")
print(f"当前价: {df.iloc[-1]['close']:.4f}")
