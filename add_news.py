with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
# 在import部分加news
c = c.replace("from notifier import send_wx", "from notifier import send_wx\nfrom news import get_latest_news\npushed_news = set()")
# 在主循环里加新闻检查
old_loop = '''while True:
        monitor_once()
        time.sleep(60)'''
new_loop = '''while True:
        monitor_once()
        # 每10分钟查一次新闻
        news = get_latest_news()
        for n in news:
            if n not in pushed_news:
                pushed_news.add(n)
                send_wx("📰 币相关新闻", n)
        time.sleep(60)'''
c = c.replace(old_loop, new_loop)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("加完了")
