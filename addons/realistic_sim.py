#!/usr/bin/env python3
"""
Production-Grade Realistic Simulation Engine for Crypto Perpetual Futures.

Models what ACTUALLY happens when trading with compounding equity and leverage:
- Square-root market impact (Donier & Bonart 2015)
- Exchange position limits (Hyperliquid)
- Leverage-aware liquidation with bar-by-bar checks
- Hourly funding on notional
- Taker fees on notional
- Capacity analysis across equity levels
"""

import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# =============================================================================
# CONSTANTS
# =============================================================================

ENGINE = "/home/ubuntu/hypertrader-engine-v4/target/release/hypertrader-engine"
DATA_DIR = "/opt/hypertrader/addons/backtest-data"

# Asset-specific parameters (calibrated from research)
ASSET_PARAMS = {
    "BTC": {"spread_bps": 0.5, "k": 150.0, "maint_margin": 0.005,
            "max_market_order": 15_000_000.0, "max_position": 500_000_000.0},
    "ETH": {"spread_bps": 1.0, "k": 200.0, "maint_margin": 0.005,
            "max_market_order": 15_000_000.0, "max_position": 200_000_000.0},
    "SOL": {"spread_bps": 3.0, "k": 300.0, "maint_margin": 0.01,
            "max_market_order": 5_000_000.0, "max_position": 50_000_000.0},
}

DEFAULT_PARAMS = {"spread_bps": 5.0, "k": 400.0, "maint_margin": 0.01,
                  "max_market_order": 2_000_000.0, "max_position": 20_000_000.0}

TAKER_FEE_RATE = 0.00035  # 3.5 bps
DEFAULT_FUNDING_PER_8H = 0.0001  # 0.01% per 8 hours

# =============================================================================
# DATA LOADING
# =============================================================================

@dataclass
class BarData:
    ts: list
    opens: list
    highs: list
    lows: list
    closes: list
    volumes: list
    bar_minutes: float

    def __len__(self):
        return len(self.ts)

    def volume_usd(self, i: int) -> float:
        return self.volumes[i] * self.closes[i]


def load_bar_data(asset: str, timeframe: str = "15m", data_dir: str = DATA_DIR) -> BarData:
    sym = asset.lower()
    path_15m = os.path.join(data_dir, f"mega_{sym}_15m.json")
    with open(path_15m) as f:
        raw = json.load(f)

    ts = [b["open_time"] for b in raw]
    o = [float(b["open"]) for b in raw]
    h = [float(b["high"]) for b in raw]
    l = [float(b["low"]) for b in raw]
    c = [float(b["close"]) for b in raw]
    v = [float(b["volume"]) for b in raw]

    if timeframe in ("15m", "15"):
        return BarData(ts=ts, opens=o, highs=h, lows=l, closes=c, volumes=v, bar_minutes=15.0)

    minutes_map = {"30m": 30, "30": 30, "1H": 60, "1h": 60, "4H": 240, "4h": 240, "1D": 1440, "1d": 1440}
    target_min = minutes_map.get(timeframe, 15)
    ms_per_bar = target_min * 60 * 1000

    r_ts, r_o, r_h, r_l, r_c, r_v = [], [], [], [], [], []
    i = 0
    n = len(ts)
    while i < n:
        bucket = ts[i] // ms_per_bar
        bar_o = o[i]; bar_h = h[i]; bar_l = l[i]; bar_c = c[i]; bar_v = v[i]
        bar_ts = bucket * ms_per_bar
        i += 1
        while i < n and ts[i] // ms_per_bar == bucket:
            bar_h = max(bar_h, h[i]); bar_l = min(bar_l, l[i]); bar_c = c[i]; bar_v += v[i]
            i += 1
        r_ts.append(bar_ts); r_o.append(bar_o); r_h.append(bar_h)
        r_l.append(bar_l); r_c.append(bar_c); r_v.append(bar_v)

    return BarData(ts=r_ts, opens=r_o, highs=r_h, lows=r_l, closes=r_c,
                   volumes=r_v, bar_minutes=float(target_min))


def compute_rolling_volatility(closes: list, period: int = 20) -> list:
    n = len(closes)
    vol = [0.0] * n
    log_returns = [0.0] * n
    for i in range(1, n):
        if closes[i] > 0 and closes[i-1] > 0:
            log_returns[i] = math.log(closes[i] / closes[i-1])
    for i in range(period, n):
        window = log_returns[i - period + 1 : i + 1]
        mean = sum(window) / period
        var = sum((r - mean) ** 2 for r in window) / (period - 1)
        vol[i] = math.sqrt(var)
    return vol


def compute_rolling_avg_volume(volumes: list, period: int = 20) -> list:
    n = len(volumes)
    avg = [0.0] * n
    for i in range(period, n):
        avg[i] = sum(volumes[i - period + 1 : i + 1]) / period
    return avg


# =============================================================================
# MARKET IMPACT MODEL — Square-Root Law
# =============================================================================

def calculate_market_impact(
    trade_notional: float, bar_volume_usd: float, daily_volume_usd: float,
    daily_volatility: float, asset: str,
) -> float:
    """Returns slippage as a decimal (not bps)."""
    params = ASSET_PARAMS.get(asset, DEFAULT_PARAMS)
    spread_bps = params["spread_bps"]
    k = params["k"]

    if daily_volume_usd <= 0 or trade_notional <= 0:
        return spread_bps / 2.0 / 10000.0

    participation_rate = trade_notional / daily_volume_usd
    spread_cost = spread_bps / 2.0
    physical_impact = k * daily_volatility * math.sqrt(participation_rate)

    # Sigmoid adjustment
    sigmoid_adj = 0.0
    if participation_rate < 0.005:
        sigmoid_adj = daily_volatility * 10000.0 * 0.05
    elif participation_rate > 0.20:
        sigmoid_adj = (participation_rate - 0.20) * 50.0

    return (spread_cost + physical_impact + sigmoid_adj) / 10000.0


def apply_slippage(price: float, slippage_decimal: float, is_buy: bool) -> float:
    if is_buy:
        return price * (1.0 + slippage_decimal)
    else:
        return price * (1.0 - slippage_decimal)


def get_order_split_penalty(notional: float, asset: str) -> float:
    params = ASSET_PARAMS.get(asset, DEFAULT_PARAMS)
    max_order = params["max_market_order"]
    if notional <= max_order:
        return 0.0
    excess = notional - max_order
    return (excess / 5_000_000.0) * 2.0 / 10000.0


