with open("strategy.py", "r", encoding="utf-8") as f:
    c = f.read()
old = '''    # BOLL规则
    if close <= ind_s['boll_l']*1.005:
        if ind_s['trend_up']:
            # 上涨碰下轨：4h向上加1.5，4h向下加0.75
            if ind_l['trend_up']:
                buy += 1.5
            else:
                buy += 0.75
        else:
            # 下跌碰下轨：不买不卖
            pass
    if close >= ind_s['boll_u']*0.995:
        if not ind_s['trend_up']:
            sell += 1.5
        else:
            # 上涨碰上轨：连续上影才加卖分
            row1 = df.iloc[-1]
            row2 = df.iloc[-2]
            body1 = abs(row1['close'] - row1['open'])
            upper1 = row1['high'] - max(row1['open'], row1['close'])
            body2 = abs(row2['close'] - row2['open'])
            upper2 = row2['high'] - max(row2['open'], row2['close'])
            two_upper = upper1 > body1*2 and upper2 > body2*2
            if two_upper:
                sell += 1.5'''
new = '''    # BOLL规则
    boll_width = (ind_s['boll_u'] - ind_s['boll_l']) / ind_s['boll_m']
    vol_now = df['vol'].iloc[-1]
    vol_avg = df['vol'].rolling(20).mean().iloc[-1]
    if close <= ind_s['boll_l']*1.005:
        if ind_s['trend_up']:
            # 上涨碰下轨：4h向上加1.5，4h向下加0.75
            if ind_l['trend_up']:
                buy += 1.5
            else:
                buy += 0.75
        else:
            # 下跌碰下轨：不买不卖
            pass
    if close >= ind_s['boll_u']*0.995:
        # 收口+放量突破上轨=启动上涨，加买分
        if boll_width < 0.03 and vol_now > vol_avg*1.5:
            buy +=1.5
        elif not ind_s['trend_up']:
            sell += 1.5
        else:
            # 上涨碰上轨：连续上影才加卖分
            row1 = df.iloc[-1]
            row2 = df.iloc[-2]
            body1 = abs(row1['close'] - row1['open'])
            upper1 = row1['high'] - max(row1['open'], row1['close'])
            body2 = abs(row2['close'] - row2['open'])
            upper2 = row2['high'] - max(row2['open'], row2['close'])
            two_upper = upper1 > body1*2 and upper2 > body2*2
            if two_upper:
                sell += 1.5'''
c = c.replace(old, new)
# 去掉后面重复的boll_width
old2 = '''    # BOLL收口如果没突破，降权
    if boll_width < 0.03 and close < ind_s['boll_u']*0.99:
        buy -=1
        sell -=1'''
new2 = '''    # BOLL收口如果没突破，降权
    if boll_width < 0.03 and close < ind_s['boll_u']*0.99:
        buy -=1
        sell -=1'''
c = c.replace(old2, new2)
with open("strategy.py", "w", encoding="utf-8") as f:
    f.write(c)
print("修好了")
