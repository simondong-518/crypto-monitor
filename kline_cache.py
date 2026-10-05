"""K 线 / 慢变数据缓存 —— 只为**减少请求数**，不改变任何判定结果。

背景：一轮 6 个币要打 50 次 HTTP，每分钟 60 秒跑一轮 ≈ 110 请求/分钟，
被 Gate 限流。其中大部分是**变化很慢**的数据被按实时频率在拉：
日线一天才出一根，却每 60 秒问一次（一天问 1440 次，1 次就够）。

════════════════════════════════════════════════════════════════
★ 最重要的一条：15m K 线**不缓存**（用户明确要求）
  对方的口径是"用还在走的这根 K 线"（iloc[-1]，有意设计）。
  一旦给 15m 加固定 TTL，延时就会叠加，信号会变晚 —— 那等于偷偷改了他的策略。
  所以 get_kline(pair, '15m') 走原路，一次不省。
════════════════════════════════════════════════════════════════

规矩（三条，都不要随手改）：

1. **只有"慢于一轮"的周期才缓存**：1d / 4h / 1h 以及大户多空比、RSS。
   判定标准是「这根 K 线有没可能已经更新」：用**当前时间所属 K 线的起点**做 key，
   整点一跨就自动失效，不需要猜 TTL。

2. **缓存命中要能把"最新一根"接对**：K 线是按 (周期起点) 分组的，
   所以 key = (pair, interval, 该周期当前 K 线的起点时间戳)。
   同一根 K 线内重复请求 → 命中；跨到下一根 → 自动重新拉。
   这样即使把 1h 缓存 1 小时，也**不会**晚于"下一个整点"发现新数据。

3. **失败不缓存**：取数失败（None/空）绝不能写进缓存，
   否则一次网络抖动会让这个币"假死"一整个周期。

怎么关掉：config.py 里 CACHE_ENABLED = False（回到全实时）。
怎么调节：CACHE_TTL 里按周期改秒数；要"彻底实时"就把该项设为 0。
"""
import threading
import time

_LOCK = threading.Lock()
_STORE = {}          # key -> (expire_ts, value)

# 命中/未命中计数（只在自检和日志里用，不参与判定）
STATS = {"hit": 0, "miss": 0, "bypass": 0}


def _cfg(name, default):
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default


def enabled():
    return bool(_cfg("CACHE_ENABLED", True))


def ttl_for(interval):
    """该周期允许多久的缓存（秒）。0 = 不缓存。"""
    table = _cfg("CACHE_TTL", {}) or {}
    try:
        return int(table.get(interval, 0))
    except Exception:
        return 0


def bar_start(interval, now=None):
    """当前时间所属 K 线的起点（Unix 秒）。

    Gate 的 K 线边界是**绝对整点**（15m → 0/15/30/45），不是"从现在往前推"，
    所以同一根 K 线对所有观察者是同一个时间窗。
    """
    now = int(now if now is not None else time.time())
    secs = {
        "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "4h": 4 * 3600, "8h": 8 * 3600,
        "1d": 86400, "1w": 7 * 86400,
    }.get(str(interval), 0)
    if not secs:
        return now              # 未知周期 → 不分组（等于不缓存）
    return now - (now % secs)


def get_or_fetch(key, ttl, fetch, *, on_hit=None):
    """取缓存；没有/过期就调 fetch() 并写回。

    key  —— 已含周期起点，跨 K 线自动换 key
    ttl  —— 秒；<=0 表示不缓存，直接 fetch（并计数 bypass）
    fetch —— 无参函数，返回数据；**返回 None/空 时不写缓存**
    """
    if not enabled() or ttl <= 0:
        STATS["bypass"] += 1
        return fetch()

    now = time.time()
    with _LOCK:
        ent = _STORE.get(key)
        if ent and ent[0] > now:
            STATS["hit"] += 1
            if on_hit:
                try:
                    on_hit()
                except Exception:
                    pass
            return ent[1]

    val = fetch()

    # 失败不缓存 —— 否则一次抖动会把这个币"假死"一整个周期
    empty = val is None or (hasattr(val, "__len__") and len(val) == 0)
    with _LOCK:
        STATS["miss"] += 1
        if not empty:
            _STORE[key] = (now + ttl, val)
    return val


def clear():
    with _LOCK:
        _STORE.clear()


def snapshot_stats():
    with _LOCK:
        return dict(STATS, entries=len(_STORE))