# =============================================================================
# LIQUIDATION
# =============================================================================

def calc_liquidation_price(entry_price: float, leverage: float, is_long: bool,
                           maint_margin_rate: float) -> float:
    if is_long:
        return entry_price * (1.0 - 1.0 / leverage + maint_margin_rate)
    else:
        return entry_price * (1.0 + 1.0 / leverage - maint_margin_rate)


# =============================================================================
# RESULT STRUCTURES
# =============================================================================

@dataclass
class TradeResult:
    asset: str
    direction: str
    entry_ts: str
    exit_ts: str
    signal_entry_price: float   # raw bar open (no slippage)
    actual_entry_price: float   # after market impact
    signal_exit_price: float    # raw bar open (no slippage)
    actual_exit_price: float    # after market impact
    margin_deployed: float
    notional: float
    target_notional: float
    bars_held: int
    ideal_pnl: float           # P&L at signal prices (no friction)
    gross_pnl: float           # P&L at actual prices (after slippage, before fees/funding)
    slippage_cost: float       # ideal_pnl - gross_pnl
    entry_fee: float
    exit_fee: float
    funding_cost: float
    liquidation_fee: float
    net_pnl: float             # gross_pnl - fees - funding - liq_fee
    equity_before: float
    equity_after: float
    liquidated: bool
    position_capped: bool
    order_split_required: bool
    bar_volume_pct: float
    participation_rate: float


@dataclass
class SimulationResult:
    initial_equity: float
    equity_fraction: float
    leverage: float

    final_equity: float
    ideal_gross_pnl: float      # P&L with zero friction
    gross_pnl: float            # P&L after slippage, before fees/funding
    net_pnl: float              # final equity - initial equity
    total_return_pct: float
    profit_factor: float
    sharpe: float
    max_drawdown_pct: float
    max_drawdown_usd: float
    win_rate: float
    total_trades: int

    # Cost breakdown (all reduce ideal → net)
    total_slippage: float       # ideal - gross
    total_fees: float           # entry + exit fees
    total_funding: float
    total_liquidation_fees: float
    total_friction: float       # slippage + fees + funding + liq_fees = ideal - net

    # As % of ideal gross P&L
    slippage_pct_of_ideal: float
    fees_pct_of_ideal: float
    funding_pct_of_ideal: float
    friction_pct_of_ideal: float

    # Risk events
    liquidations: int
    total_margin_lost_to_liquidation: float
    order_splits_required: int
    trades_exceeding_10pct_volume: int
    position_limit_hits: int
    peak_notional: float
    peak_notional_pct_of_limit: float

    starting_notional: float
    peak_equity_notional: float

    trades: list
    equity_curve: list
    yearly: dict
    annual_friction_budget: dict


# =============================================================================
# CORE SIMULATION
# =============================================================================

