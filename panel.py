"""只读前端面板（H5）：把监控状态暴露到局域网，手机上就能看。

设计原则（用户要求：**业务逻辑不变**）
  · 只看不改：不写 config、不改监控列表、不触发推送、不参与判定。
  · 面板挂了监控照跑：start() 失败只打印警告，绝不把异常抛给主循环。
  · 不在 HTTP handler 里取数：每轮由 main.monitor_once() 调 publish() 刷新缓存，handler 只读缓存。
  · **payload 里不放任何密钥**：只给通道名字与启用状态（verify_panel.py 会断言这一点）。
  · 页面由**服务端渲染**：静态 HTML 里就有数据，`verify_panel.py` 能直接断言渲染结果，
    而且手机上没有 JS 也能看。前端只负责"有新数据时告诉你"（不做自动刷新，避免丢滚动位置）。

页面结构（H5 / 移动优先）
  /            页面（模板在 panel.html，用 [[TOKEN]] 占位符替换）
  /api/state   JSON（给脚本/手机用）
  /healthz     探活
"""
import json
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import panel_chart

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "panel.html")

_lock = threading.Lock()
_server = None
_seq = 0

# 缓存状态：只有 publish() 会写，handler 只读
STATE = {
    "ready": False,
    "note": "首轮进行中…（首轮要取 6 个币的多周期数据，约 15~25 秒）",
    "coins": [],
    "alerts": [],
    "errors": [],
    "btc_chg": None,
    "round": 0,
    "round_seconds": None,
    "started_ts": time.time(),
    "last_run_ts": None,
    "channels": [],
    "version": "",
}


# ────────────────────────────────────────────────────────── 数字格式
def fmt(v, dp=None):
    """按数量级选小数位 —— 固定 2 位会把小价格币的 BOLL 压成 0.19/0.18，数字就没信息了。"""
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
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


def _num(v):
    try:
        f = float(v)
        return None if f != f else f          # NaN → None
    except (TypeError, ValueError):
        return None


# ────────────────────────────────────────────────────────── 每轮由 main 调用
def coin_view(res, fired_alerts):
    """把 evaluate.evaluate_coin() 的结果变成 JSON 友好的展示结构（不做任何判定）。

    fired_alerts: [{"key","title","body","fired","why"}]
    """
    ind_s, ind_l, ind_4h = res["ind_s"], res["ind_l"], res["ind_4h"]
    flow = res["flow"]
    # 走势图序列：直接用 indicators 里那几个函数算（公式不可能和打分漂开）
    try:
        chart = panel_chart.series(ind_s["df"])
    except Exception as e:                      # 显示层失败不影响监控
        chart = None
        print(f"[面板] {res['coin']} 走势图序列失败：{type(e).__name__}: {e}")
    return {
        "coin": res["coin"], "pair": res["pair"],
        "price": _num(ind_s["price"]),
        "day_chg": _num(ind_s["day_chg"]),
        "close": _num(ind_s["close"]),
        "bar_time": ind_s.get("bar_time"), "bar_closed": ind_s.get("bar_closed"),
        "trend_up": bool(ind_s["trend_up"]), "ma20": _num(ind_s["ma20"]),
        "boll_u": _num(ind_s["boll_u"]), "boll_l": _num(ind_s["boll_l"]), "boll_m": _num(ind_s["boll_m"]),
        "rsi_15": _num(ind_s["rsi"]), "rsi_1h": _num(ind_l["rsi"]),
        "trend_1h": bool(ind_l["trend_up"]), "boll_u_1h": _num(ind_l["boll_u"]),
        "trend_4h": bool(ind_4h["trend_up"]), "daily_up": bool(res["daily_up"]),
        "net_inflow": _num(flow.get("net_inflow")), "trades_n": flow.get("n"),
        "vol_ratio": _num(ind_s["vol_ratio"]),
        "ls_account": _num(res["ls_account"]), "ls_size": _num(res["ls_size"]),
        "ls_pct": _num(res["ls_pct"]), "ls_n": res["ls_n"],
        "buy": _num(res["b_score"]), "sell": _num(res["s_score"]),
        "signal": res["signal"],
        "chart": chart,
        "alerts": fired_alerts,
    }


