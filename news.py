import requests
import re
from datetime import datetime

# 6个币关键词
COIN_KEYWORDS = ["SUI", "WLD", "CYS", "BSV", "DOGE", "BTC", "狗狗币", "比特币"]
# 宏观风险关键词
MACRO_KEYWORDS = ["非农", "美联储", "加息", "降息", "CPI", "PCE", "暴跌", "暴涨", "SEC", "ETF"]

def get_latest_news():
    """【2026-10-06 优化】改用律动BlockBeats快讯RSS，国内可访问，中文币圈快讯更及时"""
    try:
        # 律动快讯RSS（国内第三方节点，已测试连通）
        url = "https://rsshub.dicomp.net/theblockbeats/newsflash"
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
