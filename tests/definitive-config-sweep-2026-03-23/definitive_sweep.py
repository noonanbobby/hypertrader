#!/usr/bin/env python3
"""
DEFINITIVE CONFIGURATION SWEEP — Realistic Simulator with Concurrent Position Tracking.

Sweeps all combinations of strategy variant, sizing method, leverage, starting equity,
and max deployment to find the optimal configuration.

Key fix: proper concurrent position margin tracking (the old simulator was per-trade).
"""

import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

# =============================================================================
# CONSTANTS
# =============================================================================

DATA_DIR = "/opt/hypertrader/addons/backtest-data"
HOLDOUT_DATE = "2025-03-19"

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

TAKER_FEE_RATE = 0.00035
DEFAULT_FUNDING_PER_8H = 0.0001

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

    def volume_usd(self, i):
        return self.volumes[i] * self.closes[i]


def load_bar_data(asset, timeframe="15m"):
    sym = asset.lower()
    path = os.path.join(DATA_DIR, f"mega_{sym}_15m.json")
    with open(path) as f:
        raw = json.load(f)

    ts = [b["open_time"] for b in raw]
    o = [float(b["open"]) for b in raw]
    h = [float(b["high"]) for b in raw]
    l = [float(b["low"]) for b in raw]
    c = [float(b["close"]) for b in raw]
    v = [float(b["volume"]) for b in raw]

    if timeframe in ("15m", "15"):
        return BarData(ts=ts, opens=o, highs=h, lows=l, closes=c, volumes=v, bar_minutes=15.0)

    minutes_map = {"30m": 30, "1H": 60, "1h": 60, "4H": 240, "4h": 240}
    target_min = minutes_map.get(timeframe, 15)
    ms_per_bar = target_min * 60 * 1000

    r_ts, r_o, r_h, r_l, r_c, r_v = [], [], [], [], [], []
    i = 0
    n = len(ts)
    while i < n:
        bucket = ts[i] // ms_per_bar
        bar_o, bar_h, bar_l, bar_c, bar_v = o[i], h[i], l[i], c[i], v[i]
        bar_ts = bucket * ms_per_bar
        i += 1
        while i < n and ts[i] // ms_per_bar == bucket:
            bar_h = max(bar_h, h[i]); bar_l = min(bar_l, l[i])
            bar_c = c[i]; bar_v += v[i]
            i += 1
        r_ts.append(bar_ts); r_o.append(bar_o); r_h.append(bar_h)
        r_l.append(bar_l); r_c.append(bar_c); r_v.append(bar_v)

    return BarData(ts=r_ts, opens=r_o, highs=r_h, lows=r_l, closes=r_c,
                   volumes=r_v, bar_minutes=float(target_min))


@dataclass
class PreComp:
    volatility: list  # annualized daily vol per bar
    avg_volume: list  # rolling avg volume per bar


def precompute(bar_data):
    """Precompute rolling volatility and volume for market impact."""
    result = {}
    for asset, bd in bar_data.items():
        n = len(bd.closes)
        bars_per_day = 1440.0 / bd.bar_minutes
        period = 20

        # Rolling volatility (annualized)
        log_ret = [0.0] * n
        for i in range(1, n):
            if bd.closes[i] > 0 and bd.closes[i-1] > 0:
                log_ret[i] = math.log(bd.closes[i] / bd.closes[i-1])

        vol = [0.0] * n
        for i in range(period, n):
            window = log_ret[i - period + 1: i + 1]
            mean = sum(window) / period
            var = sum((r - mean) ** 2 for r in window) / max(period - 1, 1)
            vol[i] = math.sqrt(var) * math.sqrt(bars_per_day)

        # Rolling avg volume
        avg_v = [0.0] * n
        for i in range(period, n):
            avg_v[i] = sum(bd.volumes[i - period + 1: i + 1]) / period

        result[asset] = PreComp(volatility=vol, avg_volume=avg_v)
    return result


# =============================================================================
# MARKET IMPACT MODEL
# =============================================================================

def calc_market_impact(notional, bar_vol_usd, daily_vol_usd, daily_volatility, asset):
    params = ASSET_PARAMS.get(asset, DEFAULT_PARAMS)
    spread_bps = params["spread_bps"]
    k = params["k"]

    if daily_vol_usd <= 0 or notional <= 0:
        return spread_bps / 2.0 / 10000.0

    participation = notional / daily_vol_usd
    spread_cost = spread_bps / 2.0
    physical = k * daily_volatility * math.sqrt(participation)

    sigmoid = 0.0
    if participation < 0.005:
        sigmoid = daily_volatility * 10000.0 * 0.05
    elif participation > 0.20:
        sigmoid = (participation - 0.20) * 50.0

    return (spread_cost + physical + sigmoid) / 10000.0


# =============================================================================
# CORE SIMULATION — with concurrent position tracking
# =============================================================================

@dataclass
class SimResult:
    initial_equity: float
    final_equity: float
    net_pnl: float
    total_return_pct: float
    profit_factor: float
    sharpe: float
    max_drawdown_pct: float
    max_drawdown_usd: float
    win_rate: float
    total_trades: int
    ideal_gross_pnl: float
    total_slippage: float
    total_fees: float
    total_funding: float
    total_liq_fees: float
    total_friction: float
    friction_pct_of_ideal: float
    liquidations: int
    peak_notional: float
    equity_curve: list
    yearly: dict
    trades: list  # list of dicts
    skipped_trades: int
    long_pnl: float
    short_pnl: float