def publish(coins, alerts, errors, duration=None, btc_chg=None):
    """每轮结束时调用一次（main.monitor_once）。**永不抛异常** —— 面板问题不能影响监控。"""
    global _seq
    try:
        with _lock:
            _seq += 1
            STATE.update({
                "ready": True,
                "note": "",
                "coins": coins,
                "alerts": alerts,
                "errors": errors,
                "btc_chg": _num(btc_chg),
                "round": STATE["round"] + 1,
                "round_seconds": None if duration is None else round(float(duration), 1),
                "last_run_ts": time.time(),
                "seq": _seq,
                "channels": _channels(),
                "version": getattr(config, "VERSION", ""),
                "ls_metric": getattr(config, "LS_METRIC", "top_lsr_account"),
                "ls_min": getattr(config, "LS_MIN_SAMPLES", 60),
                "cooldown_min": getattr(config, "ALERT_COOLDOWN_MIN", 30),
                "poll": getattr(config, "CHECK_INTERVAL", 60),
                "pairs": len(getattr(config, "CURRENCY_PAIRS", [])),
            })
        return _seq
    except Exception as e:                      # 面板出问题也不能影响监控主线
        print(f"[面板] 刷新失败（监控继续跑）：{type(e).__name__}: {e}")
        return _seq


def _channels():
    """通道名字 + 是否启用。**不要**把 key/webhook 放进来。

    兼容两种 notifier 实现：本版 get_channels() 返回 dict（{name, enabled}），
    旧版返回带 .name/.enabled() 的对象 —— 两种都接受，避免换版本就报 AttributeError。
    """
    try:
        from notifier import get_channels
        out = []
        for c in get_channels():
            if isinstance(c, dict):
                out.append({"name": str(c.get("name", "?")),
                            "enabled": bool(c.get("enabled"))})
            else:
                out.append({"name": str(getattr(c, "name", "?")),
                            "enabled": bool(c.enabled())})
        return out
    except Exception as e:
        return [{"name": f"（读取失败：{type(e).__name__}）", "enabled": False}]


def snapshot():
    with _lock:
        return dict(STATE)


# ────────────────────────────────────────────────────────── 服务端渲染
# 走势图渲染搬到 panel_chart.py（4 个子图：价格 / BOLL / RSI / MACD）


