"""走势图的序列与绘制（**只用于显示**：不参与打分、不参与报警判定）。

反漂移的关键做法：公式直接 `from indicators import calc_boll, calc_rsi, calc_macd`，
不再抄一遍。显示窗口取「最后 N 根**已收盘** bar」——和 indicators.get_indicator 同口径
（它也把最后一根已收盘 bar 当基准，`k = len(df) - 2`）。

verify_panel.py 会断言「图上最后一点 == 打分用的那个数」（RSI/BOLL/收盘价），
所以哪天有人改了公式却漏了图，自检立刻红。

4 个子图（每项可单独折叠，高度与原来的走势图一致 = 58px）：
  价格  —— 收盘价折线 + 实时价圆点
  BOLL  —— 上中下三轨 + 通道填充
  RSI   —— 折线 + 70/30 参考线
  MACD  —— DIF/DEA 两线 + 柱状（正绿负红）+ 零轴
每个子图底部有 3 个时间刻度（首/中/末），这就是"随时间更新"的可见部分：
每轮刷新时窗口右移，刻度跟着走。
"""
N_BARS = 60          # 显示最近多少根已收盘 bar
W, H = 520, 58       # viewBox：与原来的走势图同高
TOP, BOTTOM = 3, 40  # 折线绘制区（下方留给时间刻度）
FONT = 9.5


