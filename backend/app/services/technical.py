"""Technical analysis indicators — pure numpy, no external TA libraries."""

import numpy as np


def sma(prices: np.ndarray, window: int) -> np.ndarray:
    """Simple Moving Average.

    Returns array of same length as prices; first (window-1) values are NaN.
    """
    result = np.full(len(prices), np.nan)
    if len(prices) < window:
        return result
    cumsum = np.cumsum(prices)
    cumsum = np.insert(cumsum, 0, 0.0)
    result[window - 1 :] = (cumsum[window:] - cumsum[:-window]) / window
    return result


def ema(prices: np.ndarray, span: int) -> np.ndarray:
    """Exponential Moving Average.

    k = 2 / (span + 1), seed with SMA of first `span` values.
    Returns array of same length; first (span-1) values are NaN.
    """
    result = np.full(len(prices), np.nan)
    if len(prices) < span:
        return result
    k = 2.0 / (span + 1)
    result[span - 1] = np.mean(prices[:span])
    for i in range(span, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1 - k)
    return result


def rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index using Wilder's exponential smoothing.

    RSI = 100 - (100 / (1 + RS)) where RS = avg_gain / avg_loss.
    Returns array of same length; first `period` values are NaN.
    """
    result = np.full(len(prices), np.nan)
    if len(prices) < period + 1:
        return result

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - 100.0 / (1.0 + rs)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - 100.0 / (1.0 + rs)

    return result


def macd(
    prices: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD — returns (macd_line, signal_line, histogram).

    MACD line = EMA(fast) - EMA(slow)
    Signal line = EMA(signal_period) of MACD line
    Histogram = MACD - Signal
    All arrays same length as prices; leading values are NaN.
    """
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)

    macd_line = ema_fast - ema_slow  # NaN propagates naturally

    # Signal line: EMA of valid (non-NaN) MACD values, mapped back
    valid_mask = ~np.isnan(macd_line)
    valid_vals = macd_line[valid_mask]

    signal_line = np.full(len(prices), np.nan)
    histogram = np.full(len(prices), np.nan)

    if len(valid_vals) >= signal_period:
        sig = ema(valid_vals, signal_period)
        valid_indices = np.where(valid_mask)[0]
        for j, idx in enumerate(valid_indices):
            if not np.isnan(sig[j]):
                signal_line[idx] = sig[j]
                histogram[idx] = macd_line[idx] - sig[j]

    return macd_line, signal_line, histogram