def _coin_block(c):
    coin = c["coin"]
    sig = c["signal"]
    cls = {"买入": "buy", "卖出": "sell"}.get(sig, "")
    chg = c["day_chg"] or 0.0
    n_fired = sum(1 for a in c["alerts"] if a.get("fired"))
    n_cool = len(c["alerts"]) - n_fired
    badge = ""
    if n_fired:
        badge = f' <span class="tag fire">{n_fired} 条本轮上报</span>'
    elif n_cool:
        badge = f' <span class="tag cool">{n_cool} 条冷却中</span>'
    rows = [
        ("现价（实时）", f'<b>{fmt(c["price"])}</b>', "Gate 行情最新成交价"),
        ("当日涨跌幅", f'<span class="{"up" if chg>=0 else "down"}">{chg:+.2f}%</span>',
         "实时价 相对 当日 0 点开盘价"),
        ("指标收盘价", fmt(c["close"]), f'最后一根<b>已收盘</b> K 线（{c["bar_time"]}）'),
        ("趋势 MA20", ('🟢 上涨' if c["trend_up"] else '🔴 下跌') + f'　MA20 {fmt(c["ma20"])}',
         "已收盘 K 线收盘价 vs 20 根均线（本地算）"),
        ("BOLL 支撑/压力", f'{fmt(c["boll_l"])} / {fmt(c["boll_u"])}',
         "20 根 ±2σ（本地算，用已收盘 K 线）"),
        ("RSI 15m / 1h", f'{fmt(c["rsi_15"],1)} / {fmt(c["rsi_1h"],1)}',
         "14 周期简单均值法（本地算）"),
        ("1h / 4h 趋势", ('🟢' if c["trend_1h"] else '🔴') + ' / ' + ('🟢' if c["trend_4h"] else '🔴'),
         "各自周期收盘价 vs MA20（本地算）"),
        ("日线趋势", '🟢 向上' if c["daily_up"] else '🔴 向下', "日线已收盘 K 线 vs MA20"),
        ("量能", f'{fmt(c["vol_ratio"],2)}× 均量',
         f'已收盘 K 线量 / 20 根均量（门槛 {getattr(config,"VOL_ENOUGH_MULT",1.2)}×）'),
        ("资金流向（近 100 笔）", f'${fmt(c["net_inflow"],0)}',
         f'主动买 − 主动卖，{c["trades_n"]} 笔（本地算）'),
        ("大户持仓多空比", fmt(c["ls_size"]), "<code>contract_stats.top_lsr_size</code>（接口直返，仅展示）"),
        ("大户账户多空比", fmt(c["ls_account"]),
         f'<code>top_lsr_account</code>（接口直返）·打分口径 {getattr(config,"LS_METRIC","")}'
         + (f' · 分位 {fmt(c["ls_pct"],0)}%' if c["ls_pct"] is not None
            else f' · 预热中 {c["ls_n"]}/{getattr(config,"LS_MIN_SAMPLES",60)}（预热期不加分）')),
        ("15m 信号", f'<b>{sig}</b>', f'买分 {fmt(c["buy"],1)} / 卖分 {fmt(c["sell"],1)}　'
                                   f'（阈值 {getattr(config,"BUY_SCORE_THRESHOLD",3.5)}，本地算）'),
    ]
    trs = "\n".join(
        f'      <tr><td>{k}</td><td>{v}</td><td class="src">{s}</td></tr>' for k, v, s in rows)
    al = ""
    if c["alerts"]:
        items = "\n".join(
            f'        <li class="{"fire" if a.get("fired") else "cool"}">'
            f'<b>{a.get("title","")}</b>'
            f'<span class="why">{"本轮已上报" if a.get("fired") else str(a.get("why",""))}</span>'
            f'<div class="body">{a.get("body","").replace(chr(10), "<br>")}</div></li>'
            for a in c["alerts"])
        al = f'      <div class="sec">该币报警</div>\n      <ul class="alerts">\n{items}\n      </ul>'
    return f"""  <details open class="coin {cls}" data-persist="coin:{coin}">
    <summary>{coin}/USDT　{fmt(c["price"])}　<span class="{"up" if chg>=0 else "down"}">{chg:+.2f}%</span>　{sig}{badge}</summary>
    <div class="inner">
{panel_chart.render_chart(coin, c["chart"]) if c.get("chart") else '      <div class="hint">（走势图数据不可用）</div>'}
      <table class="m">
        <tr><th>项目</th><th>数值</th><th>口径 / 来源</th></tr>
{trs}
      </table>
{al}
    </div>
  </details>"""


def _status_block(s):
    up = int(time.time() - (s.get("started_ts") or time.time()))
    hh, mm, ss = up // 3600, up % 3600 // 60, up % 60
    last = (datetime.fromtimestamp(s["last_run_ts"]).strftime("%H:%M:%S")
            if s.get("last_run_ts") else "—")
    nxt_ts = None
    if s.get("last_run_ts"):
        nxt_ts = s["last_run_ts"] + (s.get("round_seconds") or 0) + (s.get("poll") or 60)
    chan = "　".join(
        f'<span class="pill {"ok" if c["enabled"] else "dim"}">{c["name"]}{"✅" if c["enabled"] else "（未配置）"}</span>'
        for c in s.get("channels", []))
    errs = s.get("errors") or []
    err_html = (f'<div class="sec">本轮跳过（取数失败）</div><ul class="errs">'
                + "".join(f"<li>{e}</li>" for e in errs) + "</ul>") if errs else ""
    btc = "—" if s.get("btc_chg") is None else f'{s["btc_chg"]:+.2f}%'
    return f"""<div class="stat">
  <div><span class="k">轮次</span><b>第 {s.get("round") or 0} 轮</b>{"" if s.get("ready") else "（首轮进行中）"}</div>
  <div><span class="k">上一轮耗时</span><b>{fmt(s.get("round_seconds"),1)}s</b>
       <span class="k">轮询间隔</span><b>{s.get("poll") or "—"}s</b></div>
  <div><span class="k">上一轮完成</span><b>{last}</b>
       <span class="k">下一轮</span><b id="eta">—</b></div>
  <div><span class="k">进程已运行</span><b>{hh}h{mm:02d}m{ss:02d}s</b>
       <span class="k">BTC 今日</span><b>{btc}</b></div>
  <div><span class="k">报警冷却</span><b>{s.get("cooldown_min") or "—"} 分钟</b>
       <span class="k">监控币数</span><b>{s.get("pairs") or 0}</b>
       <span class="k">版本</span><b>{s.get("version") or "—"}</b></div>
</div>
<div class="sec">通知通道（只显示名字与启用状态，页面里不含任何密钥）</div>
<div class="chips">{chan}</div>
{err_html}
<script>window.NEXT_TS = {int(nxt_ts) if nxt_ts else 0};</script>"""