def simulate(trade_log, bar_data, precomp, config):
    """
    Enhanced realistic simulation with concurrent position tracking.

    config keys:
        initial_equity: float
        sizing_method: "fixed_ratio" | "proportional_fr" | "pct_equity"
        leverage: float or dict (per-asset)
        max_deployment_pct: float (0.5, 0.75, 1.0)
        # For pct_equity:
        long_frac: float
        short_frac: float
        circuit_breaker: bool
        position_cap: float or None
        # For fixed_ratio:
        base_margin: float
        delta: float
        cap_n: int
    """
    equity = config["initial_equity"]
    starting_equity = config["initial_equity"]
    peak_equity = equity
    method = config["sizing_method"]

    sorted_trades = sorted(trade_log, key=lambda t: t.get("entry_ts", ""))

    open_positions = []  # {actual_exit_bar, margin, net_pnl}
    results = []
    equity_curve = [equity]
    yearly = defaultdict(lambda: {"start": None, "end": 0, "pnl": 0, "trades": 0,
                                   "liqs": 0, "fees": 0, "funding": 0, "slippage": 0})
    skipped = 0

    for t in sorted_trades:
        asset = t["asset"]
        direction = t["direction"]
        is_long = direction == "long"
        entry_bar = t["entry_bar"]
        exit_bar = t["exit_bar"]
        yr = t.get("entry_ts", "")[:4]

        bd = bar_data.get(asset)
        if bd is None or entry_bar >= len(bd) or exit_bar >= len(bd):
            skipped += 1
            continue

        # ── Close expired positions ──
        still_open = []
        for pos in open_positions:
            if pos["actual_exit_bar"] <= entry_bar:
                equity += pos["net_pnl"]
                equity = max(equity, 0)
                equity_curve.append(equity)
                peak_equity = max(peak_equity, equity)
            else:
                still_open.append(pos)
        open_positions = still_open

        if equity <= 0:
            skipped += 1
            continue

        if yearly[yr]["start"] is None:
            yearly[yr]["start"] = equity

        # ── Concurrent deployment check ──
        deployed = sum(p["margin"] for p in open_positions)
        max_total = equity * config["max_deployment_pct"]
        available = max(max_total - deployed, 0)

        # ── Size the position ──
        if method == "pct_equity":
            frac = config["long_frac"] if is_long else config["short_frac"]
            if frac <= 0:
                skipped += 1
                continue
            desired = equity * frac

            if config.get("circuit_breaker"):
                dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
                if dd >= 0.60:
                    skipped += 1
                    continue  # Stop trading
                elif dd >= 0.40:
                    desired *= 0.2
                elif dd >= 0.20:
                    desired *= 0.5

            if config.get("position_cap") and config["position_cap"] > 0:
                desired = min(desired, config["position_cap"])

        elif method == "fixed_ratio":
            profit = max(equity - starting_equity, 0)
            delta = config["delta"]
            if delta > 0 and profit > 0:
                n = int((math.sqrt(1 + 8 * profit / delta) - 1) / 2) + 1
            else:
                n = 1
            n = min(n, config.get("cap_n", 4))
            desired = config["base_margin"] * n

        elif method == "proportional_fr":
            base_m = starting_equity * 0.125
            delta = starting_equity * 1.0
            profit = max(equity - starting_equity, 0)
            if delta > 0 and profit > 0:
                n = int((math.sqrt(1 + 8 * profit / delta) - 1) / 2) + 1
            else:
                n = 1
            n = min(n, 4)
            desired = base_m * n
        else:
            desired = 125.0

        actual_margin = min(desired, available)
        if actual_margin <= 0:
            skipped += 1
            continue

        # ── Leverage ──
        lev_cfg = config["leverage"]
        if isinstance(lev_cfg, dict):
            lev = lev_cfg.get(asset, 10.0)
        else:
            lev = lev_cfg

        notional = actual_margin * lev

        # ── Exchange position limit ──
        params = ASSET_PARAMS.get(asset, DEFAULT_PARAMS)
        position_capped = False
        if notional > params["max_position"]:
            notional = params["max_position"]
            actual_margin = notional / lev
            position_capped = True

        if notional <= 0:
            skipped += 1
            continue

        # ── Prices ──
        signal_entry = bd.opens[entry_bar]
        signal_exit = bd.opens[min(exit_bar, len(bd) - 1)]

        # ── Entry market impact ──
        pc = precomp[asset]
        daily_vol = pc.volatility[min(entry_bar, len(pc.volatility) - 1)]
        avg_vol = pc.avg_volume[min(entry_bar, len(pc.avg_volume) - 1)]
        bars_per_day = 1440.0 / bd.bar_minutes
        daily_vol_usd = avg_vol * bd.closes[entry_bar] * bars_per_day
        bar_vol_usd = bd.volume_usd(entry_bar)

        entry_slip = calc_market_impact(notional, bar_vol_usd, daily_vol_usd, daily_vol, asset)
        actual_entry = signal_entry * (1 + entry_slip) if is_long else signal_entry * (1 - entry_slip)
        entry_fee = notional * TAKER_FEE_RATE

        # ── Ideal P&L ──
        if is_long:
            ideal_pnl = (signal_exit - signal_entry) / signal_entry * notional
        else:
            ideal_pnl = (signal_entry - signal_exit) / signal_entry * notional

        # ── Liquidation price ──
        mm = params["maint_margin"]
        if is_long:
            liq_price = actual_entry * (1.0 - 1.0 / lev + mm)
        else:
            liq_price = actual_entry * (1.0 + 1.0 / lev - mm)

        # ── Bar-by-bar: funding + liquidation check ──
        liquidated = False
        funding_cost = 0.0
        actual_exit_bar = exit_bar
        funding_per_bar = DEFAULT_FUNDING_PER_8H * (bd.bar_minutes / 480.0)

        end_bar = min(exit_bar + 1, len(bd))
        for bi in range(entry_bar + 1, end_bar):
            funding_cost += notional * funding_per_bar
            if is_long and bd.lows[bi] <= liq_price:
                liquidated = True
                actual_exit_bar = bi
                break
            elif not is_long and bd.highs[bi] >= liq_price:
                liquidated = True
                actual_exit_bar = bi
                break

        bars_held = actual_exit_bar - entry_bar

        # ── Exit ──
        if liquidated:
            gross_pnl = -actual_margin
            liq_fee = notional * 0.005
            exit_fee = 0.0
            net_pnl = -actual_margin - entry_fee - liq_fee
            slippage = ideal_pnl - gross_pnl
        else:
            eb = min(exit_bar, len(bd) - 1)
            exit_daily_vol = pc.volatility[min(eb, len(pc.volatility) - 1)]
            exit_avg_vol = pc.avg_volume[min(eb, len(pc.avg_volume) - 1)]
            exit_daily_vol_usd = exit_avg_vol * bd.closes[eb] * bars_per_day

            exit_slip = calc_market_impact(notional, bd.volume_usd(eb), exit_daily_vol_usd, exit_daily_vol, asset)
            actual_exit = signal_exit * (1 - exit_slip) if is_long else signal_exit * (1 + exit_slip)
            exit_fee = notional * TAKER_FEE_RATE

            if is_long:
                gross_pnl = (actual_exit - actual_entry) / actual_entry * notional
            else:
                gross_pnl = (actual_entry - actual_exit) / actual_entry * notional

            liq_fee = 0.0
            slippage = ideal_pnl - gross_pnl
            net_pnl = gross_pnl - entry_fee - exit_fee - funding_cost

        # ── Track open position ──
        open_positions.append({
            "actual_exit_bar": actual_exit_bar,
            "margin": actual_margin,
            "net_pnl": net_pnl,
        })

        # ── Yearly ──
        yearly[yr]["end"] = equity  # will be updated on close
        yearly[yr]["pnl"] += net_pnl
        yearly[yr]["trades"] += 1
        if liquidated:
            yearly[yr]["liqs"] += 1
        yearly[yr]["fees"] += entry_fee + exit_fee
        yearly[yr]["funding"] += funding_cost
        yearly[yr]["slippage"] += slippage

        results.append({
            "asset": asset, "direction": direction,
            "margin": actual_margin, "notional": notional,
            "ideal_pnl": ideal_pnl, "gross_pnl": gross_pnl, "net_pnl": net_pnl,
            "entry_fee": entry_fee, "exit_fee": exit_fee,
            "funding_cost": funding_cost, "liq_fee": liq_fee,
            "slippage": slippage, "liquidated": liquidated,
            "bars_held": bars_held,
            "entry_ts": t.get("entry_ts", ""), "exit_ts": t.get("exit_ts", ""),
        })

    # ── Close remaining open positions ──
    for pos in open_positions:
        equity += pos["net_pnl"]
        equity = max(equity, 0)
        equity_curve.append(equity)
        peak_equity = max(peak_equity, equity)

    # Update yearly end values
    for yr in yearly:
        yearly[yr]["end"] = equity

    # ── Aggregate stats ──
    total_ideal = sum(r["ideal_pnl"] for r in results)
    total_slip = sum(r["slippage"] for r in results)
    total_fees = sum(r["entry_fee"] + r["exit_fee"] for r in results)
    total_fund = sum(r["funding_cost"] for r in results)
    total_liq = sum(r["liq_fee"] for r in results)
    total_friction = total_slip + total_fees + total_fund + total_liq
    net_pnl_total = equity - starting_equity

    # Drawdown
    peak = starting_equity
    max_dd_pct = 0.0
    max_dd_usd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        dd = peak - e
        dd_pct = dd / peak * 100 if peak > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_usd = dd

    # Win rate
    wins = sum(1 for r in results if r["net_pnl"] > 0)
    win_rate = wins / len(results) * 100 if results else 0

    # Profit factor
    gross_wins = sum(r["net_pnl"] for r in results if r["net_pnl"] > 0)
    gross_losses = abs(sum(r["net_pnl"] for r in results if r["net_pnl"] <= 0))
    pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    # Sharpe
    sharpe = _sharpe(equity_curve)

    # Friction %
    abs_ideal = abs(total_ideal) if total_ideal != 0 else 1
    fric_pct = total_friction / abs_ideal * 100

    # Peak notional
    peak_not = max((r["notional"] for r in results), default=0)

    # Liquidations
    liqs = sum(1 for r in results if r["liquidated"])

    # Long/short P&L
    long_pnl = sum(r["net_pnl"] for r in results if r["direction"] == "long")
    short_pnl = sum(r["net_pnl"] for r in results if r["direction"] == "short")

    return SimResult(
        initial_equity=starting_equity, final_equity=equity,
        net_pnl=net_pnl_total,
        total_return_pct=(equity / starting_equity - 1) * 100 if starting_equity > 0 else 0,
        profit_factor=pf, sharpe=sharpe,
        max_drawdown_pct=max_dd_pct, max_drawdown_usd=max_dd_usd,
        win_rate=win_rate, total_trades=len(results),
        ideal_gross_pnl=total_ideal, total_slippage=total_slip,
        total_fees=total_fees, total_funding=total_fund,
        total_liq_fees=total_liq, total_friction=total_friction,
        friction_pct_of_ideal=fric_pct, liquidations=liqs,
        peak_notional=peak_not, equity_curve=equity_curve,
        yearly=dict(yearly), trades=results, skipped_trades=skipped,
        long_pnl=long_pnl, short_pnl=short_pnl,
    )