def realistic_simulate(
    trade_log: list,
    bar_data: dict,
    initial_equity: float = 100_000.0,
    equity_fraction: float = 0.50,
    leverage: float = 7.0,
    funding_rate_8h: float = DEFAULT_FUNDING_PER_8H,
    timeframe: str = "15m",
    **_kwargs,
) -> SimulationResult:
    """Production-grade realistic simulation.

    CRITICAL: Sorts trade_log chronologically before processing.
    Uses raw bar open prices (not engine's slippage-adjusted prices).
    """
    bar_minutes = {"15m": 15, "30m": 30, "1H": 60, "1h": 60,
                   "4H": 240, "4h": 240, "1D": 1440}.get(timeframe, 15)

    # CRITICAL FIX: Sort trades chronologically across all assets
    sorted_trades = sorted(trade_log, key=lambda t: t.get("entry_ts", ""))

    equity = initial_equity
    results = []
    equity_curve = [equity]
    yearly = defaultdict(lambda: {"start": None, "end": 0, "pnl": 0, "trades": 0,
                                   "liqs": 0, "fees": 0, "funding": 0, "slippage": 0})

    # Precompute rolling volatility and volume for each asset
    asset_vol = {}
    asset_avg_v = {}
    for asset, bd in bar_data.items():
        bars_per_day = 1440.0 / bd.bar_minutes
        per_bar_vol = compute_rolling_volatility(bd.closes, period=20)
        asset_vol[asset] = [v * math.sqrt(bars_per_day) for v in per_bar_vol]
        asset_avg_v[asset] = compute_rolling_avg_volume(bd.volumes, period=20)

    peak_equity = equity
    peak_notional = 0.0

    for t in sorted_trades:
        asset = t["asset"]
        direction = t["direction"]
        is_long = direction == "long"
        entry_bar = t["entry_bar"]
        exit_bar = t["exit_bar"]
        yr = t.get("entry_ts", "")[:4]

        if yearly[yr]["start"] is None:
            yearly[yr]["start"] = equity

        bd = bar_data.get(asset)
        if bd is None:
            continue

        params = ASSET_PARAMS.get(asset, DEFAULT_PARAMS)
        bars_per_day = 1440.0 / bd.bar_minutes

        # === RAW SIGNAL PRICES from bar data (not engine's slippage-adjusted) ===
        if entry_bar >= len(bd) or exit_bar >= len(bd):
            continue
        signal_entry = bd.opens[entry_bar]
        signal_exit = bd.opens[exit_bar]

        # === SIZING ===
        if equity <= 0:
            continue
        target_notional = equity_fraction * equity * leverage
        margin = equity * equity_fraction
        notional = target_notional

        # Exchange position limit
        position_capped = False
        if notional > params["max_position"]:
            notional = params["max_position"]
            margin = notional / leverage
            position_capped = True

        if notional <= 0:
            continue

        peak_notional = max(peak_notional, notional)

        # === VOLUME & VOLATILITY at entry ===
        daily_vol = _safe_get(asset_vol.get(asset, []), entry_bar)
        avg_vol_base = _safe_get(asset_avg_v.get(asset, []), entry_bar)
        daily_volume_usd = avg_vol_base * bd.closes[entry_bar] * bars_per_day
        bar_vol_usd = bd.volume_usd(entry_bar)

        # === ENTRY MARKET IMPACT ===
        entry_slippage = calculate_market_impact(notional, bar_vol_usd, daily_volume_usd, daily_vol, asset)
        order_split = notional > params["max_market_order"]
        entry_slippage += get_order_split_penalty(notional, asset)

        actual_entry = apply_slippage(signal_entry, entry_slippage, is_buy=is_long)

        # Entry fee on notional
        entry_fee = notional * TAKER_FEE_RATE

        # === IDEAL P&L (zero friction) ===
        if is_long:
            ideal_pnl = (signal_exit - signal_entry) / signal_entry * notional
        else:
            ideal_pnl = (signal_entry - signal_exit) / signal_entry * notional

        # === LIQUIDATION PRICE ===
        liq_price = calc_liquidation_price(actual_entry, leverage, is_long, params["maint_margin"])

        # === BAR-BY-BAR: funding accrual + liquidation check ===
        liquidated = False
        liquidation_fee = 0.0
        funding_cost = 0.0
        actual_exit = signal_exit
        actual_exit_bar = exit_bar
        bars_held = exit_bar - entry_bar

        funding_per_bar = funding_rate_8h * (bd.bar_minutes / 480.0)

        for bar_i in range(entry_bar + 1, min(exit_bar + 1, len(bd))):
            funding_cost += notional * funding_per_bar

            if is_long and bd.lows[bar_i] <= liq_price:
                liquidated = True
                actual_exit = liq_price
                actual_exit_bar = bar_i
                bars_held = bar_i - entry_bar
                liquidation_fee = notional * 0.005
                break
            elif not is_long and bd.highs[bar_i] >= liq_price:
                liquidated = True
                actual_exit = liq_price
                actual_exit_bar = bar_i
                bars_held = bar_i - entry_bar
                liquidation_fee = notional * 0.005
                break

        # === EXIT ===
        exit_fee = 0.0
        exit_slippage_cost = 0.0

        if liquidated:
            gross_pnl = -margin
            net_pnl = -margin - entry_fee - liquidation_fee
            slippage_cost = ideal_pnl - gross_pnl
        else:
            # Exit market impact
            exit_bar_c = min(exit_bar, len(bd) - 1)
            exit_daily_vol = _safe_get(asset_vol.get(asset, []), exit_bar_c)
            exit_avg_vol = _safe_get(asset_avg_v.get(asset, []), exit_bar_c)
            exit_daily_vol_usd = exit_avg_vol * bd.closes[exit_bar_c] * bars_per_day

            exit_slippage = calculate_market_impact(
                notional, bd.volume_usd(exit_bar_c), exit_daily_vol_usd, exit_daily_vol, asset)
            exit_slippage += get_order_split_penalty(notional, asset)

            actual_exit = apply_slippage(signal_exit, exit_slippage, is_buy=not is_long)
            exit_fee = notional * TAKER_FEE_RATE

            if is_long:
                gross_pnl = (actual_exit - actual_entry) / actual_entry * notional
            else:
                gross_pnl = (actual_entry - actual_exit) / actual_entry * notional

            slippage_cost = ideal_pnl - gross_pnl
            net_pnl = gross_pnl - entry_fee - exit_fee - funding_cost

        # === EQUITY UPDATE ===
        equity_before = equity
        equity += net_pnl
        equity = max(equity, 0)
        equity_curve.append(equity)
        peak_equity = max(peak_equity, equity)

        # Volume metrics
        bar_volume_pct = (notional / bar_vol_usd * 100) if bar_vol_usd > 0 else 0
        participation_rate = (notional / daily_volume_usd) if daily_volume_usd > 0 else 0

        # Yearly tracking
        yearly[yr]["end"] = equity
        yearly[yr]["pnl"] += net_pnl
        yearly[yr]["trades"] += 1
        if liquidated:
            yearly[yr]["liqs"] += 1
        yearly[yr]["fees"] += entry_fee + exit_fee
        yearly[yr]["funding"] += funding_cost
        yearly[yr]["slippage"] += slippage_cost

        # Exit timestamp
        exit_ts = t.get("exit_ts", "")
        if liquidated and actual_exit_bar < len(bd.ts):
            exit_ts = _ms_to_iso(bd.ts[actual_exit_bar])

        results.append(TradeResult(
            asset=asset, direction=direction,
            entry_ts=t.get("entry_ts", ""), exit_ts=exit_ts,
            signal_entry_price=signal_entry, actual_entry_price=actual_entry,
            signal_exit_price=signal_exit, actual_exit_price=actual_exit,
            margin_deployed=margin, notional=notional, target_notional=target_notional,
            bars_held=bars_held,
            ideal_pnl=ideal_pnl, gross_pnl=gross_pnl, slippage_cost=slippage_cost,
            entry_fee=entry_fee, exit_fee=exit_fee, funding_cost=funding_cost,
            liquidation_fee=liquidation_fee,
            net_pnl=net_pnl, equity_before=equity_before, equity_after=equity,
            liquidated=liquidated, position_capped=position_capped,
            order_split_required=order_split,
            bar_volume_pct=bar_volume_pct, participation_rate=participation_rate,
        ))

    # === AGGREGATE STATS ===
    total_ideal = sum(r.ideal_pnl for r in results)
    total_slippage = sum(r.slippage_cost for r in results)
    total_fees = sum(r.entry_fee + r.exit_fee for r in results)
    total_funding = sum(r.funding_cost for r in results)
    total_liq_fees = sum(r.liquidation_fee for r in results)
    total_friction = total_slippage + total_fees + total_funding + total_liq_fees
    gross_pnl_total = sum(r.gross_pnl for r in results)
    net_pnl_total = equity - initial_equity

    # Drawdown
    peak = initial_equity
    max_dd_pct = 0.0
    max_dd_usd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        dd = peak - e
        dd_pct = dd / peak * 100 if peak > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_usd = dd

    wins = sum(1 for r in results if r.net_pnl > 0)
    win_rate = wins / len(results) * 100 if results else 0

    gross_wins = sum(r.net_pnl for r in results if r.net_pnl > 0)
    gross_losses = abs(sum(r.net_pnl for r in results if r.net_pnl <= 0))
    pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    sharpe = _compute_sharpe(equity_curve)

    # Cost breakdown as % of ideal gross P&L
    abs_ideal = abs(total_ideal) if total_ideal != 0 else 1
    slip_pct = total_slippage / abs_ideal * 100
    fees_pct = total_fees / abs_ideal * 100
    fund_pct = total_funding / abs_ideal * 100
    fric_pct = total_friction / abs_ideal * 100

    # Risk events
    liquidations = sum(1 for r in results if r.liquidated)
    margin_lost = sum(r.margin_deployed for r in results if r.liquidated)
    order_splits = sum(1 for r in results if r.order_split_required)
    vol_exceed = sum(1 for r in results if r.bar_volume_pct > 10)
    pos_caps = sum(1 for r in results if r.position_capped)

    ref_limit = ASSET_PARAMS.get("BTC", DEFAULT_PARAMS)["max_position"]
    peak_notional_pct = peak_notional / ref_limit * 100

    starting_notional = equity_fraction * initial_equity * leverage
    peak_eq_notional = equity_fraction * peak_equity * leverage

    afb = _compute_annual_friction_budget(
        initial_equity, equity_fraction, leverage,
        len(results), _estimate_years(sorted_trades), bar_minutes)

    return SimulationResult(
        initial_equity=initial_equity, equity_fraction=equity_fraction, leverage=leverage,
        final_equity=equity, ideal_gross_pnl=total_ideal, gross_pnl=gross_pnl_total,
        net_pnl=net_pnl_total, total_return_pct=(equity / initial_equity - 1) * 100 if initial_equity > 0 else 0,
        profit_factor=pf, sharpe=sharpe,
        max_drawdown_pct=max_dd_pct, max_drawdown_usd=max_dd_usd,
        win_rate=win_rate, total_trades=len(results),
        total_slippage=total_slippage, total_fees=total_fees,
        total_funding=total_funding, total_liquidation_fees=total_liq_fees,
        total_friction=total_friction,
        slippage_pct_of_ideal=slip_pct, fees_pct_of_ideal=fees_pct,
        funding_pct_of_ideal=fund_pct, friction_pct_of_ideal=fric_pct,
        liquidations=liquidations, total_margin_lost_to_liquidation=margin_lost,
        order_splits_required=order_splits, trades_exceeding_10pct_volume=vol_exceed,
        position_limit_hits=pos_caps, peak_notional=peak_notional,
        peak_notional_pct_of_limit=peak_notional_pct,
        starting_notional=starting_notional, peak_equity_notional=peak_eq_notional,
        trades=results, equity_curve=equity_curve, yearly=dict(yearly),
        annual_friction_budget=afb,
    )


