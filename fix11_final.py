with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
lines[10] = "pushed_news = set()\n"
with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("改第11行")
