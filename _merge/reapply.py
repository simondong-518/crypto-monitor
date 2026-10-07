#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把对方发来的新代码重新贴回「我方改动」（三方合并，多文件）。

为什么需要这个
    对方习惯整包重发代码。直接覆盖会丢掉我们的东西：面板接线、推送总闸、
    小信号开关、BOLL 15m/1h 口径、两处崩溃修复、日志逐行刷新、新闻缓存……

原理（三方合并）
    base   = _merge/base/<文件>   对方 v3.7 —— 我方改动所基于的版本
    ours   = ./<文件>             我方当前版本
    theirs = 对方新包里的 <文件>
    git merge-file：
      · 他的新功能   → 自动带进来
      · 我方改动     → 自动保住
      · 两边都动过同一处 → 冲突，默认**取 his**（他的重构通常是取代旧代码）

用法
    python _merge/reapply.py <他的新目录>                 # 试运行（只报告）
    python _merge/reapply.py <他的新目录> --write         # 写入（先自动备份）
    python _merge/reapply.py <他的新目录> --files main.py,notifier.py
    python _merge/reapply.py <他的新目录> --write --out-dir ./merged

安全
    · 默认试运行，不碰任何文件
    · --write 前每个文件自动备份为 <文件>.bak_<时间戳>
    · 合并后做接缝自检；我方接缝缺失就报错且**拒绝写入**
"""
import io
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE_DIR = os.path.join(HERE, "base")

# 默认合并这些（我们会改、他也可能改的）
DEFAULT_FILES = ["main.py", "notifier.py", "news.py", "indicators.py"]

# ── 我方接缝清单：合并后必须都在 ────────────────────────────────
SEAMS = {
    "main.py": [
        ("面板导入",      "import panel"),
        ("面板适配器",    "import panel_adapter"),
        ("面板启动",      "panel.start()"),
        ("面板视图收集",  "coin_view("),
        ("面板发布",      "panel.publish"),
        ("小信号开关",    "small_signal_switch"),
        ("BOLL 15m/1h",   "_boll_open_up"),
        ("崩溃修复·盘口", "补缺口"),
        ("崩溃修复·影线", "同批缺口"),
        ("日志逐行刷新",  "line_buffering"),
    ],
    "notifier.py": [
        ("推送总闸",      "push_switch"),
        ("通道可用状态",  "get_channels"),
    ],
    "news.py": [
        ("新闻缓存",      "kline_cache"),
    ],
    "indicators.py": [],
}

# ── 对方新功能：合并后应当出现（缺了说明没合进来）────────────────
FEATURES = {
    "main.py": [
        ("缩量慢涨",     "check_shrink_rise"),
        ("缩量慢跌",     "check_shrink_drop"),
        ("BOLL破轨过滤", "check_boll_breakout"),
        ("板块联动",     "板块联动"),
        ("变盘位置",     "变盘位置"),
    ],
    "indicators.py": [
        ("BOLL破轨过滤", "check_boll_breakout"),
    ],
    "news.py": [],
    "notifier.py": [],
}


def _lf(path):
    with io.open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


def _merge_file(base, ours, theirs, auto_theirs):
    tmp = os.path.join(HERE, "_tmp")
    os.makedirs(tmp, exist_ok=True)
    p = {}
    for name, text in (("base", base), ("ours", ours), ("theirs", theirs)):
        p[name] = os.path.join(tmp, name + ".py")
        with io.open(p[name], "w", encoding="utf-8", newline="") as f:
            f.write(text)
    cmd = ["git", "merge-file", "-p"]
    if auto_theirs:
        cmd.append("--theirs")
    cmd += [p["ours"], p["base"], p["theirs"]]
    r = subprocess.run(cmd, capture_output=True)
    return r.stdout.decode("utf-8"), r.returncode


def _conflict_blocks(text):
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("<<<<<<<"):
            j = i
            while j < len(lines) and not lines[j].startswith(">>>>>>>"):
                j += 1
            mid = j
            for k in range(i, j + 1):
                if lines[k].startswith("======="):
                    mid = k
                    break
            out.append((i + 1, j + 1,
                        [l for l in lines[i + 1:mid]],
                        [l for l in lines[mid + 1:j]]))
            i = j + 1
        else:
            i += 1
    return out


def _check(text, items):
    bad = []
    for label, key in items:
        if key not in text:
            bad.append(label)
    return bad


# ── 语义 fixup：三方合并解决不了的、需要"两边都要"的地方 ──────────
def _fixup_news_cache(text):
    """news.py：对方换了新闻源，我方要保留缓存 → 他的源 + 我们的缓存壳。

    合并后他的 get_latest_news() 是内联抓取。这里把它拆成：
        get_latest_news()  = 缓存壳（我方，稳定）
        _fetch_news()      = 他的抓取逻辑（他的领域）
    以后他再改源，只要改 _fetch_news，两边就几乎不会再冲突。
    """
    if "kline_cache" in text:
        return text, False
    if "\nimport time" not in text:
        text = text.replace("import re\n", "import re\nimport time\n", 1)
    m = re.search(r'def get_latest_news\(\):\n(?:    """.*?"""\n)?', text, re.S)
    if not m:
        return text, False
    wrapper = (
        'def get_latest_news():\n'
        '    """取新闻（对方的新源 + 我方缓存）。\n'
        '\n'
        '    我方补充：走缓存 —— 资讯不是每分钟都变，能省则省。\n'
        '    源换成了对方的（国内可访问），抓取逻辑在 _fetch_news。\n'
        '    """\n'
        '    try:\n'
        '        import kline_cache\n'
        '        ttl = kline_cache.ttl_for("news")\n'
        '        if ttl > 0:\n'
        '            bucket = int(time.time()) // max(ttl, 1) * max(ttl, 1)\n'
        '            return kline_cache.get_or_fetch(("news", bucket), ttl, _fetch_news)\n'
        '    except Exception as e:\n'
        '        print(f"[news] 缓存跳过（{type(e).__name__}: {e}），改为直接取", flush=True)\n'
        '    return _fetch_news()\n'
        '\n'
        '\n'
        'def _fetch_news():\n'
    )
    text = text[:m.start()] + wrapper + text[m.end():]
    return text, True


