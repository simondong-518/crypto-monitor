with open("strategy.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace("    if three_up and close > ind_s['boll_m']:\n        buy +=1", "    if three_up and close > ind_s['boll_m']:\n        buy +=1.5")
with open("strategy.py", "w", encoding="utf-8") as f:
    f.write(c)
print("改完了")
