"""本机私有配置模板 —— 复制成 config_local.py 再填（config_local.py 不会进仓库）。

    copy config_local.example.py config_local.py        # Windows
    cp config_local.example.py config_local.py          # git-bash

why：这个仓库要推给对方看，config.py 里的值会被提交。webhook / 密钥 / SendKey
属于"谁拿到谁就能往你群里发消息"的东西 —— 写在这里就不会出网。
config_local.py 里定义的变量会在 config.py 最后**覆盖**同名变量。

改完怎么验证（会真发一条测试消息，占用 Server酱 当日额度）：
    python notify_test.py
只想看通道有没有被启用、不想发消息：
    python notify_test.py --list
"""

# ── 钉钉自定义机器人（推荐主通道，不限量）──────────────────────────
# 拿法：钉钉群 → 右上角 群设置 → 智能群助手 → 添加机器人 → 自定义（通过 Webhook 接入）
#      → 安全设置里选一种 → 勾选同意 → 复制 Webhook 地址（一定要点"完成"，否则机器人不生效）
#      安全设置三选一：
#        · 自定义关键词：填的词**必须出现在消息文本里**，否则钉钉拒收（errcode 310000）
#        · 加签        ：会额外给你一个 "SEC..." 开头的密钥 → 填 DINGTALK_SECRET
#        · IP 地址段   ：服务器出口 IP 不在范围就拒收（本机跑家用宽带会变，不建议）
#      ⚠ 钉钉机器人限速约 20 条/分钟，同一内容 20 分钟内重复发也会被拦。
DINGTALK_WEBHOOK = ""     # 形如 https://oapi.dingtalk.com/robot/send?access_token=xxxx
DINGTALK_SECRET = ""      # 选了"加签"就填（SEC 开头）；没选加签留空
DINGTALK_KEYWORD = ""     # 选了"自定义关键词"就填那个词（通道会自动把它前置到消息里）

# ── 想换 Server酱 key 也在这里改（别改 config.py）───────────────
# SERVERCHAN_KEYS = ["SCT...你的key1", "SCT...你的key2"]

# ── 想把面板只开在本机（手机看不了，但公网也碰不到）─────────────
# PANEL_HOST = "127.0.0.1"
