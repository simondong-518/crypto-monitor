# -*- coding: utf-8 -*-
"""报告渲染层。

架构分离自 main.py（纯搬运，逻辑一字未改）：把某个币的
"全方位分析" 表格 + 持仓/空仓建议 渲染成 markdown 行。
"""
from config import *
from signals import _is_report_signal  # noqa: F401  (保持与原上下文一致)

def render(rep):
    """rep: signals.evaluate_coin() 返回的上下文 dict → 报告行 list"""
    out = []
    coin = rep['coin']
    alerts = rep['alerts']
    big_flow_1h = rep['big_flow_1h']
    btc_chg = rep['btc_chg']
    buy_taker = rep['buy_taker']
    current_signal = rep['current_signal']
    daily_up = rep['daily_up']
    df_s = rep['df_s']
    drawdown_high = rep['drawdown_high']
    eff_high = rep['eff_high']
    eff_low = rep['eff_low']
    flow = rep['flow']
    flow_1h = rep['flow_1h']
    flow_1h_val = rep['flow_1h_val']
    fmt_money = rep['fmt_money']
    ind_l = rep['ind_l']
    ind_s = rep['ind_s']
    lsd = rep['lsd']
    recent_flow_15 = rep['recent_flow_15']
    rise_low = rep['rise_low']
    sell_taker = rep['sell_taker']
    today_high = rep['today_high']
    today_low = rep['today_low']
    top_ratio = rep['top_ratio']
    trail_thr = rep['trail_thr']
    upper_count = rep['upper_count']
    out.append(f"## {coin}/USDT 全方位分析:")
    out.append("")
    out.append(f"- **现价**: ${ind_s['close']:.4f}，今日 {ind_s['day_chg']:+.2f}%")
    out.append(f"- **当日高低点**: 低{today_low:.4f} / 高{today_high:.4f}")
    out.append(f"- **当前位置**: 从低点反弹{rise_low:.1f}% / 从高点回撤{drawdown_high:.1f}%")
    # 2026-10-07 新增：展示最近30分钟变盘点位置，和信号触发口径一致
    low_30m = df_s['low'].tail(3).min()
    high_30m = df_s['high'].tail(3).max()
    rise_30m = (ind_s['close'] - low_30m)/low_30m*100
    drawdown_30m = (high_30m - ind_s['close'])/high_30m*100
    out.append(f"- **变盘位置**: 从最近30分钟低点反弹{rise_30m:.1f}% / 从最近30分钟高点回撤{drawdown_30m:.1f}%")
    out.append(f"- **移动止盈**: 阈值{trail_thr:.1f}%，还差{trail_thr - drawdown_high:.1f}%触发")
    trend_emoji = "🟢" if ind_s['trend_up'] else "🔴"
    trend_text = "上涨" if ind_s['trend_up'] else "下跌"
    trend_judge = "15分钟站上EMA20" if ind_s['trend_up'] else "15分钟跌破EMA20"  # 2026-10-05 改显示为EMA20，和实际指标一致
    out.append(f"- **趋势**: {trend_emoji} {trend_text}（{trend_judge}）")
    out.append(f"- **RSI**: 15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f}（中性）")
    space_up = (ind_s['boll_u'] - ind_s['close'])/ind_s['close']*100
    out.append(f"- **BOLL上轨**: {ind_s['boll_u']:.4f}，还有{space_up:.1f}%空间")
    net_flow = flow['net_inflow']
    if net_flow >=0:
        flow_text = f"净流入{fmt_money(net_flow)}"
    else:
        flow_text = f"净流出{fmt_money(-net_flow)}"
    flow_judge = "主力在进" if net_flow>1000 else "主力在跑" if net_flow<-1000 else "平衡"
    out.append(f"- **现货资金(瞬时)**: {flow_text}（{flow_judge}）")
    if flow_1h_val >=0:
        flow1h_text = f"净流入{fmt_money(flow_1h_val)}"
    else:
        flow1h_text = f"净流出{fmt_money(-flow_1h_val)}"
    flow1h_judge = "1小时主力大幅进" if flow_1h_val>10000 else "1小时主力大幅跑" if flow_1h_val<-10000 else "1小时平衡"
    out.append(f"- **现货资金(1h累计)**: {flow1h_text}（{flow1h_judge}）")
    ls_acc_judge = "大户偏空" if top_ratio<0.9 else "大户偏多" if top_ratio>1.1 else "平衡"
    out.append(f"- **大户持仓多空比**: {top_ratio:.2f}（{ls_acc_judge}）")
    ls_size_ratio = float(lsd.get('top_lsr_size', 1.0))
    ls_size_judge = "明显偏空" if ls_size_ratio<0.5 else "明显偏多" if ls_size_ratio>2 else "平衡"
    out.append(f"- **大户账户多空比**: {ls_size_ratio:.2f}（{ls_size_judge}）")
    taker_ratio = buy_taker/max(sell_taker,1)
    taker_judge = "散户疯狂主动买，追高" if taker_ratio>1.5 else "散户恐慌卖" if taker_ratio<0.7 else "平衡"
    out.append(f"- **Taker主动买卖比**: {taker_ratio:.2f}（{taker_judge}）")
    out.append(f"- **资金费率**: 未接入（暂无数据源，请勿参考）")
    upper_judge = "还在拉，没抛压" if upper_count<2 else "上方抛压重"
    out.append(f"- **连续上影线**: {upper_count}根（{upper_judge}）")
    daily_text = "🟢" if daily_up else "🔴"
    daily_judge = "日线向上" if daily_up else "日线向下"
    out.append(f"- **日线趋势**: {daily_text} {daily_judge}")
    # 2026-10-05 21:00 修复：分析BTC自身时不判断联动，直接显示自身走势
    if 'BTC' in coin:
        sync_text = "自身走势"
    else:
        sync_text = "和BTC同步" if ind_s['day_chg']*btc_chg>0 else "和BTC背离"
    out.append(f"- **BTC联动**: BTC{btc_chg:+.2f}%（{sync_text}）")
    # 加关键支撑压力位
    out.append(f"- **关键价位**: 下方支撑{today_low:.4f}，上方压力{today_high:.4f}")
    # 止损止盈
    stop_loss = ind_s['boll_l']
    take_profit = ind_s['boll_u']
    daily_judge = "日线向上" if daily_up else "日线向下"
    if current_signal == "探底反弹":
        # if daily_up 是判断日线趋势的
        if daily_up:
            pos = "3成重仓"
        else:
            pos = "1成轻仓"
        hold_advice = f"可以买入{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"
        empty_advice = f"可以建仓{pos}，止损{stop_loss:.4f}，止盈{take_profit:.4f}"
    elif current_signal == "碰BOLL上轨":
        hold_advice = "可以持有"
        empty_advice = "别买，等回调"
    else:
        # 综合所有策略维度判断建议，直接给最终唯一结论
        sell_score = 0
        buy_score = 0
        # 最高权重：触止盈线
        if any('止盈' in a for a in alerts):
            sell_score += 10
        # 次高权重：主力大幅进/出
        if any('主力大幅出' in a or '主力大幅跑路' in a for a in alerts):
            sell_score += 8
        if any('主力大幅进' in a or '主力大幅进场' in a for a in alerts):
            buy_score += 8
        # 中等权重：大户极端/BOLL破轨，分位置反向判断
        dist_high = abs(ind_s['close'] - eff_high)/eff_high*100
        dist_low = abs(ind_s['close'] - eff_low)/eff_low*100
        # 大户极空<0.5：低位就是轧空看涨，高位才是真看跌
        if any('大户极空' in a for a in alerts):
            if dist_low < 2:
                buy_score += 5
            else:
                sell_score += 5
        # 大户极多>2：高位就是多头挤兑看跌，低位才是真看涨
        if any('大户极多' in a for a in alerts):
            if dist_high < 2:
                sell_score += 5
            else:
                buy_score += 5
        if any('超卖下轨' in a for a in alerts):
            buy_score += 5
        if dist_high < 1:
            sell_score += 3
        if dist_low < 1:
            buy_score += 3
        # RSI辅助
        if ind_s['rsi'] < 20 and any('急跌V反' in a for a in alerts):
            buy_score += 2
        if ind_s['rsi'] > 80 and any('连续上影' in a for a in alerts):
            sell_score += 2
        # 低权重信号
        if any('连续上影' in a for a in alerts):
            sell_score += 2
        if any('急跌V反' in a for a in alerts):
            buy_score += 2
        # 直接给最终唯一结论（2026-10-05 20:45 修正：资金判断用分档阈值，和信号触发一致）
        final_score = 0
        # 偏多加分项
        if daily_up:
            final_score +=1
        if flow_1h >= big_flow_1h:
            final_score +=1
        if recent_flow_15 > 0:
            final_score +=1
        if ind_s.get('kdj_j',50) < 20:
            final_score +=1
        if ind_s['close'] > ind_s.get('boll_m', ind_s['close']):
            final_score +=1
        # 偏空减分项
        if ind_s['close'] < ind_s.get('ema20', ind_s['close']):
            final_score -=1
        if flow_1h <= -big_flow_1h:
            final_score -=1
        if recent_flow_15 < 0:
            final_score -=1
        if ind_s.get('kdj_j',50) > 80:
            final_score -=1
        if upper_count >=2:
            final_score -=1
        # 按分数给明确建议
        if final_score >=2:
            hold_advice = "🟢 持有，可逢低加仓"
            empty_advice = "🟢 低吸机会，可小仓建仓"
        elif final_score <=-2:
            hold_advice = "🔴 逢高减仓，注意回调"
            empty_advice = "🔴 别接盘，等企稳再看"
        else:
            hold_advice = "🟡 持有观望，不动"
            empty_advice = "🟡 观望，等明确信号"
    out.append("")
    out.append(f"**📌 结论**: {trend_judge}，资金{flow_judge}，{daily_judge}")
    out.append(f"**💼 持仓建议**: {hold_advice}")
    out.append(f"**👀 空仓建议**: {empty_advice}")
    out.append("")
    return out
