"""回归测试：覆盖两批修复。

第一批（阶段1）：P0-1 乱码比较 / N13 三连阳 / N14 三连阴 / N15 高位止盈 / P0-2 计数压制 / P0-6 推送失败可见
第二批（本轮）：P1-1 已收盘bar口径 / P1-3 多空比分位数 / P1-7 单一判定入口 / P1-12 到价状态式 /
               N12 移动止盈 / 通知通道可插拔 / 冷却制取代次数上限

全部离线：不联网（唯一的网络入口 indicators.get_kline 被替换成桩），不推送，不写仓库文件。

跑法（需要 pandas）：
    M:\\project\\PA_Agent\\.venv\\Scripts\\python.exe tools\\test_regression.py
"""
import io
import json
import re
import sys
import tempfile
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import pandas as pd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name +
          (("    <- " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


def raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


# ============================================================ T1 单一判定入口
print("T1 (P1-7) 判定入口唯一：main/check_* 都走 evaluate.py，不再各算一套")
main_src = (ROOT / "main.py").read_text(encoding="utf-8")
strat_src = (ROOT / "strategy.py").read_text(encoding="utf-8")
eval_src = (ROOT / "evaluate.py").read_text(encoding="utf-8")
check("main.py 从 evaluate 导入", "from evaluate import" in main_src)
check("main.py 自己不调 calc_score", "calc_score(" not in main_src)
check("main.py 自己不调 get_indicator", "get_indicator(" not in main_src)
check("main.py 不再用次数上限压制", "MAX_PUSH_PER_SIGNAL" not in main_src)
check("main.py 不再读写 pushed.json", ("pushed.json" not in main_src) and ("load_pushed" not in main_src))
for f in ("check_all_alerts.py", "check_coin.py", "full_analysis.py"):
    src = (ROOT / f).read_text(encoding="utf-8")
    own = ("calc_score(" in src) or ("get_indicator(" in src)
    check(f + " 不自己算分/取数（委托给共享入口）", not own, f + " 仍在自己算一套")
    check(f + " 引用共享入口（evaluate 或 check_all_alerts）",
          ("evaluate" in src) or ("check_all_alerts" in src), f)

import strategy  # noqa: E402

returned = set(re.findall(r'current\s*=\s*"([^"]+)"', strat_src))
check("get_signal 返回值集合 == {买入,卖出,观望}", returned == {"买入", "卖出", "观望"}, repr(returned))

import evaluate  # noqa: E402

# 建议文案必须由 get_signal 的返回值驱动（结构上不可能再出现"字面量对不上导致分支永不命中"）
compared_lit = set(re.findall(r'signal\s*==\s*"([^"]+)"', eval_src))
check("_advice 比较的中文字面量全部来自 get_signal 的返回值（P0-1 型 bug 的结构性防线）",
      bool(compared_lit) and compared_lit <= returned,
      "compared=" + str(compared_lit) + " returned=" + str(returned))
fake_res = {"signal": "买入", "daily_up": True, "ind_s": {"boll_l": 9.0, "boll_u": 11.0}}
check("买入信号 → 给出建仓建议（P0-1 之前这里永不执行）",
      "3成仓" in evaluate._advice(fake_res)[0], str(evaluate._advice(fake_res)))
fake_res["signal"] = "卖出"
check("卖出信号 → 给出卖出建议", "卖出" in evaluate._advice(fake_res)[0], str(evaluate._advice(fake_res)))
fake_res["signal"] = "观望"
check("观望 → 持有观望", "观望" in evaluate._advice(fake_res)[0], str(evaluate._advice(fake_res)))

# ============================================================ T2 编码
print("T2 (P0-1) main.py 不含 BOM、不含乱码")
import check_encoding  # noqa: E402

errs, moji, cmp_lines, sus = check_encoding.check_file(ROOT / "main.py", False)
check("无 BOM / 合法 UTF-8", not errs, str(errs))
check("无二次编码乱码", (not moji) and (not sus), "严格=" + str(moji) + " 疑似=" + str(sus))

# ============================================================ T3 P1-1 已收盘bar
print("T3 (P1-1) 指标算在最后一根已收盘 bar，只有价格类用实时值")
import indicators  # noqa: E402

TS0 = int(time.mktime(time.strptime("2026-09-29 00:00", "%Y-%m-%d %H:%M")))
FAKE = [[str(TS0 + i * 900), "0", "10.0", "10.05", "9.95", "10.0", "100", "true"] for i in range(30)]
# 最后一根 = 形成中的 bar：量巨大、价格离谱、wc=false（这正是原代码拿来算指标的那根）
FAKE[-1] = [str(TS0 + 30 * 900), "0", "99.0", "99.5", "98.5", "99.0", "99999", "false"]
indicators.get_kline = lambda *a, **k: [list(r) for r in FAKE]      # 桩：离线
ind = indicators.get_indicator("SUI_USDT", "15m")
check("实时价 = 形成中bar的close(99.0)", ind["price"] == 99.0, str(ind["price"]))
check("指标用价 = 已收盘bar的close(10.0)", ind["close"] == 10.0, str(ind["close"]))
check("量能比 = 已收盘bar量(100)/均量(100) = 1.0，不是 99999/100",
      abs(ind["vol_ratio"] - 1.0) < 1e-9, str(ind["vol_ratio"]))
check("bar_closed 标记为 True（看到的是已收盘bar）", ind["bar_closed"] is True, str(ind["bar_closed"]))
check("bar_time 指向已收盘bar而不是形成中bar",
      ind["bar_time"] == time.strftime("%Y-%m-%d %H:%M", time.localtime(int(FAKE[-2][0]))), ind["bar_time"])
check("MA20 不含形成中bar（=10.0）", abs(ind["ma20"] - 10.0) < 1e-9, str(ind["ma20"]))
check("形态取自最近两根已收盘bar（body=0, upper=0.05）",
      ind["shadows"][0][0] == 0.0 and abs(ind["shadows"][0][1] - 0.05) < 1e-9, str(ind["shadows"][0]))
indicators.get_kline = lambda *a, **k: []
check("K线条数不足 → 抛异常，不静默用坏数据",
      raises(lambda: indicators.get_indicator("X_USDT", "15m")))
indicators.get_kline = lambda *a, **k: [list(r) for r in FAKE]

# ============================================================ T4 P1-3 多空比
print("T4 (P1-3) 大户多空比按分位数打分：预热期不加分，高分位加买、低分位加卖")


def score_with_ls(ls_pct):
    ind_s = {"close": 10.0, "boll_u": 11.0, "boll_m": 10.0, "boll_l": 9.0, "trend_up": True,
             "boll_all_up": False, "rsi": 50.0, "macd_gold": False, "macd_dead": False,
             "kdj_j": 50.0, "k_gold": False, "k_dead": False, "vol_ratio": 1.0,
             "shadows": [(1.0, 0.1, 0.1), (1.0, 0.1, 0.1)]}
    df = pd.DataFrame([{"open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "vol": 100.0}] * 25)
    return strategy.calc_score(ind_s, {"rsi": 50.0, "trend_up": False}, {"net_inflow": 0.0}, ls_pct, df)


b_none, s_none = score_with_ls(None)
b_hi, s_hi = score_with_ls(95.0)
b_lo, s_lo = score_with_ls(5.0)
b_mid, s_mid = score_with_ls(50.0)
check("预热期(None) = 中分位，都不加分",
      (b_none, s_none) == (b_mid, s_mid), str((b_none, s_none, b_mid, s_mid)))
check("高分位(95%) 买分 +1", round(b_hi - b_none, 4) == 1.0, str(b_none) + " -> " + str(b_hi))
check("高分位不加卖分", round(s_hi - s_none, 4) == 0.0, str(s_none) + " -> " + str(s_hi))
check("低分位(5%) 卖分 +1", round(s_lo - s_none, 4) == 1.0, str(s_none) + " -> " + str(s_lo))
check("低分位不加买分", round(b_lo - b_none, 4) == 0.0, str(b_none) + " -> " + str(b_lo))

# ============================================================ T5 N13/N14
print("T5 (N13/N14) 连续3根阳线 buy+1.5 / 连续3根阴线 sell+1.5（用已收盘的3根）")


def make_case(three_up, three_down, live_close):
    """基准态用「十字星」（close == open）：既不是阳线也不是阴线，两条规则都不触发。"""
    rows = [{"open": 9.9, "high": 10.05, "low": 9.88, "close": 10.0, "vol": 100.0} for _ in range(25)]
    df = pd.DataFrame(rows)
    for pos in (-4, -3, -2):                      # 最后 3 根「已收盘」bar
        i = len(df) + pos
        df.loc[i, "open"] = 10.0
        if three_up:
            df.loc[i, "close"] = 10.30
            df.loc[i, "high"] = 10.35
        elif three_down:
            df.loc[i, "close"] = 9.70
            df.loc[i, "low"] = 9.65
        else:
            df.loc[i, "close"] = 10.0
    df.loc[len(df) - 1, "close"] = live_close     # 形成中的 bar，不该被这条规则看到
    ind_s = {"close": live_close, "boll_u": 11.0, "boll_m": 10.0, "boll_l": 9.0,
             "trend_up": True, "boll_all_up": False, "rsi": 50.0,
             "macd_gold": False, "macd_dead": False, "kdj_j": 50.0, "k_gold": False, "k_dead": False,
             "vol_ratio": 1.0, "shadows": [(1.0, 0.1, 0.1), (1.0, 0.1, 0.1)]}
    return strategy.calc_score(ind_s, {"rsi": 50.0, "trend_up": False}, {"net_inflow": 0.0}, None, df)


b0, s0 = make_case(False, False, 10.2)
b1, s1 = make_case(True, False, 10.2)
b2, s2 = make_case(False, True, 9.8)
b3, s3 = make_case(False, True, 10.2)
check("N13 三连阳加买分 1.5（" + str(b0) + " → " + str(b1) + "）", round(b1 - b0, 4) == 1.5)
check("N13 不影响卖分", round(s1 - s0, 4) == 0.0)
check("N14 三连阴加卖分 1.5（" + str(s0) + " → " + str(s2) + "）", round(s2 - s0, 4) == 1.5)
check("N14 不影响买分", round(b2 - b0, 4) == 0.0)
check("N14 收盘价在中轨之上时不加卖分", round(s3 - s0, 4) == 0.0)

# ============================================================ T6 N15 高位止盈
print("T6 (N15) 涨幅过大提示高位止盈，不再喊拿住")
import config  # noqa: E402

TH = 2.0
v = evaluate.day_chg_verdict
check("+12% 触发且提示高位止盈",
      v(12.0, True, True, TH)[0] and "高位止盈" in v(12.0, True, True, TH)[1], str(v(12.0, True, True, TH)))
check("+7% 仍然喊拿住（原为乱码）",
      v(7.0, True, True, TH)[1] == "趋势启动，拿住", str(v(7.0, True, True, TH)))
check("量不够时 3% 不触发", v(3.0, True, False, TH)[0] is False)
check("量够时 3% 触发", v(3.0, True, True, TH)[0] is True)
check("|涨幅|>=5% 不看量也触发", v(-6.0, False, False, TH)[0] is True)
check("HIGH_CHG_THRESHOLD 可配置且为 10", getattr(config, "HIGH_CHG_THRESHOLD", None) == 10.0)

# ============================================================ T7 报警状态
print("T7 (P0-2/P1-12) 报警状态：日期分区 + 冷却（不再是推满 3 次就当天沉默）")
from alert_state import AlertState  # noqa: E402

tmpdir = Path(tempfile.mkdtemp())
today = datetime.now().strftime("%Y-%m-%d")
stf = tmpdir / "alert_state.json"
stf.write_text(json.dumps({
    "2026-01-01|SUI_涨跌幅": 1.0,                 # 更早的日期
    today + "|SUI_涨跌幅": time.time() - 3600,     # 今天、1 小时前报过
}, ensure_ascii=False), encoding="utf-8")
st = AlertState(stf)
check("加载时丢弃非当天记录", ("2026-01-01|SUI_涨跌幅" not in st.data) and len(st.data) == 1, str(st.data))
st_now = AlertState(tmpdir / "empty.json")
ok1, why1 = st_now.check("SUI_涨跌幅", 30)
check("首次触发必报", ok1 is True and why1 == "首次触发", str(ok1) + " " + why1)
st_now.mark("SUI_涨跌幅")
ok2, why2 = st_now.check("SUI_涨跌幅", 30)
check("刚报过 + 冷却 30 分钟 → 不报", ok2 is False and "冷却中" in why2, str(ok2) + " " + why2)
ok3, _why3 = st_now.check("SUI_涨跌幅", 0)
check("冷却 0 分钟 → 立刻可报（没有次数上限）", ok3 is True)
ok4, why4 = st.check("SUI_涨跌幅", 30)             # 1 小时前报过，冷却 30 分钟
check("沉默超过冷却时间 → 重新上报（原实现此时已被 3 次上限永久压制）",
      ok4 is True and "重新上报" in why4, str(ok4) + " " + why4)
st_now.save()
check("save/load 往返一致", set(AlertState(st_now.path).data.keys()) == set(st_now.data.keys()))
check("prune 返回清掉的条数", isinstance(st_now.prune(), int))

# ============================================================ T8 通知通道
print("T8 (通知架构) 通道可插拔：控制台/文件/Server酱/钉钉，任一失败不影响其它")
import notifier  # noqa: E402


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._p


class FakeReq:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def post(self, url, *a, **k):
        self.calls.append((url, k))
        return self.resp


names = [c.name for c in notifier.get_channels()]
check("默认通道含控制台 + 文件留痕",
      any("控制台" in n for n in names) and any("文件" in n for n in names), str(names))
check("未配置钉钉时不启用钉钉通道（本机已配则反过来断言）",
      (any("钉钉" in n for n in names) if getattr(config, "DINGTALK_WEBHOOK", "")
       else not any("钉钉" in n for n in names)), str(names))
check("Server酱 key 非空时启用", any("Server酱" in n for n in names), str(names))

# 文件通道指向临时目录：测试绝不能往仓库里写 alerts.log
_tmp_log = Path(tempfile.mkdtemp()) / "alerts.log"
_old_notify_file = getattr(config, "NOTIFY_FILE", "")
config.NOTIFY_FILE = str(_tmp_log)

notifier.requests = FakeReq(FakeResp(200, {"code": 0, "data": {"pushid": "p1"}}))
buf = io.StringIO()
with redirect_stdout(buf):
    r = notifier.notify("测试标题", "测试内容")
out = buf.getvalue()
check("成功场景 ok>=1", r["ok"] >= 1, str(r))
check("文件留痕通道真的落盘（所有网络通道挂掉时报警也不会丢）",
      _tmp_log.exists() and ("测试标题" in _tmp_log.read_text(encoding="utf-8")), str(_tmp_log))

notifier.requests = FakeReq(FakeResp(200, {"code": 40001, "message": "今日推送条数已达上限"}))
buf2 = io.StringIO()
with redirect_stdout(buf2):
    r2 = notifier.notify("测试标题", "测试内容")
out2 = buf2.getvalue()
check("HTTP 200 但 code!=0 → 该通道记为失败", r2["fail"] >= 1, str(r2))
check("失败原因可见（含 code 与原因）", ("40001" in out2) and ("上限" in out2), repr(out2))
check("日志里不出现任何密钥", (config.SENDKEY1 not in out) and (config.SENDKEY1 not in out2))

# 钉钉：配上 webhook 后自动启用；errcode=0 视为成功；带加签与关键词
_old_webhook = getattr(config, "DINGTALK_WEBHOOK", "")
_old_secret = getattr(config, "DINGTALK_SECRET", "")
config.DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=FAKE"
config.DINGTALK_SECRET = "SECfake"
config.DINGTALK_KEYWORD = "监控"
dt_names = [c.name for c in notifier.get_channels()]
check("配置 webhook 后钉钉通道自动启用", any("钉钉" in n for n in dt_names), str(dt_names))
freq = FakeReq(FakeResp(200, {"errcode": 0, "errmsg": "ok"}))
notifier.requests = freq
buf3 = io.StringIO()
with redirect_stdout(buf3):
    r3 = notifier.notify("报警", "内容")
check("钉钉 errcode=0 → 成功", r3["ok"] >= 1, str(r3))
dt_calls = [(u, k) for u, k in freq.calls if "dingtalk" in u]
check("钉钉请求带加签参数（timestamp+sign）",
      bool(dt_calls) and ("sign=" in dt_calls[0][0]) and ("timestamp=" in dt_calls[0][0]), str(dt_calls))
check("钉钉消息带关键词（机器人安全设置要求）",
      any("监控" in json.dumps(k.get("json", {}), ensure_ascii=False) for _u, k in dt_calls),
      str([k.get("json") for _u, k in dt_calls]))
config.DINGTALK_WEBHOOK = _old_webhook
config.DINGTALK_SECRET = _old_secret
config.NOTIFY_FILE = _old_notify_file

# ============================================================ T9 报警判定 + 报告
print("T9 (P1-7/N12/P1-12) 报警判定与报告渲染：来源唯一、key 稳定、用实时价")


TOP_KEYS = {"pair", "coin", "signal", "reverse_alert", "b_score", "s_score",
            "ls_pct", "ls_n", "daily_up", "flow", "ls_account", "ls_size"}


def mk_res(**kw):
    """构造一份 evaluate.evaluate_coin 的返回结构（离线，不联网）。"""
    res = {"pair": "SUI_USDT", "coin": "SUI",
           "ind_l": {"rsi": 50.0, "close": 100.0, "boll_u": 110.0, "boll_l": 90.0,
                     "boll_m": 100.0, "trend_up": True},
           "ind_4h": {"trend_up": True}, "daily_up": True, "flow": {"net_inflow": 0.0},
           "ls_account": 0.6, "ls_size": 0.9, "ls_pct": None, "ls_n": 3,
           "b_score": 0.0, "s_score": 0.0, "signal": "观望", "reverse_alert": None}
    ind = {"price": 100.0, "close": 100.0, "day_chg": 0.0, "vol_ratio": 1.0, "trend_up": True,
           "rsi": 50.0, "ma20": 90.0, "prev_close": 95.0, "bar_time": "2026-09-29 09:15",
           "boll_u": 110.0, "boll_l": 90.0, "boll_m": 100.0, "bar_closed": True, "df": None,
           "shadows": [(1.0, 0.1, 0.1), (1.0, 0.1, 0.1)]}
    for k, v in kw.items():
        if k in TOP_KEYS:
            res[k] = v
        elif k == "rsi_l":
            res["ind_l"]["rsi"] = v
        else:
            ind[k] = v
    res["ind_s"] = ind
    return res


check("平静行情不产生报警", evaluate.build_alerts(mk_res()) == [], str(evaluate.build_alerts(mk_res())))
al = evaluate.build_alerts(mk_res(day_chg=6.0))
check("+6% 触发涨跌幅报警", any("涨跌幅" in k for k, _t, _b in al), str([k for k, _t, _b in al]))
check("报警 key 不含具体数字（同类告警才能被冷却识别）",
      all(not re.search(r"\d", k.split("_", 1)[1]) for k, _t, _b in al), str([k for k, _t, _b in al]))
check("报警正文含已收盘bar时间与量能", ("09:15" in al[0][2]) and ("均量" in al[0][2]), al[0][2])
check("跌破MA20 触发",
      any("跌破MA20" in k for k, _t, _b in evaluate.build_alerts(mk_res(prev_close=95.0, close=89.0, ma20=90.0, trend_up=True))))
check("信号反转触发",
      any("信号反转" in k for k, _t, _b in evaluate.build_alerts(mk_res(reverse_alert="信号反转：观望→买入"))))
r_rsi = mk_res(rsi=85.0)
r_rsi["ind_l"]["rsi"] = 85.0
r_rsi["ind_s"]["shadows"] = [(1.0, 2.0, 0.1), (1.0, 2.0, 0.1)]
check("RSI超买+连续长上影触发",
      any("超买长上影" in k for k, _t, _b in evaluate.build_alerts(r_rsi)))

# 移动止盈（N12）：当天最高价从 K 线 ts 列取
today_ts = int(time.mktime(time.strptime(datetime.now().strftime("%Y-%m-%d") + " 00:00", "%Y-%m-%d %H:%M")))
kdf = pd.DataFrame([{"ts": str(today_ts + i * 900), "high": 100.0 + i, "open": 100.0,
                     "close": 100.0, "low": 99.0, "vol": 100.0} for i in range(10)])
check("当天最高价从 K 线 ts 列取（原补丁脚本用 df.index.date 会 AttributeError）",
      evaluate.day_high(kdf) == 109.0, str(evaluate.day_high(kdf)))
r_dd = mk_res(price=95.0)
r_dd["ind_s"]["df"] = kdf
check("N12 回撤 >=3% 触发移动止盈提醒",
      any("移动止盈" in k for k, _t, _b in evaluate.build_alerts(r_dd)),
      str([k for k, _t, _b in evaluate.build_alerts(r_dd)]))
r_dd2 = mk_res(price=109.5)
r_dd2["ind_s"]["df"] = kdf
check("回撤不足 3% 不提醒", not any("移动止盈" in k for k, _t, _b in evaluate.build_alerts(r_dd2)))

# 到价提醒用实时价（P1-12：原来用已收盘 bar 的 close，止损会晚一步）
config.PRICE_ALERT["SUI_USDT"] = (9999.0, 90.0)      # 临时注入：止盈 9999 / 止损 90
try:
    al_stop = evaluate.build_alerts(mk_res(price=89.0, close=95.0))
    check("到价提醒用实时价（89 跌破止损 90）触发",
          any("止损" in k for k, _t, _b in al_stop), str([k for k, _t, _b in al_stop]))
    al_ok = evaluate.build_alerts(mk_res(price=95.0, close=89.0))
    check("已收盘bar的 close(89) 不参与到价判断（实时价 95 时不触发）",
          not any(("止损" in k) or ("止盈" in k) for k, _t, _b in al_ok),
          str([k for k, _t, _b in al_ok]))
finally:
    config.PRICE_ALERT.pop("SUI_USDT", None)

rep = "\n".join(evaluate.render_coin_report(mk_res(day_chg=1.0)))
check("报告含 bar 口径说明", ("已收盘" in rep) and ("09:15" in rep), rep[:200])
check("报告同时展示 size 与 account 两个口径",
      ("持仓多空比" in rep) and ("账户多空比" in rep), rep)
check("报告给出双向建议（持仓/空仓）", ("持仓建议" in rep) and ("空仓建议" in rep), rep)

# ── 走势图（展示层）────────────────────────────────────────────
# 为什么单列一节：序列与渲染都要**有数据**才会被走到，函数名写错（NameError）之类
# 的错误在没有行情时完全测不出来，一上线有币了整页就 500。
import panel_chart                                                            # noqa: E402
_wave = pd.DataFrame([{"ts": str(1_700_000_000 + i * 900),
                       "close": 100.0 + ((i * 37) % 23) - 11 + i * 0.05,
                       "high": 101.0 + ((i * 37) % 23) - 11 + i * 0.05,
                       "low": 99.0 + ((i * 37) % 23) - 11 + i * 0.05,
                       "open": 100.0 + ((i * 37) % 23) - 11 + i * 0.05,
                       "vol": 1000.0 + i} for i in range(100)])
_s = panel_chart.series(_wave)
_html = panel_chart.render_chart("SUI", _s)
check("走势图窗口 = 显示根数（取到最后一根已收盘 bar）",
      _s["n"] == panel_chart.N_BARS and len(_s["close"]) == _s["n"], f'n={_s["n"]}')
check("走势图 4 个子图 + 4 个时间刻度",
      _html.count('<svg class="chart"') == 4 and _html.count('class="xaxis"') == 4,
      f'svg={_html.count(chr(60) + "svg class=" + chr(34) + "chart" + chr(34))} axis={_html.count("xaxis")}')
check("走势图渲染不抛异常且标签配对（有数据才会走到的代码）",
      _html.count("<details") == _html.count("</details>") and "<svg" in _html, _html[:120])
check("走势图不泄漏 nan/None",
      ("nan" not in _html.lower()) and ("None" not in _html), "")
check("每条折线至少 2 个点",
      all(len(p.split()) >= 2 for p in re.findall(r'points="([^"]*)"', _html)), "")
check("图上最后一个点 == 该根已收盘 bar 的指标值（防漂移）",
      abs(panel_chart.last_values(_s)["rsi"]
          - float(__import__("indicators").calc_rsi(_wave["close"]).iloc[-2])) < 1e-6,
      str(panel_chart.last_values(_s)["rsi"]))
check("子图写显式折叠键（summary 里有实时数字，自动派生键会每轮变）",
      _html.count('data-persist="chart:SUI:') == 4, "")

# ============================================================ 汇总
print("\n" + "-" * 70)
if FAILS:
    print("结果：" + str(len(FAILS)) + " 项失败")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("结果：全部通过")
sys.exit(0)
