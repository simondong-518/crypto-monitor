# -*- coding: utf-8 -*-
"""架构分离 · 抽取器

把 main.py 里"信号 / 报告 / 推送 / 冷却"四块**逐字搬运**到独立模块。
所有切片都按"标记行"定位并断言，搬过去的代码与原文一字不差（只做统一缩进），
因此行为等价性可由 verify_refactor.py 的金标准对比来证明。

用法：
    python _refactor/extract.py --dry     # 只打印边界/自由变量，不写文件
    python _refactor/extract.py --write   # 生成模块 + 重写 main.py
"""
import io
import os
import sys
import ast
import textwrap
import builtins

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "main.py")
src = io.open(SRC, encoding="utf-8-sig").read()
L = src.splitlines()


def find(sub, start=0, end=None):
    end = len(L) if end is None else end
    for i in range(start, end):
        if sub in L[i]:
            return i
    raise SystemExit("!! 找不到标记: %r (from %d)" % (sub, start))


def block(a, b):
    """取 [a, b) 行，去掉首尾空行"""
    seg = L[a:b]
    while seg and not seg[0].strip():
        seg.pop(0)
    while seg and not seg[-1].strip():
        seg.pop()
    return seg


def dedent4(seg):
    """整段左移 4 空格（只对以 4 空格开头的行）"""
    out = []
    for ln in seg:
        if ln.startswith("    "):
            out.append(ln[4:])
        elif ln.strip() == "":
            out.append("")
        else:
            raise SystemExit("!! 缩进异常(不足4空格): %r" % ln)
    return out


def dedent8(seg):
    """整段左移 8 空格（12 -> 4）"""
    out = []
    for ln in seg:
        if ln.startswith("        "):
            out.append(ln[8:])
        elif ln.strip() == "":
            out.append("")
        else:
            raise SystemExit("!! 缩进异常(不足8空格): %r" % ln)
    return out


def free_names(seg):
    """把片段当成函数体，求它的自由变量（Load 但未在内部绑定）"""
    code = "\n".join(ln[4:] if ln.startswith("    ") else ln for ln in seg)
    wrap = "def _f(rep):\n" + textwrap.indent(code, "    ") + "\n"
    try:
        tree = ast.parse(wrap)
    except SyntaxError as e:
        raise SystemExit("!! 片段语法错误（缩进/continue?）: %s" % e)
    fn = tree.body[0]
    bound, used = set(), set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name):
            (bound if isinstance(n.ctx, (ast.Store, ast.Del)) else used).add(n.id)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
    return sorted(used - bound)


# ── 定位所有边界 ──────────────────────────────────────────────
i_fmt      = find("def fmt_money(v):")
i_dt       = find("from datetime import datetime")
i_pushed   = find("# 加载之前保存的推送记录")
i_alertcmt = find("# ── 报警冷却状态（我方）")
i_should   = find("def should_alert(key):")
i_pushednews = find("pushed_news = set()")
i_slowlock = find("SLOW_START_LOCK = {}")
i_signal_lk = find("SIGNAL_LOCK = {}")
i_flowprev = find("FLOW_PREV = {}")
i_lastflow = find("# 记录每个币上一轮的方向状态")
i_lastbt   = find("#回测结果全局变量")
i_shrink   = find("# 【2026-10-06 新增】缩量慢涨/慢跌信号锁")
i_savepush = find("def save_pushed():")
i_analyze  = find("def analyze_trades(")
i_upext    = find("# 动态更新当日有效高低点")
i_bollopen = find("def _boll_open_up(")
i_repkw    = find("_REPORT_KEYWORDS = (")
i_monitor  = find("def monitor_once():")
i_notices  = find("# BTC暴跌>3%避险提醒", i_monitor)
i_body     = find('ind_s = get_indicator(pair, "15m")', i_monitor)
i_partb    = find('lines.append(f"## {coin}/USDT 全方位分析:")', i_body)
i_except   = find("        except Exception as e:", i_partb)
i_sector   = find("# 2026-10-07 新增：板块联动判断", i_monitor)
i_panel1   = find("# ── 面板：发布本轮结果（只读展示）──", i_sector)
# 市场级提醒块（BTC避险/新闻/价格止盈止损）到 `except: pass` 为止；
# 再往后是 alerts_all/lines 初始化 + for 循环 + try:，那些属于框架层
i_notices_end = find("except: pass", i_notices) + 1
i_main     = find('if __name__ == "__main__":')