def _overview_block(s):
    """常驻总览：手机上不用展开任何折叠框就能先看全 6 个币。"""
    rows = []
    for c in s.get("coins") or []:
        chg = c["day_chg"] or 0.0
        sig = c["signal"]
        cls = "sig-u" if sig == "买入" else ("sig-d" if sig == "卖出" else "dim")
        rows.append(
            f'    <tr class="ovr"><td>{c["coin"]}</td><td>{fmt(c["price"])}</td>'
            f'<td class="{"up" if chg >= 0 else "down"}">{chg:+.2f}%</td>'
            f'<td class="{cls}">{sig}</td><td class="dim">{fmt(c["vol_ratio"],2)}×</td></tr>')
    return "\n".join(rows)


def _alerts_block(s):
    al = s.get("alerts") or []
    if not al:
        return '<div class="hint">本轮没有触发任何报警。判定规则与 main.py 完全同一处（evaluate.build_alerts）。</div>'
    out = []
    for a in al:
        out.append(
            f'<li class="{"fire" if a.get("fired") else "cool"}">'
            f'<span class="tm">{a.get("t","")}</span> <b>{a.get("title","")}</b>'
            f'<span class="why">{a.get("coin","")} · {"本轮已上报" if a.get("fired") else str(a.get("why",""))}</span>'
            f'<div class="body">{a.get("body","").replace(chr(10), "<br>")}</div></li>')
    return '<ul class="alerts">\n' + "\n".join(out) + "\n</ul>"


def render_page():
    s = snapshot()
    try:
        with open(TEMPLATE, "r", encoding="utf-8") as f:
            tpl = f.read()
    except OSError as e:
        return (f"<h1>panel.html 读取失败</h1><pre>{e}</pre>", "text/html; charset=utf-8")
    if not s.get("coins"):
        body = f'<div class="note">{s.get("note") or "正在取数…"}</div>'
    else:
        blocks = []
        for c in s["coins"]:
            try:
                blocks.append(_coin_block(c))
            except Exception as e:      # 单枚币渲染坏掉不能把整页弄死（改版最容易踩）
                print(f"[面板] {c.get('coin')} 这块渲染失败：{type(e).__name__}: {e}", flush=True)
                blocks.append(f'<div class="hint">⚠️ {c.get("coin") or "?"} 这块渲染失败：'
                              f'{type(e).__name__}: {e}<br>监控与报警不受影响；'
                              f'细节见跑监控那个窗口 / 日志。</div>')
        body = "\n".join(blocks)
    html = (tpl.replace("[[VERSION]]", str(s.get("version") or ""))
               .replace("[[SEQ]]", str(s.get("seq") or 0))
               .replace("[[ROUND]]", str(s.get("round") or 0))
               .replace("[[COINN]]", str(len(s.get("coins") or [])))
               .replace("[[ALERTN]]", str(len(s.get("alerts") or [])))
               .replace("[[STATUS]]", _status_block(s))
               .replace("[[OVERVIEW]]", _overview_block(s))
               .replace("[[COINS]]", body)
               .replace("[[ALERTS]]", _alerts_block(s))
               .replace("[[REFRESH]]", str(getattr(config, "PANEL_REFRESH_SEC", 10))))
    return html, "text/html; charset=utf-8"


