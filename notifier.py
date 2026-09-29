import requests
import time
import winsound
from config import SENDKEY1, SENDKEY2

# 2026-09-26 推送模块：推微信，蜂鸣
# 2026-09-29 修（P0-6）：原实现 requests.post 之后不看返回体、异常又被 except: pass 吞掉，
#   配额用尽时 Server酱 仍返回 HTTP 200 但 body 里 code != 0 —— 消息静默丢失，日志里一个字都没有。
#   现在每个渠道的成功/失败都会打印（只打渠道标签，不打 key 本身）。

CHANNELS = [("通道1", SENDKEY1), ("通道2", SENDKEY2)]


def send_wx(title, desp):
    """推送到所有渠道，返回成功的渠道数。失败一定可见。"""
    ok = 0
    for label, key in CHANNELS:
        try:
            r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                              data={"title": title, "desp": desp}, timeout=10)
            try:
                body = r.json()
            except Exception:
                body = {}
            code = body.get("code") if isinstance(body, dict) else None
            if r.status_code == 200 and code == 0:
                ok += 1
                pushid = (body.get("data") or {}).get("pushid", "-")
                print(f"[推送成功] {label} pushid={pushid}")
            else:
                msg = body.get("message") if isinstance(body, dict) else None
                print(f"[推送失败] {label} HTTP={r.status_code} code={code} msg={msg!r}")
        except Exception as e:
            print(f"[推送异常] {label} {type(e).__name__}: {e}")
        time.sleep(3)
    if ok == 0:
        print("[推送失败] 所有渠道都没成功 —— 本条消息未送达")
    return ok


def beep():
    for i in range(3):
        winsound.Beep(1000+i*200, 300)
