with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
lines[153] = '                hold_advice = f"可以买入{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"\n'
lines[154] = '                empty_advice = f"可以建仓{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"\n'
lines[159] = '                hold_advice = "持有观望，不动"\n'
lines[162] = '            lines.append(f"**结论**: {trend_judge}，资金{flow_judge}，{daily_judge}")\n'
lines[163] = '            lines.append(f"**持仓建议**: {hold_advice}")\n'
lines[164] = '            lines.append(f"**空仓建议**: {empty_advice}")\n'
with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("改完154-165")
