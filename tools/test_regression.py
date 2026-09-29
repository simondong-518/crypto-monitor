"""最小回归测试：对应本轮 6 项修复（P0-1 / N13 / N14 / N15 / P0-2 / P0-6）。

全部离线：不联网、不推送、不写仓库里的文件（临时文件写到系统临时目录）。
为什么要有这个文件：P0-1 那种「比较用的中文字面量和实际返回值不一致」的 bug，
本质上是**没有任何断言**在看着这段代码 —— 3 行断言就能拦住它。

跑法（需要 pandas）：
    M:\\project\\PA_Agent\\.venv\\Scripts\\python.exe tools\\test_regression.py
"""
import io
import json
import re
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import pandas as pd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"    <- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- P0-1
print("T1 (P0-1) main.py 比较的中文字面量，必须来自 strategy.py 实际返回的信号值")
main_src = (ROOT / "main.py").read_text(encoding="utf-8")
strat_src = (ROOT / "strategy.py").read_text(encoding="utf-8")
returned = set(re.findall(r'current\s*=\s*"([^"]+)"', strat_src))
compared = set(re.findall(r'current_signal\s*==\s*"([^"]+)"', main_src))
check("strategy.py 的返回值集合 == {买入,卖出,观望}", returned == {"买入", "卖出", "观望"}, repr(returned))
check("main.py 比较的每个字面量都在该集合内", bool(compared) and compared <= returned,
      f"compared={compared} returned={returned}")

import strategy  # noqa: E402

strategy.last_signal.clear()
sig_buy, _ = strategy.get_signal(
    "T1", 4.0, 0.0,
    {"rsi": 40, "close": 10.5, "boll_m": 10.0},
    {"rsi": 40, "close": 10.5, "boll_m": 10.0},
)
check("买分4.0+双周期RSI<45 → get_signal 真的返回 买入", sig_buy == "买入", sig_buy)
check("该返回值能被 main.py 的分支命中（否则建议永远走 else）", sig_buy in compared,
      f"{sig_buy!r} not in {compared!r}")

# ------------------------------------------------------- 编码（P0-1 验收）
print("T2 (P0-1) main.py 不含 BOM、不含乱码")
import check_encoding  # noqa: E402

errs, moji, cmp_lines, sus = check_encoding.check_file(ROOT / "main.py", False)
check("无 BOM / 合法 UTF-8", not errs, str(errs))
check("无二次编码乱码", not moji and not sus, f"严格={moji} 疑似={sus}")


# ------------------------------------------------------------ N13 / N14
print("T3 (N13/N14) 连续3根阳线 buy+1.5 / 连续3根阴线 sell+1.5（用已收盘的3根）")

def make_case(three_up, three_down, live_close):
    """构造 25 根 15m K 线：其它规则全部保持中性，只让「连续3根」这一条可变。
    基准态用「十字星」（close == open）—— 既不是阳线也不是阴线，两条规则都不触发。"""
    rows = []
    for i in range(25):
        rows.append({"open": 9.9, "high": 10.05, "low": 9.88, "close": 10.0, "vol": 100.0})
    df = pd.DataFrame(rows)
    # 最后 3 根「已收盘」bar = iloc[-4:-1]
    for pos in (-4, -3, -2):
        i = len(df) + pos
        df.loc[i, "open"] = 10.0
        if three_up:
            df.loc[i, "close"] = 10.30
            df.loc[i, "high"] = 10.35
        elif three_down:
            df.loc[i, "close"] = 9.70
            df.loc[i, "low"] = 9.65
        else:
            df.loc[i, "close"] = 10.0          # 十字星
    df.loc[len(df) - 1, "close"] = live_close  # 形成中的 bar，不该被这条规则看到
    ind_s = {
        "close": live_close, "boll_u": 11.0, "boll_m": 10.0, "boll_l": 9.0,
        "trend_up": True, "boll_all_up": False, "rsi": 50.0,
        "macd_gold": False, "macd_dead": False,
        "kdj_j": 50.0, "k_gold": False, "k_dead": False,
    }
    ind_l = {"rsi": 50.0, "trend_up": False}
    flow = {"net_inflow": 0.0}
    return strategy.calc_score(ind_s, ind_l, flow, 1.0, df)


b0, s0 = make_case(False, False, 10.2)   # 基准：无 3 连
b1, s1 = make_case(True, False, 10.2)    # 3 连阳 + close>中轨
b2, s2 = make_case(False, True, 9.8)     # 3 连阴 + close<中轨
b3, s3 = make_case(False, True, 10.2)    # 3 连阴但 close>中轨 → 不该加卖分
check(f"N13 三连阳加买分 1.5（基准 b={b0} → b={b1}）", round(b1 - b0, 4) == 1.5, f"{b0} -> {b1}")
check(f"N13 不影响卖分（{s0} -> {s1}）", round(s1 - s0, 4) == 0.0, f"{s0} -> {s1}")
check(f"N14 三连阴加卖分 1.5（基准 s={s0} → s={s2}）", round(s2 - s0, 4) == 1.5, f"{s0} -> {s2}")
check(f"N14 不影响买分（{b0} -> {b2}）", round(b2 - b0, 4) == 0.0, f"{b0} -> {b2}")
check(f"N14 收盘价在中轨之上时不加卖分（{s0} -> {s3}）", round(s3 - s0, 4) == 0.0, f"{s0} -> {s3}")

