import requests
import re
import time
from datetime import datetime

# 6个币关键词
COIN_KEYWORDS = ["SUI", "WLD", "CYS", "BSV", "DOGE", "BTC", "狗狗币", "比特币"]
# 宏观风险关键词
MACRO_KEYWORDS = ["非农", "美联储", "加息", "降息", "CPI", "PCE", "暴跌", "暴涨"]

def get_latest_news():
    """爬金色财经最新新闻，返回和咱们币相关的列表。

    走缓存：资讯不是每分钟都变，且这个源在**别的域名**上 —— 它不占
    Gate 的额度，但同样是每轮一次的请求，能省则省。
    """
    try:
        import kline_cache
        ttl = kline_cache.ttl_for("news")
        if ttl > 0:
            bucket = int(time.time()) // max(ttl, 1) * max(ttl, 1)
            return kline_cache.get_or_fetch(("news", bucket), ttl, _fetch_news)
    except Exception as e:
        print(f"[news] 缓存跳过（{type(e).__name__}: {e}），改为直接取", flush=True)
    return _fetch_news()


def _fetch_news():
    try:
        # 金色财经RSS
        url = "https://www.jinse.com/lives.rss"
        r = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        text = r.text
        items = re.findall(r'<item>(.*?)</item>', text, re.S)
        related = []
        macro_alert = []
        for item in items[:20]:
            title = re.search(r'<title>(.*?)</title>', item, re.S)
            if not title: continue
            t = title.group(1).strip()
            # 先判断宏观风险
            for kw in MACRO_KEYWORDS:
                if kw in t:
                    macro_alert.append(t)
                    break
            # 再判断单个币新闻
            for kw in COIN_KEYWORDS:
                if kw in t:
                    related.append(t)
                    break
        return related, macro_alert
    except Exception as e:
        return [], []
