with open("strategy.py", "r", encoding="utf-8") as f:
    c = f.read()
old = '''    # 连续3根阳线加买分
    last3 = df.tail(3)
    three_up = (last3['close'] > last3['open']).sum() == 3
    if three_up and close > ind_s['boll_m']:
        buy +=1.5'''
new = '''    # 连续3根阳线加买分
    last3 = df.tail(3)
    three_up = (last3['close'] > last3['open']).sum() == 3
    if three_up and close > ind_s['boll_m']:
        buy +=1.5
    # 连续3根阴线减买分加卖分
    three_down = (last3['close'] < last3['open']).sum() == 3
    if three_down and close < ind_s['boll_m']:
        sell +=1.5'''
c = c.replace(old, new)
with open("strategy.py", "w", encoding="utf-8") as f:
    f.write(c)
print("加完了")
