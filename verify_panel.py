"""面板自检：抓页面 + /api/state，断言**渲染后的结果**而不是意图。

跑法：先让面板起来（python main.py，或测试用的 demo），然后
    <解释器> verify_panel.py [端口]          # 不给端口就用 config.PANEL_PORT
每改一次页面都跑一遍 —— 它就是下次改动的回归测试。

重点断言：
  · 静态 HTML 里就有 6 个币的表格与走势图（服务端渲染，不依赖 JS）
  · 三列表格带「口径 / 来源」列、每币一张
  · 所有 [[占位符]] 都被替换掉了（漏替换会直接暴露在页面上）
  · 页面**不含任何密钥**（SendKey / webhook / secret 一律不出网）
  · 没有 <meta http-equiv="refresh">（刷新由用户决定，别顶掉滚动位置）
  · 移动端 viewport + 主题三态 + 折叠框 + 全部展开/收起
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request

import config

BASE = f"http://127.0.0.1:{sys.argv[1] if len(sys.argv) > 1 else getattr(config, 'PANEL_PORT', 8787)}"


def fetch(path: str) -> str:
    with urllib.request.urlopen(BASE + path, timeout=20) as r:      # noqa: S310
        return r.read().decode("utf-8")


def status(path: str) -> int:
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as r:  # noqa: S310
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def fetch_ready(timeout=300, interval=5):
    """等第一轮跑完再断言。刚启动的面板 ready=False、coins 为空，
    此时抓页面会得到"等待中"的骨架 —— 一堆计数断言就会打印误导性的 FAIL。"""
    import time
    t0 = time.time()
    while True:
        try:
            raw = fetch("/api/state")
            st = json.loads(raw)
        except Exception as e:
            print(f"抓不到面板 {BASE} —— 先把它跑起来（python main.py）。\n  {type(e).__name__}: {e}")
            return None, None, True
        if st.get("ready"):
            return st, raw, False
        if time.time() - t0 > timeout:
            print(f"⚠ 面板在跑，但第一轮监控还没结束（ready=False，已等 {int(time.time() - t0)}s）。")
            print("  不是故障：一轮要给每个币拉 15m/1h/4h K 线与多空比，网络慢时会要几分钟。")
            print("  等它跑完再执行一次本脚本即可。")
            return st, raw, True
        print(f"  等第一轮跑完…（{int(time.time() - t0)}s）")
        time.sleep(interval)


def main() -> int:
    checks = []
    st, raw_state, gave_up = fetch_ready()
    if st is None or gave_up:
        return 2
    try:
        # 必须在 ready 之后再抓页面，否则抓到的还是没有币的骨架
        page = fetch("/")
    except Exception as e:
        print(f"抓不到面板页面 {BASE}。\n  {type(e).__name__}: {e}")
        return 2

    # 指纹检查：先确认应答的是**本项目**的面板。不然后面 n_coins=0 会让
    # "每个币都有卡片" 这类计数断言 0==0 假通过，把"连错了服务"伪装成全绿。
    if "coins" not in st or "channels" not in st:
        print(f"⚠ 端口 {BASE} 上应答的不是本项目面板（/api/state 里没有 coins/channels 字段）。")
        print(f"  它返回的键：{sorted(st)}")
        print("  8787 通常是另一个项目（dev\\crypto_monitor）的面板；"
              f"本项目默认端口 {getattr(config, 'PANEL_PORT', 8789)}。")
        return 2
    n_coins = len(st.get("coins") or [])
    want = len(set(list(config.CURRENCY_PAIRS) + list(config.PRICE_ALERT.keys())))
    print(f"面板 {BASE}　ready={st.get('ready')}　轮次={st.get('round')}　币数={n_coins}　"
          f"耗时={st.get('round_seconds')}s　报警={len(st.get('alerts') or [])} 条")
    for c in st.get("coins") or []:
        ch = c.get("chart") or {}
        print(f"  {c['pair']:<10} {c['signal']:<4} 买{fmt0(c['buy'])}/卖{fmt0(c['sell'])} "
              f"收盘K {c['bar_time']} 图 {len(ch.get('close') or [])} 点 "
              f"量能 {fmt0(c['vol_ratio'])}× 报警 {len(c['alerts'])}")

    # ── 页面结构 ──
    n_details = len(re.findall(r"<details", page))
    n_tables = len(re.findall(r'<table class="m">', page))
    n_chart = len(re.findall(r'<svg class="chart"', page))
    n_xaxis = len(re.findall(r'class="xaxis"', page))
    n_persist = len(re.findall(r'data-persist="', page))
    n_coin_sum = len(re.findall(r"<summary>[A-Z0-9]+/USDT", page))
    left = re.findall(r"\[\[[A-Z]+\]\]", page)

    # 反漂移：图上最后一个点必须**等于**打分用的那个值（同一条公式、同一个基准 bar）
    # 注：本版基准 bar = iloc[-1]（含未收盘那根，对方确认为有意设计），故断言按末点比。
    drift = []
    for c in st.get("coins") or []:
        ch = c.get("chart") or {}
        pairs = (("close", "close"), ("boll_u", "boll_u"), ("boll_m", "boll_m"), ("rsi", "rsi_15"))
        for key, field in pairs:
            vals = [v for v in (ch.get(key) or []) if v is not None]
            a, b = (vals[-1] if vals else None), c.get(field)
            if a is None or b is None or abs(float(a) - float(b)) > 1e-6:
                drift.append(f'{c.get("coin")}.{key}: 图={a} 指标={b}')

    checks += [
        ("/healthz 返回 200", status("/healthz") == 200),
        ("未知路径 404（不乱抛）", status("/favicon.ico") == 404),
        ("/api/state 是合法 JSON", isinstance(st, dict)),
        ("首轮已完成（ready）", st.get("ready") is True),
        ("币数与 config 一致", n_coins == want and n_coins > 0),
        ("每币都有 K 线基准时间", all(c.get("bar_time") for c in st.get("coins") or [])),
        ("每币都有走势图序列（价格/BOLL/RSI/KDJ/MACD）",
         all(len((c.get("chart") or {}).get("close") or []) > 10
             and (c.get("chart") or {}).get("rsi")
             and (c.get("chart") or {}).get("dif")
             and (c.get("chart") or {}).get("boll_u")
             and (c.get("chart") or {}).get("macd") for c in st.get("coins") or [])),
        ("图上最后一个点 == 打分用的值（无漂移）", not drift),
        ("序列带时间刻度（首/中/末）",
         all(len((c.get("chart") or {}).get("tick") or []) == 3 for c in st.get("coins") or [])),
        ("信号只有 买入/卖出/观望", {c["signal"] for c in st.get("coins") or []} <= {"买入", "卖出", "持有观望", "观望"}),
        ("买分/卖分是数字", all(isinstance(c.get("buy"), (int, float)) and
                              isinstance(c.get("sell"), (int, float)) for c in st.get("coins") or [])),
        ("通道清单非空", len(st.get("channels") or []) >= 2),
        ("页面上每个币都有一张卡", n_coins > 0 and n_coin_sum == n_coins),
        ("页面上每个币都有一张三列表格", n_coins > 0 and n_tables == n_coins),
        ("页面上每个币都有一张走势图（5 项子图）", n_coins > 0 and n_chart == n_coins * 5),
        ("每项子图都有时间刻度", n_xaxis == n_coins * 5),
        ("折叠状态可记忆（币卡 + 5 子图都有显式键）", n_persist >= n_coins * 6),
        ("有折叠记忆机制（含新增项自动记住）",
         all(k in page for k in ("cm-open-state", "applyPersist", "dkey(", "resetDet", "data-persist"))),
        ("有「重置折叠」按钮", "重置折叠" in page),
        ("表格带「口径 / 来源」列", "口径 / 来源" in page),
        ("折叠框够用（状态+币卡+报警+口径+说明）", n_details >= n_coins + 4),
        ("常驻总览表每币一行（收起也能看）", len(re.findall(r'<tr class="ovr"', page)) == n_coins),
        ("标题图标没被走势图样式套住（class=ico）",
         '<span class="ico"' in page and '<h1><span class="spark"' not in page),
        ("没有漏替换的占位符", not left),
        ('没有 <meta http-equiv="refresh">', 'http-equiv="refresh"' not in page),
        ("JS 轮询 /api/state（不自动刷新）", "/api/state" in page and "setInterval(poll" in page),
        ("离线时会提示（连不上监控）", "连不上监控进程" in page),
        ("有下一轮倒计时", "window.NEXT_TS" in page),
        ("有全部展开/全部收起", "全部展开" in page and "全部收起" in page),
        ("有立即刷新按钮", "location.reload()" in page),
        ("主题三态（跟随系统/浅色/深色）",
         all(k in page for k in ("跟随系统", "浅色", "深色", "prefers-color-scheme", "localStorage"))),
        ("移动端 viewport", "width=device-width" in page),
        ("浅色/深色两套变量", 'html[data-theme=light]' in page and "--bg:#0e1116" in page),
        ("写明面板是只读的、关掉不影响监控", "只读" in page and "关掉浏览器不影响监控" in page),
    ]

    # ── 密钥绝不出网（页面与 JSON 都查）──
    secrets = [config.SENDKEY1, config.SENDKEY2, getattr(config, "DINGTALK_WEBHOOK", ""),
               getattr(config, "DINGTALK_SECRET", "")]
    leaked = [s for s in secrets if s and s in raw_state]
    leaked_page = [s for s in secrets if s and s in page]
    checks += [
        ("SENDKEY 不在 /api/state 里", not leaked),
        ("SENDKEY 不在页面里", not leaked_page),
        ("payload 里没有 SENDKEY/webhook 字段名",
         not re.search(r'sendkey|webhook|secret|access_token', raw_state, re.I)),
    ]

    print("\n=== 断言 ===")
    bad = 0
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        bad += 0 if ok else 1
    print(f"\n结果: {len(checks) - bad}/{len(checks)} 通过")
    if left:
        print(f"漏替换的占位符: {sorted(set(left))}")
    return 1 if bad else 0


def fmt0(v):
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


if __name__ == "__main__":
    sys.exit(main())
