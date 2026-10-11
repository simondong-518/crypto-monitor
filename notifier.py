import requests
import time
import winsound

# 飞书机器人webhook
# 2026-10-07 更新为新机器人地址
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/82ca26f7-f23c-4309-a0de-b4767eb15d81"

# 推送模块：推飞书，蜂鸣
def send_wx(title, desp):
    try:
        data = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [
                            [
                                {
                                    "tag": "text",
                                    "text": desp
                                }
                            ]
                        ]
                    }
                }
            }
        }
        requests.post(FEISHU_WEBHOOK, json=data, timeout=10)
    except Exception as e:
        print(f"飞书推送失败: {e}")

def beep():
    for i in range(3):
        winsound.Beep(1000+i*200, 300)
