"""通知层：通道可插拔（2026-09-29 重写）。

修订历史：
  2026-09-26 初版：只推 Server酱，不检查返回体、异常被 except: pass 吞掉。
  2026-09-29 P0-6：检查返回体 code —— 配额用尽时 Server酱 仍返回 HTTP 200 但 code != 0，
                   消息会静默丢失，日志里一个字都没有。
  2026-09-29 本次：按用户定调重写为通道注册表。

设计原则（用户定调）：
  1. **只要规则触发就必须上报** —— 上报与否不取决于通道额度，也不取决于通道是否可用。
  2. **通道失败不影响业务主线** —— 某个通道挂了其它通道继续；全挂了也不丢（本地文件留痕）。
  3. **加通道 = 加一个 Channel 子类 + config 一项**，不动报警判定与自检（N10 依赖这一点）。

当前通道：控制台横幅 + 本地文件留痕 + Server酱（临时、限量）
后续主通道：钉钉机器人（不限量）—— config 里填 DINGTALK_WEBHOOK 即自动启用
"""
import base64
import hashlib
import hmac
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests

import config


class Channel:
    name = "channel"

    def enabled(self):
        return True

    def send(self, title, body):
        """返回 (是否成功, 详情字符串)"""
        raise NotImplementedError


class ConsoleChannel(Channel):
    """控制台报警横幅。每轮的屏幕报告由 main.py 自己打印，这里不重复刷整篇报告。"""
    name = "控制台"

    def send(self, title, body):
        print("\n" + "!" * 66)
        print(f"[报警] {title}")
        for line in body.split("\n"):
            s = line.strip()
            if s.startswith("- **") or s.startswith("**结论**") or s.startswith("**持仓建议**"):
                print("   " + s)
        print("!" * 66)
        return True, "printed"


class FileChannel(Channel):
    """本地留痕：任何通道全挂都不会丢报警；事后核对"到底报没报"就看这个文件。"""
    name = "文件"

    def __init__(self, path):
        self.path = Path(path)

    def enabled(self):
        return bool(str(self.path).strip())

    def send(self, title, body):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"\n===== {ts} | {title} =====\n{body}\n")
        return True, str(self.path)


class ServerChanChannel(Channel):
    """Server酱（方糖）：当前临时通道。免费版 5 条/天，且**失败也计数**。"""

    def __init__(self, key, label):
        self.key = key
        self.name = label

    def enabled(self):
        return bool(str(self.key).strip())

    def send(self, title, body):
        r = requests.post(f"https://sctapi.ftqq.com/{self.key}.send",
                          data={"title": title, "desp": body}, timeout=10)
        try:
            j = r.json()
        except Exception:
            j = {}
        code = j.get("code") if isinstance(j, dict) else None
        if r.status_code == 200 and code == 0:
            return True, f"pushid={(j.get('data') or {}).get('pushid', '-')}"
        msg = j.get("message") if isinstance(j, dict) else None
        return False, f"HTTP={r.status_code} code={code} msg={msg!r}"


class DingTalkChannel(Channel):
    """钉钉自定义机器人（后续主通道，不限量）。配了 webhook 就自动启用。

    加签：sign = urlencode(base64(HMAC-SHA256(secret, f"{timestamp}\\n{secret}")))
    返回体：成功为 {"errcode": 0, "errmsg": "ok"}
    """
    name = "钉钉"

    def __init__(self, webhook, secret="", keyword=""):
        self.webhook = webhook
        self.secret = secret
        self.keyword = keyword

    def enabled(self):
        return bool(str(self.webhook).strip())

    def _url(self):
        url = str(self.webhook).strip()
        if self.secret:
            ts = str(round(time.time() * 1000))
            raw = hmac.new(str(self.secret).encode("utf-8"),
                           f"{ts}\n{self.secret}".encode("utf-8"),
                           hashlib.sha256).digest()
            sign = base64.b64encode(raw).decode("utf-8")
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
                {"timestamp": ts, "sign": sign})
        return url

    def send(self, title, body):
        text = f"{title}\n\n{body}"
        if self.keyword and self.keyword not in text:
            text = f"{self.keyword}\n{text}"
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
        r = requests.post(self._url(), json=payload, timeout=10)
        try:
            j = r.json()
        except Exception:
            j = {}
        if isinstance(j, dict) and j.get("errcode") == 0:
            return True, "ok"
        errcode = j.get("errcode") if isinstance(j, dict) else None
        errmsg = j.get("errmsg") if isinstance(j, dict) else None
        return False, f"HTTP={r.status_code} errcode={errcode} errmsg={errmsg!r}"


def get_channels():
    """按 config 组装启用中的通道列表。新增通道只需在这里多一行。"""
    ch = []
    if getattr(config, "NOTIFY_CONSOLE", True):
        ch.append(ConsoleChannel())
    fp = getattr(config, "NOTIFY_FILE", "")
    if str(fp).strip():
        ch.append(FileChannel(fp))
    for i, key in enumerate(getattr(config, "SERVERCHAN_KEYS", []), 1):
        if str(key).strip():
            ch.append(ServerChanChannel(key, f"Server酱#{i}"))
    webhook = getattr(config, "DINGTALK_WEBHOOK", "")
    if str(webhook).strip():
        ch.append(DingTalkChannel(webhook,
                                  getattr(config, "DINGTALK_SECRET", ""),
                                  getattr(config, "DINGTALK_KEYWORD", "")))
    return ch


def notify(title, body):
    """逐通道发送并汇总。任一通道失败都不抛异常、不影响调用方继续工作。"""
    results = []
    for c in get_channels():
        if not c.enabled():
            continue
        try:
            ok, detail = c.send(title, body)
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append({"channel": c.name, "ok": ok, "detail": detail})
        if c.name != "控制台":
            print(f"[通知{'成功' if ok else '失败'}] {c.name} {detail}")
    ok_n = sum(1 for r in results if r["ok"])
    if not results:
        print("[通知失败] 没有任何启用的通道 —— 本条报警没有送出，请检查配置")
    elif ok_n == 0:
        print("[通知失败] 所有通道都失败 —— 本条报警没有送出")
    return {"ok": ok_n, "fail": len(results) - ok_n, "total": len(results), "results": results}


def send_wx(title, desp):
    """兼容旧调用方（api.check_events / backtest.py 仍在用）。"""
    return notify(title, desp)["ok"]


def beep():
    try:
        import winsound
        for i in range(3):
            winsound.Beep(1000 + i * 200, 300)
    except Exception:
        pass
