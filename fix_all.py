with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
# 第41行
lines[40] = '        send_wx("⚠️ BTC暴跌预警", f"BTC今日跌{btc_chg:.1f}%，所有币大概率跟跌，别抄底，手里有币逢高减仓")\n'
# 第48行
lines[47] = '            key_tp = f"{coin}_止盈{take_profit}"\n'
# 第49行
lines[48] = '            key_sl = f"{coin}_止损{stop_loss}"\n'
# 第52行
lines[51] = '                send_wx(f"✅ {coin}到止盈价！", f"现价{price}，到你设置的止盈价{take_profit}，可以卖出止盈了")\n'
# 第56行
lines[55] = '                send_wx(f"⚠️ {coin}到止损价！", f"现价{price}，到你设置的止损价{stop_loss}，注意风险")\n'
# 第60行
lines[59] = '    lines = ["# 📈 K线监测报告", f"时间：{datetime.now().strftime(\'%Y-%m-%d %H:%M\')}", ""]\n'
# 第98行
lines[97] = '                alerts.append("⚠️ 跌破MA20，止盈落袋")\n'
# 第109行
lines[108] = '                    alerts.append("RSI极度超买+连续长上影")\n'
# 第124行
lines[123] = '            trend_judge = "大趋势向上" if ind_s[\'trend_up\'] else "大趋势向下"\n'
# 第127行
lines[126] = '            lines.append(f"| 支撑/压力 | 支撑{ind_s[\'boll_l\']:.4f} / 压力{ind_s[\'boll_u\']:.4f} | 离压力{space:.1f}% |")\n'
# 第131行
lines[130] = '            else: rsi_judge.append("15m中性")\n'
# 第134行
lines[133] = '            else: rsi_judge.append("1h中性")\n'
# 第142行
lines[141] = '            s_emoji = "🟢" if current_signal=="买入" else ("🔴" if current_signal=="卖出" else "⚪")\n'
# 第143行
lines[142] = '            lines.append(f"| 15m信号 | {s_emoji} {current_signal} | 买{b_score:.1f}/卖{s_score:.1f} |")\n'
with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("全部改完")
