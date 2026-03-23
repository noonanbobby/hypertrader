#!/usr/bin/env python3
"""Forensic investigation of the realistic simulator."""

import json
import math
import os
import sys

DATA_DIR = "/opt/hypertrader/addons/backtest-data"

# Exact params from realistic_sim.py
ASSET_PARAMS = {
    "BTC": {"spread_bps": 0.5, "k": 150.0, "maint_margin": 0.005,
            "max_market_order": 15_000_000.0, "max_position": 500_000_000.0},
    "ETH": {"spread_bps": 1.0, "k": 200.0, "maint_margin": 0.005,
            "max_market_order": 15_000_000.0, "max_position": 200_000_000.0},
    "SOL": {"spread_bps": 3.0, "k": 300.0, "maint_margin": 0.01,
            "max_market_order": 5_000_000.0, "max_position": 50_000_000.0},
}
TAKER_FEE_RATE = 0.00035
DEFAULT_FUNDING_PER_8H = 0.0001

# ===========================================================================
# INVESTIGATION 2 — MARKET IMPACT MODEL
# ===========================================================================

def calculate_market_impact(trade_notional, bar_volume_usd, daily_volume_usd,
                            daily_volatility, asset):
    """Exact copy from realistic_sim.py"""
    params = ASSET_PARAMS.get(asset, {})
    spread_bps = params["spread_bps"]
    k = params["k"]

    if daily_volume_usd <= 0 or trade_notional <= 0:
        return spread_bps / 2.0 / 10000.0

    participation_rate = trade_notional / daily_volume_usd
    spread_cost = spread_bps / 2.0
    physical_impact = k * daily_volatility * math.sqrt(participation_rate)

    sigmoid_adj = 0.0
    if participation_rate < 0.005:
        sigmoid_adj = daily_volatility * 10000.0 * 0.05
    elif participation_rate > 0.20:
        sigmoid_adj = (participation_rate - 0.20) * 50.0

    total_bps = spread_cost + physical_impact + sigmoid_adj
    return total_bps / 10000.0


print("=" * 80)
print("  FORENSIC AUDIT — REALISTIC SIMULATOR")
print("=" * 80)

# ── 2A: Parameters ──
print("\n\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 2A — ASSET PARAMETERS")
print("══════════════════════════════════════════════════════════════")
for asset, p in ASSET_PARAMS.items():
    print(f"  {asset}: spread={p['spread_bps']}bps, k={p['k']}, "
          f"max_order=${p['max_market_order']/1e6:.0f}M, "
          f"max_position=${p['max_position']/1e6:.0f}M, "
          f"maint_margin={p['maint_margin']*100:.1f}%")

# ── 2B: Impact at various sizes ──
print("\n\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 2B — MARKET IMPACT AT VARIOUS POSITION SIZES")
print("══════════════════════════════════════════════════════════════")

# Use realistic daily volumes and volatility
# BTC daily volume on Hyperliquid: ~$2-5B on a good day
# BTC daily volatility: ~2% annualized 60-80%, per-day ~3.5-5%
# Let's use the actual data to get these numbers

# Load a sample of actual data to get real volume/volatility
def load_bar_data_sample(asset):
    path = os.path.join(DATA_DIR, f"mega_{asset.lower()}_15m.json")
    with open(path) as f:
        raw = json.load(f)
    closes = [float(b["close"]) for b in raw]
    volumes = [float(b["volume"]) for b in raw]
    return closes, volumes

