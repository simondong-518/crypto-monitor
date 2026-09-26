with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()
old = '''            if abs(ind_s['day_chg']) >= threshold and vol_enough:
                alerts.append(f"今日{'大涨' if ind_s['day_chg']>0 else '大跌'}{ind_s['day_chg']:.1f}%")'''
new = '''            if abs(ind_s['day_chg']) >= 5:
                alerts.append(f"今日{'大涨' if ind_s['day_chg']>0 else '大跌'}{ind_s['day_chg']:.1f}%")
                if ind_s['trend_up'] and ind_s['day_chg']>0:
                    alerts.append("，趋势启动，拿住")
            elif abs(ind_s['day_chg']) >= threshold and vol_enough:
                alerts.append(f"今日{'大涨' if ind_s['day_chg']>0 else '大跌'}{ind_s['day_chg']:.1f}%")'''
content = content.replace(old, new)
# 加跌破MA20提醒
old2 = '''            if reverse_alert:
                alerts.append(reverse_alert)'''
new2 = '''            ma20 = ind_s['df']['close'].rolling(20).mean().iloc[-1]
            prev_close = ind_s['df']['close'].iloc[-2]
            if prev_close > ma20 and ind_s['close'] < ma20 and ind_s['trend_up']:
                alerts.append("⚠️ 跌破MA20，止盈落袋")
            if reverse_alert:
                alerts.append(reverse_alert)'''
content = content.replace(old2, new2)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("改完了")
