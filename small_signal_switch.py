"""「小信号要不要一起推」的开关（服务端状态，所有设备共享，持久化）。

背景
    对方 2026-10-05 把推送逻辑改成：
        单个小信号（BOLL开口、大户多空比、缩量上涨…）**只打控制台，不推飞书**；
        只有综合打分 ≥90 的"最佳低吸/高抛点"才推。

    而用户的原则是"只要触发规则就该上报"。两种偏好都要能工作，
    所以这里加一个开关，由用户自己选：

        关（默认，= 对方的设计）：只推关键点
        开                      ：小信号也一起推

★ 本开关**不改变任何判定**，也不改他的打分 ——
  它只决定"已经产生的报警里，哪些进发送队列"。
  也就是说：打分、阈值、信号生成，一个字都没动。

与 push_switch 的关系：
    push_switch   = 总闸（关掉 -> 一条都不发）
    本开关         = 细分（总闸开着时，小信号发不发）
"""
import json
import os
import threading
import time

from datetime import datetime

SWITCH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "small_signal_switch.json")

_LOCK = threading.Lock()
_cache = None


def _default_state():
    return {"enabled": False,          # ★ 默认关 = 保持对方的设计
            "changed_at": None,
            "changed_by": None}


def _read_file():
    try:
        with open(SWITCH_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return _default_state()
        return {
            "enabled": bool(d.get("enabled", False)),
            "changed_at": d.get("changed_at"),
            "changed_by": d.get("changed_by"),
        }
    except Exception:
        # 读不到/损坏 → 按"关"（= 对方的设计，安全方向）
        return _default_state()


def _write_file(state):
    tmp = SWITCH_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SWITCH_FILE)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def get_state():
    """读状态。★ 以文件为准，按 mtime 失效（外部进程改了立刻可见）。"""
    global _cache
    try:
        stamp = os.path.getmtime(SWITCH_FILE)
    except OSError:
        stamp = None
    with _LOCK:
        if _cache is None or stamp != _cache.get("_mtime"):
            st = _read_file()
            st["_mtime"] = stamp
            _cache = st
        return {k: v for k, v in _cache.items() if k != "_mtime"}


def is_enabled():
    """小信号是否也推送。默认 False。"""
    return bool(get_state().get("enabled"))


def set_enabled(enabled, by="web"):
    global _cache
    with _LOCK:
        state = {
            "enabled": bool(enabled),
            "changed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "changed_by": str(by)[:40],
        }
        ok = _write_file(state)
        try:
            state["_mtime"] = os.path.getmtime(SWITCH_FILE)
        except OSError:
            state["_mtime"] = None
        _cache = state
        out = {k: v for k, v in state.items() if k != "_mtime"}
        out["persisted"] = ok
        return out


def toggle(by="web"):
    return set_enabled(not is_enabled(), by=by)
