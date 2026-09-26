with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
old = '''            lines.append(f"| RSI | 15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f} | {', '.join(rsi_judge)} |")'''
new = '''            lines.append(f"| RSI | 15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f} | {', '.join(rsi_judge)} |")
            # 1h趋势
            l_space = (ind_l['boll_u'] - ind_l['close'])/ind_l['close']*100
            lines.append(f"| 1h趋势 | BOLL上轨{ind_l['boll_u']:.4f} | 离上轨{l_space:.1f}%，{'上涨' if ind_l['trend_up'] else '下跌'}")'''
c = c.replace(old, new)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("加完了")
