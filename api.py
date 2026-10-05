import requests
import time
from config import BASE


def _get_json(url, timeout=15, tries=3):
    """统一的请求 + 重试 + **状态码检查 + 返回类型检查**。

    原来每个函数都是：
        try: r = requests.get(url, timeout=15); return r.json()
        except: time.sleep(1)
    问题有三个：
      1) `except:` 光秃秃的 —— 连 KeyboardInterrupt 都吞，Ctrl+C 都停不下来；
      2) 不看 status_code —— 被限流返回 HTML 时 r.json() 抛异常被吞，
         **上层拿到 [] 当成"没数据"，报警静默失效**；
      3) 返回 [] 和返回数据在调用方无法区分。
    现在：HTTP 非 200 或返回的不是 list/dict 都算失败并打印原因；重试后仍失败才返回 None，
    调用方可以据此提示"这轮数据缺失"。

    ★ API Key 轮换（gate_keys）：见该模块说明。默认**不签名**，
      所以行为和以前完全一致；把路径加进 GATE_SIGNED_PATHS 后，
      该路径的请求会自动带上轮换到的 key，额度就被分摊开了。
    """
    last = ""
    for i in range(tries):
        # ── 选 key（默认不签名 → 返回空头，行为不变）──
        headers = {}
        used_key = None
        try:
            import gate_keys
            if gate_keys.needs_sign(url):
                used_key, _sec = gate_keys.pick(url)
                if used_key:
                    headers = gate_keys.sign_headers(url, key=used_key[0]
                                                     if isinstance(used_key, tuple)
                                                     else used_key)
        except Exception as e:
            print(f"[api] key 轮换跳过（{type(e).__name__}: {e}）", flush=True)

        try:
            r = requests.get(url, timeout=timeout, headers=headers or None)
            try:
                import gate_keys as _gk
                throttled = r.status_code in (429, 503)
                _gk.note_use(url,
                             key=(used_key[0] if isinstance(used_key, tuple) else used_key),
                             throttled=throttled)
            except Exception:
                pass

            if r.status_code != 200:
                last = f"HTTP {r.status_code} {r.text[:120]}"
                # 被限流：等一下再试（也用掉下一次尝试换 key 的机会）
                if r.status_code in (429, 503):
                    print(f"[api] 被限流 HTTP {r.status_code}，{1.5 * (i + 1):.1f}s 后重试"
                          f"（第 {i + 1}/{tries} 次）", flush=True)
                    time.sleep(1.5 * (i + 1))
                else:
                    time.sleep(1)
                continue
            data = r.json()
            if not isinstance(data, (list, dict)):
                last = f"返回类型异常：{type(data).__name__}"
                time.sleep(1)
                continue
            return data
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(1)
        except ValueError as e:                 # r.json() 失败
            last = f"JSON 解析失败: {e}"
            time.sleep(1)
    print(f"[api] 取数失败（已重试 {tries} 次）: {url}  → {last}", flush=True)
    return None


def get_kline(pair, interval='15m', limit=100):
    """K 线。**15m 一律实时**（对方口径：用还在走的那根，不能加延时）。

    其余周期（1h/4h/1d…）走缓存 —— 它们"下一个整点才可能变"，
    按实时频率拉纯属浪费，也是被限流的主因。
    缓存 key 带"当前 K 线起点"，跨整点自动失效，所以不会晚发现新数据。
    """
    url = f"{BASE}/spot/candlesticks?currency_pair={pair}&interval={interval}&limit={limit}"

    ttl = 0
    try:
        import kline_cache
        if str(interval) != "15m":          # ★ 15m 永不缓存
            ttl = kline_cache.ttl_for(interval)
        if ttl > 0:
            key = ("kline", pair, str(interval), limit,
                   kline_cache.bar_start(interval))
            data = kline_cache.get_or_fetch(key, ttl, lambda: _get_json(url))
            return data if isinstance(data, list) else []
    except Exception as e:
        # 缓存层出任何问题都必须退化成"直接取"，绝不能因为缓存把数据搞没
        print(f"[api] 缓存跳过（{type(e).__name__}: {e}），改为直接取数", flush=True)

    data = _get_json(url)
    return data if isinstance(data, list) else []


def get_trades(pair, limit=100):
    """逐笔成交。

    ★ 小窗口（limit<=100）走**极短**缓存（默认 20 秒）：
      理由：一轮 27 秒里有 3 处要逐笔 —— 主循环 1 次 + 1h 资金流内部 1 次，
      开的还是同一个币的**同一份最新成交列表**。同一轮里重复拉纯属浪费。
      20 秒 < 一轮，所以**每轮至少真取一次**，跟得上最新成交。

    ★ 大窗口（limit=1000，算 1h 资金流用）**不缓存**，
      它本来就是历史汇总，且需要每次都看到最新几百笔。
    """
    url = f"{BASE}/spot/trades?currency_pair={pair}&limit={limit}"
    ttl = 0
    try:
        import kline_cache
        if int(limit) <= 100:
            ttl = kline_cache.ttl_for("trades")
        if ttl > 0:
            bucket = int(time.time() * 1000) // (ttl * 1000)
            data = kline_cache.get_or_fetch(
                ("trades", pair, int(limit), bucket), ttl, lambda: _get_json(url))
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[api] 缓存跳过（{type(e).__name__}: {e}），改为直接取数", flush=True)
    data = _get_json(url)
    return data if isinstance(data, list) else []


