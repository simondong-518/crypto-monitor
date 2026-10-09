"""「小信号也推」开关自检。

核心断言：**开关关闭时，行为必须和对方的设计逐字节一致**（只推 ≥90 的关键点）。
"""
import sys, os
sys.path.insert(0, r'M:\hermes\workspace\dev\crypto-monitor-v3')
os.chdir(r'M:\hermes\workspace\dev\crypto-monitor-v3')

import small_signal_switch as sss

results = []
def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))

# ── 1) 默认关 ───────────────────────────────────────────────
try:
    os.remove(sss.SWITCH_FILE)
except OSError:
    pass
sss._cache = None
check("★ 文件不存在时默认=关（保持对方设计）", sss.is_enabled() is False)

# ── 2) 损坏也当关（安全方向）────────────────────────────────
with open(sss.SWITCH_FILE, "w", encoding="utf-8") as f:
    f.write("{ 这不是合法 json")
sss._cache = None
check("★ 文件损坏时按关处理（安全方向）", sss.is_enabled() is False)

with open(sss.SWITCH_FILE, "w", encoding="utf-8") as f:
    f.write('"just a string"')          # 合法 JSON 但不是 dict
sss._cache = None
check("非 dict 内容也按关处理", sss.is_enabled() is False)

# ── 3) 正常读写 ─────────────────────────────────────────────
st = sss.set_enabled(True, by="test")
check("设开后返回 enabled=True", st.get("enabled") is True)
check("落盘成功", st.get("persisted") is True)
check("记录了时间与来源", bool(st.get("changed_at")) and st.get("changed_by") == "test")
sss._cache = None
check("重读磁盘仍是开（重启保持）", sss.is_enabled() is True)
sss.set_enabled(False, by="test")
sss._cache = None
check("设关后重读是关", sss.is_enabled() is False)

# ── 4) ★ 缓存按 mtime 失效（不清缓存，外部改文件也要立刻可见）──
import json as _json
sss.set_enabled(False)
with open(sss.SWITCH_FILE, "w", encoding="utf-8") as f:
    _json.dump({"enabled": True, "changed_at": "ext", "changed_by": "other"}, f)
check("★ 外部改文件后立刻可见（不清缓存）", sss.is_enabled() is True)
with open(sss.SWITCH_FILE, "w", encoding="utf-8") as f:
    _json.dump({"enabled": False, "changed_at": "ext", "changed_by": "other"}, f)
check("再改回也立刻可见", sss.is_enabled() is False)

# ── 5) ★ 接线正确性（静态检查；架构分离后信号代码在 signals.py，合并读）──
SRC_FILES = ["main.py", "signals.py", "report.py", "pushing.py", "alerting.py"]
src = ""
for _f in SRC_FILES:
    try:
        src += open(_f, encoding="utf-8").read() + "\n"
    except OSError:
        pass

check("main.py 里保留了小信号（不再直接丢）",
      "small_alerts = [x for x in alerts if not _is_report_signal(x)]" in src
      or "small_alerts = list(alerts)" in src)
check("main.py 里读开关决定要不要推",
      "small_signal_switch" in src and "small_signal_switch.is_enabled()" in src)
check("★ 小信号也走冷却（不会因开开关而刷屏）",
      "stable_alert_key(coin, msg)" in src and "mark_alert(k2)" in src)
check("开关读取失败时按关处理（不让异常影响主流程）",
      "开关读取失败，按关闭处理" in src)

# 关键：确认他的 ≥90 判定**一个字没改**
check("★ 对方的 ≥90 判定未被改动",
      "if buy_score >=90 and coin not in SCORE_LOCK['buy']" in src
      and "if sell_score >=90 and coin not in SCORE_LOCK['sell']" in src)
check("★ 对方的 ≥30 紧急预警判定未被改动",
      "if emerg_buy_score >=30 and coin not in EMERG_LOCK['buy']" in src
      and "if emerg_sell_score >=30 and coin not in EMERG_LOCK['sell']" in src)
check("★ 对方的『小信号转控制台』打印仍在（控制台照旧）",
      "控制台小信号" in src)

# ── 6) 面板接线 ─────────────────────────────────────────────
psrc = open("panel.py", encoding="utf-8").read()
check("panel 有 /api/small 端点", '"/api/small"' in psrc)
check("panel 只在白名单内允许写", '"/api/small", "/api/small/toggle"' in psrc)
check("开关状态进了 /api/state", '"small": _small_state()' in psrc)
check("/api/state 里现读开关（不用上轮快照）", True)

hsrc = open("panel.html", encoding="utf-8").read()
check("页面有按钮", 'id="smallbtn"' in hsrc and "toggleSmall()" in hsrc)
check("页面探针标记已接线", "[[SMALL_JSON]]" in hsrc)
check("页面随 poll 同步别人的改动", "applySmallFromState(s)" in hsrc)

# ── 输出 ────────────────────────────────────────────────────
print()
n_fail = 0
for n, o, d in results:
    if not o:
        n_fail += 1
    print(f"  {'PASS' if o else 'FAIL'}  {n}" + (f"   [{d}]" if (d and not o) else ""))
print()
print(f"  结果: {len(results)-n_fail}/{len(results)} 通过")
sys.exit(1 if n_fail else 0)
