"""推送开关自检：默认关闭 / 落盘 / 全局共享 / 关掉时不发对外通道。

用法： <解释器> verify_push_switch.py          （不依赖服务是否在跑）
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
results = []


def check(name, ok, note=""):
    results.append((name, bool(ok), note))


import push_switch

# ── 备份真实开关文件，测完还原（绝不能把用户的状态改坏）──
REAL = push_switch.SWITCH_FILE
backup = None
if os.path.exists(REAL):
    backup = io.open(REAL, encoding="utf-8").read()

tmpdir = tempfile.mkdtemp(prefix="pushsw_")
try:
    # 1) 文件不存在 → 默认必须是"停"
    push_switch.SWITCH_FILE = os.path.join(tmpdir, "nofile.json")
    push_switch._cache = None
    st = push_switch.get_state()
    check("文件不存在时默认为「停止推送」", st.get("enabled") is False, str(st))
    check("默认状态不含时间戳（说明是新状态）", st.get("changed_at") is None)

    # 2) 打开 → 必须落盘，且能读回
    st = push_switch.set_enabled(True, by="test")
    check("开启后返回 enabled=True", st.get("enabled") is True)
    check("开启后文件已写入", os.path.exists(push_switch.SWITCH_FILE))
    check("写入结果是持久化的", st.get("persisted") is True)
    check("记录了修改时间", bool(st.get("changed_at")))
    check("记录了修改来源", st.get("changed_by") == "test")

    # 3) 清缓存重读（模拟"另一个浏览器/另一个进程"）→ 状态必须一致
    push_switch._cache = None
    check("重读磁盘后仍是开启（全局共享、重启不丢）",
          push_switch.is_enabled() is True)

    # 3b) ★ 真实场景：**不清缓存**，外部进程直接改文件 —— 必须立刻可见
    #     （踩过的坑：缓存只写不失效 → 接口报旧值 → 页面上点按钮"没反应"）
    import json as _json
    with io.open(push_switch.SWITCH_FILE, "w", encoding="utf-8") as f:
        _json.dump({"enabled": False, "changed_at": "ext", "changed_by": "other"}, f)
    check("外部改文件（关）后立刻可见，无需清缓存",
          push_switch.is_enabled() is False, "缓存没有按 mtime 失效")
    with io.open(push_switch.SWITCH_FILE, "w", encoding="utf-8") as f:
        _json.dump({"enabled": True, "changed_at": "ext", "changed_by": "other"}, f)
    check("外部再改文件（开）后也立刻可见",
          push_switch.is_enabled() is True, "缓存没有按 mtime 失效")

    # 4) 关闭 → 落盘
    st = push_switch.set_enabled(False, by="test2")
    push_switch._cache = None
    check("关闭后重读仍是关闭", push_switch.is_enabled() is False)

    # 5) 文件损坏 → 必须当"停"，绝不能当"开"
    with io.open(push_switch.SWITCH_FILE, "w", encoding="utf-8") as f:
        f.write("{ 这不是合法 json")
    push_switch._cache = None
    check("文件损坏时按「停止推送」处理（安全方向）",
          push_switch.is_enabled() is False)

    # 6) 内容被改成非法类型（比如字符串）→ 也是"停"
    with io.open(push_switch.SWITCH_FILE, "w", encoding="utf-8") as f:
        f.write('"true"')
    push_switch._cache = None
    check("内容类型异常时按「停止推送」处理",
          push_switch.is_enabled() is False)

    # 7) toggle 行为
    push_switch.set_enabled(False, by="test")
    push_switch.toggle(by="test")
    check("toggle 能从关翻到开", push_switch.is_enabled() is True)
    push_switch.toggle(by="test")
    check("toggle 能从开翻到关", push_switch.is_enabled() is False)

    # 8) 关掉时：对外通道不发，但文件留痕照写
    push_switch.SWITCH_FILE = os.path.join(tmpdir, "off.json")
    push_switch._cache = None
    push_switch.set_enabled(False, by="test")
    import notifier
    # 伪造一个"已配置"的飞书 webhook，确保跳过是因为开关、不是因为没配置
    orig_fw = notifier.FEISHU_WEBHOOK
    sent = {"called": False}
    orig_feishu = notifier._feishu

    def fake_feishu(title, desp):
        sent["called"] = True
        return True, "fake"

    notifier.FEISHU_WEBHOOK = "https://example.invalid/fake"
    notifier._feishu = fake_feishu
    orig_console = notifier.NOTIFY_CONSOLE
    notifier.NOTIFY_CONSOLE = False
    orig_file = notifier.NOTIFY_FILE
    notifier.NOTIFY_FILE = os.path.join(tmpdir, "alerts.log")
    notifier.reset_suppressed()
    try:
        notifier.send_wx("自检标题", "自检内容")
        check("开关关闭时【不调用】飞书发送", sent["called"] is False)
        check("开关关闭时仍写入文件留痕（报警不丢）",
              os.path.exists(notifier.NOTIFY_FILE)
              and "自检标题" in io.open(notifier.NOTIFY_FILE, encoding="utf-8").read())
        check("关掉时计数被累加（页面可显示暂存条数）",
              notifier.suppressed_count().get("n", 0) >= 1)

        # 9) 打开后 → 必须真的调用
        sent["called"] = False
        push_switch.set_enabled(True, by="test")
        push_switch._cache = None
        notifier.send_wx("开着的标题", "内容")
        check("开关打开时【会调用】飞书发送", sent["called"] is True)
    finally:
        notifier.FEISHU_WEBHOOK = orig_fw
        notifier._feishu = orig_feishu
        notifier.NOTIFY_CONSOLE = orig_console
        notifier.NOTIFY_FILE = orig_file

    # 10) 面板暴露的字段
    push_switch.SWITCH_FILE = os.path.join(tmpdir, "panel.json")
    push_switch._cache = None
    push_switch.set_enabled(False, by="web")
    import panel
    ps = panel._push_state()
    check("面板能读到开关状态", "enabled" in ps)
    check("面板状态默认是关", ps.get("enabled") is False)
    check("面板状态带 suppressed 计数", "suppressed" in ps)

    # 11) 页面里有按钮与说明
    src = io.open(os.path.join(HERE, "panel.html"), encoding="utf-8").read()
    check("页面有「开始推送」按钮文案", "开始推送" in src or "togglePush" in src)
    check("页面有「停止推送」逻辑", "停止推送" in src)
    check("页面声明开关是全局的", "全局" in src)
    check("页面说明与折叠记忆的区别", "localStorage" in src or "折叠" in src)
    check("页面有 /api/push 调用", "/api/push" in src)

    # 12) 服务端只允许改开关这一个东西（do_POST 白名单）
    psrc = io.open(os.path.join(HERE, "panel.py"), encoding="utf-8").read()
    check("面板 do_POST 只放行推送开关路径",
          '"/api/push"' in psrc and "/api/push/on" in psrc and "/api/push/off" in psrc)
    check("面板不含任意文件写入接口",
          "do_PUT" not in psrc and "do_DELETE" not in psrc)

finally:
    # 还原真实开关文件
    try:
        if backup is not None:
            with io.open(REAL, "w", encoding="utf-8") as f:
                f.write(backup)
        elif os.path.exists(REAL):
            os.remove(REAL)
        push_switch.SWITCH_FILE = REAL
        push_switch._cache = None
    except Exception:
        pass
    shutil.rmtree(tmpdir, ignore_errors=True)

# ── 输出 ──
w = max(len(n) for n, _o, _x in results)
fails = 0
for name, ok, note in results:
    flag = "PASS" if ok else "FAIL"
    if not ok:
        fails += 1
    print(f"  {flag}  {name}" + (f"   [{note}]" if (note and not ok) else ""))

print()
print(f"  结果: {len(results) - fails}/{len(results)} 通过")
sys.exit(1 if fails else 0)
