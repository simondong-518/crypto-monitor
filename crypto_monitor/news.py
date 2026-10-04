import requests
import re
from datetime import datetime

# 6个币关键词
COIN_KEYWORDS = ["SUI", "WLD", "CYS", "BSV", "DOGE", "BTC", "狗狗币", "比特币"]
# 宏观风险关键词
MACRO_KEYWORDS = ["非农", "美联储", "加息", "降息", "CPI", "PCE", "暴跌", "暴涨"]

def get_latest_news():
    """爬金色财经最新新闻，返回和咱们币相关的列表"""
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
