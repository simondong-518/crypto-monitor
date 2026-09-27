with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace('f"BTC浠婃棩璺寋btc_chg:.1f}%', 'f"BTC今日跌{btc_chg:.1f}%')
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("修好了")