def _sharpe(eq):
    if len(eq) < 3:
        return 0.0
    rets = []
    for i in range(1, len(eq)):
        if eq[i-1] > 0:
            rets.append(eq[i] / eq[i-1] - 1)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var) if var > 0 else 0
    if std == 0:
        return 0.0
    return round(mean / std * math.sqrt(len(rets)), 2)


# =============================================================================
# SWEEP DEFINITIONS
# =============================================================================

STARTING_EQUITIES = [1_000, 5_000, 10_000, 25_000, 50_000, 100_000]

LEVERAGE_OPTIONS = {
    "3x": 3.0,
    "5x": 5.0,
    "7x": 7.0,
    "10x": 10.0,
    "10/10/5": {"BTC": 10.0, "ETH": 10.0, "SOL": 5.0},
}

MAX_DEPLOY_OPTIONS = [0.50, 0.75, 1.00]

def build_sizing_configs():
    """Return list of (label, config_dict) for each sizing method."""
    configs = []

    # Method 1: Fixed Ratio d=$1K
    configs.append(("FR_d1K", {
        "sizing_method": "fixed_ratio",
        "base_margin": 125.0, "delta": 1000.0, "cap_n": 4,
        "long_frac": 0, "short_frac": 0,
    }))

    # Method 2: Proportional FR
    configs.append(("PropFR", {
        "sizing_method": "proportional_fr",
        "long_frac": 0, "short_frac": 0,
    }))

    # Method 3-6: Percent of equity at various fractions
    for pct in [10, 25, 50, 75]:
        frac = pct / 100.0
        configs.append((f"PctEq_{pct}", {
            "sizing_method": "pct_equity",
            "long_frac": frac, "short_frac": frac,
        }))

    # Method 7: 50% with circuit breaker
    configs.append(("PctEq_50_CB", {
        "sizing_method": "pct_equity",
        "long_frac": 0.50, "short_frac": 0.50,
        "circuit_breaker": True,
    }))

    # Method 8: 50% with position cap $50K
    configs.append(("PctEq_50_Cap", {
        "sizing_method": "pct_equity",
        "long_frac": 0.50, "short_frac": 0.50,
        "position_cap": 50_000.0,
    }))

    return configs


ASYMMETRIC_COMBOS = [
    ("50/50", 0.50, 0.50),
    ("50/25", 0.50, 0.25),
    ("50/10", 0.50, 0.10),
    ("50/5",  0.50, 0.05),
    ("75/25", 0.75, 0.25),
    ("75/10", 0.75, 0.10),
    ("25/25", 0.25, 0.25),
]

ASSET_PORTFOLIOS = {
    "BTC_only": ["BTC"],
    "BTC_ETH": ["BTC", "ETH"],
    "BTC_ETH_SOL": ["BTC", "ETH", "SOL"],
    "ETH_SOL": ["ETH", "SOL"],
}


# =============================================================================
# SWEEP RUNNER
# =============================================================================

def filter_trades(trade_log, assets=None, period="training"):
    """Filter trade log by assets and training/holdout split."""
    trades = trade_log
    if assets:
        trades = [t for t in trades if t["asset"] in assets]
    if period == "training":
        trades = [t for t in trades if t.get("entry_ts", "") < HOLDOUT_DATE]
    elif period == "holdout":
        trades = [t for t in trades if t.get("entry_ts", "") >= HOLDOUT_DATE]
    return trades


def run_one(trade_log, bar_data, precomp, sizing_cfg, leverage, start_eq, max_deploy):
    """Run a single simulation with given parameters."""
    cfg = dict(sizing_cfg)
    cfg["initial_equity"] = start_eq
    cfg["leverage"] = leverage
    cfg["max_deployment_pct"] = max_deploy

    # For pct_equity methods, the equity fraction is bounded by max_deployment
    # Each trade targets long_frac/short_frac of equity, but total can't exceed max_deploy
    # This is handled naturally in the simulator via the concurrent position check

    return simulate(trade_log, bar_data, precomp, cfg)


def run_full_sweep(trades_A, trades_B, bar_data, precomp):
    """Run the complete sweep: all combos of variant × sizing × leverage × equity × deployment."""
    sizing_cfgs = build_sizing_configs()
    all_results = []
    total = 2 * len(sizing_cfgs) * len(LEVERAGE_OPTIONS) * len(STARTING_EQUITIES) * len(MAX_DEPLOY_OPTIONS)
    done = 0
    t0 = time.time()

    for variant_label, trade_log in [("L+S", trades_A), ("L-only", trades_B)]:
        for sz_label, sz_cfg in sizing_cfgs:
            for lev_label, lev_val in LEVERAGE_OPTIONS.items():
                for start_eq in STARTING_EQUITIES:
                    for max_dep in MAX_DEPLOY_OPTIONS:
                        sim = run_one(trade_log, bar_data, precomp,
                                      sz_cfg, lev_val, start_eq, max_dep)
                        all_results.append({
                            "variant": variant_label,
                            "sizing": sz_label,
                            "leverage": lev_label,
                            "start_eq": start_eq,
                            "max_deploy": max_dep,
                            "final_eq": sim.final_equity,
                            "return_pct": sim.total_return_pct,
                            "sharpe": sim.sharpe,
                            "mdd_pct": sim.max_drawdown_pct,
                            "pf": sim.profit_factor,
                            "trades": sim.total_trades,
                            "liqs": sim.liquidations,
                            "peak_notional": sim.peak_notional,
                            "friction_pct": sim.friction_pct_of_ideal,
                            "win_rate": sim.win_rate,
                            "skipped": sim.skipped_trades,
                            "long_pnl": sim.long_pnl,
                            "short_pnl": sim.short_pnl,
                            "total_slippage": sim.total_slippage,
                            "total_fees": sim.total_fees,
                            "total_funding": sim.total_funding,
                            "total_liq_fees": sim.total_liq_fees,
                            "total_friction": sim.total_friction,
                            "ideal_pnl": sim.ideal_gross_pnl,
                            "yearly": sim.yearly,
                        })
                        done += 1
                        if done % 100 == 0:
                            elapsed = time.time() - t0
                            print(f"  [{done}/{total}] {elapsed:.1f}s ...", file=sys.stderr)

    elapsed = time.time() - t0
    print(f"  Core sweep: {done} simulations in {elapsed:.1f}s", file=sys.stderr)
    return all_results


