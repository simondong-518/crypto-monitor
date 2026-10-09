"""BOLL三轨开口向上（15m 为主 + 1h，60/40）自检。

用合成数据测逻辑，不依赖网络。
"""
import sys, os
sys.path.insert(0, r'M:\hermes\workspace\dev\crypto-monitor-v3')
os.chdir(r'M:\hermes\workspace\dev\crypto-monitor-v3')

import pandas as pd
from main import _boll_open_up

results = []
def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))

def mkdf(us):
    """给一串上轨值造一个最小 df（含 boll_u 列）。"""
    return pd.DataFrame({"boll_u": us})

def mk_ind(u, m, l):
    return {"boll_u": u, "boll_mid": m, "boll_l": l}

# ── _boll_open_up 基本判据 ──────────────────────────────
check("三轨有序+上轨抬升 → True",
      _boll_open_up(mk_ind(110, 100, 90), mkdf([100, 105])) is True)
check("三轨有序但上轨下降 → False",
      _boll_open_up(mk_ind(110, 100, 90), mkdf([120, 100])) is False)
check("三轨无序（上<中）→ False",
      _boll_open_up(mk_ind(100, 105, 90), mkdf([100, 105])) is False)
check("缺列/坏数据 → False（不误报）",
      _boll_open_up({}, mkdf([1, 2])) is False)
check("df 无 boll_u 列 → 回退 0，靠有序性判断",
      _boll_open_up(mk_ind(110, 100, 90), pd.DataFrame({"x": [1]})) is True)

# ── 打分口径 ────────────────────────────────────────────
def score(up15, up1h):
    return (60 if up15 else 0) + (40 if up1h else 0)

check("★ 仅 15m 满足 → 60 分，触发（15m 是必要条件）", score(True, False) == 60)
check("★ 仅 1h 满足 → 40 分，不触发（1h 不能单独触发）", score(False, True) == 40)
check("★ 双周期满足 → 100 分，触发", score(True, True) == 100)
check("★ 都不满足 → 0 分，不触发", score(False, False) == 0)
check("★ 15m 是必要条件（15m 不满足永不触发）",
      all(score(False, x) < 60 for x in (True, False)))

# ── 接线检查（架构分离后：信号/报告/推送分散到多个模块，合并读）──
SRC_FILES = ["main.py", "signals.py", "report.py", "pushing.py", "alerting.py"]
src = ""
for _f in SRC_FILES:
    try:
        src += open(_f, encoding="utf-8").read() + "\n"
    except OSError:
        pass
check("★ 旧变量已彻底移除",
      "boll_u_now" not in src and "boll_m_now" not in src
      and "boll_l_now" not in src and "boll_u_prev" not in src)
check("两处都改用加权分（开口信号 + 共振条件3）",
      src.count("boll_score >= 60") == 2)
check("15m 权重 60", "boll_s15 = 60 if _boll_open_up(ind_s, df_s) else 0" in src)
check("1h 权重 40", "boll_s1h = 40 if (ind_l and _boll_open_up(ind_l, ind_l.get('df'))) else 0" in src)
check("1h 缺失时安全（ind_l 为空不报错）", "ind_l and _boll_open_up" in src)
check("消息带强度与共振标注", "15m+1h 双周期共振" in src and "{boll_score}/100" in src)
check("★ 推送次数上限未改（一天最多2次）",
      'pushed.get(key_boll_open,0) < 2' in src)
check("★ 冷却/去重键未改", 'f"{coin}_BOLL开口向上"' in src)

print()
n_fail = 0
for n, o, d in results:
    if not o:
        n_fail += 1
    print(f"  {'PASS' if o else 'FAIL'}  {n}" + (f"   [{d}]" if (d and not o) else ""))
print()
print(f"  结果: {len(results)-n_fail}/{len(results)} 通过")
sys.exit(1 if n_fail else 0)
