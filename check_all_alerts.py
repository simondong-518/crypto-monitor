"""报警自检（N10 起点 / P1-7）：逐条给出「命中 / 未命中 + 当前数值 + 距离命中还差多少」。

关键点：本脚本调用 **evaluate.py —— 与 main.py 完全同一个判定入口**。
  原来的版本自己算一套：只看"买分/卖分 ≥3.5"就打印 ✅买/✅卖，
  而 main.py 的**推送**根本不看分数（看的是涨跌幅 / 跌破MA20 / 信号反转 / 长上影 / 到价 / 移动止盈）。
  所以拿它去查"为什么没提醒"会得到**错误答案**。

只读：不推送、不写状态文件（ls 样本会记一笔，这是打分预热需要的）。

跑法：
    <python> check_all_alerts.py              # 全部监测币
    <python> check_all_alerts.py SUI_USDT     # 指定币
"""
import sys

from config import (ALERT_COOLDOWN_MIN, CHG_THRESHOLD, LS_HISTORY_FILE, LS_MIN_SAMPLES,
                    VOL_ENOUGH_MULT)
from evaluate import build_alerts, day_chg_verdict, evaluate_coin
from ls_percentile import LSPercentile


def show(pair, ls_state):
    try:
        res = evaluate_coin(pair, ls_state)
    except Exception as e:
        print(f"\n【{pair}】取数/评估失败：{type(e).__name__}: {e}")
        return
    ind_s, ind_l = res["ind_s"], res["ind_l"]
    coin, price = res["coin"], ind_s['price']
    thr = CHG_THRESHOLD.get(coin, CHG_THRESHOLD['default'])

    print(f"\n{'=' * 74}")
    print(f"【{coin}】现价 {price:.6g}（实时）"
          f"｜指标口径 = 已收盘 bar {ind_s['bar_time']} 收 {ind_s['close']:.6g}"
          f"（wc={ind_s['bar_closed']}）")
    print(f"  买分 {res['b_score']:.1f} / 卖分 {res['s_score']:.1f}　信号：{res['signal']}")

    vol_ok = ind_s['vol_ratio'] > VOL_ENOUGH_MULT
    fire, note = day_chg_verdict(ind_s['day_chg'], ind_s['trend_up'], vol_ok, thr)
    gap = max(thr - abs(ind_s['day_chg']), 0.0)
    print(f"  ① 涨跌幅　{ind_s['day_chg']:+.2f}%（阈值 {thr}%）"
          f"{'✅ 命中' if fire else f'❌ 不够（还差 {gap:.2f}%）'}"
          f"　量能 {ind_s['vol_ratio']:.2f}× 均量（门槛 {VOL_ENOUGH_MULT}×）"
          f"{'✅' if vol_ok else '❌'}")
    if note:
        print(f"      ↳ {note}")

    m20 = ind_s['ma20']
    print(f"  ② 跌破MA20　前收 {ind_s['prev_close']:.6g} "
          f"{'>' if ind_s['prev_close'] > m20 else '<='} MA20 {m20:.6g}"
          f"　现(已收盘) {ind_s['close']:.6g} {'<' if ind_s['close'] < m20 else '>='} MA20"
          f"　趋势{'向上' if ind_s['trend_up'] else '向下'}"
          f"　→ {'✅ 命中' if (ind_s['prev_close'] > m20 and ind_s['close'] < m20 and ind_s['trend_up']) else '❌ 未命中'}")

    print(f"  ③ RSI超买：15m {ind_s['rsi']:.1f} / 1h {ind_l['rsi']:.1f}"
          f"（>80 才算）{'✅' if (ind_s['rsi'] > 80 or ind_l['rsi'] > 80) else '❌'}")

    if res['ls_pct'] is None:
        print(f"  ④ 多空比分位　预热中 {res['ls_n']}/{LS_MIN_SAMPLES}"
              f"（样本不足不加分，account={res['ls_account']} size={res['ls_size']}）")
    else:
        print(f"  ④ 多空比分位　{res['ls_pct']:.0f}%（account={res['ls_account']} / "
              f"size={res['ls_size']}，n={res['ls_n']}）")

    fired = build_alerts(res)
    print(f"  → 当前会触发的报警：{len(fired)} 条"
          f"（同类报警冷却 {ALERT_COOLDOWN_MIN} 分钟；首次触发必报）")
    for _key, title, body in fired:
        print(f"     · {title}")
        for line in body.split("\n"):
            print(f"         {line}")
    if not fired:
        need_b = 3.5 - res['b_score']
        print(f"     （无）买分距离 3.5 还差 {need_b:.1f}，"
              f"卖分距离 3.5 还差 {3.5 - res['s_score']:.1f}")


def main(argv):
    from config import CURRENCY_PAIRS
    ls_state = LSPercentile(LS_HISTORY_FILE)
    pairs = argv[1:] or list(CURRENCY_PAIRS)
    print(f"报警自检：{len(pairs)} 个币种，判定入口 evaluate.py（与 main.py 同一套）")
    for pair in pairs:
        show(pair, ls_state)
    print(f"\n{'=' * 74}")
    print("提示：这里只做判定，不推送。真实推送由 main.py 的 run_alert 按冷却执行。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
