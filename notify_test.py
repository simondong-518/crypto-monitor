"""通知通道自检：真发一条测试消息，逐通道给出成功/失败**与原因**。

    python notify_test.py              # 真发一条（占用 Server酱 当日额度）
    python notify_test.py "自定义标题"
    python notify_test.py --list       # 只列出通道与配置摘要，不发任何消息

为什么需要它：钉钉/Server酱 都是 **HTTP 200 但返回体里报错**（errcode/errmsg、code/message），
只看"没报异常"会以为通了。这个脚本把每个通道的返回体原因打出来。

诚实边界：本脚本能证明**请求发出去了、对方收下了**；"你手机上真的看到了"只有你自己看手机才知道。
"""
import sys
from datetime import datetime

import config
import notifier


def _mask(url: str) -> str:
    """只在屏幕上显示到 host，token 打码 —— 免得截图/日志把 webhook 泄出去。"""
    s = str(url or "").strip()
    if not s:
        return "（未配置）"
    head = s.split("?")[0]
    return head + "?access_token=***"


def main() -> int:
    args = [a for a in sys.argv[1:]]
    list_only = "--list" in args
    title_args = [a for a in args if not a.startswith("--")]
    title = title_args[0] if title_args else f"✅ 通知通道自检 {datetime.now():%H:%M:%S}"

    channels = notifier.get_channels()
    print("=" * 66)
    print(f"配置来源：config.py" + ("　+ config_local.py（已加载）"
          if _local_loaded() else "　（没有 config_local.py）"))
    print(f"通道清单（{len(channels)} 个启用）：")
    for c in channels:
        print(f"  · {c.name}")
    print("-" * 66)
    print("各通道的配置状况（密钥只显示打码结果）：")
    print(f"  控制台            {'开' if getattr(config, 'NOTIFY_CONSOLE', True) else '关'}")
    print(f"  文件留痕          {getattr(config, 'NOTIFY_FILE', '') or '（关闭）'}")
    for i, k in enumerate(getattr(config, "SERVERCHAN_KEYS", []), 1):
        print(f"  Server酱#{i}        {'已配置' if str(k).strip() else '（空 → 不启用）'}"
              f"{'　⚠ 免费版 5 条/天且失败也计数' if str(k).strip() else ''}")
    webhook = getattr(config, "DINGTALK_WEBHOOK", "")
    secret = getattr(config, "DINGTALK_SECRET", "")
    kw = getattr(config, "DINGTALK_KEYWORD", "")
    print(f"  钉钉（主通道）     {_mask(webhook)}")
    print(f"     加签密钥        {'已配置（加签已启用）' if str(secret).strip() else '（留空 → 不加签；若机器人开了加签会 errcode 310000）'}")
    print(f"     自定义关键词    {kw or '（留空）'}")
    if not str(webhook).strip():
        print("     → 还没配。照 config_local.example.py 顶部的步骤拿到 Webhook 地址填进去即可，代码不用改。")
    print("=" * 66)

    if list_only:
        print("（--list 模式：没有发送任何消息）")
        return 0

    body = ("这是一条**通道自检**消息，来自 crypto-monitor 的通知层。\n\n"
            f"- 时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n"
            "- 你在钉钉群里看到它 = 钉钉通道已打通；在 Server酱/微信里看到 = 那条通道也通。\n"
            "- 没看到但这里显示成功 = 检查机器人是否只推给了某个群/人。")
    print(f"发送测试消息：{title}")
    r = notifier.notify(title, body)
    print("-" * 66)
    for item in r["results"]:
        print(f"  {'✅ 成功' if item['ok'] else '❌ 失败'}  {item['channel']:<12} {item['detail']}")
    print(f"汇总：成功 {r['ok']} / 失败 {r['fail']} / 共 {r['total']}")
    if r["ok"] and r["fail"]:
        print("提示：有通道失败不影响其它通道，也不影响报警判定（这是设计如此）。")
    if not r["total"]:
        print("提示：一个通道都没启用 —— 报警会只留在控制台/文件里，请检查配置。")
    # 退出码：只要**有通道失败**就非 0 —— 控制台/文件几乎总是成功，
    # 若按"有任一成功就算过"，这个工具对脚本和人都没有信号。
    if r["fail"]:
        print(f"结论：有 {r['fail']} 个通道失败（上面有原因）→ 退出码 1。"
              f"报警判定不受影响，但这条通道的消息送不到。")
    return 0 if (r["ok"] and not r["fail"]) else 1


def _local_loaded() -> bool:
    try:
        import config_local                                     # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    sys.exit(main())