# ────────────────────────────────────────────────────────── HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "crypto-monitor-panel"
    protocol_version = "HTTP/1.1"

    def _send(self, code, payload: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass                     # 手机锁屏/切网时连接会被直接掐掉，不该刷日志

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
        if path == "/":
            try:
                html, ctype = render_page()
            except Exception as e:      # 渲染抛异常时给一张能看懂的错误页，而不是断连接
                import traceback
                tb = traceback.format_exc().strip().splitlines()[-3:]
                print(f"[面板] 渲染失败：{type(e).__name__}: {e}", flush=True)
                html = ("<meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                        "<h2>⚠️ 面板渲染失败</h2><p>监控与报警不受影响，数据仍在 "
                        "<a href='/api/state'>/api/state</a>。</p><pre>"
                        + "\n".join(tb) + "</pre>")
                ctype = "text/html; charset=utf-8"
            self._send(200, html.encode("utf-8"), ctype)
        elif path == "/api/state":
            s = snapshot()
            s["server_now"] = time.time()
            s.pop("started_ts", None)
            self._send(200, json.dumps(s, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")
        elif path == "/healthz":
            self._send(200, b"ok", "text/plain; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_HEAD(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
        self._send(200 if path in ("/", "/api/state", "/healthz") else 404, b"",
                   "text/html; charset=utf-8")

    def log_message(self, *a):
        return                        # 手机每 10 秒轮询一次，不要写满日志


def lan_urls(port):
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return [f"http://{ip}:{port}/" for ip in ips]


def _probe(port, timeout=2.0):
    """确认这个端口上应答的**确实是我们**（不是别人的服务）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=timeout) as r:
            return r.read().strip() == b"ok"
    except Exception:
        return False


def start(host=None, port=None):
    """在后台线程里起面板。**永不抛异常**：面板起不来不能影响监控主线。"""
    global _server
    host = host or getattr(config, "PANEL_HOST", "0.0.0.0")
    port = int(port or getattr(config, "PANEL_PORT", 8789))
    if not getattr(config, "PANEL_ENABLED", True):
        print("[面板] 已在 config 里关闭（PANEL_ENABLED=False）")
        return False
    # 关键：**不要** SO_REUSEADDR。Windows 上它会把"端口已被别的程序占用"变成假装成功 ——
    # 0.0.0.0:8787 能绑上，但访问 127.0.0.1:8787 会被绑得更精确的那个程序接走，
    # 你会一直看到别人的页面，而且一点报错都没有。（本项目实测踩到：8787 上
    # 另一个项目的面板正监听 127.0.0.1，我的 0.0.0.0 绑定"成功"却没接到请求。）
    # 宁可 bind 失败大声报出来。刚重启时可能撞 TIME_WAIT，重试几次。
    ThreadingHTTPServer.allow_reuse_address = False
    srv, last = None, None
    for _ in range(5):
        try:
            srv = ThreadingHTTPServer((host, port), Handler)
            break
        except OSError as e:
            last = e
            time.sleep(1.0)
    if srv is None:
        print(f"[面板] 启动失败：{type(last).__name__}: {last}", flush=True)
        print(f"[面板] 端口 {port} 被占用（或刚释放还没到期）。监控继续跑，报警不受影响。", flush=True)
        print("[面板] 换端口：改 config.PANEL_PORT；关掉面板：PANEL_ENABLED=False", flush=True)
        return False
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="panel", daemon=True).start()
    _server = srv
    urls = lan_urls(port)
    # flush=True 是必须的：计划任务把 stdout 重定向到文件时是**块缓冲**，
    # 不 flush 的话这几行"面板地址"会憋到第一轮报告打印时才出现 ——
    # 用户去看日志会以为面板根本没起来。
    print(f"[面板] 本机 http://127.0.0.1:{port}/", flush=True)
    for u in urls[:4]:
        print(f"[面板] 手机试这个（要和你手机同一网段）：{u}", flush=True)
    # 自检：确认应答的是我们。SO_REUSEADDR 那种"假成功"在这里会被抓出来。
    if not _probe(port):
        print(f"[面板] ⚠ 警告：{port} 端口上应答的不是本项目（可能被别的程序抢占）——"
              f"请改 config.PANEL_PORT 换一个端口。监控与报警不受影响。", flush=True)
    return True


def stop():
    global _server
    if _server is not None:
        try:
            _server.shutdown()
            _server.server_close()
        except Exception:
            pass
        _server = None
