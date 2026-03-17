#!/usr/bin/env python3
"""Stress tests and bias checks for Finalist B."""
import sys, json, time, copy
import numpy as np
sys.path.insert(0, 'addons')
from backtest import *

start_time = time.time()

# ======================================================================
# PART 7 FIRST: Try to fetch maximum historical data
# ======================================================================
print("=" * 120)
print("PART 7: MAXIMUM HISTORICAL DATA")
print("=" * 120)

# Try progressively larger windows to find the limit
print("\n  Testing how far back Hyperliquid 15m data goes...")
import requests as req

test_days = [180, 365, 540, 730, 1000]
for d in test_days:
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (d * 86400000)
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": "BTC", "interval": "15m", "startTime": start_ms, "endTime": start_ms + 500 * 15 * 60000},
    }
    try:
        resp = req.post("https://api.hyperliquid.xyz/info", json=payload, timeout=15)
        batch = resp.json()
        if batch and len(batch) > 0:
            first_date = datetime.fromtimestamp(batch[0]["t"] / 1000, tz=timezone.utc)
            print(f"    {d} days ago: GOT DATA, first candle = {first_date.strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"    {d} days ago: NO DATA")
    except Exception as e:
        print(f"    {d} days ago: ERROR {e}")
    time.sleep(0.3)

# Delete cache to force refetch with max days
cache_15m = DATA_DIR / "BTC_15m_candles.json"
if cache_15m.exists():
    cache_15m.unlink()
    print("\n  Cleared 15m cache, refetching with maximum range...")

data = load_all_data(days=730)  # Try 2 years
n = len(data["15m"])
days_span = (data["15m"][-1]["t"] - data["15m"][0]["t"]) / 86400000 if n > 1 else 0
first_date = datetime.fromtimestamp(data["15m"][0]["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
last_date = datetime.fromtimestamp(data["15m"][-1]["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
print(f"\n  RESULT: {n} bars spanning {days_span:.0f} days ({first_date} to {last_date})")

# ======================================================================
# Define Finalist B
# ======================================================================
finalist_b = SimConfig(
    atr_period=9, multiplier=3.0, source="hl2",
    rsi_enabled=True, rsi_period=7, rsi_buy_min=40, rsi_buy_max=70,
    rsi_sell_max=60, rsi_sell_min=20,
    trailing_supertrend=True,
)

finalist_b_no_trail = SimConfig(
    atr_period=9, multiplier=3.0, source="hl2",
    rsi_enabled=True, rsi_period=7, rsi_buy_min=40, rsi_buy_max=70,
    rsi_sell_max=60, rsi_sell_min=20,
    trailing_supertrend=False,
)

# Run baseline on full (possibly expanded) data
print("\n  Running Finalist B on full dataset...")
base_r = run_simulation(finalist_b, data, 0, n)
base_no_trail = run_simulation(finalist_b_no_trail, data, 0, n)

def print_stats(label, r):
    print(f"    {label:<40} Tr={r.total_trades:>4} WR={r.win_rate:>5.1f}% PF={r.profit_factor:>6.2f} PnL=${r.net_pnl:>9.2f} DD={r.max_drawdown_pct:>5.1f}% Sharpe={r.sharpe_ratio:>5.2f}")

print_stats("Finalist B (with trail)", base_r)
print_stats("Finalist B (no trail)", base_no_trail)

# ======================================================================
# PART 1: SINGLE TRADE SENSITIVITY
# ======================================================================
print(f"\n{'=' * 120}")
print("PART 1: SINGLE TRADE SENSITIVITY")
print(f"{'=' * 120}")

if base_r.trades:
    pnls = sorted([t["pnl"] for t in base_r.trades], reverse=True)
    total_pnl = sum(pnls)

    print(f"\n  Total P&L: ${total_pnl:.2f} across {len(pnls)} trades")
    print(f"\n  Top 10 individual trade P&Ls:")
    for i, p in enumerate(pnls[:10]):
        pct = p / total_pnl * 100
        print(f"    #{i+1}: ${p:>9.2f}  ({pct:>5.1f}% of total P&L)")

    print(f"\n  Bottom 5 (worst trades):")
    for i, p in enumerate(pnls[-5:]):
        print(f"    #{len(pnls)-4+i}: ${p:>9.2f}")

    # Remove top 1
    without_1 = total_pnl - pnls[0]
    # Remove top 3
    without_3 = total_pnl - sum(pnls[:3])
    # Remove top 5
    without_5 = total_pnl - sum(pnls[:5])
    # Remove top 1 AND bottom 1
    without_extremes = total_pnl - pnls[0] - pnls[-1]

    print(f"\n  Sensitivity analysis:")
    print(f"    Full P&L:                    ${total_pnl:>9.2f}")
    print(f"    Remove #1 winner (${pnls[0]:.0f}):  ${without_1:>9.2f}  {'PROFITABLE' if without_1 > 0 else 'UNPROFITABLE'}")
    print(f"    Remove top 3 winners:        ${without_3:>9.2f}  {'PROFITABLE' if without_3 > 0 else 'UNPROFITABLE'}")
    print(f"    Remove top 5 winners:        ${without_5:>9.2f}  {'PROFITABLE' if without_5 > 0 else 'UNPROFITABLE'}")
    print(f"    Remove top+bottom 1:         ${without_extremes:>9.2f}  {'PROFITABLE' if without_extremes > 0 else 'UNPROFITABLE'}")

    # Concentration metrics
    top1_pct = pnls[0] / total_pnl * 100 if total_pnl > 0 else 0
    top3_pct = sum(pnls[:3]) / total_pnl * 100 if total_pnl > 0 else 0
    top5_pct = sum(pnls[:5]) / total_pnl * 100 if total_pnl > 0 else 0
    print(f"\n  P&L concentration:")
    print(f"    Top 1 trade: {top1_pct:.1f}% of total P&L")
    print(f"    Top 3 trades: {top3_pct:.1f}% of total P&L")
    print(f"    Top 5 trades: {top5_pct:.1f}% of total P&L")

    # What % of trades are profitable?
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]
    print(f"\n  Distribution:")
    print(f"    Winners: {len(winners)} trades, total ${sum(winners):.2f}, avg ${np.mean(winners):.2f}")
    print(f"    Losers:  {len(losers)} trades, total ${sum(losers):.2f}, avg ${np.mean(losers):.2f}")
    print(f"    Median trade P&L: ${np.median(pnls):.2f}")

    # Also do same analysis for no-trail version
    if base_no_trail.trades:
        pnls_nt = sorted([t["pnl"] for t in base_no_trail.trades], reverse=True)
        total_nt = sum(pnls_nt)
        without_1_nt = total_nt - pnls_nt[0]
        without_3_nt = total_nt - sum(pnls_nt[:3])
        print(f"\n  Same analysis for NO-TRAIL version:")
        print(f"    Full P&L:             ${total_nt:>9.2f} ({len(pnls_nt)} trades)")
        print(f"    Remove #1 winner:     ${without_1_nt:>9.2f}  {'PROFITABLE' if without_1_nt > 0 else 'UNPROFITABLE'}")
        print(f"    Remove top 3:         ${without_3_nt:>9.2f}  {'PROFITABLE' if without_3_nt > 0 else 'UNPROFITABLE'}")
        top1_pct_nt = pnls_nt[0] / total_nt * 100 if total_nt > 0 else 0
        print(f"    Top 1 concentration:  {top1_pct_nt:.1f}%")

# ======================================================================
# PART 2: LOOK-AHEAD BIAS CHECK
# ======================================================================
print(f"\n{'=' * 120}")
print("PART 2: LOOK-AHEAD BIAS CHECK")
print(f"{'=' * 120}")

print("""
  THE ISSUE: The trailing ST stop checks if bar_low < st_line on each 15m bar.

  With OHLC data, we know the bar's low but NOT when during the bar it occurred.
  Possible sequences within a bar:
    A) Open -> High -> Low -> Close (low happens late, we'd see it before close)
    B) Open -> Low -> High -> Close (low happens early, we'd catch it in real-time)
    C) Open -> drop to Low -> bounce to High -> settle at Close

  The backtest assumes we EXIT at the Supertrend line price when low < st_line.
  In reality:
    - We poll price every few seconds in the bot
    - Price could gap through the ST line (slippage)
    - We might not catch the exact ST line price

  BIAS: The exit price is assumed to be exactly st_line[i], but real execution
  would be at whatever price we detect the cross. This is OPTIMISTIC — real exits
  would typically be slightly worse than st_line.

  MITIGATION: The 0.005% slippage model partially accounts for this, but may
  be insufficient for fast-moving bars.

  CONCLUSION: There IS mild look-ahead bias in the trailing stop. The standard
  Supertrend exit (exit on flip at next bar's open) has ZERO look-ahead bias.
""")

print_stats("WITH trailing stop (mild bias)", base_r)
print_stats("WITHOUT trailing stop (zero bias)", base_no_trail)
diff = base_r.net_pnl - base_no_trail.net_pnl
print(f"\n    Trailing stop adds: ${diff:>+.2f} P&L, {base_r.total_trades - base_no_trail.total_trades:+d} trades")

# ======================================================================
# PART 3: FUNDING RATE ANALYSIS
# ======================================================================
print(f"\n{'=' * 120}")
print("PART 3: FUNDING RATE ANALYSIS")
print(f"{'=' * 120}")

# Check actual funding data
funding = data.get("funding", [])
if funding:
    rates = [f["rate"] for f in funding]
    print(f"\n  Actual Hyperliquid funding data: {len(funding)} entries")
    print(f"    Mean rate per 8h:    {np.mean(rates)*100:.4f}%")
    print(f"    Median rate per 8h:  {np.median(rates)*100:.4f}%")
    print(f"    Std dev:             {np.std(rates)*100:.4f}%")
    print(f"    Min:                 {min(rates)*100:.4f}%")
    print(f"    Max:                 {max(rates)*100:.4f}%")
    print(f"    % positive (longs pay): {sum(1 for r in rates if r > 0)/len(rates)*100:.1f}%")
else:
    print("\n  No actual funding data available")

# The backtest currently uses FUNDING_RATE_PER_8H = 0.0001 (0.01%) as a flat estimate.
# Let's test sensitivity to funding rate
print(f"\n  Current model: flat 0.01% per 8h for longs, -0.01% for shorts")
print(f"  Sensitivity to different funding rate assumptions:")

# We need to modify the global FUNDING_RATE_PER_8H and rerun
import backtest as bt
original_rate = bt.FUNDING_RATE_PER_8H

for rate_pct in [0.0, 0.01, 0.02, 0.05, 0.10]:
    bt.FUNDING_RATE_PER_8H = rate_pct / 100
    r = run_simulation(finalist_b, data, 0, n)
    funding_cost = r.total_funding
    print(f"    Rate {rate_pct:.2f}%/8h: PnL=${r.net_pnl:>9.2f}  Funding cost=${funding_cost:>7.2f}  PF={r.profit_factor:.2f}  {'PROFITABLE' if r.net_pnl > 0 else 'BREAK-EVEN' if abs(r.net_pnl) < 10 else 'UNPROFITABLE'}")

bt.FUNDING_RATE_PER_8H = original_rate

# ======================================================================
# PART 4: VARIABLE SLIPPAGE
# ======================================================================
print(f"\n{'=' * 120}")
print("PART 4: VARIABLE SLIPPAGE SENSITIVITY")
print(f"{'=' * 120}")

original_slippage = bt.SLIPPAGE
print(f"\n  Current slippage model: {bt.SLIPPAGE*100:.3f}%")

for slip_pct in [0.005, 0.01, 0.02, 0.05, 0.10, 0.15, 0.20]:
    bt.SLIPPAGE = slip_pct / 100
    r = run_simulation(finalist_b, data, 0, n)
    label = ""
    if abs(slip_pct - 0.005) < 0.001: label = " (current)"
    elif abs(slip_pct - 0.01) < 0.001: label = " (2x)"
    elif abs(slip_pct - 0.02) < 0.001: label = " (4x)"
    elif abs(slip_pct - 0.05) < 0.001: label = " (10x)"
    elif abs(slip_pct - 0.10) < 0.001: label = " (20x)"
    print(f"    Slippage {slip_pct:.3f}%{label:<12}: PnL=${r.net_pnl:>9.2f}  Fees+Slip=${r.total_fees:>7.2f}  PF={r.profit_factor:.2f}  {'PROFITABLE' if r.net_pnl > 0 else 'BREAK-EVEN' if abs(r.net_pnl) < 10 else 'UNPROFITABLE'}")

bt.SLIPPAGE = original_slippage

# Also test no-trail with variable slippage
print(f"\n  Same for NO-TRAIL version:")
for slip_pct in [0.005, 0.01, 0.02, 0.05, 0.10]:
    bt.SLIPPAGE = slip_pct / 100
    r = run_simulation(finalist_b_no_trail, data, 0, n)
    label = ""
    if abs(slip_pct - 0.005) < 0.001: label = " (current)"
    elif abs(slip_pct - 0.01) < 0.001: label = " (2x)"
    elif abs(slip_pct - 0.02) < 0.001: label = " (4x)"
    elif abs(slip_pct - 0.05) < 0.001: label = " (10x)"
    print(f"    Slippage {slip_pct:.3f}%{label:<12}: PnL=${r.net_pnl:>9.2f}  PF={r.profit_factor:.2f}  {'PROFITABLE' if r.net_pnl > 0 else 'UNPROFITABLE'}")

bt.SLIPPAGE = original_slippage

# ======================================================================
# PART 5: EXECUTION DELAY
# ======================================================================
print(f"\n{'=' * 120}")
print("PART 5: EXECUTION DELAY SENSITIVITY")
print(f"{'=' * 120}")

print(f"\n  Current model: execute on next bar's open (1 bar delay = 15 min)")
print(f"  Testing additional delays...")

# We need to modify the execution logic. The simplest way is to shift the
# opens array we use for execution. In the backtest, entry is at opens[i+1].
# To add N bars delay, we use opens[i+1+N].
# Let's create modified versions by adjusting the entry index.

candles = data["15m"]
timestamps_arr = np.array([c["t"] for c in candles])
opens_arr = np.array([c["o"] for c in candles])
closes_arr = np.array([c["c"] for c in candles])

# Rerun with different delays by creating offset open arrays
for delay_bars in [0, 1, 2, 4, 8]:
    total_delay_min = (delay_bars + 1) * 15  # +1 because baseline already has 1 bar delay

    # Create modified candle data with shifted opens for execution
    # Simplest: modify the simulation to use opens[i+1+delay] instead of opens[i+1]
    # We'll do this by creating a wrapper
    modified_candles = []
    for i, c in enumerate(candles):
        mc = dict(c)
        # Shift the "next bar open" used for execution by delay_bars
        exec_idx = i + 1 + delay_bars
        if exec_idx < len(candles):
            mc["_exec_open"] = candles[exec_idx]["o"]
        else:
            mc["_exec_open"] = c["c"]
        modified_candles.append(mc)

    # Since we can't easily modify run_simulation, let's use a different approach:
    # Run the simulation and then retroactively recalculate P&L with delayed entry prices
    r = run_simulation(finalist_b, data, 0, n)

    if delay_bars == 0:
        print_stats(f"  Delay 0 extra bars (15min total)", r)
        continue

    # For each trade, find what the entry price would have been with extra delay
    adjusted_pnl = 0
    adjusted_trades = 0
    for t in r.trades:
        entry_t = t["entry_time"]
        # Find bar index
        idx = np.searchsorted(timestamps_arr, entry_t)
        delayed_idx = idx + delay_bars
        if delayed_idx >= len(candles):
            continue
        delayed_entry = opens_arr[delayed_idx]
        original_exit = t["exit_price"]
        size = t["size"]
        direction = t["direction"]

        if direction == 1:
            pnl = size * (original_exit - delayed_entry) / delayed_entry
        else:
            pnl = size * (delayed_entry - original_exit) / delayed_entry

        fee = size * (TAKER_FEE + SLIPPAGE) * 2  # entry + exit
        adjusted_pnl += pnl - fee
        adjusted_trades += 1

    total_delay = total_delay_min
    status = "PROFITABLE" if adjusted_pnl > 0 else "UNPROFITABLE"
    cost = base_r.net_pnl - adjusted_pnl
    print(f"    Delay +{delay_bars} bars ({total_delay}min total): PnL=${adjusted_pnl:>9.2f}  Cost of delay: ${cost:>+9.2f}  {status}")

# Same for no-trail
print(f"\n  Same for NO-TRAIL version:")
r_nt = run_simulation(finalist_b_no_trail, data, 0, n)
for delay_bars in [1, 2, 4]:
    adjusted_pnl = 0
    for t in r_nt.trades:
        entry_t = t["entry_time"]
        idx = np.searchsorted(timestamps_arr, entry_t)
        delayed_idx = idx + delay_bars
        if delayed_idx >= len(candles):
            continue
        delayed_entry = opens_arr[delayed_idx]
        original_exit = t["exit_price"]
        size = t["size"]
        direction = t["direction"]
        if direction == 1:
            pnl = size * (original_exit - delayed_entry) / delayed_entry
        else:
            pnl = size * (delayed_entry - original_exit) / delayed_entry
        fee = size * (TAKER_FEE + SLIPPAGE) * 2
        adjusted_pnl += pnl - fee

    total_delay = (delay_bars + 1) * 15
    cost = base_no_trail.net_pnl - adjusted_pnl
    status = "PROFITABLE" if adjusted_pnl > 0 else "UNPROFITABLE"
    print(f"    Delay +{delay_bars} bars ({total_delay}min total): PnL=${adjusted_pnl:>9.2f}  Cost: ${cost:>+9.2f}  {status}")

# ======================================================================
# PART 6: LAGGED REGIME DETECTION
# ======================================================================
print(f"\n{'=' * 120}")
print("PART 6: LAGGED REGIME DETECTION (20-bar trailing ADX average)")
print(f"{'=' * 120}")

highs = np.array([c["h"] for c in candles])
lows = np.array([c["l"] for c in candles])
closes = np.array([c["c"] for c in candles])
timestamps = np.array([c["t"] for c in candles])

adx_14 = adx(highs, lows, closes, 14)

# Compute 20-bar trailing average of ADX (lagged)
adx_lagged = np.full(len(adx_14), np.nan)
for i in range(20, len(adx_14)):
    window = adx_14[i-20:i]  # Note: does NOT include current bar (lagged)
    valid = window[~np.isnan(window)]
    if len(valid) >= 10:
        adx_lagged[i] = np.mean(valid)

# Compare instant vs lagged regime classification
valid_both = ~(np.isnan(adx_14) | np.isnan(adx_lagged))
if np.any(valid_both):
    instant_trending = np.sum((adx_14[valid_both] >= 25))
    instant_ranging = np.sum((adx_14[valid_both] < 20))
    lagged_trending = np.sum((adx_lagged[valid_both] >= 25))
    lagged_ranging = np.sum((adx_lagged[valid_both] < 20))
    total_valid = np.sum(valid_both)

    print(f"\n  Regime classification comparison ({total_valid} bars):")
    print(f"    {'':20} {'Instant ADX':>15} {'Lagged ADX(20)':>15}")
    print(f"    {'Trending (>=25)':<20} {instant_trending:>15} {lagged_trending:>15}")
    print(f"    {'Ranging (<20)':<20} {instant_ranging:>15} {lagged_ranging:>15}")

# Classify trades by LAGGED regime
configs_to_test = {
    "Finalist B (trail)": base_r,
    "Finalist B (no trail)": base_no_trail,
}

for cfg_name, r in configs_to_test.items():
    print(f"\n  {cfg_name} - LAGGED regime P&L:")
    trending_trades = []
    ranging_trades = []
    neutral_trades = []

    for t in r.trades:
        idx = np.searchsorted(timestamps, t["entry_time"])
        if idx >= len(adx_lagged):
            idx = len(adx_lagged) - 1

        a = adx_lagged[idx]
        if np.isnan(a):
            neutral_trades.append(t)
        elif a >= 25:
            trending_trades.append(t)
        elif a < 20:
            ranging_trades.append(t)
        else:
            neutral_trades.append(t)

    for regime_name, trades_list in [("TRENDING", trending_trades), ("RANGING", ranging_trades), ("NEUTRAL", neutral_trades)]:
        if not trades_list:
            print(f"    {regime_name:<12} {0:>4} trades  ${0:>9.2f}  WR={0:>5.1f}%")
            continue
        pnls = [t["pnl"] for t in trades_list]
        n_t = len(pnls)
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / n_t * 100
        print(f"    {regime_name:<12} {n_t:>4} trades  ${total:>9.2f}  WR={wr:>5.1f}%  {'PROFITABLE' if total > 0 else 'LOSING'}")

    all_pnl = sum(t["pnl"] for t in r.trades)
    print(f"    {'TOTAL':<12} {len(r.trades):>4} trades  ${all_pnl:>9.2f}")

# ======================================================================
# PART 8: COMPARISON WITHOUT TRAILING STOP (comprehensive)
# ======================================================================
print(f"\n{'=' * 120}")
print("PART 8: FINALIST B WITHOUT TRAILING STOP (comprehensive)")
print(f"{'=' * 120}")

# Also run Finalist A without trail for comparison
finalist_a_no_trail = SimConfig(
    atr_period=14, multiplier=3.0, source="close",
    cooldown_enabled=True, cooldown_minutes=20, cooldown_override_pct=1.0,
    tod_enabled=True, tod_block_start=0, tod_block_end=6,
    trailing_supertrend=False,
)
finalist_a_trail = SimConfig(
    atr_period=14, multiplier=3.0, source="close",
    cooldown_enabled=True, cooldown_minutes=20, cooldown_override_pct=1.0,
    tod_enabled=True, tod_block_start=0, tod_block_end=6,
    trailing_supertrend=True,
)

r_a_no = run_simulation(finalist_a_no_trail, data, 0, n)
r_a_yes = run_simulation(finalist_a_trail, data, 0, n)

print(f"\n  Full comparison:")
print(f"  {'Config':<50} {'Tr':>4} {'WR':>6} {'PF':>6} {'PnL':>10} {'DD%':>6} {'Sharpe':>7} {'Whip':>5}")
print(f"  {'-' * 100}")

all_configs = [
    ("Finalist B WITH trail", base_r),
    ("Finalist B WITHOUT trail", base_no_trail),
    ("Finalist A WITH trail", r_a_yes),
    ("Finalist A WITHOUT trail", r_a_no),
]

for name, r in all_configs:
    print(f"  {name:<50} {r.total_trades:>4} {r.win_rate:>5.1f}% {r.profit_factor:>6.2f} ${r.net_pnl:>9.2f} {r.max_drawdown_pct:>5.1f}% {r.sharpe_ratio:>7.2f} {r.whipsaw_count:>5}")

# Monthly for no-trail B
print(f"\n  Monthly P&L - Finalist B WITHOUT trail:")
if base_no_trail.monthly_pnl:
    for month, pnl in sorted(base_no_trail.monthly_pnl.items()):
        sign = "+" if pnl > 0 else ""
        print(f"    {month}: ${sign}{pnl:>8.2f}")

# Walk-forward for no-trail B
_, split, end = train_test_split(data)
train_nt = run_simulation(finalist_b_no_trail, data, 0, split)
val_nt = run_simulation(finalist_b_no_trail, data, split, end)
print(f"\n  Walk-forward (no-trail):")
print(f"    Training:   Tr={train_nt.total_trades:>3} PF={train_nt.profit_factor:.2f} PnL=${train_nt.net_pnl:.2f}")
print(f"    Validation: Tr={val_nt.total_trades:>3} PF={val_nt.profit_factor:.2f} PnL=${val_nt.net_pnl:.2f} {'PASS' if val_nt.net_pnl > 0 else 'FAIL'}")

# Robustness for no-trail
print(f"\n  Robustness check (no-trail, +/-10% params):")
all_robust = True
for vlabel, vatr, vmult in [
    ("ATR-10%", max(5, round(finalist_b_no_trail.atr_period * 0.9)), finalist_b_no_trail.multiplier),
    ("ATR+10%", round(finalist_b_no_trail.atr_period * 1.1), finalist_b_no_trail.multiplier),
    ("Mult-10%", finalist_b_no_trail.atr_period, round(finalist_b_no_trail.multiplier * 0.9, 2)),
    ("Mult+10%", finalist_b_no_trail.atr_period, round(finalist_b_no_trail.multiplier * 1.1, 2)),
]:
    vcfg = SimConfig(**{k: v for k, v in finalist_b_no_trail.__dict__.items()})
    vcfg.atr_period = vatr
    vcfg.multiplier = vmult
    vr = run_simulation(vcfg, data, 0, n)
    status = "OK" if vr.net_pnl > 0 else "FAIL"
    if vr.net_pnl <= 0: all_robust = False
    print(f"    {vlabel:<10}: PnL=${vr.net_pnl:>9.2f} PF={vr.profit_factor:.2f} {status}")
print(f"    Verdict: {'ROBUST' if all_robust else 'FRAGILE'}")

# ======================================================================
# FINAL SUMMARY
# ======================================================================
print(f"\n{'=' * 120}")
print("FINAL SUMMARY")
print(f"{'=' * 120}")
print(f"""
  Data: {days_span:.0f} days of 15m BTC candles ({n} bars)

  FINALIST B (WITH trailing ST stop):
    PnL: ${base_r.net_pnl:.2f} | Trades: {base_r.total_trades} | WR: {base_r.win_rate:.1f}% | PF: {base_r.profit_factor:.2f} | DD: {base_r.max_drawdown_pct:.1f}%
    - Has mild look-ahead bias on trailing stop exits
    - Requires bot-level implementation

  FINALIST B (WITHOUT trailing ST stop):
    PnL: ${base_no_trail.net_pnl:.2f} | Trades: {base_no_trail.total_trades} | WR: {base_no_trail.win_rate:.1f}% | PF: {base_no_trail.profit_factor:.2f} | DD: {base_no_trail.max_drawdown_pct:.1f}%
    - Zero look-ahead bias
    - Can be implemented via TradingView alerts + RSI condition
""")

elapsed = time.time() - start_time
print(f"Stress tests completed in {elapsed:.0f}s")