# 断言：关键边界行内容
assert L[i_body].strip() == 'ind_s = get_indicator(pair, "15m")'
assert L[i_partb].strip().startswith('lines.append(f"## {coin}/USDT')
assert L[i_except].strip() == "except Exception as e:"
assert L[i_sector].strip().startswith("# 2026-10-07 新增：板块联动")

# ── 切片 ──────────────────────────────────────────────────────
S_fmt      = block(i_fmt, i_dt)
S_pushed   = block(i_pushed, i_alertcmt)
S_alertst  = block(i_alertcmt, i_should)
S_should   = block(i_should, i_lastflow)
S_g_slow   = block(i_slowlock, i_signal_lk + 1)      # SLOW_START_LOCK + SIGNAL_LOCK
S_g_flow   = block(i_flowprev - 1, i_flowprev + 1)   # FLOW_PREV
S_globals  = block(i_lastflow, i_lastbt)
S_shrink   = block(i_shrink, i_savepush)
S_savepush = block(i_savepush, i_analyze)
S_analyze  = block(i_analyze, i_upext)
S_upext    = block(i_upext, i_bollopen)
S_bollopen = block(i_bollopen, i_repkw)
S_repkw    = block(i_repkw, i_monitor)
S_notices  = block(i_notices, i_notices_end)
S_body     = block(i_body, i_partb)
S_partb    = block(i_partb, i_except)
S_dispatch = block(i_sector, i_panel1)

# 统计诊断
diag = {
    "边界行号": dict(fmt=i_fmt + 1, pushed=i_pushed + 1, alertcmt=i_alertcmt + 1,
                     should=i_should + 1, lastflow=i_lastflow + 1, shrink=i_shrink + 1,
                     savepush=i_savepush + 1, analyze=i_analyze + 1, upext=i_upext + 1,
                     bollopen=i_bollopen + 1, repkw=i_repkw + 1, monitor=i_monitor + 1,
                     notices=i_notices + 1, body=i_body + 1, partb=i_partb + 1,
                     except_=i_except + 1, sector=i_sector + 1,
                     panel1=i_panel1 + 1, main=i_main + 1),
    "切片行数": dict(fmt=len(S_fmt), pushed=len(S_pushed), alertst=len(S_alertst),
                     should=len(S_should), globals=len(S_globals), shrink=len(S_shrink),
                     savepush=len(S_savepush), analyze=len(S_analyze), upext=len(S_upext),
                     bollopen=len(S_bollopen), repkw=len(S_repkw), notices=len(S_notices),
                     body=len(S_body), partb=len(S_partb), dispatch=len(S_dispatch)),
}

# continue / break 检查（body 里若有 continue，搬进函数会语法错）
body_continues = [i + i_body + 1 for i, ln in enumerate(S_body) if ln.strip() == "continue"]
body_breaks = [i + i_body + 1 for i, ln in enumerate(S_body) if ln.strip() == "break"]
diag["body内continue行号"] = body_continues
diag["body内break行号"] = body_breaks

# Part B 的自由变量
S_partb_out = [ln.replace("lines.append(", "out.append(") for ln in S_partb]
leftover_lines = [i + i_partb + 1 for i, ln in enumerate(S_partb_out)
                  if "lines" in ln and "out.append" not in ln]
diag["partb里残留lines的行号"] = leftover_lines
diag["partb自由变量"] = free_names(S_partb_out)

# last_backtest_result 相关
diag["last_backtest_result出现行"] = [i + 1 for i, ln in enumerate(L) if "last_backtest_result" in ln]
diag["MAX_FLOW出现行"] = [i + 1 for i, ln in enumerate(L) if "MAX_FLOW" in ln]

import json
print(json.dumps(diag, ensure_ascii=False, indent=1))

if "--write" not in sys.argv:
    print("\n(dry run，未写文件)")
    sys.exit(0)

# ── 生成模块 ──────────────────────────────────────────────────
HEAD = "# -*- coding: utf-8 -*-\n"

# 1) alerting.py
alerting = HEAD + '''"""报警冷却 / 去重 / 推送记录持久化。

架构分离自 main.py（纯搬运，逻辑一字未改）：
    · pushed.json 的加载与保存
    · 冷却状态 AlertState + should_alert / mark_alert
"""
import json
from alert_state import AlertState


''' + "\n".join(S_pushed) + "\n\n\n" + "\n".join(S_alertst) + "\n\n\n" + "\n".join(S_should) + "\n\n\n" + "\n".join(S_savepush) + "\n"

