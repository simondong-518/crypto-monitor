with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
old = '''            lines.append(f"| 仓位建议 | {position} | 日线{'向上3成仓' if daily_up else '向下1成仓'} |")'''
new = '''            lines.append(f"| 仓位建议 | {position} | 日线{'向上3成仓' if daily_up else '向下1成仓'} |")
            # 操作结论
            if current_signal == "买入":
                concl = "持仓：可加仓；空仓：现在可上车"
            elif current_signal == "卖出":
                concl = "持仓：止盈落袋；空仓：别接飞刀"
            elif ind_s['rsi'] > 80:
                concl = "持仓：拿住别乱卖；空仓：别追高等回调"
            else:
                concl = "持仓：持有不动；空仓：观望等信号"
            lines.append(f"| 操作结论 | {concl} | 低吸高抛 |")'''
c = c.replace(old, new)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("加完了")
