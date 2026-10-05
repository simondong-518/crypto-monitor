"""全局推送开关（服务端状态，**所有浏览器/手机共享同一个**）。

与"折叠记忆"的区别（用户明确要求）：
  · 折叠 = 每个浏览器自己的 localStorage，互不影响
  · 本开关 = 服务器上的一个文件，任何设备打开页面看到的都是同一个状态，
    任何一处点了「开始/停止推送」，其它设备刷新后立刻看到同样结果

设计要点：
  1) 状态**落盘**（push_switch.json）—— 进程重启不会自己变回"开"。
  2) **默认关**。首次运行/文件不存在/文件损坏 → 一律当作"停止推送"。
     理由：这个开关存在的意义就是"别打扰对方"，默认开=风险，默认关=安全。
  3) 只写这一个文件。面板本身是只读的，这里把"唯一的写入能力"限制在此模块，
     不把写文件的能力散到别处。
  4) 每次改动记录时间与来源，出问题能追。

本模块**只决定"要不要发到外部通道"**，不参与任何判定：
  监控照跑、指标照算、页面照更新、报警照常判定并记录冷却状态
  （这样"打开推送"时不会补发一堆历史报警）。
"""

import json
import os
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SWITCH_FILE = os.path.join(HERE, "push_switch.json")

_lock = threading.Lock()

# 内存缓存：避免每次推送都读盘
_cache = None


def _default_state():
    """默认 = 停止推送（安全方向）。"""
    return {
        "enabled": False,
        "changed_at": None,
        "changed_by": None,
    }


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
    except FileNotFoundError:
        return _default_state()
    except Exception:
        # 文件损坏 → 当作"关"，不是"开"。宁可少发，不可误发。
        return _default_state()


def _write_file(state):
    """原子写：先写临时文件再替换，避免写一半被读到。"""
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
    """返回当前开关状态（含 enabled / changed_at / changed_by）。

    ★ 关键：**以文件为准**。
      缓存只在"文件没变"时复用；一旦文件被改动（别的进程、手动编辑、
      甚至两个服务实例同时开），靠 mtime 立刻发现并重读。
      早期版本只缓存不失效 → 外部改了文件，接口还报旧值，
      面板按钮点了没反应，排查半天。不要退回那种写法。
    """
    global _cache
    try:
        stamp = os.path.getmtime(SWITCH_FILE)
    except OSError:
        stamp = None            # 文件不存在
    with _lock:
        if _cache is None or stamp != _cache.get("_mtime"):
            st = _read_file()
            st["_mtime"] = stamp
            _cache = st
        return {k: v for k, v in _cache.items() if k != "_mtime"}


def is_enabled():
    """推送是否开启。**默认为 False**。"""
    return bool(get_state().get("enabled"))


def set_enabled(enabled, by="web"):
    """设置开关。返回设置后的状态。写盘失败会如实回报。"""
    global _cache
    with _lock:
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
    """翻转开关（供只有一个按钮的界面用）。"""
    return set_enabled(not is_enabled(), by=by)


def reload_from_disk():
    """丢弃缓存重读（多进程/手工改文件后用）。"""
    global _cache
    with _lock:
        _cache = _read_file()
        return dict(_cache)


def status_text():
    st = get_state()
    if st.get("enabled"):
        return "推送中"
    return "已暂停"
