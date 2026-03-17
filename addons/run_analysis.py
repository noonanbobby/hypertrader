#!/usr/bin/env python3
"""Final analysis: comparison + regime analysis."""
import sys, json, time
import numpy as np
sys.path.insert(0, 'addons')
from backtest import *

start_time = time.time()
data = load_all_data(180)

n = len(data["15m"])
candles = data["15m"]
days_span = (candles[-1]["t"] - candles[0]["t"]) / 86400000

# ======================================================================
# DEFINE ALL 5 CONFIGS
# ======================================================================
configs = {
    "Finalist A: ST(14,3.0,close)+CD+TOD+Trail": SimConfig(
        atr_period=14, multiplier=3.0, source="close",
        cooldown_enabled=True, cooldown_minutes=20, cooldown_override_pct=1.0,
        tod_enabled=True, tod_block_start=0, tod_block_end=6,
        trailing_supertrend=True),
    "Finalist B: ST(9,3.0,hl2)+RSI+Trail": SimConfig(
        atr_period=9, multiplier=3.0, source="hl2",
        rsi_enabled=True, rsi_period=7, rsi_buy_min=40, rsi_buy_max=70,
        rsi_sell_max=60, rsi_sell_min=20,
        trailing_supertrend=True),
    "Current Live: ST(10,2.0,hl2)+RSI(14)": SimConfig(
        atr_period=10, multiplier=2.0, source="hl2",
        rsi_enabled=True, rsi_period=14, rsi_buy_min=50, rsi_buy_max=80,
        rsi_sell_max=50, rsi_sell_min=20),
    "Colleague: ST(10,1.3,close)": SimConfig(
        atr_period=10, multiplier=1.3, source="close"),
    "Baseline: ST(10,3.0,hl2)": SimConfig(
        atr_period=10, multiplier=3.0, source="hl2"),
}

# ======================================================================
# PART 1: FULL COMPARISON
# ======================================================================
print(f"\n{'=' * 130}")
print("PART 1: FULL DATASET COMPARISON (all 52 days)")
print(f"{'=' * 130}")

results = {}
for name, cfg in configs.items():
    r = run_simulation(cfg, data, 0, n)
    results[name] = r

# Side-by-side stats
stat_labels = [
    ("Total Trades", lambda r: f"{r.total_trades}"),
    ("Win Rate", lambda r: f"{r.win_rate:.1f}%"),
    ("Profit Factor", lambda r: f"{r.profit_factor:.2f}"),
    ("Net P&L ($)", lambda r: f"${r.net_pnl:.2f}"),
    ("Net P&L (%)", lambda r: f"{r.net_pnl_pct:.1f}%"),
    ("Max Drawdown ($)", lambda r: f"${r.max_drawdown:.2f}"),
    ("Max Drawdown (%)", lambda r: f"{r.max_drawdown_pct:.1f}%"),
    ("Sharpe Ratio", lambda r: f"{r.sharpe_ratio:.2f}"),
    ("Sortino Ratio", lambda r: f"{r.sortino_ratio:.2f}"),
    ("Avg Trade P&L", lambda r: f"${r.avg_trade_pnl:.2f}"),
    ("Avg Winner", lambda r: f"${r.avg_winner:.2f}"),
    ("Avg Loser", lambda r: f"${r.avg_loser:.2f}"),
    ("Win/Loss Ratio", lambda r: f"{r.win_loss_ratio:.2f}"),
    ("Largest Win", lambda r: f"${r.largest_win:.2f}"),
    ("Largest Loss", lambda r: f"${r.largest_loss:.2f}"),
    ("Total Fees", lambda r: f"${r.total_fees:.2f}"),
    ("Total Funding", lambda r: f"${r.total_funding:.2f}"),
    ("Avg Hold (bars)", lambda r: f"{r.avg_hold_bars:.0f}"),
    ("Avg Hold (hours)", lambda r: f"{r.avg_hold_bars * 0.25:.1f}h"),
    ("Trades/Day", lambda r: f"{r.trades_per_day:.2f}"),
    ("Whipsaws", lambda r: f"{r.whipsaw_count}"),
    ("Win Streak", lambda r: f"{r.longest_win_streak}"),
    ("Lose Streak", lambda r: f"{r.longest_lose_streak}"),
    ("Blocked Trades", lambda r: f"{r.blocked_trades}"),
    ("Blocked Winners", lambda r: f"{r.blocked_winners}"),
    ("Blocked Losers", lambda r: f"{r.blocked_losers}"),
]

