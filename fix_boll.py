with open("strategy.py", "r", encoding="utf-8") as f:
    c = f.read()
old = '''    # BOLL规则
    if close < ind_s['boll_l']*1.01:
        if ind_s['trend_up']:
            buy +=1.5
        else:
            buy -=1
    if close > ind_s['boll_u']*0.99:
        if not ind_s['trend_up']:
            sell -=0.5
        else:
            sell +=1.5'''
new = '''    # BOLL规则
    boll_width = (ind_s['boll_u'] - ind_s['boll_l']) / ind_s['boll_m']
    vol_now = df['vol'].iloc[-1]
    vol_avg = df['vol'].rolling(20).mean().iloc[-1]
    if close < ind_s['boll_l']*1.01:
        if ind_s['trend_up']:
            buy +=1.5
        else:
            buy -=1
    if close > ind_s['boll_u']*0.99:
        # 收口+放量突破上轨=启动上涨，加买分
        if boll_width < 0.03 and vol_now > vol_avg*1.5:
            buy +=1.5
        elif not ind_s['trend_up']:
            sell -=0.5
        else:
            sell +=1.5'''
c = c.replace(old, new)
# 去掉后面重复的BOLL收口降权
old2 = '''    # BOLL收口降权
    boll_width = (ind_s['boll_u'] - ind_s['boll_l']) / ind_s['boll_m']
    if boll_width < 0.03:
        buy -=1
        sell -=1'''
new2 = '''    # BOLL收口如果没突破，降权
    if boll_width < 0.03 and close < ind_s['boll_u']*0.99:
        buy -=1
        sell -=1'''
c = c.replace(old2, new2)
with open("strategy.py", "w", encoding="utf-8") as f:
    f.write(c)
print("改完了")
