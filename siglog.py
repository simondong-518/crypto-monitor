# -*- coding: utf-8 -*-
"""siglog.py —— 结构化信号日志（**工具层**）

目的：把"面板只显示当前状态、alerts.log 只记推送留痕"补成**可回溯的完整历史**。

每轮、每个币写一行 JSONL（含全部指标快照 + 打分 + 本轮触发的所有信号），
包括**没触发任何信号**的币 —— 这正是 alerts.log 缺的那部分。

★ 铁律：本模块**不参与任何判定**，只把已经算好的东西落盘。
   · 任何异常都在内部吞掉（只打印一行），绝不影响监控主线
   · 只追加，不修改、不删除既有文件
   · 关掉它：config.SIGLOG_ENABLED = False 或环境变量 SIGLOG=0

文件：signal_logs/signals_YYYY-MM-DD.jsonl（按天切，天然可回溯）
"""
import io
import os
import json
import time
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "signal_logs")

_lock = threading.Lock()
_round = 0
_round_started = None
_last_err_ts = 0.0
ERR_THROTTLE = 60          # 同一类写盘错误最多每分钟打印一次，避免刷屏


def enabled():
    """开关：config.SIGLOG_ENABLED 优先，其次环境变量 SIGLOG，默认开。"""
    try:
        import config
        v = getattr(config, "SIGLOG_ENABLED", None)
        if v is not None:
            return bool(v)
    except Exception:
        pass
    return os.environ.get("SIGLOG", "1") != "0"


def round_start():
    """每轮开始时调用一次，给本轮所有记录一个统一的轮次号。"""
    global _round, _round_started
    _round += 1
    _round_started = time.strftime("%Y-%m-%d %H:%M:%S")
    return _round


def _n(v):
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _write(rec):
    """追加一行 JSONL。任何失败都不抛出去。"""
    global _last_err_ts
    try:
        day = rec["ts"][:10]
        path = os.path.join(LOG_DIR, "signals_%s.jsonl" % day)
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with _lock:
            if not os.path.isdir(LOG_DIR):
                os.makedirs(LOG_DIR)
            with io.open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:
        now = time.time()
        if now - _last_err_ts > ERR_THROTTLE:
            _last_err_ts = now
            print("[信号日志] 写盘失败（监控继续跑）：%s: %s"
                  % (type(e).__name__, e), flush=True)


def record(coin, pair, ind_s, ind_l=None, flow=None, score=None,
           signal="", alerts=None, report=False, extra=None):
    """写一条"正常评估"记录。入参全是调用方已经算好的值，这里只做改名与兜底。"""
    if not enabled():
        return
    ind_s = ind_s or {}
    ind_l = ind_l or {}
    flow = flow or {}
    b = s = None
    try:
        if isinstance(score, (list, tuple)) and len(score) >= 2:
            b, s = _n(score[0]), _n(score[1])
        elif isinstance(score, dict):
            b, s = _n(score.get("buy")), _n(score.get("sell"))
    except Exception:
        pass

    vol_ratio = None
    try:
        vn, vm = ind_s.get("vol_now"), ind_s.get("vol_ma")
        if vn is not None and vm:
            vol_ratio = round(float(vn) / float(vm), 3)
    except (TypeError, ValueError, ZeroDivisionError):
        vol_ratio = None

    rec = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "round": _round,
        "coin": coin,
        "pair": pair,
        "close": _n(ind_s.get("close")),
        "day_chg": _n(ind_s.get("day_chg")),
        "rsi15": _n(ind_s.get("rsi")),
        "rsi1h": _n(ind_l.get("rsi")),
        "kdj_j": _n(ind_s.get("kdj_j")),
        "macd": _n(ind_s.get("macd")),
        "boll_u": _n(ind_s.get("boll_u")),
        "boll_m": _n(ind_s.get("boll_mid")),
        "boll_l": _n(ind_s.get("boll_l")),
        "ma20": _n(ind_s.get("ma20")),
        "trend15": bool(ind_s.get("trend_up")),
        "trend1h": bool(ind_l.get("trend_up")),
        "vol_ratio": vol_ratio,
        "net_inflow": _n(flow.get("net_inflow")),
        "score_buy": b,
        "score_sell": s,
        "signal": signal,
        "report": bool(report),
        "alerts": list(alerts or []),
    }
    if extra:
        try:
            rec.update(extra)
        except Exception:
            pass
    _write(rec)


def record_error(coin, pair, exc):
    """写一条"该币本轮评估失败"记录 —— 让缺口可见，而不是静默少一行。"""
    if not enabled():
        return
    _write({
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "round": _round,
        "coin": coin,
        "pair": pair,
        "error": "%s: %s" % (type(exc).__name__, exc),
    })


def stats():
    """给自检/面板用：当前日志规模（只读）。"""
    out = {"dir": LOG_DIR, "files": [], "enabled": enabled(), "round": _round}
    try:
        for f in sorted(os.listdir(LOG_DIR)):
            if f.endswith(".jsonl"):
                p = os.path.join(LOG_DIR, f)
                out["files"].append({"name": f, "bytes": os.path.getsize(p)})
    except Exception:
        pass
    return out
