# -*- coding: utf-8 -*-
"""架构分离 · 等价性金标准验证（replay harness）

做法：把"取数层"整体替换成**确定性合成数据**（固定种子 + 每轮推进），
然后跑真实的 monitor_once()，把所有 send_wx 调用 + 全部打印抓下来，
存成 JSON 金标准。重构后再跑一次，逐字节对比。

只要两次输出完全一致，就证明"架构分离"是纯搬运、零行为变化。

用法：
    python verify_refactor.py --dump  golden.json
    python verify_refactor.py --diff  golden.json
"""
import sys
import os
import io
import json
import random
import tempfile
import traceback

ROUNDS = int(os.environ.get("VR_ROUNDS", "4"))
SEED = int(os.environ.get("VR_SEED", "20261009"))

# ── 必须在导入 main 之前把 cwd 换到干净目录（pushed.json / alert_state.json 隔离）──
_TMP = tempfile.mkdtemp(prefix="vr_")
os.chdir(_TMP)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pandas as pd  # noqa: E402

_round = 0
_calls = []          # send_wx 记录


def _h(*parts):
    """跨进程稳定的哈希（Python 的 str hash 每个进程都会变，不能用）"""
    import hashlib
    s = "|".join(str(x) for x in parts)
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def make_kline(pair, interval, rnd):
    """确定性合成 OHLCV。列序：t, volume, close, high, low, open, amount, is_contract"""
    rng = random.Random(_h((SEED, pair, interval, rnd)) & 0x7FFFFFFF)
    n = 160
    step = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(interval, 900)
    t0 = 1750000000 - n * step
    px = 1.0 + (_h(pair) % 400) / 100.0
    rows = []
    for i in range(n):
        # 用 rnd 影响整体漂移方向，让不同轮次出现不同信号
        drift = rng.uniform(-0.018, 0.018) + (0.004 if (i % 20) < 10 else -0.004)
        px = max(0.0001, px * (1 + drift))
        o = px * (1 + rng.uniform(-0.004, 0.004))
        c = px
        h = max(o, c) * (1 + rng.uniform(0, 0.012))
        l = min(o, c) * (1 - rng.uniform(0, 0.012))
        v = rng.uniform(5_000, 300_000)
        rows.append([t0 + i * step, v, c, h, l, o, v * c, 0])
    return rows


def make_trades(pair, rnd):
    rng = random.Random(_h((SEED, "tr", pair, rnd)) & 0x7FFFFFFF)
    out = []
    for _ in range(60):
        side = "buy" if rng.random() < 0.5 else "sell"
        out.append({"amount": str(rng.uniform(1, 500)),
                    "price": str(rng.uniform(1, 200)),
                    "side": side})
    return out


def make_ls(pair, rnd):
    rng = random.Random(_h((SEED, "ls", pair, rnd)) & 0x7FFFFFFF)
    # 故意制造极端值，触发大户多空比信号
    ratio = rng.choice([0.4, 0.8, 1.0, 1.3, 2.2, 3.0])
    return [{"top_lsr_account": ratio, "top_lsr_size": ratio * rng.uniform(0.5, 1.6)}]


def make_flow_1h(pair, rnd):
    rng = random.Random(_h((SEED, "f1", pair, rnd)) & 0x7FFFFFFF)
    # 大范围摆动，跨越 big_flow 阈值
    return rng.choice([-600_000, -180_000, -60_000, -8_000, 0,
                       8_000, 60_000, 180_000, 600_000])


def make_btc_chg(rnd):
    rng = random.Random(_h((SEED, "btc", rnd)) & 0x7FFFFFFF)
    return rng.choice([-4.0, -1.6, -0.4, 0.3, 1.2, 3.5])


