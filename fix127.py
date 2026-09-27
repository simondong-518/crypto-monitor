with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
lines[126] = '            lines.append(f"| 支撑/压力 | 支撑{ind_s[\'boll_l\']:.4f} / 压力{ind_s[\'boll_u\']:.4f} | 离压力{space:.1f}% |")\n'
with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("改完127行")
