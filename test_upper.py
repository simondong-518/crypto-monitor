import sys
sys.path.insert(0, 'crypto_monitor')
from indicators import get_indicator

ind = get_indicator("SUI_USDT", "15m")
df = ind['df']
print("最近5根K线的开高低收和影线长度：")
for i in range(-5,0):
    row = df.iloc[i]
    open_p = row['open']
    close_p = row['close']
    high_p = row['high']
    low_p = row['low']
    body = abs(close_p - open_p)
    upper = high_p - max(open_p, close_p)
    lower = min(open_p, close_p) - low_p
    print(f"K线{i}: open={open_p:.4f}, close={close_p:.4f}, high={high_p:.4f}, low={low_p:.4f}")
    print(f"   实体={body:.4f}, 上影={upper:.4f}, 下影={lower:.4f}, 上影/实体={upper/body if body>0 else 0:.2f}")