def run_asymmetric_sweep(trades_A, bar_data, precomp):
    """Run asymmetric long/short sizing sweep (variant A only)."""
    results = []
    for label, long_f, short_f in ASYMMETRIC_COMBOS:
        cfg = {
            "sizing_method": "pct_equity",
            "long_frac": long_f, "short_frac": short_f,
        }
        for lev_label, lev_val in LEVERAGE_OPTIONS.items():
            for start_eq in STARTING_EQUITIES:
                # Use max_deploy = max(long_f, short_f) * 2 to allow 2 concurrent
                # Actually, use 1.0 to not additionally constrain
                max_dep = 1.0
                sim = run_one(trades_A, bar_data, precomp, cfg, lev_val, start_eq, max_dep)
                results.append({
                    "label": label, "long_frac": long_f, "short_frac": short_f,
                    "leverage": lev_label, "start_eq": start_eq,
                    "final_eq": sim.final_equity, "return_pct": sim.total_return_pct,
                    "sharpe": sim.sharpe, "mdd_pct": sim.max_drawdown_pct,
                    "trades": sim.total_trades, "liqs": sim.liquidations,
                    "long_pnl": sim.long_pnl, "short_pnl": sim.short_pnl,
                    "skipped": sim.skipped_trades,
                })
    print(f"  Asymmetric sweep: {len(results)} simulations", file=sys.stderr)
    return results


def run_asset_sweep(trades_A, bar_data, precomp, best_sizing, best_lev):
    """Run asset portfolio sweep with the best config from core sweep."""
    results = []
    for port_label, assets in ASSET_PORTFOLIOS.items():
        filtered_bd = {a: bar_data[a] for a in assets if a in bar_data}
        filtered_pc = {a: precomp[a] for a in assets if a in precomp}
        for start_eq in STARTING_EQUITIES:
            ftrades = [t for t in trades_A if t["asset"] in assets]
            sim = run_one(ftrades, filtered_bd, filtered_pc,
                          best_sizing, best_lev, start_eq, 1.0)
            results.append({
                "portfolio": port_label, "assets": assets,
                "start_eq": start_eq,
                "final_eq": sim.final_equity, "return_pct": sim.total_return_pct,
                "sharpe": sim.sharpe, "mdd_pct": sim.max_drawdown_pct,
                "trades": sim.total_trades, "liqs": sim.liquidations,
                "total_slippage": sim.total_slippage,
                "friction_pct": sim.friction_pct_of_ideal,
            })
    print(f"  Asset sweep: {len(results)} simulations", file=sys.stderr)
    return results


def run_holdout(trade_log, bar_data, precomp, configs):
    """Run holdout validation for a list of configs."""
    holdout_trades = [t for t in trade_log if t.get("entry_ts", "") >= HOLDOUT_DATE]
    results = []
    for label, variant_trades, cfg, lev, start_eq, max_dep in configs:
        htrades = [t for t in variant_trades if t.get("entry_ts", "") >= HOLDOUT_DATE]
        if not htrades:
            results.append({"label": label, "trades": 0, "final_eq": start_eq,
                            "return_pct": 0, "mdd_pct": 0, "liqs": 0})
            continue
        sim = run_one(htrades, bar_data, precomp, cfg, lev, start_eq, max_dep)
        results.append({
            "label": label, "start_eq": start_eq,
            "final_eq": sim.final_equity, "return_pct": sim.total_return_pct,
            "sharpe": sim.sharpe, "mdd_pct": sim.max_drawdown_pct,
            "trades": sim.total_trades, "liqs": sim.liquidations,
        })
    return results


def run_year_by_year(trade_log, bar_data, precomp, cfg, lev, max_dep):
    """Run simulation and return year-by-year results."""
    sim = run_one(trade_log, bar_data, precomp, cfg, lev, 25_000, max_dep)
    return sim.yearly, sim.final_equity


# =============================================================================
# PHASE 0 — MARGIN DEPLOYMENT AUDIT
# =============================================================================

def audit_previous_result(trades_A, bar_data, precomp):
    """Check if the previous $21.7M result had per-trade or total deployment."""
    lines = []
    lines.append("\n" + "=" * 72)
    lines.append("PHASE 0 — MARGIN DEPLOYMENT AUDIT")
    lines.append("=" * 72)

    # The old simulator used equity_fraction=0.50 per-trade with no concurrent cap
    # Replicate that behavior: max_deploy=100% so concurrent positions aren't constrained
    old_cfg = {
        "sizing_method": "pct_equity",
        "long_frac": 0.50, "short_frac": 0.50,
        "initial_equity": 100_000.0,
        "leverage": 7.0,
        "max_deployment_pct": 100.0,  # No concurrent cap = old behavior
    }
    train_trades = filter_trades(trades_A, period="training")
    sim_old = simulate(train_trades, bar_data, precomp, old_cfg)

    lines.append(f"\n  Old behavior (50% per-trade, NO concurrent cap):")
    lines.append(f"    Final equity: ${sim_old.final_equity:,.0f} (was $21,708,983)")
    lines.append(f"    Trades executed: {sim_old.total_trades}")
    lines.append(f"    Skipped: {sim_old.skipped_trades}")
    lines.append(f"    Liquidations: {sim_old.liquidations}")

    # Now with proper 50% total cap
    new_cfg = dict(old_cfg)
    new_cfg["max_deployment_pct"] = 0.50
    sim_new = simulate(train_trades, bar_data, precomp, new_cfg)

    lines.append(f"\n  Corrected behavior (50% TOTAL concurrent cap):")
    lines.append(f"    Final equity: ${sim_new.final_equity:,.0f}")
    lines.append(f"    Trades executed: {sim_new.total_trades}")
    lines.append(f"    Skipped (margin constrained): {sim_new.skipped_trades}")
    lines.append(f"    Liquidations: {sim_new.liquidations}")

    lines.append(f"\n  VERDICT:")
    lines.append(f"    Previous result was per-TRADE (no concurrent cap)")
    lines.append(f"    With concurrent cap: ${sim_new.final_equity:,.0f} vs ${sim_old.final_equity:,.0f}")
    diff_pct = (sim_old.final_equity - sim_new.final_equity) / sim_new.final_equity * 100
    lines.append(f"    Overstatement: {diff_pct:.1f}%")

    # Also test at $25K
    for eq in [25_000, 100_000]:
        for dep in [0.50, 0.75, 1.00]:
            cfg = dict(old_cfg)
            cfg["initial_equity"] = eq
            cfg["max_deployment_pct"] = dep
            s = simulate(train_trades, bar_data, precomp, cfg)
            lines.append(f"    ${eq/1000:.0f}K / 7x / 50% frac / {dep*100:.0f}% deploy: "
                         f"${s.final_equity:,.0f} | MDD {s.max_drawdown_pct:.1f}% | "
                         f"Trades {s.total_trades} | Skipped {s.skipped_trades}")

    return "\n".join(lines)


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def fmt_eq(v):
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:,.2f}M"
    elif abs(v) >= 1_000:
        return f"${v:,.0f}"
    else:
        return f"${v:,.2f}"