# =============================================================================
# CAPACITY ANALYSIS
# =============================================================================

def run_capacity_analysis(trade_log, bar_data, equity_levels=None,
                          equity_fraction=0.50, leverage=7.0, timeframe="15m", **kw):
    if equity_levels is None:
        equity_levels = [10_000, 50_000, 100_000, 250_000, 500_000,
                         1_000_000, 5_000_000, 10_000_000, 50_000_000, 100_000_000]
    results = []
    for eq in equity_levels:
        sim = realistic_simulate(trade_log, bar_data, initial_equity=eq,
                                  equity_fraction=equity_fraction, leverage=leverage,
                                  timeframe=timeframe, **kw)
        results.append({
            "starting_equity": eq, "final_equity": sim.final_equity,
            "return_pct": sim.total_return_pct, "sharpe": sim.sharpe,
            "slippage_pct": sim.slippage_pct_of_ideal,
            "limit_hits": sim.position_limit_hits,
            "liquidations": sim.liquidations, "mdd_pct": sim.max_drawdown_pct,
            "friction_pct": sim.friction_pct_of_ideal,
        })
    return results


def find_capacity_ceiling(capacity_results):
    if not capacity_results or len(capacity_results) < 2:
        return float('inf')
    base_sharpe = capacity_results[0]["sharpe"]
    if base_sharpe <= 0:
        return capacity_results[0]["starting_equity"]
    for r in capacity_results[1:]:
        if r["sharpe"] < base_sharpe * 0.75:
            return r["starting_equity"]
    return capacity_results[-1]["starting_equity"]


# =============================================================================
# HELPERS
# =============================================================================

def _safe_get(arr, idx):
    if not arr:
        return 0.0
    return arr[min(idx, len(arr) - 1)]


def _ms_to_iso(ts_ms):
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _compute_sharpe(equity_curve):
    if len(equity_curve) < 3:
        return 0.0
    returns = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i-1] > 0:
            returns.append(equity_curve[i] / equity_curve[i-1] - 1)
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std_r = math.sqrt(var) if var > 0 else 0
    if std_r == 0:
        return 0.0
    # Annualize using trades per year
    sharpe = mean_r / std_r * math.sqrt(len(returns))
    return round(sharpe, 2)


def _estimate_years(trade_log):
    if not trade_log:
        return 1.0
    first = trade_log[0].get("entry_ts", "2020-01-01")
    last = trade_log[-1].get("exit_ts", "2025-01-01")
    try:
        t0 = datetime.fromisoformat(first)
        t1 = datetime.fromisoformat(last)
        return max((t1 - t0).days / 365.25, 0.5)
    except:
        return 5.0