# Short names for column headers
short_names = {
    "Finalist A: ST(14,3.0,close)+CD+TOD+Trail": "Finalist A",
    "Finalist B: ST(9,3.0,hl2)+RSI+Trail": "Finalist B",
    "Current Live: ST(10,2.0,hl2)+RSI(14)": "Current Live",
    "Colleague: ST(10,1.3,close)": "Colleague",
    "Baseline: ST(10,3.0,hl2)": "Baseline",
}

# Print header
names_list = list(configs.keys())
header = f"{'Metric':<22}"
for name in names_list:
    header += f" {short_names[name]:>14}"
print(header)
print("-" * (22 + 15 * len(names_list)))

for label, fn in stat_labels:
    row = f"{label:<22}"
    for name in names_list:
        row += f" {fn(results[name]):>14}"
    print(row)

# Monthly comparison
print(f"\n{'=' * 130}")
print("MONTHLY P&L COMPARISON")
print(f"{'=' * 130}")

all_months = set()
for r in results.values():
    all_months.update(r.monthly_pnl.keys())

header = f"{'Month':<10}"
for name in names_list:
    header += f" {short_names[name]:>14}"
print(header)
print("-" * (10 + 15 * len(names_list)))

for month in sorted(all_months):
    row = f"{month:<10}"
    for name in names_list:
        pnl = results[name].monthly_pnl.get(month, 0)
        sign = "+" if pnl > 0 else ""
        row += f" ${sign}{pnl:>12.2f}"
    print(row)

# Totals
row = f"{'TOTAL':<10}"
for name in names_list:
    row += f" ${results[name].net_pnl:>+12.2f}"
print("-" * (10 + 15 * len(names_list)))
print(row)


# ======================================================================
# PART 2: REGIME ANALYSIS
# ======================================================================
print(f"\n{'=' * 130}")
print("PART 2: REGIME ANALYSIS (Trending vs Ranging)")
print(f"{'=' * 130}")

# Compute ADX on 15m data
highs = np.array([c["h"] for c in candles])
lows = np.array([c["l"] for c in candles])
closes = np.array([c["c"] for c in candles])
timestamps = np.array([c["t"] for c in candles])

adx_14 = adx(highs, lows, closes, 14)

# Classify each bar
trending_bars = 0
ranging_bars = 0
neutral_bars = 0
valid_bars = 0

for i in range(len(adx_14)):
    if np.isnan(adx_14[i]):
        continue
    valid_bars += 1
    if adx_14[i] >= 25:
        trending_bars += 1
    elif adx_14[i] < 20:
        ranging_bars += 1
    else:
        neutral_bars += 1

trending_pct = trending_bars / valid_bars * 100
ranging_pct = ranging_bars / valid_bars * 100
neutral_pct = neutral_bars / valid_bars * 100

print(f"\n  ADX(14) regime breakdown across {valid_bars} valid bars ({days_span:.0f} days):")
print(f"    Trending (ADX >= 25): {trending_bars:>5} bars ({trending_pct:.1f}%) = ~{trending_bars * 15 / 60 / 24:.0f} days")
print(f"    Neutral  (20-25):     {neutral_bars:>5} bars ({neutral_pct:.1f}%) = ~{neutral_bars * 15 / 60 / 24:.0f} days")
print(f"    Ranging  (ADX < 20):  {ranging_bars:>5} bars ({ranging_pct:.1f}%) = ~{ranging_bars * 15 / 60 / 24:.0f} days")

# Now classify each TRADE by the regime at entry time
print(f"\n  Per-config P&L by regime:")
print(f"  {'Config':<25} {'Regime':<12} {'Trades':>6} {'WR':>6} {'PnL':>10} {'AvgPnL':>8} {'PF':>6}")
print(f"  {'-' * 80}")

regime_summary = {}
for name in names_list:
    r = results[name]
    sname = short_names[name]
    trending_trades = []
    ranging_trades = []
    neutral_trades = []

    for t in r.trades:
        # Find the bar index for entry time
        entry_t = t["entry_time"]
        # Binary search for closest bar
        idx = np.searchsorted(timestamps, entry_t)
        if idx >= len(adx_14):
            idx = len(adx_14) - 1

        adx_val = adx_14[idx]
        if np.isnan(adx_val):
            neutral_trades.append(t)
        elif adx_val >= 25:
            trending_trades.append(t)
        elif adx_val < 20:
            ranging_trades.append(t)
        else:
            neutral_trades.append(t)

    regime_summary[name] = {
        "trending": trending_trades,
        "ranging": ranging_trades,
        "neutral": neutral_trades,
    }

    for regime_name, trades_list in [("TRENDING", trending_trades), ("RANGING", ranging_trades), ("NEUTRAL", neutral_trades)]:
        if not trades_list:
            pnl = 0
            wr = 0
            avg = 0
            pf = 0
            n_trades = 0
        else:
            pnls = [t["pnl"] for t in trades_list]
            n_trades = len(pnls)
            pnl = sum(pnls)
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            wr = len(wins) / n_trades * 100
            avg = np.mean(pnls)
            gross_w = sum(wins)
            gross_l = abs(sum(losses))
            pf = gross_w / gross_l if gross_l > 0 else (999 if gross_w > 0 else 0)

        label = sname if regime_name == "TRENDING" else ""
        print(f"  {label:<25} {regime_name:<12} {n_trades:>6} {wr:>5.1f}% ${pnl:>9.2f} ${avg:>7.2f} {pf:>6.2f}")

    print()

