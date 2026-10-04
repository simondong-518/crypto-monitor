# ==============================================
# 配置文件：所有参数都在这里改
# ==============================================

VERSION = "v2.2.1"
VERSION_DATE = "2026-09-28"

# GATE API地址
BASE = "https://api.gateio.ws/api/v4"

# 监测币种
CURRENCY_PAIRS = ["CYS_USDT", "SUI_USDT", "WLD_USDT", "BSV_USDT", "DOGE_USDT", "BTC_USDT"]

# Server酱SendKey
SENDKEY1 = ""
SENDKEY2 = ""

# 涨跌幅提醒阈值
CHG_THRESHOLD = {
    "default": 2.0
}

# 信号打分阈值
BUY_SCORE_THRESHOLD = 3.5
SELL_SCORE_THRESHOLD = 3.5

# ==============================================
# 报警上报策略：**冷却制**（替代原来的"每个信号最多推 3 次"）
#
# 旧配置 MAX_PUSH_PER_SIGNAL = 3 的含义是"每个信号一天最多推 3 次"，
# 副作用是：一个持续存在的止损/跑路信号在推满 3 次后**当天彻底不再提醒**，
# 而且界面上看不出来。现在改成冷却时间：首次必报，条件还在就按间隔重报，不设上限。
# 保留 MAX_PUSH_PER_SIGNAL 只为兼容旧引用（已不再用于判定）。
# ==============================================
ALERT_COOLDOWN_MIN = 30          # 同一个报警多久可以重报一次（分钟）
ALERT_STATE_FILE = "alert_state.json"
MAX_PUSH_PER_SIGNAL = 3          # 仅兼容旧引用；判定一律走 alert_state 的冷却制

# 监测间隔（秒）
CHECK_INTERVAL = 60

# 回测间隔（秒，默认4小时）
BACKTEST_INTERVAL = 4 * 3600
# 自定义到位提醒
PRICE_ALERT = {}

# 手续费（回测用）
FEE_RATE = 0.001

# 动态有效高低点存储
DAILY_EXTREME = {
    "date": "",
    "high": {},
    "low": {}
}

# 不同币种的移动止盈回撤阈值
TRAILING_STOP = {
    "WLD_USDT": 0.035,
    "BSV_USDT": 0.035,
    "SUI_USDT": 0.035,
    "CYS_USDT": 0.035,
    "DOGE_USDT": 0.035,
    "BTC_USDT": 0.02
}
