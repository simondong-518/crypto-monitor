with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
# 去掉直接推新闻的逻辑
old = '''        # 每10分钟查一次新闻
        news = get_latest_news()
        for n in news:
            if n not in pushed_news:
                pushed_news.add(n)
                send_wx("📰 币相关新闻", n)'''
new = '''        # 新闻作为打分参考，不单独推送
        news = get_latest_news()'''
c = c.replace(old, new)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("改完了")