# ======================================================================
# PART 3: THE KEY QUESTION
# ======================================================================
print(f"\n{'=' * 130}")
print("PART 3: THE KEY QUESTION - Profitable trending + breakeven ranging?")
print(f"{'=' * 130}")
print()
print(f"  {'Config':<25} {'Trend PnL':>10} {'Range PnL':>10} {'Trend+Range':>12} {'Ranging':>12} {'VERDICT':>12}")
print(f"  {'-' * 85}")

for name in names_list:
    sname = short_names[name]
    rs = regime_summary[name]
    trend_pnl = sum(t["pnl"] for t in rs["trending"])
    range_pnl = sum(t["pnl"] for t in rs["ranging"])
    total = trend_pnl + range_pnl

    if trend_pnl > 0 and range_pnl >= 0:
        verdict = "*** WINNER ***"
    elif trend_pnl > 0 and range_pnl > -50:
        verdict = "CLOSE"
    elif trend_pnl > 0:
        verdict = "Gives back"
    else:
        verdict = "Bad"

    range_label = "breakeven" if abs(range_pnl) < 20 else ("losing" if range_pnl < 0 else "winning")
    print(f"  {sname:<25} ${trend_pnl:>9.2f} ${range_pnl:>9.2f} ${total:>11.2f} {range_label:>12} {verdict:>12}")

# ======================================================================
# PART 4: DEEPER REGIME DRILL-DOWN
# ======================================================================
print(f"\n{'=' * 130}")
print("PART 4: TRADE-BY-TRADE REGIME DETAIL FOR TOP CONFIGS")
print(f"{'=' * 130}")

# Show the ranging trades for the top 2 finalists
for name in names_list[:2]:
    sname = short_names[name]
    rs = regime_summary[name]
    print(f"\n  {sname} - RANGING TRADES:")
    if not rs["ranging"]:
        print(f"    No ranging trades")
        continue
    print(f"    {'Entry Date':<20} {'Dir':>5} {'Entry':>10} {'Exit':>10} {'PnL':>10} {'Bars':>5} {'ADX':>6}")
    for t in rs["ranging"]:
        entry_dt = datetime.fromtimestamp(t["entry_time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        direction = "LONG" if t["direction"] == 1 else "SHORT"
        idx = np.searchsorted(timestamps, t["entry_time"])
        if idx >= len(adx_14): idx = len(adx_14) - 1
        adx_at_entry = adx_14[idx]
        print(f"    {entry_dt:<20} {direction:>5} ${t['entry_price']:>9.0f} ${t['exit_price']:>9.0f} ${t['pnl']:>9.2f} {t['hold_bars']:>5} {adx_at_entry:>6.1f}")

# ======================================================================
# ADX over time chart (text-based)
# ======================================================================
print(f"\n{'=' * 130}")
print("PART 5: ADX TIMELINE (daily average)")
print(f"{'=' * 130}")

# Average ADX per day
day_adx = {}
for i in range(len(adx_14)):
    if np.isnan(adx_14[i]):
        continue
    day = datetime.fromtimestamp(timestamps[i] / 1000, tz=timezone.utc).strftime("%m-%d")
    if day not in day_adx:
        day_adx[day] = []
    day_adx[day].append(adx_14[i])

print(f"  Date   ADX   |10  15  20  25  30  35  40  45  50")
print(f"  {'_' * 60}")
for day in sorted(day_adx.keys()):
    avg = np.mean(day_adx[day])
    bar_len = int(avg / 2)
    marker = "T" if avg >= 25 else ("R" if avg < 20 else ".")
    bar = marker * bar_len
    regime = "TREND" if avg >= 25 else ("RANGE" if avg < 20 else "")
    print(f"  {day}  {avg:>5.1f}  |{bar:<25} {regime}")

elapsed = time.time() - start_time
print(f"\nAnalysis completed in {elapsed:.0f}s")