def get_ls(pair):
    """大户多空比（公开接口，无需签名）。

    ★ 修 P0-5（新发现）：原实现调 `/futures/{pair}/long_short`，Gate 已经要求
      `Timestamp`/`KEY`/`SIGN` 签名头，**匿名调用一律 HTTP 400**
      （实测：Missing required header: Timestamp）。
      而 main.py 里是 `lsd = ls[-1] if ls else {'top_lsr_account': 1}` —— 于是永远走兜底值 1，
      结果：
        · strategy.calc_score 里 top_ratio<0.5 / >2 两档打分**永不生效**
        · "大户多空比<0.5 极端偏空 / >2 极端偏多" 两条报警**永不触发**
        · 报告里"大户持仓多空比 1.00（平衡）"是**假的**，看着一切正常
      改成公开的 `/futures/usdt/contract_stats`，一次拿到 top_lsr_account 与 top_lsr_size。
    """
    url = f"{BASE}/futures/usdt/contract_stats?contract={pair}&limit=1"
    # Gate 自身约 5 分钟更新一次；按 60s 轮询纯属重复拉。
    # key 取 5 分钟桶 —— 跨桶自动重拉，不会晚于 Gate 的更新节奏。
    try:
        import kline_cache
        ttl = kline_cache.ttl_for("ls")
        if ttl > 0:
            bucket = int(time.time()) // 300 * 300
            data = kline_cache.get_or_fetch(
                ("ls", pair, bucket), ttl, lambda: _get_json(url, timeout=10))
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[api] 缓存跳过（{type(e).__name__}: {e}），改为直接取数", flush=True)
    data = _get_json(url, timeout=10)
    if isinstance(data, list):
        return data
    return []


def get_flow_1h(pair):
    """最近 1 小时资金净流入：拿最近 1000 笔逐笔成交，累加买卖差额。"""
    try:
        trades = get_trades(pair, limit=1000)
        if not trades:
            return 0
        buy_v = sell_v = 0.0
        for t in trades:
            v = float(t['amount']) * float(t['price'])
            if t['side'] == 'buy':
                buy_v += v
            else:
                sell_v += v
        return buy_v - sell_v
    except (KeyError, TypeError, ValueError) as e:
        print(f"[api] get_flow_1h({pair}) 数据异常：{type(e).__name__}: {e}", flush=True)
        return 0


def get_btc_chg():
    """BTC 最近 1 小时涨跌幅（用最近 2 根 1h K线）。"""
    try:
        data = get_kline('BTC_USDT', '1h', limit=2)
        if len(data) >= 2:
            prev_close = float(data[-2][2])
            now_close = float(data[-1][2])
            if prev_close:
                return (now_close - prev_close) / prev_close * 100
    except (IndexError, TypeError, ValueError) as e:
        print(f"[api] get_btc_chg 数据异常：{type(e).__name__}: {e}", flush=True)
    return 0


def check_events():
    return []


# ↓↓↓ 以下两个是**占位实现**，返回值永远是常数。报告里请明确标注"未接入"，
#     不要让它们看起来像真实数据（原来 predict.py 直接当真实值展示）。
def get_big_order(pair):
    """未接入：暂无大单数据源，恒返回 (0, 0)。"""
    return (0, 0)


def get_funding_rate(pair):
    """未接入：暂无资金费率数据源，恒返回 (0.001, 0)。

    报告里原来硬编码显示"资金费率: 0.01%（正常）"——那是假的，见 main.py 的说明。
    """
    return (0.001, 0)


def get_orderbook(pair):
    """买卖一价 + 两侧挂单总额（USD 估算）。

    注意：挂单总额是把各档 price*amount 直接累加，只是"深度体量"的粗略指标，
    不代表压力/支撑（挂单可以随时撤）。报告里别过度解读。
    """
    url = f"{BASE}/spot/order_book?currency_pair={pair}&limit=50"
    data = _get_json(url, timeout=10)
    try:
        bids = data.get('bids', []) if isinstance(data, dict) else []
        asks = data.get('asks', []) if isinstance(data, dict) else []
        bid_total = sum(float(p) * float(a) for p, a in bids)
        ask_total = sum(float(p) * float(a) for p, a in asks)
        buy1 = float(bids[0][0]) if bids else 0
        sell1 = float(asks[0][0]) if asks else 0
        return (buy1, sell1, bid_total, ask_total)
    except (AttributeError, IndexError, TypeError, ValueError) as e:
        print(f"[api] get_orderbook({pair}) 数据异常：{type(e).__name__}: {e}", flush=True)
        return (0, 0, 0, 0)


def analyze_trades(trades):
    buy_v = sell_v = 0.0
    for t in trades:
        v = float(t['amount']) * float(t['price'])
        if t['side'] == 'buy':
            buy_v += v
        else:
            sell_v += v
    return {"buy_volume": buy_v, "sell_volume": sell_v, "net_inflow": buy_v - sell_v}

