import requests
import time
import winsound
from config import SENDKEY1, SENDKEY2

# 2026-09-26 推送模块：推微信，蜂鸣
def send_wx(title, desp):
    for key in [SENDKEY1, SENDKEY2]:
        try:
            requests.post(f"https://sctapi.ftqq.com/{key}.send", data={"title": title, "desp": desp}, timeout=10)
            time.sleep(3)
        except: pass

def beep():
    for i in range(3):
        winsound.Beep(1000+i*200, 300)