# 2) signals.py
signals = HEAD + '''"""信号判定层。

架构分离自 main.py（纯搬运，逻辑一字未改）。包含：
    · 信号锁 / 方向状态 等全局量
    · 缩量慢涨慢跌、BOLL 开口、当日有效高低点、资金分析 等判定函数
    · 信号分级 _is_report_signal（哪些进"带完整报告"）
    · evaluate_coin()：单个币 取数 → 指标快照 → 打分 → 全部信号判定
      返回 report.render() 需要的上下文（无重要信号则返回 None）

⚠️ 算法口径以对方为准，本模块只做搬运，不改任何阈值/触发条件。
"""
import json
import time
from datetime import datetime

from config import *
from api import get_kline, get_trades, get_ls, get_btc_chg, get_flow_1h
from indicators import get_indicator, get_daily_trend
from strategy import calc_score, get_signal, last_signal
from alert_state import stable_alert_key
from alerting import pushed, should_alert, mark_alert, save_pushed

# 只读 H5 面板（展示层）—— 不参与判定；导入失败也不能挡住监控
try:
    import panel_adapter
    _PANEL_IMPORT_OK = True
except Exception:
    _PANEL_IMPORT_OK = False


''' + "\n".join(S_fmt) + "\n\n\n" + "\n".join(S_g_slow) + "\n\n\n" + \
    "\n".join(S_g_flow) + "\n\n\n" + "\n".join(S_globals) + "\n\n\n" + \
    "\n".join(S_shrink) + "\n\n\n" + "\n".join(S_analyze) + "\n\n\n" + \
    "\n".join(S_upext) + "\n\n\n" + "\n".join(S_bollopen) + "\n\n\n" + \
    "\n".join(S_repkw) + "\n\n\n"

# evaluate_coin
body_d = dedent4(S_body)
# continue → return None
joined = "\n".join(body_d)
assert "        if not has_important:\n            continue" in joined, "没找到 has_important 的 continue"
joined = joined.replace("        if not has_important:\n            continue",
                        "        if not has_important:\n            return None")
_BUILTINS = set(dir(builtins))
free = [n for n in free_names(S_partb_out) if n != "coin" and n != "out"
        and n not in _BUILTINS]
ret_items = ["            'coin': coin,"] + ["            %r: %s," % (n, n) for n in free]
signals += '''def evaluate_coin(pair, coin, btc_chg, alerts_all, lines, coin_chg, panel_coins):
    """单个币：取数 → 指标快照 → 打分 → 全部信号判定（含分级）。

    返回 report.render() 需要的上下文 dict；
    该币本轮没有"带完整报告"的重要信号（或取数异常）时返回 None。
    """
    try:
''' + joined + '''
        return {
''' + "\n".join(ret_items) + '''
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"{coin}出错: {e}")
        return None
'''

# 3) report.py
report = HEAD + '''"""报告渲染层。

架构分离自 main.py（纯搬运，逻辑一字未改）：把某个币的
"全方位分析" 表格 + 持仓/空仓建议 渲染成 markdown 行。
"""
from config import *
from signals import _is_report_signal  # noqa: F401  (保持与原上下文一致)

''' + "def render(rep):\n" + '''    """rep: signals.evaluate_coin() 返回的上下文 dict → 报告行 list"""
    out = []
''' + "".join('    %s = rep[%r]\n' % (n, n) for n in ["coin"] + free) + \
    "\n".join(dedent8(S_partb_out)) + '''
    return out
'''

# 4) pushing.py
pushing = HEAD + '''"""推送编排层。

架构分离自 main.py（纯搬运，逻辑一字未改）：
    · check_market_notices()：BTC 避险 / 新闻 / 价格止盈止损（市场级提醒）
    · dispatch()：板块联动 + 信号分级 → 标题/正文 → 发送 → 落盘
"""
import time
from datetime import datetime

from config import *
from indicators import get_indicator
from news import get_latest_news
from notifier import send_wx
from alerting import pushed, should_alert, mark_alert, save_pushed
from signals import _is_report_signal

# 新闻推送全局变量
pushed_news = set()
last_news_date = ""
news_count = 0


''' + "def check_market_notices(btc_chg):\n" + '''    """市场级提醒：BTC 避险 / 新闻 / 价格止盈止损。"""
    global last_news_date, news_count
''' + "\n".join(S_notices) + "\n\n\n"