def format_master_table(results, n_top=50, n_bottom=10):
    lines = []
    lines.append("\n" + "=" * 140)
    lines.append("PHASE 3A — MASTER RESULTS (sorted by final equity, $25K start)")
    lines.append("=" * 140)

    # Filter to $25K and sort
    r25 = [r for r in results if r["start_eq"] == 25_000]
    r25.sort(key=lambda r: r["final_eq"], reverse=True)

    header = (f"  {'#':>3} │ {'Variant':<7} │ {'Sizing':<13} │ {'Lev':<7} │ {'Deploy':<6} │ "
              f"{'Final Eq':>14} │ {'Return':>9} │ {'Sharpe':>6} │ {'MDD%':>6} │ "
              f"{'Liqs':>4} │ {'Trades':>6} │ {'Fric%':>6}")
    lines.append(header)
    lines.append(f"  {'─'*3}─┼─{'─'*7}─┼─{'─'*13}─┼─{'─'*7}─┼─{'─'*6}─┼─"
                 f"{'─'*14}─┼─{'─'*9}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*4}─┼─{'─'*6}─┼─{'─'*6}")

    for i, r in enumerate(r25[:n_top]):
        lines.append(
            f"  {i+1:>3} │ {r['variant']:<7} │ {r['sizing']:<13} │ {r['leverage']:<7} │ "
            f"{r['max_deploy']*100:>5.0f}% │ {fmt_eq(r['final_eq']):>14} │ "
            f"{r['return_pct']:>8.0f}% │ {r['sharpe']:>6.2f} │ {r['mdd_pct']:>5.1f}% │ "
            f"{r['liqs']:>4} │ {r['trades']:>6} │ {r['friction_pct']:>5.1f}%"
        )

    if n_bottom and len(r25) > n_top + n_bottom:
        lines.append(f"  ... ({len(r25) - n_top - n_bottom} rows omitted) ...")
        for i, r in enumerate(r25[-n_bottom:]):
            idx = len(r25) - n_bottom + i + 1
            lines.append(
                f"  {idx:>3} │ {r['variant']:<7} │ {r['sizing']:<13} │ {r['leverage']:<7} │ "
                f"{r['max_deploy']*100:>5.0f}% │ {fmt_eq(r['final_eq']):>14} │ "
                f"{r['return_pct']:>8.0f}% │ {r['sharpe']:>6.2f} │ {r['mdd_pct']:>5.1f}% │ "
                f"{r['liqs']:>4} │ {r['trades']:>6} │ {r['friction_pct']:>5.1f}%"
            )

    return "\n".join(lines)


def format_optimal_per_equity(results):
    lines = []
    lines.append("\n" + "=" * 72)
    lines.append("PHASE 3B — OPTIMAL CONFIG PER STARTING EQUITY")
    lines.append("=" * 72)

    for eq in STARTING_EQUITIES:
        req = [r for r in results if r["start_eq"] == eq]
        if not req:
            continue

        lines.append(f"\n  ${eq:,}:")

        # Best by final equity
        best_eq = max(req, key=lambda r: r["final_eq"])
        lines.append(f"    Best by final equity: {best_eq['variant']} / {best_eq['sizing']} / "
                     f"{best_eq['leverage']} / {best_eq['max_deploy']*100:.0f}%dep → "
                     f"{fmt_eq(best_eq['final_eq'])}")

        # Best by Sharpe
        best_sh = max(req, key=lambda r: r["sharpe"])
        lines.append(f"    Best by Sharpe: {best_sh['variant']} / {best_sh['sizing']} / "
                     f"{best_sh['leverage']} → Sharpe {best_sh['sharpe']:.2f}")

        # Best Sharpe with MDD < 30%
        mdd30 = [r for r in req if r["mdd_pct"] < 30]
        if mdd30:
            best30 = max(mdd30, key=lambda r: r["sharpe"])
            lines.append(f"    Best Sharpe MDD<30%: {best30['variant']} / {best30['sizing']} / "
                         f"{best30['leverage']} → Sharpe {best30['sharpe']:.2f}, MDD {best30['mdd_pct']:.1f}%")
        else:
            lines.append(f"    Best Sharpe MDD<30%: NONE qualify")

        # Best Sharpe with MDD < 50%
        mdd50 = [r for r in req if r["mdd_pct"] < 50]
        if mdd50:
            best50 = max(mdd50, key=lambda r: r["sharpe"])
            lines.append(f"    Best Sharpe MDD<50%: {best50['variant']} / {best50['sizing']} / "
                         f"{best50['leverage']} → Sharpe {best50['sharpe']:.2f}, MDD {best50['mdd_pct']:.1f}%")

    return "\n".join(lines)


def format_head_to_head(results):
    lines = []
    lines.append("\n" + "=" * 120)
    lines.append("PHASE 3C — LONGS+SHORTS vs LONG-ONLY (head-to-head)")
    lines.append("=" * 120)

    header = (f"  {'Start':>8} │ {'Best Sizing':<13} │ {'Lev':<7} │ "
              f"{'L+S Final':>14} │ {'L-Only Final':>14} │ {'L+S MDD':>7} │ {'L-O MDD':>7} │ Winner")
    lines.append(header)
    lines.append(f"  {'─'*8}─┼─{'─'*13}─┼─{'─'*7}─┼─{'─'*14}─┼─{'─'*14}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*8}")

    for eq in STARTING_EQUITIES:
        ls_results = [r for r in results if r["start_eq"] == eq and r["variant"] == "L+S"]
        lo_results = [r for r in results if r["start_eq"] == eq and r["variant"] == "L-only"]
        if not ls_results or not lo_results:
            continue

        best_ls = max(ls_results, key=lambda r: r["final_eq"])
        # Find matching config in long-only
        matching_lo = [r for r in lo_results if r["sizing"] == best_ls["sizing"]
                       and r["leverage"] == best_ls["leverage"]
                       and r["max_deploy"] == best_ls["max_deploy"]]
        if matching_lo:
            best_lo = matching_lo[0]
        else:
            best_lo = max(lo_results, key=lambda r: r["final_eq"])

        winner = "L+S" if best_ls["final_eq"] > best_lo["final_eq"] else "L-only"
        lines.append(
            f"  ${eq:>7,} │ {best_ls['sizing']:<13} │ {best_ls['leverage']:<7} │ "
            f"{fmt_eq(best_ls['final_eq']):>14} │ {fmt_eq(best_lo['final_eq']):>14} │ "
            f"{best_ls['mdd_pct']:>6.1f}% │ {best_lo['mdd_pct']:>6.1f}% │ {winner}"
        )

    return "\n".join(lines)


def format_leverage_comparison(results):
    lines = []
    lines.append("\n" + "=" * 100)
    lines.append("PHASE 3D — LEVERAGE COMPARISON ($25K start, best sizing, longs+shorts)")
    lines.append("=" * 100)

    # Find best sizing at $25K for L+S
    r25_ls = [r for r in results if r["start_eq"] == 25_000 and r["variant"] == "L+S"]
    if not r25_ls:
        return "\n  No L+S results at $25K"

    best = max(r25_ls, key=lambda r: r["final_eq"])
    best_sz = best["sizing"]
    best_dep = best["max_deploy"]

    header = (f"  {'Leverage':<10} │ {'Final Eq':>14} │ {'Return':>9} │ {'Sharpe':>6} │ "
              f"{'MDD%':>6} │ {'Liqs':>4} │ {'Fric%':>6}")
    lines.append(f"\n  Using sizing: {best_sz}, deploy: {best_dep*100:.0f}%")
    lines.append(header)
    lines.append(f"  {'─'*10}─┼─{'─'*14}─┼─{'─'*9}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*4}─┼─{'─'*6}")

    for lev_label in LEVERAGE_OPTIONS:
        matches = [r for r in r25_ls if r["leverage"] == lev_label
                   and r["sizing"] == best_sz and r["max_deploy"] == best_dep]
        if matches:
            r = matches[0]
            lines.append(
                f"  {lev_label:<10} │ {fmt_eq(r['final_eq']):>14} │ {r['return_pct']:>8.0f}% │ "
                f"{r['sharpe']:>6.2f} │ {r['mdd_pct']:>5.1f}% │ {r['liqs']:>4} │ {r['friction_pct']:>5.1f}%"
            )

    return "\n".join(lines)


