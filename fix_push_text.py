with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
# 替换所有乱码表格行
c = c.replace('lines.append("| 鎸囨爣 | 鏁板€?| 鍒ゆ柇 |")', 'lines.append("| 指标 | 数值 | 判断 |")')
c = c.replace('lines.append("|------|------|------|")', 'lines.append("|------|------|------|")')
c = c.replace('trend_emoji = "馃煝" if ind_s[\'trend_up\'] else "馃敶"', 'trend_emoji = "🟢" if ind_s[\'trend_up\'] else "🔴"')
c = c.replace('lines.append(f"| 瓒嬪娍 | {trend_emoji} {"涓婃定" if ind_s[\'trend_up\'] else "涓嬭穼"}(MA20) | {trend_judge} |")',
'lines.append(f"| 趋势 | {trend_emoji} {"上涨" if ind_s[\'trend_up\'] else "下跌"}(MA20) | {trend_judge} |")')
c = c.replace('lines.append(f"| 鏀敮/鍘嬪姏 | 鏀敮{ind_s[\'boll_l\']:.4f} / 鍘嬪姏{ind_s[\'boll_u\']:.4f} | 绂诲帇鍔泏space:.1f}% |")',
'lines.append(f"| 支撑/压力 | 支撑{ind_s[\'boll_l\']:.4f} / 压力{ind_s[\'boll_u\']:.4f} | 离压力{space:.1f}% |")')
c = c.replace('if ind_s[\'rsi\']<30: rsi_judge.append("15m瓒呭崠")', 'if ind_s[\'rsi\']<30: rsi_judge.append("15m超卖")')
c = c.replace('elif ind_s[\'rsi\']>70: rsi_judge.append("15m瓒呬拱")', 'elif ind_s[\'rsi\']>70: rsi_judge.append("15m超买")')
c = c.replace('else: rsi_judge.append("15m涓€?)', 'else: rsi_judge.append("15m中性")')
c = c.replace('if ind_l[\'rsi\']<30: rsi_judge.append("1h瓒呭崠")', 'if ind_l[\'rsi\']<30: rsi_judge.append("1h超卖")')
c = c.replace('elif ind_l[\'rsi\']>70: rsi_judge.append("1h瓒呬拱")', 'elif ind_l[\'rsi\']>70: rsi_judge.append("1h超买")')
c = c.replace('else: rsi_judge.append("1h涓€?)', 'else: rsi_judge.append("1h中性")')
c = c.replace('lines.append(f"| 璧勯噾娴佸悜 | ${flow[\'net_inflow\']:.0f} | {flow_judge} |")',
'lines.append(f"| 资金流向 | ${flow[\'net_inflow\']:.0f} | {flow_judge} |")')
c = c.replace('lines.append(f"| 澶ф埛澶氱┖姣?| {top_ratio:.2f} | {\'鍋忕┖\' if top_ratio<0.7 else \'鍋忓\' if top_ratio>1.3 else \'骞宠　\'} |")',
'lines.append(f"| 大户多空比 | {top_ratio:.2f} | {\'偏空\' if top_ratio<0.7 else \'偏多\' if top_ratio>1.3 else \'平衡\'} |")')
c = c.replace('s_emoji = "馃煝" if current_signal=="涔板叆" else ("馃敶" if current_signal=="鍗栧嚭" else "鈿?)',
's_emoji = "🟢" if current_signal=="买入" else ("🔴" if current_signal=="卖出" else "⚪")')
c = c.replace('lines.append(f"| 15m淇″彿 | {s_emoji} {current_signal} | 涔皗b_score:.1f}/鍗杮s_score:.1f} |")',
'lines.append(f"| 15m信号 | {s_emoji} {current_signal} | 买{b_score:.1f}/卖{s_score:.1f} |")')
c = c.replace('hold_advice = "鎸佹湁瑙傛湜锛笉鍔?', 'hold_advice = "持有观望，不动"')
c = c.replace('empty_advice = "瑙傛湜锛岀瓑鏄庣′淇″彿"', 'empty_advice = "观望，等明确信号"')
c = c.replace('lines.append(f"**缁撹**: {trend_judge}锛岃祫閲憑flow_judge}锛寋daily_judge}")',
'lines.append(f"**结论**: {trend_judge}，资金{flow_judge}，{daily_judge}")')
c = c.replace('lines.append(f"**鎸佷粨寤鸿**: {hold_advice}")', 'lines.append(f"**持仓建议**: {hold_advice}")')
c = c.replace('lines.append(f"**绌轰粨寤鸿**: {empty_advice}")', 'lines.append(f"**空仓建议**: {empty_advice}")')
c = c.replace('sync = "鍚屾涓婃定" if ind_s[\'day_chg\']*btc_chg>0 else "鑳岀"',
'sync = "同步上涨" if ind_s[\'day_chg\']*btc_chg>0 else "背离"')
c = c.replace('flow_judge = "鏄庢樉娴佸叆" if flow[\'net_inflow\']>1000 else ("鏄庢樉娴佸嚭" if flow[\'net_inflow\']<-1000 else "骞宠　")',
'flow_judge = "明显流入" if flow[\'net_inflow\']>1000 else ("明显流出" if flow[\'net_inflow\']<-1000 else "平衡")')
c = c.replace('daily_judge = "鏃ョ嚎鍚戜笂" if daily_up else "鏃ョ嚎鍚戜笅"',
'daily_judge = "日线向上" if daily_up else "日线向下"')
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("乱码全部改完")
