with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
c = c.replace('lines.append(f"| 瓒嬪娍 | {trend_emoji} {"涓婃定" if ind_s[\'trend_up\'] else "涓嬭穼"}(MA20) | {trend_judge} |")',
'lines.append(f"| 趋势 | {trend_emoji} {"上涨" if ind_s[\'trend_up\'] else "下跌"}(MA20) | {trend_judge} |")')
c = c.replace('empty_advice = "瑙傛湜锛岀瓑鏄庣′淇″彿"', 'empty_advice = "观望，等明确信号"')
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("改完最后两个乱码")
