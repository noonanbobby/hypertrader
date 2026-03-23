#!/usr/bin/env python3
"""
DEFINITIVE CONFIGURATION SWEEP v2 — All 6 Simulator Bugs Fixed.

Fixes applied:
  1. Removed sigmoid discontinuity — impact is now monotonically increasing
  2. Recalibrated k parameters for Hyperliquid crypto order books
  3. Realistic position limits ($10M BTC, $5M ETH, $2M SOL)
  4. Concurrent position margin tracking
  5. Realistic funding rates (0.03%/8h longs, -0.01%/8h shorts)
  6. Order splitting penalty for large orders
"""

import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

# =============================================================================
# CONSTANTS — ALL CORRECTED
# =============================================================================

DATA_DIR = "/opt/hypertrader/addons/backtest-data"
HOLDOUT_DATE = "2025-03-19"

# BUG #2 FIX: Recalibrated k for Hyperliquid crypto order books
# Formula: impact_bps = spread/2 + k * sqrt(notional_usd)
# Calibrated so: BTC $1M→7bps, ETH $1M→12bps, SOL $500K→20bps
#
# BUG #3 FIX: Realistic position limits
# BTC $10M, ETH $5M, SOL $2M (was $500M/$200M/$50M)
ASSET_PARAMS = {
    "BTC": {"spread_bps": 0.5, "k": 0.00675, "maint_margin": 0.005,
            "max_position": 10_000_000.0},
    "ETH": {"spread_bps": 1.0, "k": 0.01150, "maint_margin": 0.005,
            "max_position": 5_000_000.0},
    "SOL": {"spread_bps": 3.0, "k": 0.02616, "maint_margin": 0.01,
            "max_position": 2_000_000.0},
}
DEFAULT_PARAMS = {"spread_bps": 5.0, "k": 0.04, "maint_margin": 0.01,
                  "max_position": 1_000_000.0}

TAKER_FEE_RATE = 0.00035  # 3.5 bps per side

# BUG #5 FIX: Realistic funding rates
FUNDING_LONG_PER_8H = 0.0003   # 0.03% — longs pay during bull trends
FUNDING_SHORT_PER_8H = -0.0001 # -0.01% — shorts receive (net)

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
    i = 0; n = len(ts)
    while i < n:
        bucket = ts[i] // ms_per_bar
        bar_o, bar_h, bar_l, bar_c, bar_v = o[i], h[i], l[i], c[i], v[i]
        bar_ts = bucket * ms_per_bar; i += 1
        while i < n and ts[i] // ms_per_bar == bucket:
            bar_h = max(bar_h, h[i]); bar_l = min(bar_l, l[i])
            bar_c = c[i]; bar_v += v[i]; i += 1
        r_ts.append(bar_ts); r_o.append(bar_o); r_h.append(bar_h)
        r_l.append(bar_l); r_c.append(bar_c); r_v.append(bar_v)
    return BarData(ts=r_ts, opens=r_o, highs=r_h, lows=r_l, closes=r_c,
                   volumes=r_v, bar_minutes=float(target_min))


@dataclass
class PreComp:
    volatility: list
    avg_volume: list


def precompute(bar_data):
    result = {}
    for asset, bd in bar_data.items():
        n = len(bd.closes); bars_per_day = 1440.0 / bd.bar_minutes; period = 20
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
        avg_v = [0.0] * n
        for i in range(period, n):
            avg_v[i] = sum(bd.volumes[i - period + 1: i + 1]) / period
        result[asset] = PreComp(volatility=vol, avg_volume=avg_v)
    return result


# =============================================================================
# BUG #1 FIX: NEW MARKET IMPACT MODEL — Monotonically Increasing
# =============================================================================

def calc_market_impact(notional, daily_volume_usd, asset):
    """
    Fixed impact model: impact_bps = spread/2 + k * sqrt(notional)
    - No sigmoid, no discontinuity
    - Monotonically increasing with position size
    - Calibrated to Hyperliquid order book depth
    """
    params = ASSET_PARAMS.get(asset, DEFAULT_PARAMS)
    spread_bps = params["spread_bps"]
    k = params["k"]

    if notional <= 0:
        return 0.0

    impact_bps = spread_bps / 2.0 + k * math.sqrt(notional)

    # BUG #6 FIX: Order splitting penalty
    # Orders exceeding 1% of daily volume need multiple bars to execute,
    # causing additional adverse price movement
    if daily_volume_usd > 0:
        participation = notional / daily_volume_usd
        if participation > 0.01:
            # Each additional 1% of daily volume adds 5 bps penalty
            extra_pct = participation - 0.01
            splitting_penalty = extra_pct * 500  # 5 bps per 1% of daily volume
            impact_bps += splitting_penalty

    return impact_bps / 10000.0  # return as decimal


# =============================================================================
# CORE SIMULATION — BUG #4 FIX: Concurrent position tracking
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
    trades: list
    skipped_trades: int
    long_pnl: float
    short_pnl: float
    capped_trades: int


