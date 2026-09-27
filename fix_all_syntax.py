with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
# 修第52行
c = c.replace('send_wx(f"鉁?{coin}鍒版鐩堜环锛?, f"鐜颁环{price}锛屽埌浣犺缃殑姝㈢泩浠穥take_profit}锛屽彲浠ュ崠鍑烘鐩堜簡")',
'send_wx(f"✅ {coin}到止盈价！", f"现价{price}，到你设置的止盈价{take_profit}，可以卖出止盈了")')
# 修第56行
c = c.replace('send_wx(f"鈿狅笍 {coin}鍒版鎹熶环锛?, f"鐜颁环{price}锛屽埌浣犺缃殑姝㈡崯浠穥stop_loss}锛屾敞鎰忛闄?)',
'send_wx(f"⚠️ {coin}到止损价！", f"现价{price}，到你设置的止损价{stop_loss}，注意风险")')
# 修第60行
c = c.replace('lines = ["# 馃搳 K绾跨洃娴嬫姤鍛?, f"鏃堕棿锛歿datetime.now().strftime(\'%Y-%m-%d %H:%M\')}", ""]',
'lines = ["# 📈 K线监测报告", f"时间：{datetime.now().strftime(\'%Y-%m-%d %H:%M\')}", ""]')
# 修第98行
c = c.replace('alerts.append("鈿狅笍 璺岀牬MA20锛屾鐩堣惤琚?)',
'alerts.append("⚠️ 跌破MA20，止盈落袋")')
# 修第109行
c = c.replace('alerts.append("RSI鏋佸害瓒呬拱+杩炵画闀夸笂褰?)',
'alerts.append("RSI极度超买+连续长上影")')
# 修第124行
c = c.replace('trend_judge = "澶ц秼鍔垮悜涓? if ind_s[\'trend_up\'] else "澶ц秼鍔垮悜涓?',
'trend_judge = "大趋势向上" if ind_s[\'trend_up\'] else "大趋势向下"')
# 修第127行
c = c.replace('lines.append(f"| 鏀敮/鍘嬪姏 | 鏀敮{ind_s[\'boll_l\']:.4f} / 鍘嬪姏{ind_s[\'boll_u\']:.4f} | 绂诲帇鍔泏space:.1f}% |")',
'lines.append(f"| 支撑/压力 | 支撑{ind_s[\'boll_l\']:.4f} / 压力{ind_s[\'boll_u\']:.4f} | 离压力{space:.1f}% |")')
# 修第131行
c = c.replace('else: rsi_judge.append("15m涓€?)',
'else: rsi_judge.append("15m中性")')
# 修第134行
c = c.replace('else: rsi_judge.append("1h涓€?)',
'else: rsi_judge.append("1h中性")')
# 修第142行
c = c.replace('s_emoji = "馃煝" if current_signal=="涔板叆" else ("馃敶" if current_signal=="鍗栧嚭" else "鈿?)',
's_emoji = "🟢" if current_signal=="买入" else ("🔴" if current_signal=="卖出" else "⚪")')
# 修第143行
c = c.replace('lines.append(f"| 15m淇″彿 | {s_emoji} {current_signal} | 涔皗b_score:.1f}/鍗杮s_score:.1f} |")',
'lines.append(f"| 15m信号 | {s_emoji} {current_signal} | 买{b_score:.1f}/卖{s_score:.1f} |")')
# 修第160行
c = c.replace('hold_advice = "鎸佹湁瑙傛湜锛笉鍔?',
'hold_advice = "持有观望，不动"')
# 修第163行
c = c.replace('lines.append(f"**缁撹**: {trend_judge}锛岃祫閲憑flow_judge}锛寋daily_judge}")',
'lines.append(f"**结论**: {trend_judge}，资金{flow_judge}，{daily_judge}")')
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("修完语法错误了")