def bollinger(
    prices: np.ndarray,
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands — returns (upper, middle, lower).

    Middle = SMA(window), Upper/Lower = middle +/- num_std * rolling std.
    """
    middle = sma(prices, window)
    upper = np.full(len(prices), np.nan)
    lower = np.full(len(prices), np.nan)

    for i in range(window - 1, len(prices)):
        w = prices[i + 1 - window : i + 1]
        std = float(np.std(w, ddof=0))
        upper[i] = middle[i] + num_std * std
        lower[i] = middle[i] - num_std * std

    return upper, middle, lower


def vwap(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> np.ndarray:
    """Volume Weighted Average Price.

    Typical price = (H + L + C) / 3
    VWAP = cumulative(TP * volume) / cumulative(volume)
    """
    typical_price = (highs + lows + closes) / 3.0
    cum_tp_vol = np.cumsum(typical_price * volumes)
    cum_vol = np.cumsum(volumes)
    # Avoid division by zero
    result = np.where(cum_vol > 0, cum_tp_vol / cum_vol, np.nan)
    return result


def find_support_resistance(
    prices: np.ndarray,
    window: int = 20,
) -> dict:
    """Detect support and resistance levels using rolling window local extrema.

    Returns dict with 'support' and 'resistance' lists,
    each entry: {'price': float, 'strength': int, 'lastIndex': int}.
    """
    if len(prices) < window * 2 + 1:
        return {"support": [], "resistance": []}

    support_indices: list[int] = []
    resistance_indices: list[int] = []

    half = window
    for i in range(half, len(prices) - half):
        local = prices[i - half : i + half + 1]
        if prices[i] == np.min(local):
            support_indices.append(i)
        if prices[i] == np.max(local):
            resistance_indices.append(i)

    def _cluster_levels(
        indices: list[int], tolerance_pct: float = 0.02
    ) -> list[dict]:
        """Cluster nearby price levels and count touches."""
        if not indices:
            return []
        levels = [prices[i] for i in indices]
        clusters: list[dict] = []
        used = [False] * len(levels)

        for i, lvl in enumerate(levels):
            if used[i]:
                continue
            cluster_prices = [lvl]
            cluster_last = indices[i]
            used[i] = True
            for j in range(i + 1, len(levels)):
                if used[j]:
                    continue
                if abs(levels[j] - lvl) / lvl <= tolerance_pct:
                    cluster_prices.append(levels[j])
                    cluster_last = max(cluster_last, indices[j])
                    used[j] = True
            clusters.append(
                {
                    "price": round(float(np.mean(cluster_prices)), 4),
                    "strength": len(cluster_prices),
                    "lastIndex": int(cluster_last),
                }
            )

        # Sort by strength descending, keep top 5
        clusters.sort(key=lambda c: c["strength"], reverse=True)
        return clusters[:5]

    return {
        "support": _cluster_levels(support_indices),
        "resistance": _cluster_levels(resistance_indices),
    }


def generate_signals(
    prices: np.ndarray,
    volumes: np.ndarray,
    dates: list[str],
) -> list[dict]:
    """Generate trading signals from technical indicators.

    Signals:
    - Golden / death cross (SMA50 vs SMA200)
    - RSI overbought (>70) / oversold (<30)
    - MACD crossover
    - Bollinger squeeze (bands narrowing)

    Returns list of {signal, type, date, description}.
    """
    signals: list[dict] = []
    n = len(prices)
    if n < 201:
        # Need at least 200+ points for SMA200
        pass

    sma50 = sma(prices, 50)
    sma200 = sma(prices, 200)
    rsi_vals = rsi(prices, 14)
    macd_line, signal_line, _ = macd(prices)
    bb_upper, bb_middle, bb_lower = bollinger(prices)

    # -- Golden / death cross (check last 5 trading days) --
    lookback = min(5, n - 200) if n > 200 else 0
    for i in range(n - lookback, n):
        if i < 1 or np.isnan(sma50[i]) or np.isnan(sma200[i]):
            continue
        if np.isnan(sma50[i - 1]) or np.isnan(sma200[i - 1]):
            continue
        if sma50[i - 1] <= sma200[i - 1] and sma50[i] > sma200[i]:
            signals.append(
                {
                    "signal": "golden_cross",
                    "type": "bullish",
                    "date": dates[i],
                    "description": f"SMA50 ({sma50[i]:.2f}) crossed above SMA200 ({sma200[i]:.2f})",
                }
            )
        elif sma50[i - 1] >= sma200[i - 1] and sma50[i] < sma200[i]:
            signals.append(
                {
                    "signal": "death_cross",
                    "type": "bearish",
                    "date": dates[i],
                    "description": f"SMA50 ({sma50[i]:.2f}) crossed below SMA200 ({sma200[i]:.2f})",
                }
            )

    # -- RSI overbought / oversold (current reading) --
    last_rsi = _last_valid(rsi_vals)
    if last_rsi is not None:
        if last_rsi > 70:
            signals.append(
                {
                    "signal": "rsi_overbought",
                    "type": "bearish",
                    "date": dates[-1],
                    "description": f"RSI at {last_rsi:.1f} (overbought > 70)",
                }
            )
        elif last_rsi < 30:
            signals.append(
                {
                    "signal": "rsi_oversold",
                    "type": "bullish",
                    "date": dates[-1],
                    "description": f"RSI at {last_rsi:.1f} (oversold < 30)",
                }
            )

    # -- MACD crossover (last 5 days) --
    for i in range(max(1, n - 5), n):
        if (
            np.isnan(macd_line[i])
            or np.isnan(signal_line[i])
            or np.isnan(macd_line[i - 1])
            or np.isnan(signal_line[i - 1])
        ):
            continue
        if macd_line[i - 1] <= signal_line[i - 1] and macd_line[i] > signal_line[i]:
            signals.append(
                {
                    "signal": "macd_bullish_crossover",
                    "type": "bullish",
                    "date": dates[i],
                    "description": "MACD line crossed above signal line",
                }
            )
        elif macd_line[i - 1] >= signal_line[i - 1] and macd_line[i] < signal_line[i]:
            signals.append(
                {
                    "signal": "macd_bearish_crossover",
                    "type": "bearish",
                    "date": dates[i],
                    "description": "MACD line crossed below signal line",
                }
            )

    # -- Bollinger squeeze (bandwidth narrowing to 20-day low) --
    if n >= 40:
        bandwidth = np.full(n, np.nan)
        for i in range(19, n):
            if not np.isnan(bb_upper[i]) and not np.isnan(bb_lower[i]) and bb_middle[i] > 0:
                bandwidth[i] = (bb_upper[i] - bb_lower[i]) / bb_middle[i]

        valid_bw = bandwidth[~np.isnan(bandwidth)]
        if len(valid_bw) >= 20:
            recent_bw = valid_bw[-1]
            bw_20d_min = np.min(valid_bw[-20:])
            if recent_bw <= bw_20d_min * 1.01:  # Within 1% of 20-day low
                signals.append(
                    {
                        "signal": "bollinger_squeeze",
                        "type": "bullish",
                        "date": dates[-1],
                        "description": f"Bollinger bandwidth at 20-day low ({recent_bw:.4f}), potential breakout",
                    }
                )

    return signals


def _last_valid(arr: np.ndarray) -> float | None:
    """Return last non-NaN value from array, or None."""
    valid = arr[~np.isnan(arr)]
    return float(valid[-1]) if len(valid) > 0 else None
