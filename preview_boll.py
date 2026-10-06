"""BOLL三轨开口向上：新旧口径对照预览（真实数据）。

用法:  python preview_boll.py
"""
import sys, os, time
sys.path.insert(0, r'M:\hermes\workspace\dev\crypto-monitor-v3')
os.chdir(r'M:\hermes\workspace\dev\crypto-monitor-v3')

import config, api
from indicators import get_indicator
from main import _boll_open_up

PAIRS = list(config.CURRENCY_PAIRS)
print(f"  币种: {PAIRS}\n")

hdr = f"  {'币':<6} {'15m开口':<9} {'1h开口':<9} {'得分':<6} {'触发':<6} {'旧口径(仅15m)':<14} 说明"
print(hdr)
print("  " + "─" * (len(hdr) + 4))

rows = []
for pair in PAIRS:
    coin = pair.split('_')[0] if '_' in pair else pair
    try:
        ind_s = get_indicator(pair, "15m")
        ind_l = get_indicator(pair, "1h")
        df_s = ind_s['df']
        up15 = _boll_open_up(ind_s, df_s)
        up1h = _boll_open_up(ind_l, ind_l.get('df'))
        s15 = 60 if up15 else 0
        s1h = 40 if up1h else 0
        score = s15 + s1h
        fire = score >= 60
        old = up15   # 旧口径 = 仅看 15m
        if score >= 100:
            note = "15m+1h 共振（强度100）"
        elif fire:
            note = "15m 为主（1h 未确认）"
        elif up1h:
            note = "仅 1h 开口 → 不触发（15m 为主）"
        else:
            note = "两周期都没开口"
        rows.append((coin, up15, up1h, score, fire, old, note))
        print(f"  {coin:<6} {'✅' if up15 else '—':<9} {'✅' if up1h else '—':<9} "
              f"{score:<6} {'🔔' if fire else '—':<6} {'🔔' if old else '—':<14} {note}")
    except Exception as e:
        print(f"  {coin:<6} 取数失败: {type(e).__name__}: {e}")
    time.sleep(0.4)

print()
fired = [r for r in rows if r[4]]
reson = [r for r in rows if r[3] >= 100]
changed = [r for r in rows if r[4] != r[5]]
print(f"  合计: {len(rows)} 币")
print(f"  新口径触发: {len(fired)} 币" + (f"  ({', '.join(r[0] for r in fired)})" if fired else ""))
print(f"  其中 15m+1h 共振(100分): {len(reson)} 币" + (f"  ({', '.join(r[0] for r in reson)})" if reson else ""))
print(f"  与旧口径相比改变结果的: {len(changed)} 币" +
      (f"  ({', '.join(r[0] for r in changed)})" if changed else "  （本次无差异）"))
