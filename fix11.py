with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace("pushed_news = set(), beep", "pushed_news = set()")
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("修好了")
