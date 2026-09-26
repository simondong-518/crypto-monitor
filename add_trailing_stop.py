with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
# 加全局最高价记录
old = '''pushed = {}
MAX_PUSH_PER_SIGNAL = 3'''
new = '''pushed = {}
MAX_PUSH_PER_SIGNAL = 3
day_high = {}  # 记录当天每个币的最高价'''
c = c.replace(old, new)
# 在每个币的提醒部分加移动止盈判断
old2 = '''            # 跌破MA20止盈提醒
            ma20 = ind_s['df']['close'].rolling(20).mean().iloc[-1]
            prev_close = ind_s['df']['close'].iloc[-2]
            if prev_close > ma20 and ind_s['close'] < ma20 and ind_s['trend_up']:
                alerts.append("⚠️ 跌破MA20，止盈落袋")'''
new2 = '''            # 移动止盈：从当天最高点回撤3%
            if coin not in day_high or ind_s['close'] > day_high[coin]:
                day_high[coin] = ind_s['close']
            drawdown = (day_high[coin] - ind_s['close'])/day_high[coin]*100
            if drawdown >= 3 and ind_s['trend_up']:
                alerts.append(f"⚠️ 从最高点{day_high[coin]:.4f}回撤{drawdown:.1f}%，移动止盈落袋")
            # 跌破MA20止盈提醒
            ma20 = ind_s['df']['close'].rolling(20).mean().iloc[-1]
            prev_close = ind_s['df']['close'].iloc[-2]
            if prev_close > ma20 and ind_s['close'] < ma20 and ind_s['trend_up']:
                alerts.append("⚠️ 跌破MA20，止盈落袋")'''
c = c.replace(old2, new2)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("加完了")