def simulate(trade_log, bar_data, precomp, config):
    """
    Realistic simulation with all 6 bug fixes.

    config keys:
        initial_equity, sizing_method, leverage (float or dict),
        max_deployment_pct, long_frac, short_frac,
        circuit_breaker, position_cap,
        base_margin, delta, cap_n  (for fixed_ratio)
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
    capped = 0

    for t in sorted_trades:
        asset = t["asset"]
        direction = t["direction"]
        is_long = direction == "long"
        entry_bar = t["entry_bar"]
        exit_bar = t["exit_bar"]
        yr = t.get("entry_ts", "")[:4]

        bd = bar_data.get(asset)
        if bd is None or entry_bar >= len(bd) or exit_bar >= len(bd):
            skipped += 1; continue

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
            skipped += 1; continue

        if yearly[yr]["start"] is None:
            yearly[yr]["start"] = equity

        # ── BUG #4 FIX: Concurrent deployment check ──
        deployed = sum(p["margin"] for p in open_positions)
        max_total = equity * config["max_deployment_pct"]
        available = max(max_total - deployed, 0)

        # ── Size the position ──
        if method == "pct_equity":
            frac = config["long_frac"] if is_long else config["short_frac"]
            if frac <= 0:
                skipped += 1; continue
            desired = equity * frac
            if config.get("circuit_breaker"):
                dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
                if dd >= 0.60:
                    skipped += 1; continue
                elif dd >= 0.40:
                    desired *= 0.2
                elif dd >= 0.20:
                    desired *= 0.5
            if config.get("position_cap") and config["position_cap"] > 0:
                desired = min(desired, config["position_cap"])
        elif method == "fixed_ratio":
            profit = max(equity - starting_equity, 0)
            delta = config["delta"]
            n = int((math.sqrt(1 + 8 * profit / delta) - 1) / 2) + 1 if delta > 0 and profit > 0 else 1
            n = min(n, config.get("cap_n", 4))
            desired = config["base_margin"] * n
        elif method == "proportional_fr":
            base_m = starting_equity * 0.125
            delta = starting_equity * 1.0
            profit = max(equity - starting_equity, 0)
            n = int((math.sqrt(1 + 8 * profit / delta) - 1) / 2) + 1 if delta > 0 and profit > 0 else 1
            n = min(n, 4)
            desired = base_m * n
        else:
            desired = 125.0

        actual_margin = min(desired, available)
        if actual_margin < 50:  # Minimum viable margin
            skipped += 1; continue

        # ── Leverage ──
        lev_cfg = config["leverage"]
        lev = lev_cfg.get(asset, 10.0) if isinstance(lev_cfg, dict) else lev_cfg

        notional = actual_margin * lev

        # ── BUG #3 FIX: Realistic position limits ──
        params = ASSET_PARAMS.get(asset, DEFAULT_PARAMS)
        position_capped = False
        if notional > params["max_position"]:
            notional = params["max_position"]
            actual_margin = notional / lev
            position_capped = True
            capped += 1

        if notional <= 0:
            skipped += 1; continue

        # ── Prices ──
        signal_entry = bd.opens[entry_bar]
        signal_exit = bd.opens[min(exit_bar, len(bd) - 1)]

        # ── BUG #1+#2+#6 FIX: New market impact model ──
        pc = precomp[asset]
        avg_vol = pc.avg_volume[min(entry_bar, len(pc.avg_volume) - 1)]
        bars_per_day = 1440.0 / bd.bar_minutes
        daily_vol_usd = avg_vol * bd.closes[entry_bar] * bars_per_day

        entry_impact = calc_market_impact(notional, daily_vol_usd, asset)
        actual_entry = signal_entry * (1 + entry_impact) if is_long else signal_entry * (1 - entry_impact)
        entry_fee = notional * TAKER_FEE_RATE

        # Ideal P&L (zero friction)
        if is_long:
            ideal_pnl = (signal_exit - signal_entry) / signal_entry * notional
        else:
            ideal_pnl = (signal_entry - signal_exit) / signal_entry * notional

        # Liquidation price
        mm = params["maint_margin"]
        if is_long:
            liq_price = actual_entry * (1.0 - 1.0 / lev + mm)
        else:
            liq_price = actual_entry * (1.0 + 1.0 / lev - mm)

        # ── BUG #5 FIX: Realistic funding rates ──
        funding_rate_8h = FUNDING_LONG_PER_8H if is_long else abs(FUNDING_SHORT_PER_8H)
        funding_per_bar = funding_rate_8h * (bd.bar_minutes / 480.0)

        # Bar-by-bar: funding + liquidation
        liquidated = False
        funding_cost = 0.0
        actual_exit_bar = exit_bar
        end_bar = min(exit_bar + 1, len(bd))
        for bi in range(entry_bar + 1, end_bar):
            funding_cost += notional * funding_per_bar
            if is_long and bd.lows[bi] <= liq_price:
                liquidated = True; actual_exit_bar = bi; break
            elif not is_long and bd.highs[bi] >= liq_price:
                liquidated = True; actual_exit_bar = bi; break

        bars_held = actual_exit_bar - entry_bar

        # ── Exit ──
        if liquidated:
            gross_pnl = -actual_margin
            liq_fee = notional * 0.005
            exit_fee = 0.0
            net_pnl = -actual_margin - entry_fee - liq_fee
            slippage = ideal_pnl - gross_pnl
        else:
            exit_avg_vol = pc.avg_volume[min(exit_bar, len(pc.avg_volume) - 1)]
            exit_daily_vol_usd = exit_avg_vol * bd.closes[min(exit_bar, len(bd)-1)] * bars_per_day

            exit_impact = calc_market_impact(notional, exit_daily_vol_usd, asset)
            actual_exit = signal_exit * (1 - exit_impact) if is_long else signal_exit * (1 + exit_impact)
            exit_fee = notional * TAKER_FEE_RATE

            if is_long:
                gross_pnl = (actual_exit - actual_entry) / actual_entry * notional
            else:
                gross_pnl = (actual_entry - actual_exit) / actual_entry * notional

            liq_fee = 0.0
            slippage = ideal_pnl - gross_pnl
            net_pnl = gross_pnl - entry_fee - exit_fee - funding_cost

        # Track open position
        open_positions.append({
            "actual_exit_bar": actual_exit_bar,
            "margin": actual_margin,
            "net_pnl": net_pnl,
        })

        # Yearly
        yearly[yr]["end"] = equity
        yearly[yr]["pnl"] += net_pnl
        yearly[yr]["trades"] += 1
        if liquidated: yearly[yr]["liqs"] += 1
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
            "bars_held": bars_held, "position_capped": position_capped,
            "entry_ts": t.get("entry_ts", ""), "exit_ts": t.get("exit_ts", ""),
            "impact_entry_bps": entry_impact * 10000,
        })

    # Close remaining
    for pos in open_positions:
        equity += pos["net_pnl"]
        equity = max(equity, 0)
        equity_curve.append(equity)
        peak_equity = max(peak_equity, equity)

    for yr in yearly:
        yearly[yr]["end"] = equity

    # Aggregates
    total_ideal = sum(r["ideal_pnl"] for r in results)
    total_slip = sum(r["slippage"] for r in results)
    total_fees = sum(r["entry_fee"] + r["exit_fee"] for r in results)
    total_fund = sum(r["funding_cost"] for r in results)
    total_liq = sum(r["liq_fee"] for r in results)
    total_friction = total_slip + total_fees + total_fund + total_liq

    peak = starting_equity; max_dd_pct = 0.0; max_dd_usd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        dd = peak - e; dd_pct = dd / peak * 100 if peak > 0 else 0
        if dd_pct > max_dd_pct: max_dd_pct = dd_pct; max_dd_usd = dd

    wins = sum(1 for r in results if r["net_pnl"] > 0)
    win_rate = wins / len(results) * 100 if results else 0
    gross_wins = sum(r["net_pnl"] for r in results if r["net_pnl"] > 0)
    gross_losses = abs(sum(r["net_pnl"] for r in results if r["net_pnl"] <= 0))
    pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
    sharpe = _sharpe(equity_curve)
    abs_ideal = abs(total_ideal) if total_ideal != 0 else 1
    fric_pct = total_friction / abs_ideal * 100
    peak_not = max((r["notional"] for r in results), default=0)
    liqs = sum(1 for r in results if r["liquidated"])
    long_pnl = sum(r["net_pnl"] for r in results if r["direction"] == "long")
    short_pnl = sum(r["net_pnl"] for r in results if r["direction"] == "short")

    return SimResult(
        initial_equity=starting_equity, final_equity=equity,
        net_pnl=equity - starting_equity,
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
        long_pnl=long_pnl, short_pnl=short_pnl, capped_trades=capped,
    )


def _sharpe(eq):
    if len(eq) < 3: return 0.0
    rets = [eq[i] / eq[i-1] - 1 for i in range(1, len(eq)) if eq[i-1] > 0]
    if len(rets) < 2: return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var) if var > 0 else 0
    return round(mean / std * math.sqrt(len(rets)), 2) if std > 0 else 0.0


# =============================================================================
# SWEEP DEFINITIONS
# =============================================================================

STARTING_EQUITIES = [1_000, 5_000, 10_000, 25_000, 50_000, 100_000]

LEVERAGE_OPTIONS = {
    "3x": 3.0, "5x": 5.0, "7x": 7.0, "10x": 10.0,
    "10/10/5": {"BTC": 10.0, "ETH": 10.0, "SOL": 5.0},
}

MAX_DEPLOY_OPTIONS = [0.50, 0.75, 1.00]


def build_sizing_configs():
    configs = []
    configs.append(("FR_d1K", {"sizing_method": "fixed_ratio", "base_margin": 125.0, "delta": 1000.0, "cap_n": 4, "long_frac": 0, "short_frac": 0}))
    configs.append(("PropFR", {"sizing_method": "proportional_fr", "long_frac": 0, "short_frac": 0}))
    for pct in [10, 25, 50, 75]:
        frac = pct / 100.0
        configs.append((f"PctEq_{pct}", {"sizing_method": "pct_equity", "long_frac": frac, "short_frac": frac}))
    configs.append(("PctEq_50_CB", {"sizing_method": "pct_equity", "long_frac": 0.50, "short_frac": 0.50, "circuit_breaker": True}))
    configs.append(("PctEq_50_Cap", {"sizing_method": "pct_equity", "long_frac": 0.50, "short_frac": 0.50, "position_cap": 50_000.0}))
    return configs


ASYMMETRIC_COMBOS = [
    ("50/50", 0.50, 0.50), ("50/25", 0.50, 0.25), ("50/10", 0.50, 0.10),
    ("50/5", 0.50, 0.05), ("75/25", 0.75, 0.25), ("75/10", 0.75, 0.10),
    ("25/25", 0.25, 0.25),
]

ASSET_PORTFOLIOS = {
    "BTC_only": ["BTC"], "BTC_ETH": ["BTC", "ETH"],
    "BTC_ETH_SOL": ["BTC", "ETH", "SOL"], "ETH_SOL": ["ETH", "SOL"],
}


# =============================================================================
# SWEEP RUNNER
# =============================================================================

def filter_trades(trade_log, period="training"):
    if period == "training":
        return [t for t in trade_log if t.get("entry_ts", "") < HOLDOUT_DATE]
    elif period == "holdout":
        return [t for t in trade_log if t.get("entry_ts", "") >= HOLDOUT_DATE]
    return trade_log


def run_one(trade_log, bar_data, precomp, sizing_cfg, leverage, start_eq, max_deploy):
    cfg = dict(sizing_cfg)
    cfg["initial_equity"] = start_eq
    cfg["leverage"] = leverage
    cfg["max_deployment_pct"] = max_deploy
    return simulate(trade_log, bar_data, precomp, cfg)


def run_full_sweep(trades_A, trades_B, bar_data, precomp):
    sizing_cfgs = build_sizing_configs()
    all_results = []
    total = 2 * len(sizing_cfgs) * len(LEVERAGE_OPTIONS) * len(STARTING_EQUITIES) * len(MAX_DEPLOY_OPTIONS)
    done = 0; t0 = time.time()

    for vlabel, tlog in [("L+S", trades_A), ("L-only", trades_B)]:
        for sz_label, sz_cfg in sizing_cfgs:
            for lev_label, lev_val in LEVERAGE_OPTIONS.items():
                for start_eq in STARTING_EQUITIES:
                    for max_dep in MAX_DEPLOY_OPTIONS:
                        sim = run_one(tlog, bar_data, precomp, sz_cfg, lev_val, start_eq, max_dep)
                        all_results.append({
                            "variant": vlabel, "sizing": sz_label, "leverage": lev_label,
                            "start_eq": start_eq, "max_deploy": max_dep,
                            "final_eq": sim.final_equity, "return_pct": sim.total_return_pct,
                            "sharpe": sim.sharpe, "mdd_pct": sim.max_drawdown_pct,
                            "pf": sim.profit_factor, "trades": sim.total_trades,
                            "liqs": sim.liquidations, "peak_notional": sim.peak_notional,
                            "friction_pct": sim.friction_pct_of_ideal, "win_rate": sim.win_rate,
                            "skipped": sim.skipped_trades, "capped": sim.capped_trades,
                            "long_pnl": sim.long_pnl, "short_pnl": sim.short_pnl,
                            "total_slippage": sim.total_slippage, "total_fees": sim.total_fees,
                            "total_funding": sim.total_funding, "total_liq_fees": sim.total_liq_fees,
                            "total_friction": sim.total_friction, "ideal_pnl": sim.ideal_gross_pnl,
                            "yearly": sim.yearly,
                        })
                        done += 1
                        if done % 200 == 0:
                            print(f"  [{done}/{total}] {time.time()-t0:.1f}s ...", file=sys.stderr)
    print(f"  Core sweep: {done} sims in {time.time()-t0:.1f}s", file=sys.stderr)
    return all_results


def run_asymmetric_sweep(trades_A, bar_data, precomp):
    results = []
    for label, long_f, short_f in ASYMMETRIC_COMBOS:
        cfg = {"sizing_method": "pct_equity", "long_frac": long_f, "short_frac": short_f}
        for lev_label, lev_val in LEVERAGE_OPTIONS.items():
            for start_eq in STARTING_EQUITIES:
                sim = run_one(trades_A, bar_data, precomp, cfg, lev_val, start_eq, 1.0)
                results.append({
                    "label": label, "long_frac": long_f, "short_frac": short_f,
                    "leverage": lev_label, "start_eq": start_eq,
                    "final_eq": sim.final_equity, "return_pct": sim.total_return_pct,
                    "sharpe": sim.sharpe, "mdd_pct": sim.max_drawdown_pct,
                    "trades": sim.total_trades, "liqs": sim.liquidations,
                    "long_pnl": sim.long_pnl, "short_pnl": sim.short_pnl,
                    "skipped": sim.skipped_trades, "capped": sim.capped_trades,
                })
    print(f"  Asymmetric: {len(results)} sims", file=sys.stderr)
    return results


def run_asset_sweep(trades_A, bar_data, precomp, best_sizing, best_lev):
    results = []
    for port_label, assets in ASSET_PORTFOLIOS.items():
        filtered_bd = {a: bar_data[a] for a in assets if a in bar_data}
        filtered_pc = {a: precomp[a] for a in assets if a in precomp}
        for start_eq in STARTING_EQUITIES:
            ftrades = [t for t in trades_A if t["asset"] in assets]
            sim = run_one(ftrades, filtered_bd, filtered_pc, best_sizing, best_lev, start_eq, 1.0)
            results.append({
                "portfolio": port_label, "start_eq": start_eq,
                "final_eq": sim.final_equity, "return_pct": sim.total_return_pct,
                "sharpe": sim.sharpe, "mdd_pct": sim.max_drawdown_pct,
                "trades": sim.total_trades, "liqs": sim.liquidations,
                "friction_pct": sim.friction_pct_of_ideal, "capped": sim.capped_trades,
            })
    return results


# =============================================================================
# FORMATTING
# =============================================================================

def fmt(v):
    if abs(v) >= 1e6: return f"${v/1e6:,.2f}M"
    elif abs(v) >= 1000: return f"${v:,.0f}"
    else: return f"${v:,.2f}"


def format_master_table(results, n_top=50, n_bot=10):
    lines = ["\n" + "=" * 150, "PHASE 3A — MASTER RESULTS (sorted by final equity, $25K start)", "=" * 150]
    r25 = sorted([r for r in results if r["start_eq"] == 25_000], key=lambda r: r["final_eq"], reverse=True)
    hdr = (f"  {'#':>3} │ {'Var':<6} │ {'Sizing':<13} │ {'Lev':<7} │ {'Dep':>4} │ "
           f"{'Final Eq':>12} │ {'Ret%':>8} │ {'CAGR':>6} │ {'Sh':>5} │ {'MDD%':>5} │ "
           f"{'Liq':>3} │ {'Cap':>3} │ {'Trds':>4} │ {'Fric%':>5}")
    lines.append(hdr)
    lines.append("  " + "─" * 145)
    for i, r in enumerate(r25[:n_top]):
        cagr = ((max(r["final_eq"], 1) / 25000) ** (1/5.2) - 1) * 100
        lines.append(
            f"  {i+1:>3} │ {r['variant']:<6} │ {r['sizing']:<13} │ {r['leverage']:<7} │ "
            f"{r['max_deploy']*100:>3.0f}% │ {fmt(r['final_eq']):>12} │ "
            f"{r['return_pct']:>7.0f}% │ {cagr:>5.0f}% │ {r['sharpe']:>5.2f} │ "
            f"{r['mdd_pct']:>4.1f}% │ {r['liqs']:>3} │ {r['capped']:>3} │ "
            f"{r['trades']:>4} │ {r['friction_pct']:>4.0f}%")
    if len(r25) > n_top + n_bot:
        lines.append(f"  ... ({len(r25) - n_top - n_bot} rows omitted) ...")
        for i, r in enumerate(r25[-n_bot:]):
            cagr = ((max(r["final_eq"], 1) / 25000) ** (1/5.2) - 1) * 100
            lines.append(
                f"  {len(r25)-n_bot+i+1:>3} │ {r['variant']:<6} │ {r['sizing']:<13} │ {r['leverage']:<7} │ "
                f"{r['max_deploy']*100:>3.0f}% │ {fmt(r['final_eq']):>12} │ "
                f"{r['return_pct']:>7.0f}% │ {cagr:>5.0f}% │ {r['sharpe']:>5.2f} │ "
                f"{r['mdd_pct']:>4.1f}% │ {r['liqs']:>3} │ {r['capped']:>3} │ "
                f"{r['trades']:>4} │ {r['friction_pct']:>4.0f}%")
    return "\n".join(lines)


def format_optimal_per_equity(results):
    lines = ["\n" + "=" * 80, "PHASE 3B — OPTIMAL CONFIG PER STARTING EQUITY", "=" * 80]
    for eq in STARTING_EQUITIES:
        req = [r for r in results if r["start_eq"] == eq]
        if not req: continue
        lines.append(f"\n  ${eq:,}:")
        best = max(req, key=lambda r: r["final_eq"])
        cagr = ((max(best["final_eq"], 1) / eq) ** (1/5.2) - 1) * 100
        lines.append(f"    Best equity: {best['variant']}/{best['sizing']}/{best['leverage']}/{best['max_deploy']*100:.0f}% "
                     f"→ {fmt(best['final_eq'])} ({cagr:.0f}% CAGR)")
        bsh = max(req, key=lambda r: r["sharpe"])
        lines.append(f"    Best Sharpe: {bsh['variant']}/{bsh['sizing']}/{bsh['leverage']} → Sharpe {bsh['sharpe']:.2f}")
        m30 = [r for r in req if r["mdd_pct"] < 30]
        if m30:
            b30 = max(m30, key=lambda r: r["sharpe"])
            lines.append(f"    Best Sh MDD<30%: {b30['variant']}/{b30['sizing']}/{b30['leverage']} "
                         f"→ Sh {b30['sharpe']:.2f}, MDD {b30['mdd_pct']:.1f}%")
        m50 = [r for r in req if r["mdd_pct"] < 50]
        if m50:
            b50 = max(m50, key=lambda r: r["final_eq"])
            c50 = ((max(b50["final_eq"], 1) / eq) ** (1/5.2) - 1) * 100
            lines.append(f"    Best eq MDD<50%: {b50['variant']}/{b50['sizing']}/{b50['leverage']} "
                         f"→ {fmt(b50['final_eq'])} ({c50:.0f}% CAGR), MDD {b50['mdd_pct']:.1f}%")
    return "\n".join(lines)


def format_leverage(results):
    lines = ["\n" + "=" * 100, "PHASE 3D — LEVERAGE COMPARISON ($25K, best sizing, L+S)", "=" * 100]
    r25 = [r for r in results if r["start_eq"] == 25_000 and r["variant"] == "L+S"]
    best = max(r25, key=lambda r: r["final_eq"])
    sz, dep = best["sizing"], best["max_deploy"]
    lines.append(f"  Sizing: {sz}, deploy: {dep*100:.0f}%")
    lines.append(f"  {'Lev':<10} │ {'Final':>12} │ {'CAGR':>6} │ {'Sharpe':>6} │ {'MDD%':>5} │ {'Liq':>3} │ {'Cap':>3} │ {'Fric%':>5}")
    lines.append(f"  {'─'*10}─┼─{'─'*12}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*5}─┼─{'─'*3}─┼─{'─'*3}─┼─{'─'*5}")
    for lev in LEVERAGE_OPTIONS:
        m = [r for r in r25 if r["leverage"] == lev and r["sizing"] == sz and r["max_deploy"] == dep]
        if m:
            r = m[0]; cagr = ((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
            lines.append(f"  {lev:<10} │ {fmt(r['final_eq']):>12} │ {cagr:>5.0f}% │ {r['sharpe']:>6.2f} │ "
                         f"{r['mdd_pct']:>4.1f}% │ {r['liqs']:>3} │ {r['capped']:>3} │ {r['friction_pct']:>4.0f}%")
    return "\n".join(lines)


def format_sizing(results):
    lines = ["\n" + "=" * 120, "PHASE 3E — SIZING METHOD COMPARISON ($25K, L+S)", "=" * 120]
    r25 = [r for r in results if r["start_eq"] == 25_000 and r["variant"] == "L+S"]
    best = max(r25, key=lambda r: r["final_eq"])
    lev, dep = best["leverage"], best["max_deploy"]
    lines.append(f"  Leverage: {lev}, deploy: {dep*100:.0f}%")
    lines.append(f"  {'Sizing':<15} │ {'Final':>12} │ {'CAGR':>6} │ {'Sh':>5} │ {'MDD%':>5} │ {'Liq':>3} │ {'Cap':>3} │ {'PeakNot':>10} │ {'Fric%':>5}")
    lines.append(f"  {'─'*15}─┼─{'─'*12}─┼─{'─'*6}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*3}─┼─{'─'*3}─┼─{'─'*10}─┼─{'─'*5}")
    for slbl, _ in build_sizing_configs():
        m = [r for r in r25 if r["sizing"] == slbl and r["leverage"] == lev and r["max_deploy"] == dep]
        if m:
            r = m[0]; cagr = ((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
            lines.append(f"  {slbl:<15} │ {fmt(r['final_eq']):>12} │ {cagr:>5.0f}% │ {r['sharpe']:>5.2f} │ "
                         f"{r['mdd_pct']:>4.1f}% │ {r['liqs']:>3} │ {r['capped']:>3} │ {fmt(r['peak_notional']):>10} │ {r['friction_pct']:>4.0f}%")
    return "\n".join(lines)


def format_headtohead(results):
    lines = ["\n" + "=" * 120, "PHASE 3C — LONGS+SHORTS vs LONG-ONLY", "=" * 120]
    for eq in STARTING_EQUITIES:
        ls = [r for r in results if r["start_eq"] == eq and r["variant"] == "L+S"]
        lo = [r for r in results if r["start_eq"] == eq and r["variant"] == "L-only"]
        if not ls or not lo: continue
        bls = max(ls, key=lambda r: r["final_eq"])
        blo = max(lo, key=lambda r: r["final_eq"])
        w = "L+S" if bls["final_eq"] > blo["final_eq"] else "L-only"
        lines.append(f"  ${eq:>7,}: L+S={fmt(bls['final_eq']):>12} MDD={bls['mdd_pct']:.0f}% │ "
                     f"L-only={fmt(blo['final_eq']):>12} MDD={blo['mdd_pct']:.0f}% │ Winner: {w}")
    return "\n".join(lines)


def format_cb(results):
    lines = ["\n" + "=" * 100, "PHASE 3F — CIRCUIT BREAKER", "=" * 100]
    for eq in STARTING_EQUITIES:
        nocb = [r for r in results if r["start_eq"]==eq and r["sizing"]=="PctEq_50" and r["variant"]=="L+S"]
        wcb = [r for r in results if r["start_eq"]==eq and r["sizing"]=="PctEq_50_CB" and r["variant"]=="L+S"]
        if nocb and wcb:
            bn = max(nocb, key=lambda r: r["final_eq"])
            bc = max(wcb, key=lambda r: r["final_eq"])
            lines.append(f"  ${eq:>7,}: No CB={fmt(bn['final_eq']):>12} MDD={bn['mdd_pct']:.0f}% │ "
                         f"CB={fmt(bc['final_eq']):>12} MDD={bc['mdd_pct']:.0f}%")
    return "\n".join(lines)


def format_assets(aresults):
    lines = ["\n" + "=" * 100, "PHASE 3G — ASSET PORTFOLIO ($25K)", "=" * 100]
    for r in aresults:
        if r["start_eq"] == 25_000:
            cagr = ((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
            lines.append(f"  {r['portfolio']:<15} │ {fmt(r['final_eq']):>12} │ {cagr:>5.0f}% CAGR │ "
                         f"Sh {r['sharpe']:.2f} │ MDD {r['mdd_pct']:.0f}% │ Cap {r['capped']}")
    return "\n".join(lines)


def format_asym(aresults):
    lines = ["\n" + "=" * 120, "PHASE 3H — ASYMMETRIC L/S SIZING ($25K)", "=" * 120]
    r25 = [r for r in aresults if r["start_eq"] == 25_000]
    if not r25: return ""
    best_lev = max(r25, key=lambda r: r["final_eq"])["leverage"]
    for r in r25:
        if r["leverage"] == best_lev:
            cagr = ((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
            lines.append(f"  {r['label']:<12} │ {fmt(r['final_eq']):>12} │ {cagr:>5.0f}% │ "
                         f"Sh {r['sharpe']:.2f} │ MDD {r['mdd_pct']:.0f}% │ "
                         f"Long={fmt(r['long_pnl'])} Short={fmt(r['short_pnl'])}")
    return "\n".join(lines)


def format_impact_table():
    lines = ["\n" + "=" * 100, "IMPACT ANALYSIS — Friction at each position size", "=" * 100]
    lines.append(f"  {'Notional':>12} │ {'BTC bps':>8} │ {'ETH bps':>8} │ {'SOL bps':>8} │ {'BTC RT$':>10} │ {'ETH RT$':>10} │ {'SOL RT$':>10}")
    lines.append(f"  {'─'*12}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*10}─┼─{'─'*10}─┼─{'─'*10}")
    for size in [1250, 12500, 125000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000]:
        bps = {}; rt = {}
        for asset in ["BTC", "ETH", "SOL"]:
            imp = calc_market_impact(size, 3e9 if asset=="BTC" else 1.5e9 if asset=="ETH" else 500e6, asset)
            bps[asset] = imp * 10000
            rt[asset] = size * imp * 2
        lines.append(f"  ${size:>11,} │ {bps['BTC']:>7.1f} │ {bps['ETH']:>7.1f} │ {bps['SOL']:>7.1f} │ "
                     f"${rt['BTC']:>9,.0f} │ ${rt['ETH']:>9,.0f} │ ${rt['SOL']:>9,.0f}")

    # Capacity ceiling: where RT friction > avg trade profit
    # Avg trade profit at flat: $91 on $1,250 notional = 7.25% of notional
    lines.append(f"\n  CAPACITY CEILING (where RT friction > avg trade profit of 7.25% of notional):")
    for asset in ["BTC", "ETH", "SOL"]:
        dvol = 3e9 if asset == "BTC" else 1.5e9 if asset == "ETH" else 500e6
        for size in range(100_000, 50_000_001, 100_000):
            imp = calc_market_impact(size, dvol, asset)
            rt_pct = imp * 2
            if rt_pct > 0.0725:
                lines.append(f"    {asset}: ${size:,} (RT friction {rt_pct*100:.1f}% > 7.25% avg profit)")
                break
    return "\n".join(lines)


def format_yearly(yearly, label):
    lines = [f"\n  {label}:"]
    lines.append(f"  {'Year':<6} │ {'Start':>12} │ {'End':>12} │ {'P&L':>12} │ {'Ret':>7} │ {'Trds':>4} │ {'Liq':>3}")
    for yr in sorted(yearly):
        y = yearly[yr]; s = y["start"] if y["start"] else 25000
        ret = y["pnl"] / s * 100 if s > 0 else 0
        lines.append(f"  {yr:<6} │ {fmt(s):>12} │ {fmt(y['end']):>12} │ {fmt(y['pnl']):>12} │ "
                     f"{ret:>6.1f}% │ {y['trades']:>4} │ {y['liqs']:>3}")
    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================

def main():
    T0 = time.time()
    report = []
    def log(s): print(s); report.append(s)

    log("=" * 80)
    log("  DEFINITIVE CONFIG SWEEP v2 — ALL 6 BUGS FIXED")
    log(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log("=" * 80)

    # ── Load ──
    log("\n[LOAD] Trade logs + bar data...")
    with open("/tmp/discovery/sweep_tradelog_A.json") as f: data_A = json.load(f)
    with open("/tmp/discovery/sweep_tradelog_B.json") as f: data_B = json.load(f)
    train_A = filter_trades(data_A["trade_log"], "training")
    train_B = filter_trades(data_B["trade_log"], "training")
    log(f"  L+S: {len(train_A)} training trades | L-only: {len(train_B)} training trades")

    bar_data = {}
    for asset in ["BTC", "ETH", "SOL"]:
        bar_data[asset] = load_bar_data(asset, "15m")
    precomp = precompute(bar_data)
    log("  Bar data and precompute done.")

    # ── Impact table ──
    log(format_impact_table())

    # ── Sanity check ──
    log("\n" + "=" * 80)
    log("STEP 2 — SANITY CHECKS")
    log("=" * 80)

    # Check 1: PctEq_50, 10/10/5, $25K, L+S
    cfg = {"sizing_method": "pct_equity", "long_frac": 0.50, "short_frac": 0.50}
    sim = run_one(train_A, bar_data, precomp, cfg, {"BTC":10.0,"ETH":10.0,"SOL":5.0}, 25_000, 1.0)
    log(f"\n  PctEq_50 / 10/10/5 / $25K / L+S:")
    log(f"    Final: {fmt(sim.final_equity)} | CAGR: {((sim.final_equity/25000)**(1/5.2)-1)*100:.0f}%")
    log(f"    Trades: {sim.total_trades} | Skipped: {sim.skipped_trades} | Capped: {sim.capped_trades}")
    log(f"    Liqs: {sim.liquidations} | MDD: {sim.max_drawdown_pct:.1f}% | Peak not: {fmt(sim.peak_notional)}")
    log(f"    Friction: {sim.friction_pct_of_ideal:.0f}% of ideal")

    # Print sample trades
    log(f"    {'#':>4} │ {'Equity':>10} │ {'Margin':>10} │ {'Notional':>10} │ {'Asset':<4} │ {'Imp bps':>7} │ {'Net P&L':>10}")
    for i, tr in enumerate(sim.trades):
        if i < 5 or i in [9, 19, 49, 99, 149] or i == len(sim.trades) - 1:
            log(f"    {i+1:>4} │ ${tr.get('margin',0)*2:>9,.0f} │ ${tr['margin']:>9,.0f} │ ${tr['notional']:>9,.0f} │ "
                f"{tr['asset']:<4} │ {tr.get('impact_entry_bps',0):>6.1f} │ ${tr['net_pnl']:>9,.0f}"
                f"{'  ← CAPPED' if tr.get('position_capped') else ''}")

    # Check 2: FR_d1K control
    cfg2 = {"sizing_method": "fixed_ratio", "base_margin": 125.0, "delta": 1000.0, "cap_n": 4, "long_frac": 0, "short_frac": 0}
    sim2 = run_one(train_A, bar_data, precomp, cfg2, {"BTC":10.0,"ETH":10.0,"SOL":5.0}, 25_000, 1.0)
    log(f"\n  FR_d1K CONTROL: {fmt(sim2.final_equity)} (was ~$59K before — "
        f"{'PASS' if 40_000 < sim2.final_equity < 80_000 else 'INVESTIGATE'})")

    # ── Full sweep ──
    log("\n[SWEEP] Running full sweep...")
    all_results = run_full_sweep(train_A, train_B, bar_data, precomp)

    log("\n[ASYM] Running asymmetric L/S sweep...")
    asym_results = run_asymmetric_sweep(train_A, bar_data, precomp)

    log("\n[ASSETS] Running asset portfolio sweep...")
    r25 = [r for r in all_results if r["start_eq"] == 25_000 and r["variant"] == "L+S"]
    best_core = max(r25, key=lambda r: r["final_eq"])
    best_sz_cfg = next(c for l, c in build_sizing_configs() if l == best_core["sizing"])
    asset_results = run_asset_sweep(train_A, bar_data, precomp, best_sz_cfg, LEVERAGE_OPTIONS[best_core["leverage"]])

    # ── Results ──
    log("\n" + "=" * 80)
    log("  PHASE 3 — RESULTS")
    log("=" * 80)

    log(format_master_table(all_results))
    log(format_optimal_per_equity(all_results))
    log(format_headtohead(all_results))
    log(format_leverage(all_results))
    log(format_sizing(all_results))
    log(format_cb(all_results))
    log(format_assets(asset_results))
    log(format_asym(asym_results))

    # Year-by-year top 3
    log("\n" + "=" * 80)
    log("PHASE 3I — YEAR-BY-YEAR (top 3 at $25K)")
    log("=" * 80)
    r25_sorted = sorted([r for r in all_results if r["start_eq"]==25_000], key=lambda r: r["final_eq"], reverse=True)
    for i, r in enumerate(r25_sorted[:3]):
        if r.get("yearly"):
            log(format_yearly(r["yearly"], f"#{i+1}: {r['variant']}/{r['sizing']}/{r['leverage']}/{r['max_deploy']*100:.0f}%"))

    # Holdout
    log("\n" + "=" * 80)
    log("PHASE 3J — HOLDOUT VALIDATION ($25K start)")
    log("=" * 80)
    all_sz = build_sizing_configs()
    for i, r in enumerate(r25_sorted[:5]):
        sz_cfg = next(c for l, c in all_sz if l == r["sizing"])
        lev_val = LEVERAGE_OPTIONS[r["leverage"]]
        vt = data_A["trade_log"] if r["variant"] == "L+S" else data_B["trade_log"]
        htrades = filter_trades(vt, "holdout")
        if htrades:
            hsim = run_one(htrades, bar_data, precomp, sz_cfg, lev_val, 25_000, r["max_deploy"])
            cagr_t = ((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
            log(f"  #{i+1} {r['variant']}/{r['sizing']}/{r['leverage']}: "
                f"Train={fmt(r['final_eq'])} ({cagr_t:.0f}%CAGR) → Hold={fmt(hsim.final_equity)} "
                f"({hsim.total_return_pct:.0f}%) MDD={hsim.max_drawdown_pct:.0f}%")

    # Cost breakdown top 3
    log("\n" + "=" * 80)
    log("PHASE 3K — COST BREAKDOWN (top 3 at $25K)")
    log("=" * 80)
    for i, r in enumerate(r25_sorted[:3]):
        ideal = r["ideal_pnl"]; ai = abs(ideal) if ideal != 0 else 1
        log(f"\n  #{i+1}: {r['variant']}/{r['sizing']}/{r['leverage']}")
        log(f"    Ideal P&L:       {fmt(ideal)}")
        log(f"    - Slippage:      {fmt(r['total_slippage'])} ({r['total_slippage']/ai*100:.1f}%)")
        log(f"    - Fees:          {fmt(r['total_fees'])} ({r['total_fees']/ai*100:.1f}%)")
        log(f"    - Funding:       {fmt(r['total_funding'])} ({r['total_funding']/ai*100:.1f}%)")
        log(f"    - Liq fees:      {fmt(r['total_liq_fees'])}")
        log(f"    = Net P&L:       {fmt(r['final_eq'] - r['start_eq'])}")
        log(f"    Friction:        {r['friction_pct']:.0f}% of ideal")

    # ── Reality check ──
    log("\n" + "=" * 80)
    log("REALITY CHECK")
    log("=" * 80)
    best25 = r25_sorted[0]
    best_cagr = ((max(best25["final_eq"],1)/25000)**(1/5.2)-1)*100
    over50m = any(r["final_eq"] > 50_000_000 for r in all_results if r["start_eq"] == 25_000)
    log(f"  1. Any $25K config > $50M?        {'YES ← investigate' if over50m else 'NO ✓'}")
    log(f"  2. Best CAGR under 200%?          {'YES ✓' if best_cagr < 200 else 'NO ← '+str(int(best_cagr))+'%'}")
    log(f"  3. FR_d1K matches old (~$59K)?    {fmt(sim2.final_equity)} {'✓' if 40_000 < sim2.final_equity < 80_000 else '← CHECK'}")
    log(f"  4. Impact >100bps at pos limit?   BTC@$10M={calc_market_impact(10e6,3e9,'BTC')*10000:.0f}bps {'✓' if calc_market_impact(10e6,3e9,'BTC')*10000>100 else '← NO'}")
    log(f"  5. Trades being size-capped?       {best25['capped']} capped {'✓' if best25['capped']>5 else '← few'}")
    pct10 = max([r for r in all_results if r["start_eq"]==25_000 and r["sizing"]=="PctEq_10"], key=lambda r:r["final_eq"], default={"final_eq":1})
    pct50 = max([r for r in all_results if r["start_eq"]==25_000 and r["sizing"]=="PctEq_50"], key=lambda r:r["final_eq"], default={"final_eq":1})
    ratio = pct50["final_eq"] / pct10["final_eq"] if pct10["final_eq"] > 0 else 999
    log(f"  6. PctEq_50/PctEq_10 ratio?       {ratio:.1f}x {'✓ reasonable' if ratio < 10 else '← too wide'}")

    # ── Definitive answer ──
    log("\n" + "=" * 80)
    log("  CORRECTED DEFINITIVE CONFIGURATION")
    log("=" * 80)

    best = max([r for r in all_results if r["start_eq"]==25_000], key=lambda r: r["final_eq"])
    cagr = ((max(best["final_eq"],1)/25000)**(1/5.2)-1)*100
    log(f"\n  MOST PROFITABLE AT $25,000:")
    log(f"    Strategy: {best['variant']} | Sizing: {best['sizing']} | Lev: {best['leverage']} | Deploy: {best['max_deploy']*100:.0f}%")
    log(f"    Training: $25,000 → {fmt(best['final_eq'])} ({cagr:.0f}% CAGR)")
    log(f"    MDD: {best['mdd_pct']:.1f}% | Liqs: {best['liqs']} | Capped trades: {best['capped']}")
    log(f"    Peak notional: {fmt(best['peak_notional'])}")
    log(f"    Friction: {best['friction_pct']:.0f}% of ideal P&L")

    m50 = [r for r in all_results if r["start_eq"]==25_000 and r["mdd_pct"]<50]
    if m50:
        b50 = max(m50, key=lambda r: r["final_eq"])
        c50 = ((max(b50["final_eq"],1)/25000)**(1/5.2)-1)*100
        log(f"\n  BEST MDD<50%: {b50['variant']}/{b50['sizing']}/{b50['leverage']} → {fmt(b50['final_eq'])} ({c50:.0f}% CAGR) MDD={b50['mdd_pct']:.1f}%")

    m30 = [r for r in all_results if r["start_eq"]==25_000 and r["mdd_pct"]<30]
    if m30:
        b30 = max(m30, key=lambda r: r["final_eq"])
        c30 = ((max(b30["final_eq"],1)/25000)**(1/5.2)-1)*100
        log(f"  BEST MDD<30%: {b30['variant']}/{b30['sizing']}/{b30['leverage']} → {fmt(b30['final_eq'])} ({c30:.0f}% CAGR) MDD={b30['mdd_pct']:.1f}%")

    r1k = [r for r in all_results if r["start_eq"]==1_000]
    if r1k:
        b1k = max(r1k, key=lambda r: r["final_eq"])
        cur = [r for r in r1k if r["sizing"]=="FR_d1K" and r["leverage"]=="10/10/5"]
        cur_eq = max(cur, key=lambda r:r["final_eq"])["final_eq"] if cur else 0
        log(f"\n  AT $1,000: Best={fmt(b1k['final_eq'])} ({b1k['variant']}/{b1k['sizing']}/{b1k['leverage']})")
        log(f"    Current FR_d1K/10/10/5: {fmt(cur_eq)}")

    # Key findings
    ls_best = max([r for r in all_results if r["start_eq"]==25_000 and r["variant"]=="L+S"], key=lambda r:r["final_eq"], default=None)
    lo_best = max([r for r in all_results if r["start_eq"]==25_000 and r["variant"]=="L-only"], key=lambda r:r["final_eq"], default=None)
    log(f"\n  KEY FINDINGS:")
    if ls_best and lo_best:
        w = "L+S" if ls_best["final_eq"] > lo_best["final_eq"] else "L-only"
        log(f"    1. {w} wins: L+S={fmt(ls_best['final_eq'])} vs L-only={fmt(lo_best['final_eq'])}")
    log(f"    2. Optimal leverage: {best['leverage']}")
    log(f"    3. Optimal sizing: {best['sizing']}")
    a25 = [r for r in asym_results if r["start_eq"]==25_000]
    if a25:
        ba = max(a25, key=lambda r: r["final_eq"])
        log(f"    4. Optimal L/S split: {ba['label']} → {fmt(ba['final_eq'])}")
    ap25 = [r for r in asset_results if r["start_eq"]==25_000]
    if ap25:
        bp = max(ap25, key=lambda r: r["final_eq"])
        log(f"    5. Optimal assets: {bp['portfolio']} → {fmt(bp['final_eq'])}")

    # Save
    output = {
        "generated": time.strftime('%Y-%m-%d %H:%M:%S UTC'),
        "version": "v2_all_bugs_fixed",
        "fixes": ["sigmoid_removed", "k_recalibrated", "position_limits_realistic",
                   "concurrent_positions", "funding_realistic", "order_splitting"],
        "params": {
            "BTC": ASSET_PARAMS["BTC"], "ETH": ASSET_PARAMS["ETH"], "SOL": ASSET_PARAMS["SOL"],
            "funding_long_8h": FUNDING_LONG_PER_8H, "funding_short_8h": FUNDING_SHORT_PER_8H,
        },
        "all_results": all_results, "asymmetric_results": asym_results,
        "asset_results": asset_results,
    }
    with open("/tmp/discovery/definitive_config_sweep_v2.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    elapsed = time.time() - T0
    log(f"\n  Runtime: {elapsed:.1f}s")
    log(f"  Saved to /tmp/discovery/definitive_config_sweep_v2.json")

    with open("/tmp/discovery/definitive_sweep_v2_report.txt", "w") as f:
        f.write("\n".join(report))


if __name__ == "__main__":
    main()
