# ==============================================
# 配置文件：所有参数都在这里改
# ==============================================

# GATE API地址
BASE = "https://api.gateio.ws/api/v4"

# 监测币种
CURRENCY_PAIRS = ["CYS_USDT", "SUI_USDT", "WLD_USDT", "BSV_USDT", "DOGE_USDT", "SOL_USDT"]

# Server酱双SendKey
SENDKEY1 = "SCT426961TeNhdBXiVI65DOs1eujHCVu8I"
SENDKEY2 = "SCT427098TfTBMz8lASeCdUCtqzwAmFACc"

# 涨跌幅提醒阈值
CHG_THRESHOLD = {
    "CYS": 4.0,
    "default": 3.0
}

# 信号打分阈值
BUY_SCORE_THRESHOLD = 3.5
SELL_SCORE_THRESHOLD = 3.5

# 每个信号最多推送次数
MAX_PUSH_PER_SIGNAL = 3

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

