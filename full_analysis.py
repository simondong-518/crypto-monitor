"""全方位分析（单币展示）。数值与判定全部来自 evaluate.py —— 与 main.py 同一套口径。

修掉的历史问题：
  · 两个多空比标签**正好对调**：印在「大户持仓多空比」上的是 account 口径，
    印在「大户账户多空比」上的是 size 口径。现在名称与字段一一对应。
  · `| 资金费率 | 0.01% | 正常 |` 是**硬编码假数据**，跟当前行情毫无关系 —— 删掉。
    api.py 目前没有资金费率接口；要显示就得先接接口，不接就不显示假数。
  · 形态统计原来用 range(-3, 0)，把形成中的 bar 也算进去了（P1-1）→ 改用已收盘 bar。

跑法：<python> full_analysis.py [SUI_USDT]
"""
import sys

from api import get_btc_chg, get_trades
from config import CHG_THRESHOLD
from evaluate import evaluate_coin


def taker_ratio(trades):
    b = s = 0
    if isinstance(trades, list):
        for t in trades:
            if t.get('side') == 'buy':
                b += 1
            else:
                s += 1
    return b / max(s, 1)


def main(argv):
    pair = argv[1] if len(argv) > 1 else "SUI_USDT"
    res = evaluate_coin(pair, None)          # 不传 ls_state：本脚本只看数，不记样本
    ind_s, ind_l, flow = res["ind_s"], res["ind_l"], res["flow"]
    coin, price = res["coin"], ind_s['price']
    btc_chg = get_btc_chg()
    thr = CHG_THRESHOLD.get(coin, CHG_THRESHOLD['default'])

    rsi_s, rsi_l = ind_s['rsi'], ind_l['rsi']
    if rsi_s > 80 and rsi_l > 70:
        rsi_judge = "双周期极度超买"
    elif rsi_s < 30 and rsi_l < 30:
        rsi_judge = "双周期极度超卖"
    elif rsi_s > 70:
        rsi_judge = "15m超买"
    elif rsi_s < 30:
        rsi_judge = "15m超卖"
    else:
        rsi_judge = "中性"

    df = ind_s['df']
    count_two_upper = 0
    for i in range(-4, -1):                  # 最近 3 根**已收盘** bar
        row = df.iloc[i]
        body = abs(row['close'] - row['open'])
        upper = row['high'] - max(row['open'], row['close'])
        if upper > body * 2:
            count_two_upper += 1

    tr = taker_ratio(get_trades(pair))
    space = (ind_s['boll_u'] - price) / price * 100
    flow_judge = "主力在跑" if flow['net_inflow'] < -5000 else ("主力在进" if flow['net_inflow'] > 5000 else "平衡")
    ls_acc_judge = "大户偏空" if (res['ls_account'] or 1) < 0.9 else ("大户偏多" if (res['ls_account'] or 0) > 1.1 else "多空平衡")
    ls_size_judge = ("明显偏空" if (res['ls_size'] or 1) < 0.5
                     else "明显偏多" if (res['ls_size'] or 0) > 2 else "平衡")
    taker_judge = "散户疯狂主动买，追高" if tr > 1.5 else ("散户恐慌卖" if tr < 0.7 else "平衡")

    print(f"## {coin}/USDT 全方位分析")
    print(f"（口径：指标=已收盘 bar {ind_s['bar_time']}，价格=实时）")
    print("| 维度 | 数值 | 判断 |")
    print("|------|------|------|")
    print(f"| 现价 | ${price:.4f} | 从0点{ind_s['day_chg']:+.2f}%（报阈值{thr}%） |")
    print(f"| 趋势 | {'🟢' if ind_s['trend_up'] else '🔴'} "
          f"{'上涨' if ind_s['trend_up'] else '下跌'} | "
          f"{'站上MA20' if ind_s['trend_up'] else '跌破MA20'}（MA20 {ind_s['ma20']:.4g}） |")
    print(f"| RSI | 15m {rsi_s:.1f} / 1h {rsi_l:.1f} | {rsi_judge} |")
    print(f"| BOLL | 上轨{ind_s['boll_u']:.4f} | 还有{space:.1f}%空间 |")
    print(f"| 现货资金 | 净流出${flow['net_inflow']:.0f} | {flow_judge} |")
    print(f"| 大户持仓多空比 | {res['ls_size'] if res['ls_size'] is not None else '—'} | {ls_size_judge} |")
    print(f"| 大户账户多空比 | {res['ls_account'] if res['ls_account'] is not None else '—'} | {ls_acc_judge} |")
    print(f"| taker主动买卖比 | {tr:.2f} | {taker_judge} |")
    print(f"| 连续上影线 | {count_two_upper}根 | {'在拉，没抛压' if count_two_upper < 2 else '上方抛压重'} |")
    print(f"| 日线趋势 | {'🟢' if res['daily_up'] else '🔴'} | {'日线向上' if res['daily_up'] else '日线向下'} |")
    print(f"| BTC联动 | BTC今日{btc_chg:+.2f}% | "
          f"{'和BTC同步' if ind_s['day_chg'] * btc_chg > 0 else '和BTC背离'} |")
    print(f"| 4h趋势 | {'🟢' if res['ind_4h']['trend_up'] else '🔴'} | "
          f"{'向上' if res['ind_4h']['trend_up'] else '向下'} |")
    print(f"| 买分/卖分 | {res['b_score']:.1f} / {res['s_score']:.1f} | 信号：{res['signal']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
