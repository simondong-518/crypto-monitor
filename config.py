# ==============================================
# 配置文件：所有参数都在这里改
# ==============================================

VERSION = "v2.2.1"
VERSION_DATE = "2026-09-28"

# GATE API地址
BASE = "https://api.gateio.ws/api/v4"
# 【2026-10-05 新增】GATE只读API Key，避免行情接口限流
GATE_API_KEY = "89c98e805fd8ef5adaf0230f3f81534b"
GATE_API_SECRET = "348c850ed189735b78ae3ffc5c9fd82ebfd1a57807d6a64a60bb4b157dccc1f9"

# 监测币种
# 2026-10-11 调整：只保留SUI/WLD/DOGE三个高波动短线币，取消BTC/BSV/CYS监测
CURRENCY_PAIRS = ["SUI_USDT", "WLD_USDT", "DOGE_USDT"]

# Server酱SendKey
SENDKEY1 = "SCT426961TeNhdBXiVI65DOs1eujHCVu8I"
SENDKEY2 = "SCT427098TfTBMz8lASeCdUCtqzwAmFACc"

# 涨跌幅提醒阈值
CHG_THRESHOLD = {
    "default": 2.0
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

