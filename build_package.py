# -*- coding: utf-8 -*-
"""打包给对方：平铺结构（跟他的包一致）+ 我们的说明文档。

排除：config_local.py（密钥）、运行时状态、__pycache__、日志、备份、
      过期的 crypto_monitor/ 副本、github_download/、_merge/_tmp。
"""
import os, io, re, shutil, zipfile, sys

SRC = r"M:\hermes\workspace\dev\crypto-monitor-v3"
OUT = r"M:\hermes\workspace\dev\dist"
NAME = "crypto-monitor_三币版_20261011"
STAGE = os.path.join(OUT, NAME)

# 要打包的文件（平铺，和他的包结构一致）
FILES = [
    # —— 他的原文件（逻辑未改）——
    "api.py", "backtest.py", "check_all_alerts.py", "check_coin.py",
    "config.py", "full_analysis.py", "indicators.py", "main.py",
    "news.py", "notifier.py", "predict.py", "strategy.py", "update_doc.py",
    "alert_state.py",
    # —— 我们新增 ——
    "panel.py", "panel.html", "panel_chart.py", "panel_adapter.py",
    "push_switch.py", "small_signal_switch.py", "gate_keys.py", "kline_cache.py",
    # —— 架构分离后的模块（main.py 依赖它们，必须带，否则跑不起来）——
    "signals.py", "report.py", "pushing.py", "alerting.py", "siglog.py",
    "verify_alerts.py", "verify_boll.py", "verify_cache.py", "verify_keys.py",
    "verify_panel.py", "verify_push_switch.py", "verify_signal_tiers.py",
    "verify_small_switch.py", "verify_backtest.py", "verify_siglog.py", "preview_boll.py",
    # —— 回测审计工具（报告里引用的证据脚本，可复现）——
    "audit_backtest.py", "audit_fantasy_price.py", "audit_backtest_honest.py",
    "audit_backtest_fixed.py", "audit_real_signals.py", "audit_by_type.py",
    # —— 配置模板 ——
    "config_local.py.example",
    # —— 依赖 ——
    "requirements.txt",
    # —— 文档 ——
    "变更说明_20261011.md", "架构分离说明_20261009.md", "信号日志说明_20261010.md",
    "合并说明_20261007.md", "回测审计报告_20261008.md", "对方代码问题清单.md",
    "使用说明.md", "全方位分析模板.png", "策略版本记录.docx",
    # —— 他的启动脚本（原样带上，路径他自己改）——
    "自动重启.bat",
]

# _merge 工具目录（保留结构，但排除 _tmp）
MERGE_FILES = ["reapply.py", "README.md"]
MERGE_BASE = ["api.py", "config.py", "indicators.py", "main.py",
              "news.py", "notifier.py", "strategy.py"]

# _merge/ 是我们内部的三方合并工具（他不需要；且 base/ 快照里含我们的 webhook）
# → 整个不打包，只在说明文档里提一句。
MERGE_FILES = []
MERGE_BASE = []

if os.path.isdir(STAGE):
    shutil.rmtree(STAGE)
os.makedirs(STAGE)

missing, copied = [], []
for f in FILES:
    s = os.path.join(SRC, f)
    if os.path.isfile(s):
        shutil.copy2(s, os.path.join(STAGE, f))
        copied.append(f)
    else:
        missing.append(f)

# analysis/ 下的分析脚本（放进 analysis/ 子目录，方便他自己复现）
ANA = ["export_siglog.py"]
_ad = os.path.join(STAGE, "analysis")
for f in ANA:
    s = os.path.join(SRC, "analysis", f)
    if os.path.isfile(s):
        if not os.path.isdir(_ad):
            os.makedirs(_ad)
        shutil.copy2(s, os.path.join(_ad, f))
        copied.append("analysis/" + f)
    else:
        missing.append("analysis/" + f)

# 安全自检：动态读我们自己 config_local.py 里的 webhook，检查有没有混进包里
OUR_HOOK = ""
cl = os.path.join(SRC, "config_local.py")
if os.path.isfile(cl):
    m = re.search(r"hook/([a-z0-9-]{20,})", io.open(cl, encoding="utf-8").read())
    if m:
        OUR_HOOK = m.group(1)

print("════════ 打包内容 ════════")
for c in sorted(copied):
    sz = os.path.getsize(os.path.join(STAGE, c))
    print("  %-38s %8d B" % (c, sz))
if missing:
    print()
    print("  ⚠️ 源里没找到（跳过）: %s" % ", ".join(missing))

print()
print("════════ 安全自检 ════════")
print("  我方 webhook 指纹（末8位）: %s" % (OUR_HOOK[-8:] if OUR_HOOK else "未读到"))
bad = []
for root, dirs, files in os.walk(STAGE):
    for f in files:
        p = os.path.join(root, f)
        rel = os.path.relpath(p, STAGE)
        if f == "config_local.py":
            bad.append("%s (密钥文件)" % rel)
        if f.endswith((".log", ".pyc")) or f == "pushed.json" \
                or (f.startswith("alert_state") and f.endswith(".json")) \
                or f in ("push_switch.json", "small_signal_switch.json"):
            bad.append("%s (运行时文件)" % rel)
        try:
            t = io.open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if OUR_HOOK and OUR_HOOK in t:
            bad.append("%s (★含我方 webhook)" % rel)
print("  %s" % ("✓ 干净：无我方密钥、无日志、无运行时状态" if not bad
                else "❌ 发现问题:\n      " + "\n      ".join(bad)))

# 打 zip
zp = os.path.join(OUT, NAME + ".zip")
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for root, dirs, files in os.walk(STAGE):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, STAGE)
            z.write(full, os.path.join(NAME, rel))

print()
print("════════ 成品 ════════")
print("  %s" % zp)
print("  大小: %d 字节 (%.1f KB)" % (os.path.getsize(zp), os.path.getsize(zp) / 1024.0))
with zipfile.ZipFile(zp) as z:
    n = len(z.namelist())
    print("  文件数: %d" % n)
    print()
    print("  ▸ 顶层结构：")
    tops = sorted({nm.split("/")[1] for nm in z.namelist() if len(nm.split("/")) > 1 and nm.split("/")[1]})
    for t in tops[:50]:
        print("      %s" % t)
sys.exit(1 if bad else 0)
