with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace("avg_vol * 1.5", "avg_vol * 1.2")
c = c.replace("浠婃棩", "今日")
c = c.replace("澶ф定", "大涨")
c = c.replace("澶ц穼", "大跌")
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("改完量门槛")