disp_d = dedent4(S_dispatch)
pushing += "def dispatch(alerts_all, lines, coin_chg, last_backtest_result=\"\"):\n" + \
    '''    """板块联动 + 信号分级推送。返回是否真的发出去了。"""
''' + textwrap.indent("\n".join(disp_d), "    ") + "\n"

# 5) 新 main.py —— 由原文件重组
main_head = block(0, i_fmt)                     # 头部：编码/sys 包装
main_imports = block(i_dt, i_pushednews)            # import 段
main_tail_loop = block(i_main, len(L))          # __main__ 主循环

new_main = "\n".join(main_head) + "\n" + "\n".join(main_imports) + '''

# ── 分层模块（架构分离：指标/信号/报告/推送/冷却 各自独立，便于修改）──
from alerting import pushed, should_alert, mark_alert, save_pushed
from signals import (SLOW_START_LOCK, SIGNAL_LOCK, FLOW_PREV,
                     LAST_FLOW_DIR, LAST_RSI_STATE,
                     MAX_FLOW_IN_15M, MAX_FLOW_OUT_15M, SHRINK_LOCK,
                     fmt_money, check_shrink_rise, check_shrink_drop,
                     analyze_trades, update_daily_extreme, _boll_open_up,
                     _is_report_signal, evaluate_coin, _REPORT_KEYWORDS)
from alert_state import stable_alert_key
import report
import pushing
from backtest import backtest, daily_backtest, last_result as last_backtest_result

# 只读 H5 面板（展示层）—— 不参与判定；导入失败也不能挡住监控
try:
    import panel
    import panel_adapter
    _PANEL_IMPORT_OK = True
except Exception as _e:
    _PANEL_IMPORT_OK = False
    print(f"[面板] 未启用（导入失败）：{type(_e).__name__}: {_e}", flush=True)

#回测结果全局变量
last_backtest_result = ""


def monitor_once():
    """一轮监测：市场级提醒 → 逐币判定 → 分级推送 → 面板发布。"""
    _round_t0 = time.time()      # 面板"上一轮耗时"用（纯展示）
    panel_coins = []             # 面板：本轮各币只读视图
    btc_chg = get_btc_chg()
    pushing.check_market_notices(btc_chg)

    alerts_all = []
    coin_chg = {}  # 2026-10-07 新增：存所有币今日涨跌幅，用于板块联动判断
    lines = ["# 📈 K线监测报告", f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    for pair in CURRENCY_PAIRS:
        coin = pair.replace("_USDT", "")
        rep = evaluate_coin(pair, coin, btc_chg, alerts_all, lines, coin_chg, panel_coins)
        if rep is not None:
            lines.extend(report.render(rep))

    pushing.dispatch(alerts_all, lines, coin_chg, last_backtest_result)

    if alerts_all:
        # ── 面板：发布本轮结果（只读展示）──
        try:
            if _PANEL_IMPORT_OK:
                panel.publish(coins=panel_coins,
                              alerts=[{'t': datetime.now().strftime('%H:%M:%S'),
                                       'coin': c, 'text': ', '.join(a)} for c, a in alerts_all],
                              errors=[], btc_chg=btc_chg,
                              duration=time.time() - _round_t0)
        except Exception as _pe:
            print(f"[面板] 发布失败：{type(_pe).__name__}: {_pe}", flush=True)

    # ── 面板：本轮无报警也要发布（页面才能看到最新状态）──
    try:
        if _PANEL_IMPORT_OK and not alerts_all:
            panel.publish(coins=panel_coins, alerts=[], errors=[],
                          btc_chg=btc_chg, duration=time.time() - _round_t0)
    except Exception as _pe:
        print(f"[面板] 发布失败：{type(_pe).__name__}: {_pe}", flush=True)


''' + "\n".join(main_tail_loop) + "\n"

for name, content in [("alerting.py", alerting), ("signals.py", signals),
                      ("report.py", report), ("pushing.py", pushing),
                      ("main.py", new_main)]:
    io.open(os.path.join(ROOT, name), "w", encoding="utf-8").write(content)
    print("written:", name, len(content.splitlines()), "行")
print("\n完成。")
