with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace("{'上涨' if ind_l['trend_up'] else '下跌'}\")", "{'上涨' if ind_l['trend_up'] else '下跌'} |\")")
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("修好了")