FIXUPS = {
    "news.py": [("新闻缓存壳", _fixup_news_cache)],
    "notifier.py": [("webhook 默认值", None)],   # 占位，下面替换
}


def _fixup_notifier_webhook(text):
    """notifier.py：对方硬编码了他的新群 webhook，我方有 env/config_local 覆盖链。

    合并后两者并存 → 我方那行 `os.environ.get(..., "")` 会把对方的新群**清空**。
    修法：把对方的新群当**默认值**，我方覆盖链照旧（覆盖不到就用他的群）。
    """
    old = 'FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")'
    new = 'FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK") or FEISHU_WEBHOOK'
    if new in text:
        return text, False
    if old not in text:
        return text, False
    # 必须有硬编码的 webhook 在上方，否则 `or FEISHU_WEBHOOK` 会 NameError
    head = text.split(old)[0]
    if "open.feishu.cn/open-apis/bot/v2/hook/" not in head:
        return text, False
    return text.replace(old, new, 1), True


FIXUPS["notifier.py"] = [("webhook 默认值", _fixup_notifier_webhook)]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    src = args[0]
    write = "--write" in sys.argv
    out_dir = None
    if "--out-dir" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--out-dir") + 1]
    files = DEFAULT_FILES
    if "--files" in sys.argv:
        files = [f.strip() for f in sys.argv[sys.argv.index("--files") + 1].split(",") if f.strip()]

    # src 可以是目录，也可以是单个 main.py
    if os.path.isdir(src):
        src_dir, src_file = src, None
    else:
        src_dir, src_file = os.path.dirname(src), os.path.basename(src)

    print("═" * 70)
    print("  三方合并重贴（多文件）")
    print("═" * 70)
    print(f"  他的新代码: {src}")
    print(f"  我方仓库  : {ROOT}")
    print(f"  模式      : {'写入' if write else '试运行（不写文件）'}")

    results = {}
    for fn in files:
        print("\n" + "─" * 70)
        print(f"  【{fn}】")
        b_path = os.path.join(BASE_DIR, fn)
        o_path = os.path.join(ROOT, fn)
        t_path = os.path.join(src_dir, fn) if src_file is None else src
        if src_file is not None and fn != src_file:
            continue
        if not os.path.exists(b_path):
            print(f"    跳过：基线 {os.path.relpath(b_path, ROOT)} 不存在")
            continue
        if not os.path.exists(o_path):
            print(f"    跳过：我方没有 {fn}")
            continue
        if not os.path.exists(t_path):
            print(f"    跳过：他的包里没有 {fn}")
            continue

        base, ours, theirs = _lf(b_path), _lf(o_path), _lf(t_path)
        raw, _ = _merge_file(base, ours, theirs, auto_theirs=False)
        conf = _conflict_blocks(raw)
        print(f"    行数 base={len(base.splitlines())} "
              f"ours={len(ours.splitlines())} theirs={len(theirs.splitlines())}")
        print(f"    冲突：{len(conf)} 处")
        for n, (a, b, ours_side, theirs_side) in enumerate(conf, 1):
            print(f"      ── 冲突 {n}（第 {a}~{b} 行）")
            if ours_side:
                print(f"         我方首行: {ours_side[0][:80]}")
            if theirs_side:
                print(f"         他方首行: {theirs_side[0][:80]}")
            else:
                print(f"         他方: （删除）")
            results.setdefault("conf", []).append((fn, n, ours_side, theirs_side))

        merged, _ = _merge_file(base, ours, theirs, auto_theirs=True)
        if "<<<<<<<" in merged:
            print("    ⚠️ 仍有未解冲突标记，需手工处理")
            results.setdefault("unresolved", []).append(fn)
            continue

        # 语义 fixup：三方合并解决不了的、需要"两边都要"的地方
        for label, fn_fix in FIXUPS.get(fn, []):
            merged, changed = fn_fix(merged)
            print(f"      {'应用' if changed else '已存在'} fixup·{label}")

        bad = _check(merged, SEAMS.get(fn, []))
        feat = _check(merged, FEATURES.get(fn, []))
        for label, key in SEAMS.get(fn, []):
            print(f"      {'OK  ' if key in merged else 'MISS'} 接缝·{label}")
        for label, key in FEATURES.get(fn, []):
            print(f"      {'OK  ' if key in merged else 'MISS'} 他的·{label}")
        if bad:
            results.setdefault("bad_seam", []).append((fn, bad))

        results.setdefault("merged", {})[fn] = merged
        print(f"    合并结果：{len(merged.splitlines())} 行")

    print("\n" + "═" * 70)
    if results.get("bad_seam"):
        for fn, bad in results["bad_seam"]:
            print(f"  ❌ {fn} 接缝缺失：{', '.join(bad)}")
    if results.get("unresolved"):
        print(f"  ❌ 未解冲突：{', '.join(results['unresolved'])}")

    if not write:
        print("  【试运行】没有写入任何文件。确认无误后加 --write")
        return 1 if (results.get("bad_seam") or results.get("unresolved")) else 0

    if results.get("bad_seam") or results.get("unresolved"):
        print("  ❌ 有问题，拒绝写入。")
        return 1

    stamp = time.strftime("%Y%m%d_%H%M%S")
    for fn, merged in results.get("merged", {}).items():
        dst = os.path.join(out_dir, fn) if out_dir else os.path.join(ROOT, fn)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        else:
            shutil.copy2(os.path.join(ROOT, fn), os.path.join(ROOT, fn + f".bak_{stamp}"))
        with io.open(dst, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(merged)
        print(f"  已写入 {dst}" + ("" if out_dir else f"（备份 {fn}.bak_{stamp}）"))
    print("\n  下一步：python -m py_compile main.py  然后跑自检")
    return 0


if __name__ == "__main__":
    sys.exit(main())