for asset in ["BTC", "ETH", "SOL"]:
    closes, volumes = load_bar_data_sample(asset)
    n = len(closes)

    # Compute rolling volatility (annualized) and daily volume at various points
    # Sample points: early (2020), mid (2022), late (2024)
    samples = [
        ("Early 2020", n // 5),
        ("Mid 2022", n * 2 // 5),
        ("Late 2023", n * 3 // 5),
        ("Mid 2024", n * 4 // 5),
        ("Late 2025", n - 100),
    ]

    print(f"\n  ─── {asset} ───")
    for label, idx in samples:
        # 20-bar rolling volatility
        if idx < 20:
            continue
        log_rets = [math.log(closes[i] / closes[i-1])
                    for i in range(idx-19, idx+1) if closes[i-1] > 0]
        mean_r = sum(log_rets) / len(log_rets)
        var = sum((r - mean_r)**2 for r in log_rets) / (len(log_rets) - 1)
        per_bar_vol = math.sqrt(var)
        bars_per_day = 96  # 15m bars
        daily_vol = per_bar_vol * math.sqrt(bars_per_day)

        avg_vol_base = sum(volumes[idx-19:idx+1]) / 20
        daily_vol_usd = avg_vol_base * closes[idx] * bars_per_day

        print(f"    {label} (bar {idx}):")
        print(f"      Price: ${closes[idx]:,.0f}")
        print(f"      Daily vol (annualized-style): {daily_vol*100:.2f}%")
        print(f"      Daily volume (USD): ${daily_vol_usd:,.0f}")
        print(f"      15m bar avg volume: ${avg_vol_base * closes[idx]:,.0f}")

        # Now compute impact at various notional sizes
        sizes = [1_250, 12_500, 125_000, 1_250_000, 12_500_000,
                 125_000_000, 500_000_000]

        print(f"      {'Notional':>15} │ {'Partic%':>8} │ {'Impact bps':>10} │ "
              f"{'Impact $':>12} │ {'Impact %':>8} │ {'Round-trip':>10}")
        print(f"      {'─'*15}─┼─{'─'*8}─┼─{'─'*10}─┼─{'─'*12}─┼─{'─'*8}─┼─{'─'*10}")

        for size in sizes:
            if size > ASSET_PARAMS[asset]["max_position"]:
                print(f"      ${size:>14,} │ EXCEEDS MAX POSITION")
                continue

            bar_vol_usd = avg_vol_base * closes[idx]  # single bar volume
            impact = calculate_market_impact(
                size, bar_vol_usd, daily_vol_usd, daily_vol, asset)
            impact_bps = impact * 10000
            impact_usd = size * impact
            partic = size / daily_vol_usd * 100 if daily_vol_usd > 0 else 0
            # Round-trip = entry impact + exit impact
            rt_impact = impact * 2

            print(f"      ${size:>14,} │ {partic:>7.2f}% │ {impact_bps:>9.1f} │ "
                  f"${impact_usd:>11,.0f} │ {impact*100:>7.3f}% │ {rt_impact*100:>9.3f}%")

# ── 2E: What SHOULD the impact be? ──
print("\n\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 2E — WHAT IMPACT SHOULD BE vs WHAT MODEL CHARGES")
print("══════════════════════════════════════════════════════════════")
print("""
  REAL WORLD REFERENCE (Hyperliquid BTC Perp):
    Daily volume: ~$2-5B (good day), ~$1-2B (quiet day)
    Order book depth at BTC (within 0.1%): ~$5-20M

    Realistic impact estimates:
      $1,250 order:      ~0.01% (negligible, fits in top-of-book)
      $125,000 order:    ~0.02-0.05% (small fish)
      $1.25M order:      ~0.1-0.3% (noticeable)
      $12.5M order:      ~0.5-2% (significant, might need TWAP)
      $125M order:       ~5-15% (would move market violently, impossible in 1 bar)
      $500M order:       IMPOSSIBLE to execute — exceeds entire order book depth

  KEY INSIGHT: The model uses daily_volume for participation rate.
  But real impact depends on ORDER BOOK DEPTH, not daily volume.
  A $500M order represents 10-25% of DAILY volume, but 100-1000% of
  order book depth. The square-root model with k=150 dramatically
  underestimates impact at large sizes because it models gradual
  execution, not a single market order hitting the book.
""")

# ── Investigation 3: Compounding Math ──
print("\n\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 3 — COMPOUNDING MATH TRACE")
print("══════════════════════════════════════════════════════════════")

# Load actual trade log
with open("/tmp/discovery/sweep_tradelog_B.json") as f:
    data_B = json.load(f)
trade_log = [t for t in data_B["trade_log"] if t["entry_ts"] < "2025-03-19"]
trade_log.sort(key=lambda t: t["entry_ts"])

# Load bar data for BTC
closes_btc, volumes_btc = load_bar_data_sample("BTC")

print(f"\n  Long-only trade log: {len(trade_log)} training trades")

# Trace trades 1, 5, 10, 20, 50
equity = 25_000.0
starting_equity = 25_000.0
leverage = 10.0
eq_frac = 0.50

print(f"\n  Config: $25K start, 50% equity, 10x leverage")
print(f"  {'#':>4} │ {'Equity':>14} │ {'Margin':>12} │ {'Notional':>14} │ "
      f"{'Flat P&L':>10} │ {'Price Move':>10} │ {'Impact':>8} │ {'Net P&L':>14} │ Asset")
print(f"  {'─'*4}─┼─{'─'*14}─┼─{'─'*12}─┼─{'─'*14}─┼─{'─'*10}─┼─{'─'*10}─┼─"
      f"{'─'*8}─┼─{'─'*14}─┼─{'─'*5}")

for i, t in enumerate(trade_log):
    asset = t["asset"]
    entry_bar = t["entry_bar"]
    exit_bar = t["exit_bar"]
    direction = t["direction"]

    if asset == "BTC":
        closes_a, volumes_a = closes_btc, volumes_btc
    else:
        closes_a, volumes_a = load_bar_data_sample(asset)

    signal_entry = closes_a[entry_bar] if entry_bar < len(closes_a) else 0
    signal_exit = closes_a[exit_bar] if exit_bar < len(closes_a) else 0

    # Wait, simulator uses opens, not closes! Let me use the correct prices
    # Actually for this trace we'll use the flat P&L from the engine output
    flat_pnl = t["pnl"]  # P&L at flat $125 margin / 10x leverage

    # Sizing
    margin = equity * eq_frac
    notional = margin * leverage

    # Cap at exchange limit
    params = ASSET_PARAMS.get(asset, ASSET_PARAMS["BTC"])
    if notional > params["max_position"]:
        notional = params["max_position"]
        margin = notional / leverage

    # Scale P&L: the engine computed P&L at $125 margin / 10x = $1,250 notional
    # Price move percentage = flat_pnl / 1250 (the flat notional)
    flat_notional = 125.0 * 10.0
    price_move_pct = flat_pnl / flat_notional

    # Ideal P&L at our size
    ideal_pnl = price_move_pct * notional

    # Market impact (use simplified calc with typical values)
    # Get actual vol and volume from data
    if entry_bar >= 20:
        log_rets = []
        for j in range(entry_bar-19, entry_bar+1):
            if j > 0 and j < len(closes_a) and closes_a[j] > 0 and closes_a[j-1] > 0:
                log_rets.append(math.log(closes_a[j] / closes_a[j-1]))
        if log_rets:
            mean_r = sum(log_rets) / len(log_rets)
            var = sum((r - mean_r)**2 for r in log_rets) / max(len(log_rets) - 1, 1)
            per_bar_vol = math.sqrt(var)
        else:
            per_bar_vol = 0.001
    else:
        per_bar_vol = 0.001
    daily_vol = per_bar_vol * math.sqrt(96)

    avg_vol = sum(volumes_a[max(0,entry_bar-19):entry_bar+1]) / 20 if entry_bar >= 20 else volumes_a[entry_bar]
    daily_vol_usd = avg_vol * closes_a[min(entry_bar, len(closes_a)-1)] * 96
    bar_vol_usd = volumes_a[min(entry_bar, len(volumes_a)-1)] * closes_a[min(entry_bar, len(closes_a)-1)]

    entry_impact = calculate_market_impact(notional, bar_vol_usd, daily_vol_usd, daily_vol, asset)
    exit_impact = calculate_market_impact(notional, bar_vol_usd, daily_vol_usd, daily_vol, asset)
    total_impact_pct = (entry_impact + exit_impact)

    # Fees + funding
    fees = notional * TAKER_FEE_RATE * 2
    bars_held = exit_bar - entry_bar
    funding = notional * DEFAULT_FUNDING_PER_8H * (15.0 / 480.0) * bars_held

    # Gross P&L (after impact)
    gross_pnl = ideal_pnl * (1 - total_impact_pct)  # Simplified
    net_pnl = gross_pnl - fees - funding

    equity += net_pnl
    equity = max(equity, 0)

    if i < 5 or i in [9, 19, 29, 49, 74, 99, 124, 149, 154]:
        print(f"  {i+1:>4} │ ${equity:>13,.0f} │ ${margin:>11,.0f} │ ${notional:>13,.0f} │ "
              f"${flat_pnl:>9,.0f} │ {price_move_pct*100:>9.2f}% │ {total_impact_pct*100:>7.3f}% │ "
              f"${net_pnl:>13,.0f} │ {asset}")
        if notional >= params["max_position"] * 0.99:
            print(f"       │ *** HIT EXCHANGE POSITION LIMIT — capped at ${params['max_position']/1e6:.0f}M ***")

print(f"\n  Final equity (approximate trace): ${equity:,.0f}")

# ── Investigation 3C: P&L calculation method ──
print("\n\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 3C — P&L CALCULATION METHOD")
print("══════════════════════════════════════════════════════════════")
print("""
  The simulator code (lines 374-378, 433-436):

    # IDEAL P&L:
    ideal_pnl = (signal_exit - signal_entry) / signal_entry * notional

    # GROSS P&L (after slippage):
    gross_pnl = (actual_exit - actual_entry) / actual_entry * notional

  This is CORRECT for a single position — P&L = price_return * notional.
  The market impact IS subtracted from the trade price (actual_entry,
  actual_exit), which then flows into gross_pnl.

  HOWEVER: The impact is computed once at entry and once at exit.
  For a $500M position, this assumes you can execute the entire $500M
  at a single slipped price. In reality, you'd need to TWAP over many
  bars, and the average fill would be much worse.

  The model treats a $500M order the same as a $500M TWAP — it just
  calculates a single impact number. For gradual execution this is
  arguably correct. But the simulator enters/exits in a SINGLE BAR.
""")

# ── Investigation 3D: Impact subtracted from P&L or equity? ──
print("\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 3D — IS IMPACT CORRECTLY SUBTRACTED?")
print("══════════════════════════════════════════════════════════════")
print("""
  Code flow:
    1. entry_slippage = calculate_market_impact(notional, ...)
    2. actual_entry = signal_entry * (1 + entry_slippage)    [for longs]
    3. exit_slippage = calculate_market_impact(notional, ...)
    4. actual_exit = signal_exit * (1 - exit_slippage)       [for longs]
    5. gross_pnl = (actual_exit - actual_entry) / actual_entry * notional
    6. net_pnl = gross_pnl - fees - funding
    7. equity += net_pnl

  Impact IS in the P&L calculation (it worsens actual_entry and actual_exit).
  This is CORRECT mechanically. But the MAGNITUDE of impact is the problem.
""")

# ── Investigation 4: Exchange limits ──
print("\n\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 4 — EXCHANGE POSITION LIMITS")
print("══════════════════════════════════════════════════════════════")
print("""
  Code limits (lines 346-351):
    BTC: max_position = $500,000,000  (500M)
    ETH: max_position = $200,000,000  (200M)
    SOL: max_position = $50,000,000   (50M)

  ACTUAL Hyperliquid limits (approximate, 2024-2025):
    BTC: max position ~$10-50M depending on account tier
         Total OI typically $1-3B
         $500M would be 17-50% of ALL open interest
    ETH: max position ~$5-20M
         Total OI typically $500M-1.5B
         $200M would be 13-40% of ALL open interest
    SOL: max position ~$2-10M
         Total OI typically $200M-800M
         $50M would be 6-25% of ALL open interest

  THE BUG: Position limits are 10-50x too high.
  Realistic limits should be:
    BTC: $10-20M max (and even that would be the largest single position)
    ETH: $5-10M max
    SOL: $2-5M max
""")

# ── Investigation 5: Funding ──
print("\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 5 — FUNDING RATE MODEL")
print("══════════════════════════════════════════════════════════════")
print(f"""
  Funding rate: {DEFAULT_FUNDING_PER_8H*100:.4f}% per 8 hours = 0.01% per 8h
  Applied to: FULL notional (correct)
  Per bar (15m): {DEFAULT_FUNDING_PER_8H * (15/480) * 100:.6f}%

  At $500M notional:
    Per 8h:  ${500_000_000 * DEFAULT_FUNDING_PER_8H:,.0f}
    Per day: ${500_000_000 * DEFAULT_FUNDING_PER_8H * 3:,.0f}
    Per month: ${500_000_000 * DEFAULT_FUNDING_PER_8H * 3 * 30:,.0f}

  NOTE: 0.01% per 8h is the BASELINE rate. During trending markets
  (which is when our long-only system has positions open), funding
  rates are typically MUCH higher — often 0.03-0.10% per 8h or more.
  Using 0.01% is very optimistic.

  At realistic 0.05% per 8h on $500M:
    Per day: ${500_000_000 * 0.0005 * 3:,.0f}
    Per month: ${500_000_000 * 0.0005 * 3 * 30:,.0f}
""")

# ── Investigation 6: Liquidation ──
print("\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 6 — LIQUIDATION MODEL")
print("══════════════════════════════════════════════════════════════")

for lev in [3, 5, 7, 10]:
    mm = 0.005
    liq_dist = (1.0/lev - mm) * 100
    print(f"  {lev}x leverage, 0.5% maint: liquidation at {liq_dist:.1f}% adverse move")

# Count adverse moves in the actual trades
print(f"\n  Checking adverse moves in {len(trade_log)} long-only trades:")
adverse_stats = {5: 0, 10: 0, 15: 0, 20: 0, 30: 0}
for t in trade_log:
    asset = t["asset"]
    entry_bar = t["entry_bar"]
    exit_bar = t["exit_bar"]
    if asset == "BTC":
        c, v = closes_btc, volumes_btc
    else:
        c, v = load_bar_data_sample(asset)

    if entry_bar >= len(c) or exit_bar >= len(c):
        continue

    entry_price = c[entry_bar]  # approximation (should be opens)
    # Check max adverse excursion during the trade
    max_adverse = 0
    for bi in range(entry_bar, min(exit_bar + 1, len(c))):
        if asset == "BTC":
            low = c[bi] * 0.99  # approximate low from close
        else:
            low = c[bi] * 0.99
        adverse = (entry_price - low) / entry_price * 100
        max_adverse = max(max_adverse, adverse)

    for threshold in adverse_stats:
        if max_adverse > threshold:
            adverse_stats[threshold] += 1

for thresh, count in sorted(adverse_stats.items()):
    print(f"    Trades with >{thresh}% max adverse excursion: {count}/{len(trade_log)}")

# ── Investigation 7: Reality check ──
print("\n\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 7 — REALITY CHECK")
print("══════════════════════════════════════════════════════════════")

# What the flat $125 sizing actually achieves
flat_pnl_total = sum(t["pnl"] for t in trade_log)
flat_notional = 125.0 * 10.0
years = 5.2

print(f"\n  Flat $125 margin / 10x leverage baseline:")
print(f"    Notional per trade: ${flat_notional:,.0f}")
print(f"    Total P&L: ${flat_pnl_total:,.0f}")
print(f"    Trades: {len(trade_log)}")
print(f"    Average P&L/trade: ${flat_pnl_total/len(trade_log):,.0f}")
print(f"    Average return/trade: {flat_pnl_total/len(trade_log)/flat_notional*100:.2f}%")

# What CAGR does this imply for compounding?
avg_return_per_trade = flat_pnl_total / len(trade_log) / flat_notional
print(f"\n  Average return per trade (on notional): {avg_return_per_trade*100:.2f}%")
print(f"  At 50% equity / 10x leverage, equity return per trade: "
      f"{avg_return_per_trade * 10 * 0.5 * 100:.1f}%")

# With compounding (ignoring friction growth)
compound_mult = 1.0
for t in trade_log:
    flat_pnl = t["pnl"]
    trade_return = flat_pnl / flat_notional
    # At 50% equity fraction, 10x leverage:
    # equity return = trade_return * leverage * equity_fraction
    # But this assumes impact doesn't grow!
    eq_return = trade_return * 10 * 0.50
    compound_mult *= (1 + eq_return)

print(f"\n  Naive compounding (no friction scaling): "
      f"${25000 * compound_mult:,.0f} from $25,000")
print(f"    This is {compound_mult:.0f}x = {(compound_mult**(1/years)-1)*100:.0f}% CAGR")
print(f"    This IGNORES that larger positions get worse fills!")

# Now with realistic friction scaling
print(f"\n  With realistic impact at each equity level:")
compound_mult_real = 1.0
equity_trace = 25_000.0
for t in trade_log:
    flat_pnl = t["pnl"]
    trade_return = flat_pnl / flat_notional

    margin = equity_trace * 0.50
    notional = min(margin * 10, 20_000_000)  # Cap at $20M (realistic Hyperliquid limit)

    # Friction scales with size
    # Use typical BTC daily vol = 3%, daily volume = $3B
    daily_vol = 0.03
    daily_volume = 3_000_000_000
    impact = calculate_market_impact(notional, daily_volume/96, daily_volume, daily_vol, "BTC")
    rt_impact = impact * 2
    fees = TAKER_FEE_RATE * 2
    funding_per_trade = DEFAULT_FUNDING_PER_8H * (15/480) * 300  # avg 300 bars held

    ideal_eq_return = trade_return * notional / equity_trace if equity_trace > 0 else 0
    friction = rt_impact + fees + funding_per_trade
    net_eq_return = ideal_eq_return * (1 - friction) - friction * abs(notional / equity_trace)

    # Simplified: just scale the flat P&L and subtract position-size-dependent friction
    ideal_pnl = trade_return * notional
    friction_cost = notional * rt_impact + notional * fees + notional * funding_per_trade
    net_pnl = ideal_pnl - friction_cost

    equity_trace += net_pnl
    equity_trace = max(equity_trace, 0)

print(f"  With $20M position cap + realistic friction: ${equity_trace:,.0f} from $25,000")
print(f"    CAGR: {((equity_trace/25000)**(1/years)-1)*100:.0f}%")

# ── Summary ──
print("\n\n══════════════════════════════════════════════════════════════")
print("INVESTIGATION 8 — ROOT CAUSE ANALYSIS")
print("══════════════════════════════════════════════════════════════")

# Calculate what the model charges at $500M vs what reality would charge
daily_vol = 0.03  # typical
daily_volume = 3_000_000_000  # $3B

for size_label, size in [("$1.25K", 1_250), ("$125K", 125_000), ("$1.25M", 1_250_000),
                          ("$12.5M", 12_500_000), ("$125M", 125_000_000), ("$500M", 500_000_000)]:
    model_impact = calculate_market_impact(size, daily_volume/96, daily_volume, daily_vol, "BTC")
    participation = size / daily_volume * 100

    # Realistic estimate (based on order book depth research)
    if size <= 100_000:
        real_impact = 0.0001  # ~1 bps
    elif size <= 1_000_000:
        real_impact = 0.0003  # ~3 bps
    elif size <= 10_000_000:
        real_impact = 0.002   # ~20 bps
    elif size <= 50_000_000:
        real_impact = 0.01    # ~100 bps (1%)
    elif size <= 100_000_000:
        real_impact = 0.05    # ~500 bps (5%) — if even possible
    else:
        real_impact = 0.15    # ~1500 bps (15%) — effectively impossible

    ratio = real_impact / model_impact if model_impact > 0 else float('inf')
    print(f"  {size_label:>8}: Model={model_impact*100:.3f}%  Reality≈{real_impact*100:.1f}%  "
          f"Under-charge={ratio:.1f}x  (partic={participation:.1f}%)")