def _compute_annual_friction_budget(equity, fraction, leverage, total_trades, years, bar_minutes):
    notional = equity * fraction * leverage
    trades_per_year = total_trades / years if years > 0 else 50
    annual_fees = notional * TAKER_FEE_RATE * 2 * trades_per_year
    fees_pct = annual_fees / equity * 100 if equity > 0 else 0
    annual_funding = notional * DEFAULT_FUNDING_PER_8H * 3 * 365
    funding_pct = annual_funding / equity * 100 if equity > 0 else 0
    annual_impact = notional * 0.0002 * trades_per_year
    impact_pct = annual_impact / equity * 100 if equity > 0 else 0
    total_pct = fees_pct + funding_pct + impact_pct
    return {
        "notional_per_trade": notional,
        "trades_per_year": round(trades_per_year, 1),
        "annual_fees": round(annual_fees, 2), "annual_fees_pct": round(fees_pct, 1),
        "annual_funding": round(annual_funding, 2), "annual_funding_pct": round(funding_pct, 1),
        "annual_impact": round(annual_impact, 2), "annual_impact_pct": round(impact_pct, 1),
        "total_annual_friction": round(annual_fees + annual_funding + annual_impact, 2),
        "total_annual_pct": round(total_pct, 1),
        "breakeven_gross_return_pct": round(total_pct, 1),
    }


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_results(sim, label=""):
    lines = []
    lines.append(f"{'=' * 72}")
    lines.append(f"REALISTIC SIMULATION{f' — {label}' if label else ''}")
    lines.append(f"{'=' * 72}")

    lines.append(f"\n  Configuration:")
    lines.append(f"    Initial equity: ${sim.initial_equity:,.0f} | "
                 f"Equity fraction: {sim.equity_fraction*100:.0f}% | Leverage: {sim.leverage:.0f}x")
    lines.append(f"    Per-trade notional at start: ${sim.starting_notional:,.0f}")
    lines.append(f"    Per-trade notional at peak:  ${sim.peak_equity_notional:,.0f}")

    lines.append(f"\n  Performance:")
    lines.append(f"    Final equity: ${sim.final_equity:,.2f} | Return: {sim.total_return_pct:,.1f}%")
    lines.append(f"    PF: {sim.profit_factor:.2f} | Sharpe: {sim.sharpe:.2f} | "
                 f"MDD: {sim.max_drawdown_pct:.1f}% (${sim.max_drawdown_usd:,.0f})")
    lines.append(f"    Trades: {sim.total_trades} | Win rate: {sim.win_rate:.1f}%")

    lines.append(f"\n  P&L Waterfall:")
    lines.append(f"    Ideal P&L (zero friction): ${sim.ideal_gross_pnl:>14,.2f}")
    lines.append(f"    − Market impact/slippage:  ${sim.total_slippage:>14,.2f} ({sim.slippage_pct_of_ideal:.1f}%)")
    lines.append(f"    = Gross P&L (after slip):   ${sim.gross_pnl:>14,.2f}")
    lines.append(f"    − Trading fees:             ${sim.total_fees:>14,.2f} ({sim.fees_pct_of_ideal:.1f}%)")
    lines.append(f"    − Funding costs:            ${sim.total_funding:>14,.2f} ({sim.funding_pct_of_ideal:.1f}%)")
    lines.append(f"    − Liquidation fees:         ${sim.total_liquidation_fees:>14,.2f}")
    lines.append(f"    {'─' * 52}")
    lines.append(f"    = Net P&L:                  ${sim.net_pnl:>14,.2f}")
    lines.append(f"    Total friction:             ${sim.total_friction:>14,.2f} ({sim.friction_pct_of_ideal:.1f}% of ideal)")

    lines.append(f"\n  Risk Events:")
    lines.append(f"    Liquidations: {sim.liquidations} (margin lost: ${sim.total_margin_lost_to_liquidation:,.0f})")
    lines.append(f"    Order splits required: {sim.order_splits_required}")
    lines.append(f"    Trades >10% bar volume: {sim.trades_exceeding_10pct_volume}")
    lines.append(f"    Position limit hits: {sim.position_limit_hits}")
    lines.append(f"    Peak notional: ${sim.peak_notional:,.0f} ({sim.peak_notional_pct_of_limit:.1f}% of limit)")

    afb = sim.annual_friction_budget
    lines.append(f"\n  Annual Friction Budget (at starting equity):")
    lines.append(f"    Notional per trade: ${afb['notional_per_trade']:,.0f}")
    lines.append(f"    Trades/year: {afb['trades_per_year']:.0f}")
    lines.append(f"    Fees: {afb['annual_fees_pct']:.1f}% | Funding: {afb['annual_funding_pct']:.1f}% | "
                 f"Impact: {afb['annual_impact_pct']:.1f}% | Total: {afb['total_annual_pct']:.1f}%")
    lines.append(f"    Breakeven gross return required: {afb['breakeven_gross_return_pct']:.1f}%")

    return "\n".join(lines)


def format_capacity_analysis(cap_results, ceiling, label=""):
    lines = []
    lines.append(f"\n{'=' * 90}")
    lines.append(f"CAPACITY ANALYSIS{f' — {label}' if label else ''}")
    lines.append(f"{'=' * 90}")
    lines.append(f"  {'Starting Eq':>14} | {'Final Eq':>16} | {'Return':>8} | "
                 f"{'Sharpe':>6} | {'Slip%':>6} | {'Fric%':>6} | {'Limits':>6} | {'Liqs':>4}")
    lines.append(f"  {'─'*14}─┼─{'─'*16}─┼─{'─'*8}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*4}")
    for r in cap_results:
        lines.append(f"  ${r['starting_equity']:>12,.0f} | ${r['final_equity']:>14,.0f} | "
                     f"{r['return_pct']:>7.0f}% | {r['sharpe']:>6.2f} | {r['slippage_pct']:>5.1f}% | "
                     f"{r['friction_pct']:>5.1f}% | {r['limit_hits']:>6} | {r['liquidations']:>4}")
    lines.append(f"\n  CAPACITY CEILING: ${ceiling:,.0f} (Sharpe degrades >25% beyond this point)")
    return "\n".join(lines)


def format_yearly(sim):
    lines = []
    lines.append(f"\n  Year-by-Year:")
    lines.append(f"  {'Year':<6}{'Start':>14}{'End':>14}{'P&L':>14}{'Return':>8}"
                 f"{'Trades':>7}{'Liqs':>6}{'Fees':>10}{'Funding':>10}{'Slippage':>10}")
    for yr in sorted(sim.yearly):
        y = sim.yearly[yr]
        s = y["start"] if y["start"] else sim.initial_equity
        ret = y["pnl"] / s * 100 if s > 0 else 0
        lines.append(f"  {yr:<6}{s:>14,.0f}{y['end']:>14,.0f}{y['pnl']:>14,.0f}{ret:>7.1f}%"
                     f"{y['trades']:>7}{y['liqs']:>6}{y['fees']:>10,.0f}"
                     f"{y['funding']:>10,.0f}{y['slippage']:>10,.0f}")
    return "\n".join(lines)


# =============================================================================
# ENGINE RUNNER
# =============================================================================

def run_engine(config, label=""):
    cfg_path = config["output_path"].replace(".json", "_cfg.json")
    with open(cfg_path, 'w') as f:
        json.dump(config, f)
    result = subprocess.run([ENGINE, cfg_path], capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"  ENGINE ERROR {label}: {result.stderr[-300:]}", file=sys.stderr)
        return {}
    with open(config["output_path"]) as f:
        return json.load(f)


# =============================================================================
# MAIN VALIDATION RUNNER
# =============================================================================