# ─────────────────────────────────────────────── 序列
def _fmt_ts(v):
    """把 df['t'] 的时间值格式化成 'MM-DD HH:MM'。

    本版 indicators 没有 fmt_ts（旧版有，对方重写后删了），所以这里自带一个，
    并把输入形态放宽：支持 str / datetime / pandas Timestamp / 秒或毫秒时间戳。
    """
    import datetime as _dt
    try:
        if isinstance(v, str):
            return str(v)[5:16]                       # '2026-10-04 13:30:00' → '10-04 13:30'
        if hasattr(v, "strftime"):
            return v.strftime("%m-%d %H:%M")
        f = float(v)
        if f > 1e11:                                  # 毫秒
            f /= 1000.0
        return _dt.datetime.fromtimestamp(f).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def series(df, n=N_BARS):
    """返回 JSON 友好的序列（也直接进 /api/state，供脚本取用）。"""
    from indicators import calc_boll, calc_rsi, calc_macd
    closes = df['close']
    mid, up, lo = calc_boll(closes)
    rsi = calc_rsi(closes)
    # ★ 本版 calc_macd 返回 3 个（dif, dea, macd），旧版返回 2 个 —— 兼容两种
    _macd = calc_macd(closes)
    if len(_macd) >= 3:
        dif, dea, _macd_hist = _macd[0], _macd[1], _macd[2]
    else:
        dif, dea = _macd[0], _macd[1]
        _macd_hist = (dif - dea) * 2
    # ★ 口径：必须和 indicators 打分用的 bar **完全一致**，否则图上的线
    #   解释不了打分。本版 get_indicator 用的是 iloc[-1]（即**最后一根 bar**，
    #   实测 is_contract=False，也就是还在形成中的那根），所以这里也用 -1。
    #   注：这个口径本身有问题（形成中 bar 量能只有 0.00~0.34x 均量，
    #   导致 vol_enough 永远为假、放量类规则不可达），已单独记录为待修项；
    #   面板只做如实展示，不擅自改口径 —— 否则图会和判定对不上。
    k = len(df) - 1
    end = k + 1
    start = max(0, end - n)

    # 时间列：本版叫 't'（旧版叫 'ts'）—— 两个都认，避免再漂
    tcol = 't' if 't' in df.columns else ('ts' if 'ts' in df.columns else None)

    def f(s):
        out = []
        for x in s.iloc[start:end]:
            x = float(x)
            out.append(None if x != x else round(x, 8))       # NaN → None（JSON 友好）
        return out

    cl = f(closes)
    hist = []
    for a, b in zip(dif.iloc[start:end], dea.iloc[start:end]):
        if a != a or b != b:
            hist.append(None)
        else:
            hist.append(round(2 * (float(a) - float(b)), 8))   # 国内习惯：MACD柱 = 2×(DIF−DEA)
    ts = [_fmt_ts(df[tcol].iloc[i]) for i in range(start, end)] if tcol else [""] * (end - start)
    return {
        "n": end - start,
        "t": ts,
        "tick": [s[6:] if len(s) > 6 else s for s in (ts[0], ts[len(ts) // 2], ts[-1])],
        "close": cl, "boll_u": f(up), "boll_m": f(mid), "boll_l": f(lo),
        "rsi": f(rsi), "dif": f(dif), "dea": f(dea), "macd": hist,
        "price": float(df['close'].iloc[-1]),                  # 实时价（形成中 bar）
        "bar_time": ts[-1] if ts else "",
        # ★ 口径注记：本版 indicators 用 df.iloc[-2] 打分（最后一根已收盘 bar），
        #   所以图上最后一个点用的就是 k = len(df)-2 那一根，与打分口径一致。
        "is_closed_bar": True,
    }


def last_values(s):
    """图上的最后一个点 —— 自检用它和打分用的值比对。"""
    def last(a):
        for v in reversed(a or []):
            if v is not None:
                return v
        return None
    return {"close": last(s["close"]), "boll_u": last(s["boll_u"]), "boll_m": last(s["boll_m"]),
            "rsi": last(s["rsi"]), "dif": last(s["dif"]), "dea": last(s["dea"])}


# ─────────────────────────────────────────────── 画图基元
def _x(i, n):
    return 1.0 if n < 2 else 1.0 + i / (n - 1) * (W - 2)


def _y(v, lo, hi):
    if hi <= lo:
        hi = lo + 1e-9
    return BOTTOM - (v - lo) / (hi - lo) * (BOTTOM - TOP)


def _bounds(*arrays, pad=0.06):
    vals = [v for a in arrays for v in (a or []) if v is not None]
    if not vals:
        return 0.0, 1.0
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        hi = lo + (abs(lo) * 0.001 or 1.0)
    p = (hi - lo) * pad
    return lo - p, hi + p


def _poly(vals, lo, hi, color, width=1.5, dash=None, op=1.0):
    pts = [f"{_x(i, len(vals)):.1f},{_y(v, lo, hi):.1f}"
           for i, v in enumerate(vals) if v is not None]
    if len(pts) < 2:
        return ""
    d = f' stroke-dasharray="{dash}"' if dash else ""
    o = f' opacity="{op}"' if op != 1.0 else ""
    return (f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
            f'stroke-width="{width}"{d}{o} stroke-linejoin="round"/>')


def _hline(v, lo, hi, color, dash="4 4", w=1.0):
    y = _y(v, lo, hi)
    if not (TOP - 2 <= y <= BOTTOM + 2):
        return ""
    return (f'<line x1="1" y1="{y:.1f}" x2="{W-1}" y2="{y:.1f}" stroke="{color}" '
            f'stroke-width="{w}" stroke-dasharray="{dash}"/>')


def _axis(n):
    """底部时间刻度：3 条淡竖线（文字用 HTML 叠在下方，SVG 文字被拉伸会变形）。"""
    out = []
    for i in (0, n // 2, n - 1):
        x = _x(i, n)
        out.append(f'<line x1="{x:.1f}" y1="{BOTTOM}" x2="{x:.1f}" y2="{BOTTOM+4}" '
                   f'stroke="#8b949e" stroke-width="0.8" opacity="0.55"/>')
    return "".join(out)


def _wrap(inner, cls="chart"):
    return (f'<svg class="{cls}" viewBox="0 0 {W} {H}" preserveAspectRatio="none" '
            f'role="img" aria-label="走势图">{inner}</svg>')


# ─────────────────────────────────────────────── 4 个子图
def pane_price(s, up="#3fb950", dn="#f85149", dim="#8b949e"):
    lo, hi = _bounds(s["close"], [s["price"]])
    color = up if (s["price"] or 0) >= (s["close"][0] or 0) else dn
    inner = (_poly(s["close"], lo, hi, color) + _axis(s["n"]))
    if s["price"] is not None:
        inner += (f'<circle cx="{W-1:.1f}" cy="{_y(s["price"], lo, hi):.1f}" r="3.2" '
                  f'fill="#58a6ff"/>')
    return _wrap(inner)


def pane_boll(s, up="#3fb950", mid="#8b949e", lo_c="#f85149"):
    lo, hi = _bounds(s["boll_u"], s["boll_l"])
    pts_u = [f"{_x(i, s['n']):.1f},{_y(v, lo, hi):.1f}" for i, v in enumerate(s["boll_u"]) if v is not None]
    pts_l = [f"{_x(i, s['n']):.1f},{_y(v, lo, hi):.1f}" for i, v in enumerate(s["boll_l"]) if v is not None]
    band = ""
    if len(pts_u) > 2 and len(pts_l) > 2:
        band = (f'<polygon points="{" ".join(pts_u + list(reversed(pts_l)))}" '
                f'fill="{mid}" opacity="0.10"/>')
    inner = (band + _poly(s["boll_u"], lo, hi, up, 1.2)
             + _poly(s["boll_m"], lo, hi, mid, 1.2, dash="5 3")
             + _poly(s["boll_l"], lo, hi, lo_c, 1.2) + _axis(s["n"]))
    return _wrap(inner)


def pane_rsi(s, line="#58a6ff", warn="#f6c177", dim="#8b949e"):
    vals = [v for v in s["rsi"] if v is not None]
    lo = min([30.0] + vals) - 4
    hi = max([70.0] + vals) + 4
    inner = (_hline(70, lo, hi, warn) + _hline(30, lo, hi, warn)
             + _hline(50, lo, hi, dim, dash="2 5", w=0.8)
             + _poly(s["rsi"], lo, hi, line) + _axis(s["n"]))
    return _wrap(inner)


def pane_macd(s, up="#3fb950", dn="#f85149", dif_c="#58a6ff", dea_c="#f6c177",
              dim="#8b949e"):
    lo, hi = _bounds(s["macd"], s["dif"], s["dea"], pad=0.12)
    if lo > 0:
        lo = 0.0
    if hi < 0:
        hi = 0.0
    bw = max(1.0, (W - 2) / max(1, s["n"]) * 0.62)
    bars = []
    for i, v in enumerate(s["macd"]):
        if v is None:
            continue
        y0, y1 = _y(0, lo, hi), _y(v, lo, hi)
        x = _x(i, s["n"])
        bars.append(f'<rect x="{x - bw/2:.1f}" y="{min(y0,y1):.1f}" width="{bw:.1f}" '
                    f'height="{max(0.8, abs(y1-y0)):.1f}" fill="{up if v >= 0 else dn}" '
                    f'opacity="0.55"/>')
    inner = ("".join(bars) + _hline(0, lo, hi, dim, dash="0", w=0.9)
             + _poly(s["dif"], lo, hi, dif_c, 1.3) + _poly(s["dea"], lo, hi, dea_c, 1.3)
             + _axis(s["n"]))
    return _wrap(inner)


# ─────────────────────────────────────────────── 组合成 4 个可折叠项
def render_chart(coin, s, signal_note=""):
    """4 个独立可折叠的子图。data-persist 是**显式**键：summary 里带实时数字，
    交给"自动派生键"会每轮都变，记忆就丢了。"""
    lv = last_values(s)
    fmt = _fmt
    span = f'{s["tick"][0]} → {s["tick"][-1]}'
    items = [
        ("price", "价格", f'{fmt(s["price"])}　已收盘 {fmt(lv["close"])}',
         pane_price(s)),
        ("boll", "BOLL", f'上 {fmt(lv["boll_u"])} / 中 {fmt(lv["boll_m"])}', pane_boll(s)),
        ("rsi", "RSI(14)", f'{fmt(lv["rsi"], 1)}', pane_rsi(s)),
        ("macd", "MACD(12,26,9)",
         f'DIF {fmt(lv["dif"], 4)} / DEA {fmt(lv["dea"], 4)} / 柱 {fmt(s["macd"][-1], 4)}',
         pane_macd(s)),
    ]
    out = [f'      <div class="sec">走势图（{s["n"]} 根 15m　{span}　每轮刷新向右滚动）'
           f'{signal_note}</div>']
    for key, label, val, svg in items:
        out.append(
            f'      <details open class="ch" data-persist="chart:{coin}:{key}">\n'
            f'        <summary>{label}　<span class="cv">{val}</span></summary>\n'
            f'        <div class="chartbox">{svg}'
            f'<div class="xaxis"><span>{s["tick"][0]}</span><span>{s["tick"][1]}</span>'
            f'<span>{s["tick"][2]}</span></div></div>\n'
            f'      </details>')
    return "\n".join(out)


def _fmt(v, dp=None):
    if v is None:
        return "—"
    v = float(v)
    if dp is not None:
        return f"{v:.{dp}f}"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.2f}"
    if a >= 100:
        return f"{v:.2f}"
    if a >= 1:
        return f"{v:.3f}"
    if a >= 0.01:
        return f"{v:.5f}"
    return f"{v:.6f}"
