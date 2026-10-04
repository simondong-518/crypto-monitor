import sys
sys.path.insert(0, 'crypto_monitor')
from indicators import get_indicator

ind = get_indicator("SUI_USDT", "15m")
df = ind['df']
print(f"SUI今日K线最高: {df['high'].max():.4f}")
print(f"SUI今日K线最低: {df['low'].min():.4f}")
print(f"SUI当前价: {ind['close']:.4f}")
print(f"SUI今日涨幅: {ind['day_chg']:.2f}%")
