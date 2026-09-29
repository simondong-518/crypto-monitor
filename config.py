# ==============================================
# 配置文件：所有参数都在这里改
# ==============================================

# 系统版本号
VERSION = "v2.2.1"
VERSION_DATE = "2026-09-28"

# GATE API地址
BASE = "https://api.gateio.ws/api/v4"

# 监测币种
CURRENCY_PAIRS = ["CYS_USDT", "SUI_USDT", "WLD_USDT", "BSV_USDT", "DOGE_USDT", "SOL_USDT"]

# Server酱双SendKey
SENDKEY1 = "SCT426961TeNhdBXiVI65DOs1eujHCVu8I"
SENDKEY2 = "SCT427098TfTBMz8lASeCdUCtqzwAmFACc"

# 涨跌幅提醒阈值
CHG_THRESHOLD = {
    "default": 2.0
}

# 信号打分阈值
BUY_SCORE_THRESHOLD = 3.5
SELL_SCORE_THRESHOLD = 3.5

# 涨幅过大阈值（%）：日涨幅达到此值后不再提示"拿住"，改为提示高位止盈（补做4）
HIGH_CHG_THRESHOLD = 10.0

# 【已废弃】每个信号最多推送次数
# 改用冷却制（见 ALERT_COOLDOWN_MIN）：硬性次数上限会导致"顶到上限后当天永久沉默"，
# 与用户定调"只要触发规则就该上报"冲突。保留常量只为兼容旧脚本。
MAX_PUSH_PER_SIGNAL = 3

# ==============================================
# 通知层（2026-09-29 定调）
#   只要规则触发就必须上报；通道额度是额度问题，不影响业务主线。
#   通道失败不影响"要不要报警"的判断，也不影响其它通道。
# ==============================================
# 当前临时通道：Server酱（免费版 5 条/天，且失败也计数）
SERVERCHAN_KEYS = [SENDKEY1, SENDKEY2]
# 后续主通道：钉钉机器人（不限量）。填上 webhook 即自动启用
DINGTALK_WEBHOOK = ""
DINGTALK_SECRET = ""     # 机器人开了"加签"就填，否则留空
DINGTALK_KEYWORD = ""    # 机器人开了"自定义关键词"就填关键词
# 本地留痕 + 控制台横幅（无凭证，永远可用；任何通道全挂也不会丢报警）
NOTIFY_FILE = "alerts.log"
NOTIFY_CONSOLE = True

# 报警冷却（防刷屏用，不是额度限制）：同一告警最少间隔多少分钟才重复上报。
# 首次触发一定上报；条件持续时按这个间隔重报；永远不会"今天不再报"。
ALERT_COOLDOWN_MIN = 30

# 涨跌幅提醒伴随的量能门槛（倍）。用**已收盘 bar** 的量能比（见 indicators.py P1-1）
VOL_ENOUGH_MULT = 1.2

# ==============================================
# 大户多空比打分（P1-3 / D1 决策）
#   两个口径都展示；打分用「币自身的滚动分位数」（高分位=看多），不再用固定 1.0 阈值
# ==============================================
LS_METRIC = "top_lsr_account"   # 打分口径：top_lsr_account / top_lsr_size
LS_WINDOW = 720                 # 滚动窗口（每分钟一个样本 → 720 ≈ 12 小时）
LS_MIN_SAMPLES = 60             # 少于这么多样本不加分（预热期绝不猜）
LS_BUY_PCT = 80.0               # 分位 ≥ 此值 → 买分 +1
LS_SELL_PCT = 20.0              # 分位 ≤ 此值 → 卖分 +1
LS_SCORE_MODE = "momentum"      # momentum=高多空比看多（与原代码同向）/ contrarian=反向
LS_HISTORY_FILE = "ls_history.json"

# ==============================================
# 移动止盈（补做 N12）
# ==============================================
TRAILING_DRAWDOWN_PCT = 3.0     # 从当天最高点回撤多少 % 提示移动止盈
TRAILING_REQUIRE_TREND_UP = True  # 只在趋势向上时提示（沿用原补丁脚本的原意）

# 到价提醒的设定日期（可选）：用于提示"止损/止盈线放太久了该复核"
# 格式 {"币名": "YYYY-MM-DD"}，没写的币不做过期提醒
PRICE_ALERT_SET = {
    "BSV_USDT": "2026-09-26",
}
PRICE_ALERT_STALE_DAYS = 14

# 监测间隔（秒）
CHECK_INTERVAL = 60

# 回测间隔（秒，默认4小时）
BACKTEST_INTERVAL = 4 * 3600

# 自定义到价提醒：格式 {"币名": [止盈价, 止损价]}
PRICE_ALERT = {
    "BSV_USDT": [22.0, 21.0],
}

# 手续费率（回测用）
FEE_RATE = 0.001

