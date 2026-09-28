import sys
sys.path.insert(0, 'crypto_monitor')
from api import get_kline, get_trades, get_ls
from indicators import get_indicator, get_daily_trend
from strategy import calc_score
from config import CURRENCY_PAIRS, CHG_THRESHOLD, BUY_SCORE_THRESHOLD, SELL_SCORE_THRESHOLD

for pair in CURRENCY_PAIRS:
    coin = pair.replace("_USDT","")
    thr = CHG_THRESHOLD.get(coin, CHG_THRESHOLD['default'])
    try:
        ind_s = get_indicator(pair, "15m")
        ind_l = get_indicator(pair, "1h")
        daily_up = get_daily_trend(pair)
        trades = get_trades(pair)
        buy_v = sell_v = 0
        for t in trades:
            v = float(t['amount']) * float(t['price'])
            if t['side'] == 'buy': buy_v += v
            else: sell_v += v
        flow = {'net_inflow': buy_v - sell_v}
        try:
            ls_ratio = float(get_ls(pair)[-1]['top_lsr_account'])
        except:
            ls_ratio = 1
        b, s = calc_score(ind_s, ind_l, flow, ls_ratio, ind_s['df'])
        if not daily_up:
            b -= 1.5
        # 4h趋势过滤
        ind_4h = get_indicator(pair, "4h")
        if not ind_4h['trend_up']:
            b -= 1
        avg_vol = ind_s['df']['vol'].rolling(20).mean().iloc[-1]
        cur_vol = ind_s['df']['vol'].iloc[-1]
        vol_enough = cur_vol > avg_vol*1.2
        chg_enough = abs(ind_s['day_chg']) >= thr
        buy_alert = b >= BUY_SCORE_THRESHOLD
        sell_alert = s >= SELL_SCORE_THRESHOLD
        print(f"\n【{coin}】现价{ind_s['close']:.4f}")
        print(f"  今日涨幅{ind_s['day_chg']:+.2f}% (阈值{thr}%): {'✅够' if chg_enough else '❌不够'}")
        print(f"  成交量: {'✅够(>1.2倍)' if vol_enough else '❌不够(缩量)'}")
        print(f"  买分{b:.1f}/卖分{s:.1f} (阈值3.5): {'✅买' if buy_alert else ''} {'✅卖' if sell_alert else ''} {'❌无信号' if not buy_alert and not sell_alert else ''}")
    except Exception as e:
        print(f"\n【{coin}】出错: {e}")
