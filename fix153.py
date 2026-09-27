with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
lines[152] = '                    pos = "1成轻仓"\n'
with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("修153行")
