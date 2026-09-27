with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace("from notifier import send_wx", "from notifier import send_wx, beep")
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("导入beep了")