def format_sizing_comparison(results):
    lines = []
    lines.append("\n" + "=" * 120)
    lines.append("PHASE 3E — SIZING METHOD COMPARISON ($25K start, longs+shorts)")
    lines.append("=" * 120)

    # Find best leverage at $25K L+S
    r25_ls = [r for r in results if r["start_eq"] == 25_000 and r["variant"] == "L+S"]
    best = max(r25_ls, key=lambda r: r["final_eq"])
    best_lev = best["leverage"]
    best_dep = best["max_deploy"]

    header = (f"  {'Sizing':<15} │ {'Final Eq':>14} │ {'Return':>9} │ {'Sharpe':>6} │ "
              f"{'MDD%':>6} │ {'Liqs':>4} │ {'Peak Not':>12} │ {'Fric%':>6}")
    lines.append(f"\n  Using leverage: {best_lev}, deploy: {best_dep*100:.0f}%")
    lines.append(header)
    lines.append(f"  {'─'*15}─┼─{'─'*14}─┼─{'─'*9}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*4}─┼─{'─'*12}─┼─{'─'*6}")

    sizing_labels = [sc[0] for sc in build_sizing_configs()]
    for sz in sizing_labels:
        matches = [r for r in r25_ls if r["sizing"] == sz
                   and r["leverage"] == best_lev and r["max_deploy"] == best_dep]
        if matches:
            r = matches[0]
            lines.append(
                f"  {sz:<15} │ {fmt_eq(r['final_eq']):>14} │ {r['return_pct']:>8.0f}% │ "
                f"{r['sharpe']:>6.2f} │ {r['mdd_pct']:>5.1f}% │ {r['liqs']:>4} │ "
                f"{fmt_eq(r['peak_notional']):>12} │ {r['friction_pct']:>5.1f}%"
            )

    return "\n".join(lines)


def format_circuit_breaker(results):
    lines = []
    lines.append("\n" + "=" * 110)
    lines.append("PHASE 3F — CIRCUIT BREAKER IMPACT")
    lines.append("=" * 110)

    header = (f"  {'Start':>8} │ {'No CB: Final':>14} │ {'MDD%':>6} │ "
              f"{'CB: Final':>14} │ {'MDD%':>6} │ {'Ret Lost':>8} │ {'MDD Cut':>7}")
    lines.append(header)
    lines.append(f"  {'─'*8}─┼─{'─'*14}─┼─{'─'*6}─┼─{'─'*14}─┼─{'─'*6}─┼─{'─'*8}─┼─{'─'*7}")

    for eq in STARTING_EQUITIES:
        # Best leverage for each
        nocb = [r for r in results if r["start_eq"] == eq and r["sizing"] == "PctEq_50"
                and r["variant"] == "L+S"]
        withcb = [r for r in results if r["start_eq"] == eq and r["sizing"] == "PctEq_50_CB"
                  and r["variant"] == "L+S"]
        if nocb and withcb:
            bn = max(nocb, key=lambda r: r["final_eq"])
            bc = max(withcb, key=lambda r: r["final_eq"])
            ret_lost = (bn["final_eq"] - bc["final_eq"]) / bn["final_eq"] * 100 if bn["final_eq"] > 0 else 0
            mdd_cut = bn["mdd_pct"] - bc["mdd_pct"]
            lines.append(
                f"  ${eq:>7,} │ {fmt_eq(bn['final_eq']):>14} │ {bn['mdd_pct']:>5.1f}% │ "
                f"{fmt_eq(bc['final_eq']):>14} │ {bc['mdd_pct']:>5.1f}% │ {ret_lost:>7.1f}% │ {mdd_cut:>6.1f}%"
            )

    return "\n".join(lines)


def format_asset_portfolio(asset_results):
    lines = []
    lines.append("\n" + "=" * 100)
    lines.append("PHASE 3G — ASSET PORTFOLIO COMPARISON ($25K start)")
    lines.append("=" * 100)

    header = (f"  {'Portfolio':<15} │ {'Final Eq':>14} │ {'Return':>9} │ {'Sharpe':>6} │ "
              f"{'MDD%':>6} │ {'Liqs':>4} │ {'Fric%':>6}")
    lines.append(header)
    lines.append(f"  {'─'*15}─┼─{'─'*14}─┼─{'─'*9}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*4}─┼─{'─'*6}")

    for r in asset_results:
        if r["start_eq"] == 25_000:
            lines.append(
                f"  {r['portfolio']:<15} │ {fmt_eq(r['final_eq']):>14} │ {r['return_pct']:>8.0f}% │ "
                f"{r['sharpe']:>6.2f} │ {r['mdd_pct']:>5.1f}% │ {r['liqs']:>4} │ {r['friction_pct']:>5.1f}%"
            )

    return "\n".join(lines)


def format_asymmetric(asym_results):
    lines = []
    lines.append("\n" + "=" * 120)
    lines.append("PHASE 3H — ASYMMETRIC LONG/SHORT SIZING ($25K start)")
    lines.append("=" * 120)

    # Find best leverage
    r25 = [r for r in asym_results if r["start_eq"] == 25_000]
    if not r25:
        return "\n  No asymmetric results at $25K"

    best = max(r25, key=lambda r: r["final_eq"])
    best_lev = best["leverage"]

    header = (f"  {'Config':<12} │ {'Final Eq':>14} │ {'Sharpe':>6} │ {'MDD%':>6} │ "
              f"{'Long P&L':>12} │ {'Short P&L':>12} │ {'Trades':>6} │ {'Skipped':>7}")
    lines.append(f"\n  Using leverage: {best_lev}")
    lines.append(header)
    lines.append(f"  {'─'*12}─┼─{'─'*14}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*12}─┼─{'─'*12}─┼─{'─'*6}─┼─{'─'*7}")

    for r in r25:
        if r["leverage"] == best_lev:
            lines.append(
                f"  {r['label']:<12} │ {fmt_eq(r['final_eq']):>14} │ {r['sharpe']:>6.2f} │ "
                f"{r['mdd_pct']:>5.1f}% │ {fmt_eq(r['long_pnl']):>12} │ "
                f"{fmt_eq(r['short_pnl']):>12} │ {r['trades']:>6} │ {r['skipped']:>7}"
            )

    return "\n".join(lines)


def format_year_by_year(yearly, label, start_eq=25_000):
    lines = []
    lines.append(f"\n  {label}:")
    lines.append(f"  {'Year':<6} │ {'Start':>12} │ {'End':>12} │ {'P&L':>12} │ "
                 f"{'Return':>8} │ {'Trades':>6} │ {'Liqs':>4}")
    lines.append(f"  {'─'*6}─┼─{'─'*12}─┼─{'─'*12}─┼─{'─'*12}─┼─{'─'*8}─┼─{'─'*6}─┼─{'─'*4}")

    for yr in sorted(yearly):
        y = yearly[yr]
        s = y["start"] if y["start"] else start_eq
        ret = y["pnl"] / s * 100 if s > 0 else 0
        lines.append(
            f"  {yr:<6} │ {fmt_eq(s):>12} │ {fmt_eq(y['end']):>12} │ "
            f"{fmt_eq(y['pnl']):>12} │ {ret:>7.1f}% │ {y['trades']:>6} │ {y['liqs']:>4}"
        )
    return "\n".join(lines)


def format_holdout(holdout_results, training_results):
    lines = []
    lines.append("\n" + "=" * 120)
    lines.append("PHASE 3J — HOLDOUT VALIDATION ($25K start)")
    lines.append("=" * 120)

    header = (f"  {'Config':<40} │ {'Train Final':>12} │ {'Hold Final':>12} │ "
              f"{'Hold Ret':>8} │ {'Hold MDD':>8} │ {'Liqs':>4}")
    lines.append(header)
    lines.append(f"  {'─'*40}─┼─{'─'*12}─┼─{'─'*12}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*4}")

    for hr in holdout_results:
        # Find training result
        train_final = "N/A"
        for tr in training_results:
            if tr.get("label") == hr["label"]:
                train_final = fmt_eq(tr["final_eq"])
                break
        lines.append(
            f"  {hr['label']:<40} │ {train_final:>12} │ {fmt_eq(hr['final_eq']):>12} │ "
            f"{hr.get('return_pct', 0):>7.0f}% │ {hr.get('mdd_pct', 0):>7.1f}% │ {hr.get('liqs', 0):>4}"
        )

    return "\n".join(lines)


