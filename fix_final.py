with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace("瓒嬪娍", "趋势")
c = c.replace("涓嬭穼", "下跌")
c = c.replace("涓婃定", "上涨")
c = c.replace("瑙傛湜锛岀瓑鏄庣′淇″彿", "观望，等明确信号")
c = c.replace("骞宠　", "平衡")
c = c.replace("鍋忕┖", "偏空")
c = c.replace("鍋忓", "偏多")
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("乱码全部修完")
