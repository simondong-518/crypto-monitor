with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace('key_tp = f"{coin}_姝㈢泩浠穥take_profit}"', 'key_tp = f"{coin}_止盈{take_profit}"')
c = c.replace('key_sl = f"{coin}_姝㈡崯浠穥stop_loss}"', 'key_sl = f"{coin}_止损{stop_loss}"')
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("修好了")