def format_cost_breakdown(results, trades_A, bar_data, precomp):
    """Run top 3 configs and show detailed cost breakdown."""
    lines = []
    lines.append("\n" + "=" * 72)
    lines.append("PHASE 3K — COST BREAKDOWN ($25K start, top 3)")
    lines.append("=" * 72)

    r25 = [r for r in results if r["start_eq"] == 25_000 and r["variant"] == "L+S"]
    r25.sort(key=lambda r: r["final_eq"], reverse=True)

    for i, r in enumerate(r25[:3]):
        lines.append(f"\n  Config {i+1}: {r['variant']} / {r['sizing']} / {r['leverage']} / {r['max_deploy']*100:.0f}%dep")
        ideal = r["ideal_pnl"]
        lines.append(f"    Ideal P&L (zero friction):     {fmt_eq(ideal)}")
        lines.append(f"    − Market impact:                {fmt_eq(r['total_slippage'])} "
                     f"({r['total_slippage']/abs(ideal)*100:.1f}% of ideal)" if ideal != 0 else "")
        lines.append(f"    − Trading fees:                 {fmt_eq(r['total_fees'])} "
                     f"({r['total_fees']/abs(ideal)*100:.1f}% of ideal)" if ideal != 0 else "")
        lines.append(f"    − Funding costs:                {fmt_eq(r['total_funding'])} "
                     f"({r['total_funding']/abs(ideal)*100:.1f}% of ideal)" if ideal != 0 else "")
        lines.append(f"    − Liquidation fees:             {fmt_eq(r['total_liq_fees'])}")
        lines.append(f"    ────────────────────────────────────────")
        net = r["final_eq"] - r["start_eq"]
        lines.append(f"    = Net P&L:                      {fmt_eq(net)}")
        lines.append(f"    Total friction:                 {fmt_eq(r['total_friction'])} "
                     f"({r['friction_pct']:.1f}% of ideal)")

    return "\n".join(lines)


def format_definitive(results, asym_results, asset_results, holdout_results):
    lines = []
    lines.append("\n" + "=" * 72)
    lines.append("  THE DEFINITIVE CONFIGURATION")
    lines.append("=" * 72)

    # Best at $25K unconstrained
    r25 = [r for r in results if r["start_eq"] == 25_000]
    best = max(r25, key=lambda r: r["final_eq"])

    lines.append(f"\n  MOST PROFITABLE AT $25,000:")
    lines.append(f"    Strategy: {best['variant']}")
    lines.append(f"    Sizing: {best['sizing']}")
    lines.append(f"    Leverage: {best['leverage']}")
    lines.append(f"    Max deployment: {best['max_deploy']*100:.0f}%")
    lines.append(f"    Training: $25,000 → {fmt_eq(best['final_eq'])} ({best['return_pct']:.0f}%)")
    lines.append(f"    MDD: {best['mdd_pct']:.1f}% | Liquidations: {best['liqs']}")
    lines.append(f"    Sharpe: {best['sharpe']:.2f} | Friction: {best['friction_pct']:.1f}% of ideal")

    # Find holdout for this config
    for hr in holdout_results:
        if hr.get("label", "").startswith("#1"):
            lines.append(f"    Holdout: ${hr['start_eq']:,} → {fmt_eq(hr['final_eq'])} ({hr.get('return_pct',0):.0f}%)")
            break

    # Best with MDD < 50%
    mdd50 = [r for r in r25 if r["mdd_pct"] < 50]
    if mdd50:
        b50 = max(mdd50, key=lambda r: r["final_eq"])
        lines.append(f"\n  MOST PROFITABLE WITH MDD < 50%:")
        lines.append(f"    {b50['variant']} / {b50['sizing']} / {b50['leverage']} / {b50['max_deploy']*100:.0f}%dep")
        lines.append(f"    Training: $25,000 → {fmt_eq(b50['final_eq'])} | MDD: {b50['mdd_pct']:.1f}%")

    # Best with MDD < 30%
    mdd30 = [r for r in r25 if r["mdd_pct"] < 30]
    if mdd30:
        b30 = max(mdd30, key=lambda r: r["final_eq"])
        lines.append(f"\n  MOST PROFITABLE WITH MDD < 30%:")
        lines.append(f"    {b30['variant']} / {b30['sizing']} / {b30['leverage']} / {b30['max_deploy']*100:.0f}%dep")
        lines.append(f"    Training: $25,000 → {fmt_eq(b30['final_eq'])} | MDD: {b30['mdd_pct']:.1f}%")

    # $1K
    r1k = [r for r in results if r["start_eq"] == 1_000]
    if r1k:
        b1k = max(r1k, key=lambda r: r["final_eq"])
        lines.append(f"\n  AT $1,000 STARTING EQUITY:")
        lines.append(f"    Most profitable: {b1k['variant']} / {b1k['sizing']} / {b1k['leverage']} "
                     f"→ {fmt_eq(b1k['final_eq'])}")

        # Current deployment (FR d=$1K, 10/10/5)
        current = [r for r in r1k if r["sizing"] == "FR_d1K"
                   and r["leverage"] == "10/10/5"]
        if current:
            c = max(current, key=lambda r: r["final_eq"])
            lines.append(f"    Current deployment: FR_d1K / 10/10/5 → {fmt_eq(c['final_eq'])}")
            diff = b1k["final_eq"] - c["final_eq"]
            lines.append(f"    Difference vs optimal: {'+' if diff > 0 else ''}{fmt_eq(diff)}")

    # KEY FINDINGS
    lines.append(f"\n  KEY FINDINGS:")

    # 1. L+S vs L-only
    ls_best = max([r for r in r25 if r["variant"] == "L+S"], key=lambda r: r["final_eq"], default=None)
    lo_best = max([r for r in r25 if r["variant"] == "L-only"], key=lambda r: r["final_eq"], default=None)
    if ls_best and lo_best:
        winner = "L+S" if ls_best["final_eq"] > lo_best["final_eq"] else "L-only"
        lines.append(f"    1. {winner} wins with compounding: "
                     f"L+S={fmt_eq(ls_best['final_eq'])} vs L-only={fmt_eq(lo_best['final_eq'])}")

    # 2. Optimal leverage
    lines.append(f"    2. Optimal leverage: {best['leverage']}")

    # 3. Optimal sizing
    lines.append(f"    3. Optimal sizing: {best['sizing']}")

    # 4. Best asymmetric
    if asym_results:
        a25 = [r for r in asym_results if r["start_eq"] == 25_000]
        if a25:
            ba = max(a25, key=lambda r: r["final_eq"])
            lines.append(f"    4. Optimal long/short split: {ba['label']} → {fmt_eq(ba['final_eq'])}")

    # 5. Best asset selection
    if asset_results:
        ap25 = [r for r in asset_results if r["start_eq"] == 25_000]
        if ap25:
            bp = max(ap25, key=lambda r: r["final_eq"])
            lines.append(f"    5. Optimal assets: {bp['portfolio']} → {fmt_eq(bp['final_eq'])}")

    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================

