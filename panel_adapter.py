# -*- coding: utf-8 -*-
"""panel_adapter.py —— 把「现在这版 main.py 每轮算出来的东西」适配成面板要的结构。

为什么要这一层：旧面板（e128a8e）读的是 evaluate.evaluate_coin() 的返回值，
而对方重写后那个模块不存在了。面板本身（HTML/CSS/SVG/折叠记忆）是好的，
所以**不改面板、不改业务逻辑**，只在中间加一层适配。

★ 字段名以 get_indicator() 的**真实返回**为准（实测键名，不是猜的）：
    close / boll_mid / boll_u / boll_l / rsi / kdj_j / ema12 / ema26 /
    dif / dea / macd / vol_now / vol_ma / vol_enough / day_chg /
    today_high / today_low / ma20 / trend_up / df
  面板里没有对应数据的字段一律 None（页面显示 "—"），**绝不用假值填充**。
"""


def _n(v):
    """数值安全转换：不是数就给 None（面板显示 —），绝不给 0 冒充。"""
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def coin_view(pair, coin, ind_s, ind_l=None, ind_4h=None, flow=None,
              daily_up=None, btc_chg=None, fired_alerts=None, chart=None,
              ls_account=None, ls_size=None, score=None, signal=None):
    """组装一枚币的面板视图。

    入参全部来自 main.monitor_once 里**已经算好的**变量，这里只做改名与兜底。
    """
    ind_s = ind_s or {}
    fired_alerts = fired_alerts or []

    # 面板需要 df 来画走势图；没传 chart 就在这里现算（只用于显示）
    if chart is None:
        try:
            import panel_chart
            df = ind_s.get("df")
            chart = panel_chart.series(df) if df is not None else None
        except Exception as e:          # 显示层失败绝不影响监控
            chart = None
            print(f"[面板] {coin} 走势图序列失败：{type(e).__name__}: {e}")

    b = s = None
    if isinstance(score, (list, tuple)) and len(score) >= 2:
        b, s = _n(score[0]), _n(score[1])
    elif isinstance(score, dict):
        b, s = _n(score.get("buy")), _n(score.get("sell"))

    # 量能比：本版 indicators 没直接给，用 vol_now / vol_ma 自算（仅显示）
    vol_ratio = None
    try:
        vn, vm = ind_s.get("vol_now"), ind_s.get("vol_ma")
        if vn is not None and vm:
            vol_ratio = float(vn) / float(vm)
    except (TypeError, ValueError, ZeroDivisionError):
        vol_ratio = None

    # K 线时间：优先用走势图序列算出的真实 bar 时间（df 索引是 RangeIndex，取不到时间）
    bar_time = None
    if isinstance(chart, dict):
        bar_time = chart.get("bar_time") or None
    if not bar_time:
        try:
            df = ind_s.get("df")
            if df is not None and len(df) and "t" in df.columns:
                t = df["t"].iloc[-2] if len(df) >= 2 else df["t"].iloc[-1]
                bar_time = str(t)[:16]
        except Exception:
            bar_time = None

    return {
        "coin": coin,
        "pair": pair,
        # 本版没有单独的"实时价"，用最新收盘价（面板里已标注口径）
        "price": _n(ind_s.get("close")),
        "day_chg": _n(ind_s.get("day_chg")),
        "close": _n(ind_s.get("close")),
        "bar_time": bar_time,
        # 口径事实：由 panel_chart 从数据推导（True=已收盘 / False=形成中 / None=未知）
        "basis_closed": (chart or {}).get("basis_closed") if isinstance(chart, dict) else None,
        "trend_up": bool(ind_s.get("trend_up")),
        "ma20": _n(ind_s.get("ma20")),
        "boll_u": _n(ind_s.get("boll_u")),
        "boll_l": _n(ind_s.get("boll_l")),
        "boll_m": _n(ind_s.get("boll_mid")),      # ← 真实键名是 boll_mid
        "rsi_15": _n(ind_s.get("rsi")),
        "rsi_1h": _n((ind_l or {}).get("rsi")),
        "trend_1h": bool((ind_l or {}).get("trend_up")),
        "boll_u_1h": _n((ind_l or {}).get("boll_u")),
        "trend_4h": None if not ind_4h else bool(ind_4h.get("trend_up")),
        "daily_up": None if daily_up is None else bool(daily_up),
        "net_inflow": _n((flow or {}).get("net_inflow")),
        "trades_n": (flow or {}).get("n"),
        "vol_ratio": vol_ratio,
        "ls_account": _n(ls_account),
        "ls_size": _n(ls_size),
        "ls_pct": None,          # 新版没有分位样本，如实留空
        "ls_n": None,
        "buy": b,
        "sell": s,
        "signal": signal,
        "btc_chg": _n(btc_chg),
        "chart": chart,
        "alerts": fired_alerts,
    }