# -------------------------------------------------------------- N15
print("T4 (N15) 涨幅过大提示高位止盈，不再喊拿住")
import main  # noqa: E402

TH = 2.0
a_big = main.day_chg_alerts(12.0, True, True, TH)
a_mid = main.day_chg_alerts(7.0, True, True, TH)
a_novol = main.day_chg_alerts(3.0, True, False, TH)
a_ok = main.day_chg_alerts(3.0, True, True, TH)
a_down = main.day_chg_alerts(-6.0, False, True, TH)
check("+12% 提示高位止盈", any("高位止盈" in x for x in a_big), str(a_big))
check("+12% 不再喊拿住", not any("拿住" in x for x in a_big), str(a_big))
check("+7% 仍然喊拿住", any("拿住" in x for x in a_mid), str(a_mid))
check("+7% 不提示高位止盈", not any("高位止盈" in x for x in a_mid), str(a_mid))
check("拿住那句话说完整了（原为乱码）", "，趋势启动，拿住" in a_mid, str(a_mid))
check("量不够时 3% 不提醒", a_novol == [], str(a_novol))
check("量够时 3% 提醒", len(a_ok) == 1, str(a_ok))
check("-6% 报大跌且不提拿住", any("大跌" in x for x in a_down) and not any("拿住" in x for x in a_down), str(a_down))
import config  # noqa: E402

check("HIGH_CHG_THRESHOLD 可配置且为 10", getattr(config, "HIGH_CHG_THRESHOLD", None) == 10.0,
      str(getattr(config, "HIGH_CHG_THRESHOLD", None)))

# -------------------------------------------------------------- P0-2
print("T5 (P0-2) 推送计数：key 带日期分区，昨天的记录不再压制今天")
today = datetime.now().strftime("%Y-%m-%d")
tmp = Path(tempfile.mkdtemp()) / "pushed.json"
tmp.write_text(json.dumps({
    "2026-01-01|SUI_今日大跌": 3,      # 昨天/更早，且已顶到上限
    "2026-01-01|BSV_止损21.0": 3,
    today + "|SUI_今日大跌": 1,        # 今天，推过 1 次
}, ensure_ascii=False), encoding="utf-8")
main.pushed_file = str(tmp)
kept = main.load_pushed()
check("旧的（非当天）key 被丢弃", "2026-01-01|SUI_今日大跌" not in kept and "2026-01-01|BSV_止损21.0" not in kept,
      str(kept))
check("当天的 key 被保留", kept.get(today + "|SUI_今日大跌") == 1, str(kept))
check("今天的新告警不会被昨天的顶格记录压掉", kept.get(today + "|BSV_止损21.0", 0) == 0, str(kept))
check("_today() 格式为 YYYY-MM-DD", re.fullmatch(r"\d{4}-\d{2}-\d{2}", main._today()) is not None, main._today())
main.pushed = {today + "|X_测试": 2}
main.save_pushed()
check("save/load 往返一致", main.load_pushed().get(today + "|X_测试") == 2)
check("pushed.json 路径不依赖启动目录（用 __file__ 定位）",
      Path(main.pushed_file).is_absolute(), main.pushed_file)

# -------------------------------------------------------------- P0-6
print("T6 (P0-6) 推送失败必须可见（原来 HTTP 200 但 code!=0 会被静默吞掉）")
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
        self.calls = 0

    def post(self, *a, **k):
        self.calls += 1
        return self.resp


notifier.time.sleep = lambda s: None

notifier.requests = FakeReq(FakeResp(200, {"code": 0, "data": {"pushid": "p1"}}))
buf = io.StringIO()
with redirect_stdout(buf):
    ok = notifier.send_wx("测试标题", "测试内容")
out = buf.getvalue()
check("成功时返回成功渠道数", ok == len(notifier.CHANNELS), f"ok={ok} channels={len(notifier.CHANNELS)}")
check("成功时打印成功行", "推送成功" in out, repr(out))

notifier.requests = FakeReq(FakeResp(200, {"code": 40001, "message": "今日推送条数已达上限"}))
buf2 = io.StringIO()
with redirect_stdout(buf2):
    ok2 = notifier.send_wx("测试标题", "测试内容")
out2 = buf2.getvalue()
check("HTTP 200 但 code!=0 → 返回 0", ok2 == 0, f"ok2={ok2}")
check("失败带 HTTP/code/原因", "推送失败" in out2 and "40001" in out2 and "上限" in out2, repr(out2))
check("所有渠道失败时有显式汇总，不静默", "未送达" in out2, repr(out2))
check("日志里不出现密钥", config.SENDKEY1 not in out and config.SENDKEY1 not in out2)

# ---------------------------------------------------------------- 汇总
print("\n" + "-" * 70)
if FAILS:
    print(f"结果：{len(FAILS)} 项失败")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("结果：全部通过 ✓")
sys.exit(0)