def main():
    T0 = time.time()
    report = []

    def log(s):
        print(s)
        report.append(s)

    log("=" * 72)
    log("  DEFINITIVE CONFIGURATION SWEEP — Realistic Simulator")
    log(f"  Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log("=" * 72)

    # ── Phase 1: Load trade logs ──
    log("\n[PHASE 1] Loading trade logs from Rust engine...")
    with open("/tmp/discovery/sweep_tradelog_A.json") as f:
        data_A = json.load(f)
    with open("/tmp/discovery/sweep_tradelog_B.json") as f:
        data_B = json.load(f)

    all_trades_A = data_A["trade_log"]
    all_trades_B = data_B["trade_log"]

    train_A = filter_trades(all_trades_A, period="training")
    train_B = filter_trades(all_trades_B, period="training")

    log(f"  Variant A (L+S): {len(all_trades_A)} total, {len(train_A)} training")
    log(f"    Longs: {sum(1 for t in all_trades_A if t['direction']=='long')}, "
        f"Shorts: {sum(1 for t in all_trades_A if t['direction']=='short')}")
    log(f"  Variant B (L-only): {len(all_trades_B)} total, {len(train_B)} training")

    # ── Load bar data ──
    log("\n[DATA] Loading bar data...")
    bar_data = {}
    for asset in ["BTC", "ETH", "SOL"]:
        bar_data[asset] = load_bar_data(asset, "15m")
        log(f"  {asset}: {len(bar_data[asset])} bars")

    log("[DATA] Precomputing volatility & volume...")
    precomp = precompute(bar_data)

    # ── Phase 0: Margin audit ──
    log("\n[PHASE 0] Auditing previous $21.7M result...")
    audit = audit_previous_result(train_A, bar_data, precomp)
    log(audit)

    # ── Phase 2: Full sweep (training data only) ──
    log("\n[PHASE 2] Running full sweep (training data)...")
    all_results = run_full_sweep(train_A, train_B, bar_data, precomp)

    # ── Phase 2.5: Asymmetric sizing sweep ──
    log("\n[PHASE 2.5] Running asymmetric L/S sizing sweep...")
    asym_results = run_asymmetric_sweep(train_A, bar_data, precomp)

    # ── Phase 2.7: Asset portfolio sweep ──
    log("\n[PHASE 2.7] Running asset portfolio sweep...")
    # Use best sizing from core sweep at $25K
    r25 = [r for r in all_results if r["start_eq"] == 25_000 and r["variant"] == "L+S"]
    best_core = max(r25, key=lambda r: r["final_eq"])
    best_sz_label = best_core["sizing"]
    best_lev_label = best_core["leverage"]
    best_dep = best_core["max_deploy"]

    # Find the sizing config
    all_sz = build_sizing_configs()
    best_sz_cfg = next(cfg for label, cfg in all_sz if label == best_sz_label)

    best_lev_val = LEVERAGE_OPTIONS[best_lev_label]
    asset_results = run_asset_sweep(train_A, bar_data, precomp, best_sz_cfg, best_lev_val)

    # ── Phase 3: Output ──
    log("\n" + "=" * 72)
    log("  PHASE 3 — RESULTS")
    log("=" * 72)

    # 3A: Master table
    log(format_master_table(all_results))

    # 3B: Optimal per equity
    log(format_optimal_per_equity(all_results))

    # 3C: Head-to-head
    log(format_head_to_head(all_results))

    # 3D: Leverage comparison
    log(format_leverage_comparison(all_results))

    # 3E: Sizing comparison
    log(format_sizing_comparison(all_results))

    # 3F: Circuit breaker
    log(format_circuit_breaker(all_results))

    # 3G: Asset portfolio
    log(format_asset_portfolio(asset_results))

    # 3H: Asymmetric sizing
    log(format_asymmetric(asym_results))

    # 3I: Year-by-year for top 3
    log("\n" + "=" * 72)
    log("PHASE 3I — YEAR-BY-YEAR (top 3 configs at $25K)")
    log("=" * 72)

    r25_all = [r for r in all_results if r["start_eq"] == 25_000]
    r25_sorted = sorted(r25_all, key=lambda r: r["final_eq"], reverse=True)

    for i, r in enumerate(r25_sorted[:3]):
        label = f"#{i+1}: {r['variant']} / {r['sizing']} / {r['leverage']} / {r['max_deploy']*100:.0f}%dep"
        # Re-run to get yearly data (already stored in results)
        if r.get("yearly"):
            log(format_year_by_year(r["yearly"], label))

    # 3J: Holdout validation
    log("\n[HOLDOUT] Running holdout validation for top configs...")

    holdout_configs = []
    training_refs = []

    # Top 5 by final equity at $25K
    for i, r in enumerate(r25_sorted[:5]):
        sz_cfg = next(cfg for label, cfg in all_sz if label == r["sizing"])
        lev_val = LEVERAGE_OPTIONS[r["leverage"]]
        variant_trades = all_trades_A if r["variant"] == "L+S" else all_trades_B
        label = f"#{i+1} {r['variant']}/{r['sizing']}/{r['leverage']}/{r['max_deploy']*100:.0f}%"
        holdout_configs.append((label, variant_trades, sz_cfg, lev_val, 25_000, r["max_deploy"]))
        training_refs.append({"label": label, "final_eq": r["final_eq"]})

    # Best MDD < 50%
    mdd50 = [r for r in r25_all if r["mdd_pct"] < 50]
    if mdd50:
        b50 = max(mdd50, key=lambda r: r["final_eq"])
        sz_cfg = next(cfg for label, cfg in all_sz if label == b50["sizing"])
        lev_val = LEVERAGE_OPTIONS[b50["leverage"]]
        vt = all_trades_A if b50["variant"] == "L+S" else all_trades_B
        label = f"BestMDD50 {b50['variant']}/{b50['sizing']}/{b50['leverage']}"
        holdout_configs.append((label, vt, sz_cfg, lev_val, 25_000, b50["max_deploy"]))
        training_refs.append({"label": label, "final_eq": b50["final_eq"]})

    # Best MDD < 30%
    mdd30 = [r for r in r25_all if r["mdd_pct"] < 30]
    if mdd30:
        b30 = max(mdd30, key=lambda r: r["final_eq"])
        sz_cfg = next(cfg for label, cfg in all_sz if label == b30["sizing"])
        lev_val = LEVERAGE_OPTIONS[b30["leverage"]]
        vt = all_trades_A if b30["variant"] == "L+S" else all_trades_B
        label = f"BestMDD30 {b30['variant']}/{b30['sizing']}/{b30['leverage']}"
        holdout_configs.append((label, vt, sz_cfg, lev_val, 25_000, b30["max_deploy"]))
        training_refs.append({"label": label, "final_eq": b30["final_eq"]})

    holdout_results = run_holdout(all_trades_A, bar_data, precomp, holdout_configs)
    log(format_holdout(holdout_results, training_refs))

    # 3K: Cost breakdown
    log(format_cost_breakdown(all_results, train_A, bar_data, precomp))

    # Phase 4: Definitive answer
    log(format_definitive(all_results, asym_results, asset_results, holdout_results))

    # ── Save all results ──
    output = {
        "generated": time.strftime('%Y-%m-%d %H:%M:%S UTC'),
        "trade_counts": {
            "variant_A_total": len(all_trades_A), "variant_A_training": len(train_A),
            "variant_B_total": len(all_trades_B), "variant_B_training": len(train_B),
        },
        "all_results": all_results,
        "asymmetric_results": asym_results,
        "asset_results": asset_results,
        "holdout_results": holdout_results,
    }

    with open("/tmp/discovery/definitive_config_sweep.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    elapsed = time.time() - T0
    log(f"\n  Total runtime: {elapsed:.1f}s")
    log(f"  Results saved to /tmp/discovery/definitive_config_sweep.json")

    # Save report text
    with open("/tmp/discovery/definitive_config_sweep_report.txt", "w") as f:
        f.write("\n".join(report))


if __name__ == "__main__":
    main()
