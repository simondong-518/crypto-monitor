with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
old = '''            # 移动止盈：从当天最高点回撤3%
            if coin not in day_high or ind_s['close'] > day_high[coin]:
                day_high[coin] = ind_s['close']
            drawdown = (day_high[coin] - ind_s['close'])/day_high[coin]*100
            if drawdown >= 3 and ind_s['trend_up']:
                alerts.append(f"⚠️ 从最高点{day_high[coin]:.4f}回撤{drawdown:.1f}%，移动止盈落袋")'''
new = '''            # 移动止盈：从当天最高点回撤3%（直接从当天K线读最高价，重启不丢）
            today_high = ind_s['df'][ind_s['df'].index.date == pd.Timestamp.now().date()]['high'].max()
            drawdown = (today_high - ind_s['close'])/today_high*100
            if drawdown >= 3 and ind_s['trend_up']:
                alerts.append(f"⚠️ 从最高点{today_high:.4f}回撤{drawdown:.1f}%，移动止盈落袋")'''
c = c.replace(old, new)
# 加pandas import
c = c.replace("import time, re, json, os", "import time, re, json, os\nimport pandas as pd")
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("修好了")