def main():
    T0 = time.time()
    HOLDOUT = "2025-03-19"
    report_lines = []

    def log(s=""):
        print(s)
        report_lines.append(s)

    log("=" * 80)
    log("  PRODUCTION-GRADE REALISTIC SIMULATION ENGINE — VALIDATION REPORT")
    log(f"  Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log("=" * 80)

    # ── Load bar data ──
    log("\n[1/7] Loading bar data...")
    bar_data_15m = {}
    bar_data_30m = {}
    for asset in ["BTC", "ETH", "SOL"]:
        bar_data_15m[asset] = load_bar_data(asset, "15m")
        bar_data_30m[asset] = load_bar_data(asset, "30m")
        log(f"  {asset}: {len(bar_data_15m[asset])} (15m), {len(bar_data_30m[asset])} (30m)")

    # ── Our system config ──
    our_base_cfg = json.load(open("/tmp/discovery/rust_baseline_config.json"))

    # ── VALIDATION 10D: Backward compatibility (FULL dataset, no date range) ──
    log("\n[2/7] Validation 10D — backward compatibility (full dataset)...")
    our_full_cfg = dict(our_base_cfg)
    our_full_cfg["output_path"] = "/tmp/realistic_ours_full.json"
    our_full_cfg.pop("date_range", None)
    r_full = run_engine(our_full_cfg, "ours-full")
    tl_full = r_full.get("trade_log", [])
    p_full = r_full.get("portfolio", {})

    asset_counts = {}
    for t in tl_full:
        a = t["asset"]
        asset_counts[a] = asset_counts.get(a, 0) + 1

    expected_counts = {"BTC": 211, "ETH": 191, "SOL": 194}
    all_match_10d = True
    for a, exp in expected_counts.items():
        got = asset_counts.get(a, 0)
        status = "PASS" if got == exp else "FAIL"
        if got != exp:
            all_match_10d = False
        log(f"  {a}: {got} trades (expected {exp}) [{status}]")
    log(f"  Full run PF={p_full.get('pf')}, Sharpe={p_full.get('sharpe')}, P&L=${p_full.get('pnl', 0):,.2f}")
    log(f"  VALIDATION 10D: {'PASS' if all_match_10d else 'FAIL'}")

    # ── Run engine: training and holdout ──
    log("\n[3/7] Running engine — our system training & holdout...")
    our_train_cfg = dict(our_base_cfg)
    our_train_cfg["output_path"] = "/tmp/realistic_ours_train.json"
    our_train_cfg["date_range"] = {"start": "2020-01-01", "end": HOLDOUT}
    r_ours = run_engine(our_train_cfg, "ours-train")
    tl_ours = r_ours.get("trade_log", [])
    p_ours = r_ours.get("portfolio", {})

    our_ho_cfg = dict(our_base_cfg)
    our_ho_cfg["output_path"] = "/tmp/realistic_ours_holdout.json"
    our_ho_cfg["date_range"] = {"start": HOLDOUT, "end": "2026-12-31"}
    r_ours_ho = run_engine(our_ho_cfg, "ours-holdout")
    tl_ours_ho = r_ours_ho.get("trade_log", [])
    p_ours_ho = r_ours_ho.get("portfolio", {})
    log(f"  Training: {len(tl_ours)} trades, PF={p_ours.get('pf')}, Sharpe={p_ours.get('sharpe')}")
    log(f"  Holdout:  {len(tl_ours_ho)} trades, PF={p_ours_ho.get('pf')}, Sharpe={p_ours_ho.get('sharpe')}")

    # ── Run engine: v10 ──
    log("\n[4/7] Running engine — v10 (30m)...")
    v10_sp = {"timeframe":"30m","atr_period":10,"base_mult":6.0,"trend_mult":4.0,"range_mult":8.0,
        "adx_adapt_thresh":25.0,"slow_atr_period":20,"slow_mult":8.0,"use_dual_st_buys":True,
        "use_dual_st_sells":True,"cooldown":2,"late_window":1,"min_score":6,"use_rsi":True,
        "rsi_period":14,"rsi_buy_max":70,"rsi_sell_min":30,"use_zlema":True,"zlema_period":200,
        "use_volume":True,"vol_sma_period":20,"vol_multiplier":1.0,"use_adx_filter":True,
        "adx_period":14,"adx_minimum":25.0,"use_squeeze":True,"exit_on_raw_flip":True,
        "use_ema_atr":True,"longs_only":False}
    v10_base = {
        "assets": ["BTC", "ETH", "SOL"], "data_dir": DATA_DIR, "mode": "baseline", "timeframe": "30m",
        "params": {"ema200_period":200,"ema50_period":50,"ema50_rising_lookback":5,
            "st_4h_atr_period":10,"st_4h_multiplier":3.0,"st_15m_atr_period":10,
            "st_15m_multiplier":2.0,"near_band_pct":0.005,"rsi_period":14,"rsi_threshold":45.0,
            "rsi_lookback":2,"ema_fast":21,"ema_slow":55,"vol_mult":2.0,"vol_sma_period":20,"warmup":300},
        "strategy": {"long_entry":{"type":"adaptive_zlema_st","params":v10_sp},
            "short_entry":{"type":"adaptive_zlema_st_short","params":{"timeframe":"30m"}},
            "exit":{"type":"current"}},
        "regime_config": {"type":"none"},
        "sizing": {"type":"flat","margin":125.0,"leverage":10.0,"starting_equity":500.0},
        "fees": {"maker_rate":0.0006,"slippage":0.0005,"funding_rate_per_8h":0.0001},
        "output_path": "/tmp/realistic_v10_train.json",
    }

    v10_train = dict(v10_base)
    v10_train["date_range"] = {"start": "2020-01-01", "end": HOLDOUT}
    v10_train["output_path"] = "/tmp/realistic_v10_train.json"
    r_v10 = run_engine(v10_train, "v10-train")
    tl_v10 = r_v10.get("trade_log", [])
    p_v10 = r_v10.get("portfolio", {})

    v10_ho = dict(v10_base)
    v10_ho["date_range"] = {"start": HOLDOUT, "end": "2026-12-31"}
    v10_ho["output_path"] = "/tmp/realistic_v10_holdout.json"
    r_v10_ho = run_engine(v10_ho, "v10-holdout")
    tl_v10_ho = r_v10_ho.get("trade_log", [])
    p_v10_ho = r_v10_ho.get("portfolio", {})
    log(f"  Training: {len(tl_v10)} trades, PF={p_v10.get('pf')}, Sharpe={p_v10.get('sharpe')}")
    log(f"  Holdout:  {len(tl_v10_ho)} trades, PF={p_v10_ho.get('pf')}, Sharpe={p_v10_ho.get('sharpe')}")

    # ══════════════════════════════════════════════════════════════════════
    # VALIDATION 10A — Sanity check
    # ══════════════════════════════════════════════════════════════════════
    log("\n" + "=" * 80)
    log("  VALIDATION 10A — SANITY CHECK ($100K, 50%, 7x)")
    log("=" * 80)

    sim_ours = realistic_simulate(tl_ours, bar_data_15m, initial_equity=100_000,
                                   equity_fraction=0.50, leverage=7.0, timeframe="15m")
    log(format_results(sim_ours, "Our System — Training"))
    log(format_yearly(sim_ours))

    checks_a = [
        ("Final equity < $1T",          sim_ours.final_equity < 1e12),
        ("Final equity > starting",     sim_ours.final_equity > 100_000),
        ("MDD > 10% (leveraged)",       sim_ours.max_drawdown_pct > 10),
        ("Total friction > 0",          sim_ours.total_friction > 0),
        ("Funding > 0",                 sim_ours.total_funding > 0),
        ("Slippage > 0",                sim_ours.total_slippage > 0),
        ("Net P&L < Ideal P&L",         sim_ours.net_pnl < sim_ours.ideal_gross_pnl),
    ]
    for desc, passed in checks_a:
        log(f"  {desc}: {'PASS' if passed else 'FAIL'}")
    log(f"  VALIDATION 10A: {'PASS' if all(p for _, p in checks_a) else 'FAIL'}")

    # ══════════════════════════════════════════════════════════════════════
    # VALIDATION 10B — Small account
    # ══════════════════════════════════════════════════════════════════════
    log("\n" + "=" * 80)
    log("  VALIDATION 10B — SMALL ACCOUNT ($1K, 50%, 7x)")
    log("=" * 80)

    sim_small = realistic_simulate(tl_ours, bar_data_15m, initial_equity=1_000,
                                    equity_fraction=0.50, leverage=7.0, timeframe="15m")
    log(format_results(sim_small, "$1K Small Account"))

    # For $1K, first trades should have negligible market impact
    # (validates model doesn't over-penalize small accounts)
    first_trades = sim_small.trades[:30]
    avg_slip_pct = 0
    early_limit_hits = 0
    early_order_splits = 0
    if first_trades:
        abs_ideals = [abs(r.ideal_pnl) for r in first_trades if abs(r.ideal_pnl) > 0]
        if abs_ideals:
            avg_slip_pct = sum(r.slippage_cost for r in first_trades) / sum(abs_ideals) * 100
        early_limit_hits = sum(1 for r in first_trades if r.position_capped)
        early_order_splits = sum(1 for r in first_trades if r.order_split_required)

    checks_b = [
        ("First 30 trades: slippage < 20% of ideal", avg_slip_pct < 20),
        ("No position limits in first 30 trades",    early_limit_hits == 0),
        ("No order splits in first 30 trades",       early_order_splits == 0),
    ]
    log(f"  Early trade slippage: {avg_slip_pct:.1f}% of ideal P&L")
    for desc, passed in checks_b:
        log(f"  {desc}: {'PASS' if passed else 'FAIL'}")
    log(f"  VALIDATION 10B: {'PASS' if all(p for _, p in checks_b) else 'FAIL'}")

    # ══════════════════════════════════════════════════════════════════════
    # VALIDATION 10C — Extreme test
    # ══════════════════════════════════════════════════════════════════════
    log("\n" + "=" * 80)
    log("  VALIDATION 10C — EXTREME TEST ($100M, 50%, 7x)")
    log("=" * 80)

    sim_extreme = realistic_simulate(tl_ours, bar_data_15m, initial_equity=100_000_000,
                                      equity_fraction=0.50, leverage=7.0, timeframe="15m")
    log(format_results(sim_extreme, "$100M Extreme"))

    checks_c = [
        ("Position limit hits > 0",                    sim_extreme.position_limit_hits > 0),
        ("Friction % higher than $100K",               sim_extreme.friction_pct_of_ideal > sim_ours.friction_pct_of_ideal),
        ("Return % lower than $100K",                  sim_extreme.total_return_pct < sim_ours.total_return_pct),
    ]
    for desc, passed in checks_c:
        log(f"  {desc}: {'PASS' if passed else 'FAIL'}")
    log(f"  VALIDATION 10C: {'PASS' if all(p for _, p in checks_c) else 'FAIL'}")

    # ══════════════════════════════════════════════════════════════════════
    # VALIDATION 10E — V10 Retest
    # ══════════════════════════════════════════════════════════════════════
    log("\n" + "=" * 80)
    log("  VALIDATION 10E — V10 RETEST (REALISTIC)")
    log("=" * 80)

    sim_v10 = realistic_simulate(tl_v10, bar_data_30m, initial_equity=100_000,
                                  equity_fraction=0.50, leverage=7.0, timeframe="30m")
    log(format_results(sim_v10, "His v10 — Training"))
    log(format_yearly(sim_v10))

    sim_v10_ho = realistic_simulate(tl_v10_ho, bar_data_30m, initial_equity=100_000,
                                     equity_fraction=0.50, leverage=7.0, timeframe="30m")
    sim_ours_ho = realistic_simulate(tl_ours_ho, bar_data_15m, initial_equity=100_000,
                                      equity_fraction=0.50, leverage=7.0, timeframe="15m")

    log(f"\n  V10 RETEST — FULL REALISTIC COMPARISON:")
    hdr = f"  {'':20}{'PF':>7}{'Sharpe':>8}{'Final Eq':>16}{'Return':>10}{'MDD%':>8}{'Friction':>12}{'Liqs':>6}"
    log(hdr)
    log(f"  {'─' * len(hdr)}")
    for lbl, s in [("v10 Training", sim_v10), ("Ours Training", sim_ours),
                    ("v10 Holdout", sim_v10_ho), ("Ours Holdout", sim_ours_ho)]:
        log(f"  {lbl:<20}{s.profit_factor:>7.2f}{s.sharpe:>8.2f}${s.final_equity:>14,.0f}"
            f"{s.total_return_pct:>9.0f}%{s.max_drawdown_pct:>7.1f}%${s.total_friction:>10,.0f}{s.liquidations:>6}")

    log(f"\n  Flat $125 comparison (pure strategy quality):")
    log(f"    v10:  Sharpe={p_v10.get('sharpe')}, PF={p_v10.get('pf')}, P&L=${p_v10.get('pnl', 0):,.2f}")
    log(f"    Ours: Sharpe={p_ours.get('sharpe')}, PF={p_ours.get('pf')}, P&L=${p_ours.get('pnl', 0):,.2f}")

    # ══════════════════════════════════════════════════════════════════════
    # CAPACITY ANALYSIS
    # ══════════════════════════════════════════════════════════════════════
    log("\n[5/7] Running capacity analysis...")
    cap_ours = run_capacity_analysis(tl_ours, bar_data_15m, timeframe="15m")
    ceiling_ours = find_capacity_ceiling(cap_ours)
    log(format_capacity_analysis(cap_ours, ceiling_ours, "Our System"))

    cap_v10 = run_capacity_analysis(tl_v10, bar_data_30m, timeframe="30m")
    ceiling_v10 = find_capacity_ceiling(cap_v10)
    log(format_capacity_analysis(cap_v10, ceiling_v10, "v10 System"))

    # ══════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════════
    log("\n" + "=" * 80)
    log("  SUMMARY")
    log("=" * 80)
    log(f"\n  Key findings:")
    log(f"    Our system ($100K realistic): ${sim_ours.final_equity:,.0f} ({sim_ours.total_return_pct:,.0f}% return)")
    log(f"    v10 ($100K realistic):        ${sim_v10.final_equity:,.0f} ({sim_v10.total_return_pct:,.0f}% return)")
    log(f"    Our capacity ceiling:         ${ceiling_ours:,.0f}")
    log(f"    v10 capacity ceiling:         ${ceiling_v10:,.0f}")
    log(f"    Friction (ours): ${sim_ours.total_friction:,.0f} ({sim_ours.friction_pct_of_ideal:.1f}% of ideal P&L)")
    log(f"    Friction (v10):  ${sim_v10.total_friction:,.0f} ({sim_v10.friction_pct_of_ideal:.1f}% of ideal P&L)")
    log(f"    Liquidations (ours): {sim_ours.liquidations}")
    log(f"    Liquidations (v10):  {sim_v10.liquidations}")

    log(f"\n  Previous $10M-cap results vs new realistic simulation:")
    log(f"    OLD v10 training:  $18.4M (flat $10M cap)")
    log(f"    NEW v10 training:  ${sim_v10.final_equity:,.0f} (full impact/liq model)")
    log(f"    OLD ours training: $105M (flat $10M cap)")
    log(f"    NEW ours training: ${sim_ours.final_equity:,.0f} (full impact/liq model)")

    elapsed = time.time() - T0
    log(f"\n  Runtime: {elapsed:.1f}s")

    # ── Validation summary ──
    all_pass = all_match_10d and all(p for _, p in checks_a) and all(p for _, p in checks_b) and all(p for _, p in checks_c)
    log(f"\n  VALIDATION SUMMARY:")
    log(f"    10A Sanity:     {'PASS' if all(p for _, p in checks_a) else 'FAIL'}")
    log(f"    10B Small:      {'PASS' if all(p for _, p in checks_b) else 'FAIL'}")
    log(f"    10C Extreme:    {'PASS' if all(p for _, p in checks_c) else 'FAIL'}")
    log(f"    10D Compat:     {'PASS' if all_match_10d else 'FAIL'}")
    log(f"    ALL: {'PASS' if all_pass else 'SOME FAILURES'}")

    # ── Save results ──
    out_dir = "/opt/hypertrader/tests/realistic-sim-2026-03-22"
    os.makedirs(out_dir, exist_ok=True)

    results_json = {
        "engine": "realistic_simulation_v2",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "runtime_seconds": round(elapsed, 1),
        "model": {
            "market_impact": "square-root law (Donier & Bonart 2015)",
            "funding": "0.01% per 8h on notional, accrued per bar",
            "fees": "3.5 bps taker per side",
            "liquidation": "bar-by-bar check against isolated margin liq price",
            "position_limits": "BTC $500M, ETH $200M, SOL $50M",
        },
        "validations": {
            "10A_sanity": all(p for _, p in checks_a),
            "10B_small_account": all(p for _, p in checks_b),
            "10C_extreme": all(p for _, p in checks_c),
            "10D_backward_compat": all_match_10d,
        },
        "flat_125": {"v10": p_v10, "ours": p_ours},
        "realistic_100k": {
            "ours_training": _sim_summary(sim_ours),
            "v10_training": _sim_summary(sim_v10),
            "ours_holdout": _sim_summary(sim_ours_ho),
            "v10_holdout": _sim_summary(sim_v10_ho),
        },
        "capacity": {
            "ours": {"results": cap_ours, "ceiling": ceiling_ours},
            "v10": {"results": cap_v10, "ceiling": ceiling_v10},
        },
    }

    with open(f"{out_dir}/results.json", 'w') as f:
        json.dump(results_json, f, indent=2, default=str)
    with open(f"{out_dir}/report.txt", 'w') as f:
        f.write("\n".join(report_lines))

    log(f"\n  Saved to {out_dir}/")
    return results_json


def _sim_summary(sim):
    return {
        "final_equity": round(sim.final_equity, 2),
        "return_pct": round(sim.total_return_pct, 1),
        "sharpe": sim.sharpe, "pf": round(sim.profit_factor, 2),
        "mdd_pct": round(sim.max_drawdown_pct, 1),
        "ideal_pnl": round(sim.ideal_gross_pnl, 2),
        "total_slippage": round(sim.total_slippage, 2),
        "total_fees": round(sim.total_fees, 2),
        "total_funding": round(sim.total_funding, 2),
        "total_friction": round(sim.total_friction, 2),
        "friction_pct_of_ideal": round(sim.friction_pct_of_ideal, 1),
        "liquidations": sim.liquidations,
        "position_limit_hits": sim.position_limit_hits,
        "peak_notional": round(sim.peak_notional, 0),
        "annual_friction_budget": sim.annual_friction_budget,
    }


if __name__ == "__main__":
    main()
