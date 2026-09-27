with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
lines[40] = '        send_wx("⚠️ BTC暴跌预警", f"BTC今日跌{btc_chg:.1f}%，所有币大概率跟跌，别抄底，手里有币逢高减仓")\n'
with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("修第41行")
