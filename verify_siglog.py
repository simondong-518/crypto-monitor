# -*- coding: utf-8 -*-
"""siglog 自检 —— 结构化信号日志（工具层）

验证：写入格式正确、按天切、坏输入不炸、关掉就不写、
      以及**绝不污染真实 signal_logs/**（全程用临时目录）。
"""
import io
import os
import sys
import json
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import siglog

PASS = []
FAIL = []


def check(label, cond):
    (PASS if cond else FAIL).append(label)
    print(("  PASS  " if cond else "  FAIL  ") + label)


def _snapshot(d):
    """真实日志目录的文件名集合（只比文件名：线上服务可能同时在追加内容）。"""
    try:
        return set(f for f in os.listdir(d) if f.endswith(".jsonl"))
    except OSError:
        return set()


TMP = tempfile.mkdtemp(prefix="siglog_test_")
REAL_DIR = siglog.LOG_DIR
REAL_BEFORE = _snapshot(REAL_DIR)
siglog.LOG_DIR = TMP

try:
    # ── 1) 基本写入 ──────────────────────────────────────────
    siglog.round_start()
    siglog.record(coin="BTC", pair="BTC_USDT",
                  ind_s={"close": 82629.1, "day_chg": -0.3, "rsi": 41.1,
                         "boll_u": 84000, "boll_mid": 82000, "boll_l": 80000,
                         "kdj_j": -13, "ma20": 82500, "trend_up": False,
                         "vol_now": 120, "vol_ma": 100},
                  ind_l={"rsi": 34.4, "trend_up": True},
                  flow={"net_inflow": 180000, "n": 100},
                  score=(30, 12), signal="持有观望",
                  alerts=["🟡 低吸预警，买入分30/110"], report=True)

    files = [f for f in os.listdir(TMP) if f.endswith(".jsonl")]
    check("写出了一个按天命名的 jsonl", len(files) == 1 and files[0].startswith("signals_"))
    check("文件名是当天日期", files[0] == "signals_%s.jsonl" % siglog.time.strftime("%Y-%m-%d"))

    lines = io.open(os.path.join(TMP, files[0]), encoding="utf-8").read().strip().split("\n")
    check("恰好一行", len(lines) == 1)
    rec = json.loads(lines[0])
    need = ["ts", "round", "coin", "pair", "close", "rsi15", "rsi1h",
            "boll_u", "boll_m", "boll_l", "trend15", "trend1h", "vol_ratio",
            "net_inflow", "score_buy", "score_sell", "signal", "report", "alerts"]
    missing = [k for k in need if k not in rec]
    check("必需字段齐全", not missing)
    check("数值正确落到字段", rec["close"] == 82629.1 and rec["score_buy"] == 30)
    check("量能比自算正确 (120/100=1.2)", rec["vol_ratio"] == 1.2)
    check("报告级标记正确", rec["report"] is True)
    check("信号列表完整保留", rec["alerts"] == ["🟡 低吸预警，买入分30/110"])
    check("轮次号已带上", rec["round"] >= 1)

    # ── 2) 轮次号递增 ────────────────────────────────────────
    r1 = siglog.round_start()
    siglog.record(coin="SUI", pair="SUI_USDT", ind_s={}, alerts=[])
    r2 = siglog.round_start()
    check("round_start 递增", r2 == r1 + 1)

    # ── 3) 空/坏输入不炸 ─────────────────────────────────────
    ok = True
    for bad in [None, {}, {"close": "abc"}, {"close": None, "rsi": "x"}]:
        try:
            siglog.record(coin="X", pair="X_USDT", ind_s=bad, ind_l=None,
                          flow=None, score=None, alerts=None)
        except Exception as e:
            ok = False
            print("     炸了:", type(e).__name__, e)
    check("空/坏输入不抛异常", ok)
    try:
        siglog.record(coin="Y", pair="Y_USDT", ind_s={}, score=("a", "b"),
                      alerts="不是列表")
        check("坏的 score/alerts 也不抛", True)
    except Exception as e:
        check("坏的 score/alerts 也不抛", False)

    # ── 4) 错误行 ────────────────────────────────────────────
    n_before = len(io.open(os.path.join(TMP, files[0]), encoding="utf-8").read().strip().split("\n"))
    siglog.record_error("DOGE", "DOGE_USDT", ValueError("模拟读超时"))
    lines = io.open(os.path.join(TMP, files[0]), encoding="utf-8").read().strip().split("\n")
    check("错误行已追加", len(lines) == n_before + 1)
    err = json.loads(lines[-1])
    check("错误行带 error 字段", "error" in err and "ValueError" in err["error"])

    # ── 5) 关掉就不写 ────────────────────────────────────────
    n_before = len(io.open(os.path.join(TMP, files[0]), encoding="utf-8").read().strip().split("\n"))
    _orig_enabled = siglog.enabled
    siglog.enabled = lambda: False
    siglog.record(coin="BTC", pair="BTC_USDT", ind_s={})
    siglog.record_error("BTC", "BTC_USDT", ValueError("x"))
    lines = io.open(os.path.join(TMP, files[0]), encoding="utf-8").read().strip().split("\n")
    check("开关关闭时一条都不写", len(lines) == n_before)
    siglog.enabled = _orig_enabled

    # ── 6) 目录不可写时也不抛 ────────────────────────────────
    old = siglog.LOG_DIR
    siglog.LOG_DIR = os.path.join(TMP, "no_such\0dir")
    try:
        siglog.record(coin="BTC", pair="BTC_USDT", ind_s={})
        check("目录非法时不抛异常", True)
    except Exception:
        check("目录非法时不抛异常", False)
    siglog.LOG_DIR = old

    # ── 7) 绝不污染真实目录 ──────────────────────────────────
    real_touched = _snapshot(REAL_DIR) != REAL_BEFORE
    check("自检没有写入真实 signal_logs/", not real_touched)

finally:
    siglog.LOG_DIR = REAL_DIR
    shutil.rmtree(TMP, ignore_errors=True)

print("\n结果: %d/%d 通过" % (len(PASS), len(PASS) + len(FAIL)))
if FAIL:
    print("失败项:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
