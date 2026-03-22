# -*- coding: utf-8 -*-
"""
Binance 价格查询模块（基于 ccxt）

用途：
- 根据「交易对 + 时间戳」获取该时刻对应 K 线收盘价（默认 1d）
- 作为保证金币种兑 USD 的动态汇率来源（如 BTC/USDT、ETH/USDT）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Tuple, List
import time

import ccxt


_INTERVAL_MS = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "8h": 8 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def _to_ms(ts) -> int:
    """将日期时间转换为 UTC 毫秒时间戳。"""
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromisoformat(str(ts))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp() * 1000)


def _to_ccxt_symbol(raw_symbol: str) -> str:
    """兼容 BTCUSDT / BTC/USD / BTCUSDC 等写法，转为 ccxt symbol。"""
    s = str(raw_symbol).upper().replace("-", "").replace("_", "").replace("/", "")
    for quote in ("USDT", "USDC", "USD", "BUSD", "FDUSD"):
        if s.endswith(quote) and len(s) > len(quote):
            base = s[: -len(quote)]
            return f"{base}/{quote}"
    return raw_symbol if "/" in str(raw_symbol) else str(raw_symbol).upper()


@dataclass
class BinancePriceClient:
    interval: str = "1d"
    timeout_sec: int = 8
    retry_times: int = 5
    retry_sleep_sec: float = 1.0
    debug: bool = False
    fail_fast_when_fallback: bool = True
    exchanges: List[str] = field(default_factory=lambda: ["binance", "binanceus"])
    _cache: Dict[Tuple[str, str, int], float] = field(default_factory=dict)
    _preferred_exchange: str | None = None
    _exchange_pool: Dict[str, ccxt.Exchange] = field(default_factory=dict)

    def _bucket_start(self, ts_ms: int) -> int:
        step = _INTERVAL_MS.get(self.interval, _INTERVAL_MS["1d"])
        return (ts_ms // step) * step

    def prefetch_range(self, symbol: str, start_ts, end_ts) -> int:
        """
        批量预拉取时间区间内的 K 线并写入缓存，减少逐日网络请求。
        返回写入缓存的 K 线数量。
        """
        ccxt_symbol = _to_ccxt_symbol(symbol)
        start_ms = self._bucket_start(_to_ms(start_ts))
        end_ms = self._bucket_start(_to_ms(end_ts))
        step_ms = _INTERVAL_MS.get(self.interval, _INTERVAL_MS["1d"])
        if end_ms < start_ms:
            return 0

        if self.debug:
            print(
                f"[margin_fx] prefetch start symbol={ccxt_symbol} "
                f"interval={self.interval} range=[{start_ts}, {end_ts}]"
            )

        # 优先上次成功的交易所，再尝试其余交易所
        exchange_ids = []
        if self._preferred_exchange:
            exchange_ids.append(self._preferred_exchange)
        for ex_id in self.exchanges:
            if ex_id not in exchange_ids:
                exchange_ids.append(ex_id)

        last_err = None
        for ex_id in exchange_ids:
            try:
                ex = self._get_exchange(ex_id)
                since = start_ms
                loaded = 0
                while since <= end_ms:
                    rows = ex.fetch_ohlcv(
                        ccxt_symbol,
                        timeframe=self.interval,
                        since=since,
                        limit=1000,
                    )
                    if not rows:
                        break

                    progressed = False
                    for row in rows:
                        row_ts = int(row[0])
                        if row_ts < start_ms:
                            continue
                        if row_ts > end_ms:
                            continue
                        bucket = self._bucket_start(row_ts)
                        key = (ccxt_symbol, self.interval, bucket)
                        self._cache[key] = float(row[4])
                        loaded += 1
                        progressed = True

                    last_row_ts = int(rows[-1][0])
                    next_since = self._bucket_start(last_row_ts) + step_ms
                    if next_since <= since:
                        break
                    since = next_since
                    if not progressed and last_row_ts > end_ms:
                        break

                self._preferred_exchange = ex_id
                if self.debug:
                    print(
                        f"[margin_fx] prefetch ok exchange={ex_id} symbol={ccxt_symbol} "
                        f"loaded={loaded}"
                    )
                return loaded
            except Exception as e:
                last_err = e
                if self.debug:
                    print(f"[margin_fx] prefetch fail exchange={ex_id} symbol={ccxt_symbol} err={type(e).__name__}: {e}")
                continue

        raise RuntimeError(
            f"prefetch failed for {ccxt_symbol} range=[{start_ts}, {end_ts}], last_error={last_err}"
        )

    def _get_exchange(self, ex_id: str) -> ccxt.Exchange:
        if ex_id in self._exchange_pool:
            return self._exchange_pool[ex_id]

        ex_cls = getattr(ccxt, ex_id)
        ex = ex_cls(
            {
                "enableRateLimit": True,
                "timeout": int(self.timeout_sec * 1000),
                "options": {
                    "adjustForTimeDifference": True,
                },
            }
        )
        self._exchange_pool[ex_id] = ex
        return ex

    def get_price_at(self, symbol: str, ts) -> float:
        """获取 symbol 在 ts 所在 K 线周期的收盘价。"""
        ccxt_symbol = _to_ccxt_symbol(symbol)
        ts_ms = _to_ms(ts)
        bucket = self._bucket_start(ts_ms)
        step_ms = _INTERVAL_MS.get(self.interval, _INTERVAL_MS["1d"])
        key = (ccxt_symbol, self.interval, bucket)
        if key in self._cache:
            return self._cache[key]

        if self.debug:
            print(
                f"[margin_fx] fetch start symbol={ccxt_symbol} ts={ts} "
                f"interval={self.interval} retry_times={self.retry_times} timeout={self.timeout_sec}s"
            )

        # 参考 binance_cfuture 的 retry_wrapper：重试 + sleep
        last_err = None
        price = None
        for _ in range(max(1, int(self.retry_times))):
            # 优先上次成功的交易所，再尝试 binance -> binanceus
            exchange_ids = []
            if self._preferred_exchange:
                exchange_ids.append(self._preferred_exchange)
            for ex_id in self.exchanges:
                if ex_id not in exchange_ids:
                    exchange_ids.append(ex_id)

            for ex_id in exchange_ids:
                try:
                    t0 = time.time()
                    ex = self._get_exchange(ex_id)
                    rows = ex.fetch_ohlcv(
                        ccxt_symbol,
                        timeframe=self.interval,
                        since=bucket,
                        limit=1,
                    )
                    if rows:
                        # [timestamp, open, high, low, close, volume]
                        row_ts = int(rows[0][0])
                        # 严格要求返回K线落在请求bucket区间，避免拿到“最早可用K线”造成历史失真
                        if not (bucket <= row_ts < bucket + step_ms):
                            raise ValueError(
                                f"ohlcv_out_of_range: request_bucket={bucket}, row_ts={row_ts}, "
                                f"symbol={ccxt_symbol}, interval={self.interval}"
                            )
                        price = float(rows[0][4])
                    else:
                        raise ValueError(
                            f"ohlcv_empty: symbol={ccxt_symbol}, bucket={bucket}, interval={self.interval}"
                        )
                    self._preferred_exchange = ex_id
                    if self.debug:
                        print(
                            f"[margin_fx] fetch ok exchange={ex_id} symbol={ccxt_symbol} "
                            f"price={price:.8f} elapsed={time.time() - t0:.2f}s"
                        )
                    break
                except Exception as e:
                    last_err = e
                    if self.debug:
                        print(f"[margin_fx] fetch fail exchange={ex_id} symbol={ccxt_symbol} err={type(e).__name__}: {e}")
                    continue

            if price is not None:
                break
            if self.fail_fast_when_fallback:
                # 外层会使用固定汇率兜底，此处不做长时间重试，避免“卡住”
                break
            time.sleep(max(0.0, float(self.retry_sleep_sec)))

        if price is None:
            raise RuntimeError(
                f"Binance price fetch failed for {ccxt_symbol} at {ts}. last_error={last_err}"
            )

        self._cache[key] = price
        return price