def install_stubs():
    # ── 关键：必须在 import main **之前**，在「源头模块」上打桩 ──────────────
    # 各模块都是 `from api import get_kline` / `from notifier import send_wx`
    # （导入那一刻就把函数对象绑到自己命名空间里）。架构分离后，取数与发送的
    # 调用点搬进了 signals.py / pushing.py，只在 main 上打补丁拦不住 ——
    # 会真的去 Gate.io 拉数据、真的往飞书群 POST（push_switch 当前是开着的）。
    import api
    import news
    import notifier
    import push_switch

    api.get_kline = lambda pair, interval='15m', limit=100: make_kline(pair, interval, _round)
    api.get_trades = lambda pair, limit=100: make_trades(pair, _round)
    api.get_ls = lambda pair: make_ls(pair, _round)
    api.get_flow_1h = lambda pair: make_flow_1h(pair, _round)
    api.get_btc_chg = lambda: make_btc_chg(_round)
    api.check_events = lambda: None
    news.get_latest_news = lambda: ([f"合成新闻{r}" for r in range(3)],
                                    [f"合成宏观{r}" for r in range(2)])

    def _send(title, desp=""):
        _calls.append([title, desp])
    notifier.send_wx = _send
    push_switch.is_enabled = lambda: False       # 双保险：绝不允许真发

    # 硬保险：任何漏网的真实网络调用直接炸掉，绝不静默打网络
    import requests
    def _no_net(*a, **k):
        raise RuntimeError("harness: 真实网络调用被拦截")
    requests.get = _no_net
    requests.post = _no_net

    import main
    import indicators
    indicators.get_kline = api.get_kline         # 双保险（它也是 from api import）
    main.send_wx = _send

    main.last_backtest_result = "合成回测：6币 45%~52%"

    # 小信号开关：只在内存里打开（它写的是仓库目录下的绝对路径文件，
    # 不能碰 —— 会影响到正在跑的线上服务）。VR_SMALL=1 时打开该分支。
    import small_signal_switch
    small_signal_switch.is_enabled = (lambda: True) if os.environ.get("VR_SMALL") == "1"         else (lambda: False)
    # 冻结时钟：报告标题与表头里带 datetime.now()，不冻就没法逐字节比对
    import datetime as _d
    _frozen = _d.datetime(2026, 10, 9, 12, 0, 0)

    class _DT(object):
        @staticmethod
        def now(tz=None):
            return _frozen

    for _name in ("main", "signals", "report", "pushing", "alerting"):
        try:
            _m = __import__(_name)
        except Exception:
            continue
        if getattr(_m, "datetime", None) is not None:
            _m.datetime = _DT
    return main


def run():
    """跑 N 轮 monitor_once，抓 send_wx + 全部打印。

    注意：main.py 导入时已把 sys.stdout 换成它自己的 TextIOWrapper，
    这里必须保存并还原**那个对象**（不能用 sys.__stdout__ —— 一旦原 wrapper
    被 GC 会连带关掉真正的 stdout buffer）。"""
    global _round
    main = install_stubs()
    _calls.clear()
    buf = io.StringIO()
    err = io.StringIO()
    prev_out, prev_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = buf, err
    try:
        for r in range(ROUNDS):
            _round = r
            try:
                main.monitor_once()
            except Exception:
                traceback.print_exc()
    finally:
        sys.stdout, sys.stderr = prev_out, prev_err
    return {"send": list(_calls), "stdout": buf.getvalue(), "stderr": err.getvalue(),
            "rounds": ROUNDS, "seed": SEED}


def main_cli():
    args = sys.argv[1:]
    if "--dump" in args:
        path = args[args.index("--dump") + 1]
        data = run()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"已生成金标准：{path}")
        print(f"  推送 {len(data['send'])} 条 / stdout {len(data['stdout'])} 字符")
        for t, _d in data["send"]:
            print("   ·", t)
    elif "--diff" in args:
        path = args[args.index("--diff") + 1]
        with open(path, "r", encoding="utf-8") as f:
            gold = json.load(f)
        now = run()
        ok = True
        if gold["send"] != now["send"]:
            ok = False
            print("!! send_wx 不一致")
            print("   金标准条数:", len(gold["send"]), " 现在:", len(now["send"]))
            for i in range(max(len(gold["send"]), len(now["send"]))):
                g = gold["send"][i] if i < len(gold["send"]) else None
                n = now["send"][i] if i < len(now["send"]) else None
                if g != n:
                    print(f"   [{i}] 金标准={g!r}")
                    print(f"   [{i}] 现在  ={n!r}")
                    break
        if gold["stdout"] != now["stdout"]:
            ok = False
            print("!! stdout 不一致")
            gl, nl = gold["stdout"].splitlines(), now["stdout"].splitlines()
            print("   行数:", len(gl), "->", len(nl))
            for i in range(max(len(gl), len(nl))):
                g = gl[i] if i < len(gl) else "<无>"
                n = nl[i] if i < len(nl) else "<无>"
                if g != n:
                    print(f"   首处差异 行{i}:")
                    print(f"     金标准: {g}")
                    print(f"     现在  : {n}")
                    break
        print("═══ 等价性：", "PASS ✓ 完全一致" if ok else "FAIL ✗ 有差异", "═══")
        return 0 if ok else 1
    else:
        print(__doc__)
        return 2


if __name__ == "__main__":
    sys.exit(main_cli())
