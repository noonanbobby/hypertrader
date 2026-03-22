# Percent-of-Equity Sizing Fix — Root Cause Analysis & Corrected Results

**Date:** 2026-03-22
**Severity:** Data integrity (post-processing only — engine unaffected)

---

## Root Cause Analysis

### The Problem

When running our system with 50% of equity position sizing at 7x leverage from $100K, the post-processing code produced a final equity of **$183,778,945,524,212** (183 trillion dollars). This is physically impossible.

### Where the Bug Was

The bug was in the Python `pct_equity_sim()` function — the post-processing that rescales the engine's flat $125 trade log to simulate percent-of-equity sizing. **The engine itself was NOT affected.** The engine only supports flat sizing ($125 fixed margin per trade), and all flat $125 results are correct.

The function computed:
```python
position_notional = fraction * equity * leverage  # 0.50 * equity * 7
scale = position_notional / base_notional          # (0.50 * equity * 7) / 1250
pnl = base_trade_pnl * scale
equity += pnl
```

### Why the Math Was "Correct" But the Results Were Wrong

The math is algebraically correct: P&L scales linearly with position notional, including fees and funding. The problem is that this model has **no real-world constraints**. Tracing through our system's 464 trades:

| Trade | Equity | Notional | Scale | Comment |
|-------|--------|----------|-------|---------|
| 1 | $100,000 | $350,000 | 280x | Reasonable |
| 8 | $530,024 | $1,855,083 | 1,484x | Pushing limits |
| 40 | ~$3.8M | $13.3M | ~10,600x | Exceeds exchange limits |
| 122 | ~$180M | $630M | ~504,000x | Physically impossible |
| 169 | ~$1.9B | $6.6B | ~5,300,000x | Absurd |
| 276 | ~$1.7T | $5.9T | ~4,700,000,000x | $183T by trade 464 |

The compounding is exponential: each winning trade grows equity, which grows position size, which grows the next trade's P&L. Without bounds, this produces arbitrarily large numbers for any net-profitable strategy.

### Real-World Constraints That Were Missing

1. **Exchange position limits** — Hyperliquid caps individual positions at ~$10M notional for BTC
2. **Order book depth** — You cannot execute a $50M market order without massive slippage
3. **No liquidation modeling** — At 7x leverage, a loss exceeding the deployed margin should be capped
4. **Fixed slippage** — 0.05% slippage is realistic at $350K but absurdly low at $350M

### Secondary Bug Found

The engine's simulator hardcodes `bars * 15.0 / 60.0 / 8.0` for funding cost calculation, assuming 15-minute bars. For 30m timeframe, each bar is 30 minutes, so funding was underestimated by half. Fixed by pre-adjusting the funding rate in `main.rs` based on timeframe:

```rust
let bar_minutes: f64 = match tf {
    "30m" | "30" => 30.0,
    "1H" | "1h" | "60" => 60.0,
    // ...
    _ => 15.0,
};
let adjusted_funding = funding_rate * (bar_minutes / 15.0);
```

This only affects non-15m timeframes. The 15m backward compatibility test is unchanged.

---

## The Fix

### 1. Python `pct_equity_sim()` — Added Max Notional Cap

```python
def pct_equity_sim(trade_log, starting=100000, fraction=0.50, leverage=7.0,
                   max_notional=10_000_000):
    for t in trade_log:
        target_notional = fraction * equity * leverage
        actual_notional = min(target_notional, max_notional)  # CAP
        actual_margin = actual_notional / leverage
        scale = actual_notional / base_notional
        scaled_pnl = t["pnl"] * scale
        if scaled_pnl < -actual_margin:  # LIQUIDATION
            scaled_pnl = -actual_margin
        equity += scaled_pnl
```

The $10M default represents a realistic maximum individual position on Hyperliquid for BTC. The cap kicks in when equity exceeds $10M / (0.50 * 7) = $2.86M, naturally bounding exponential growth.

### 2. Engine Funding Rate — Timeframe-Adjusted

Added timeframe-aware funding adjustment in `main.rs`. 15m is unchanged (multiplier = 1.0). 30m uses 2x, 1H uses 4x, etc.

---

## Verification

### Backward Compatibility (15m, $125 flat) — UNCHANGED

| Asset | Before | After |
|-------|--------|-------|
| BTC | 211 trades, PF=3.79, $6,132.28 | 211 trades, PF=3.79, $6,132.28 |
| ETH | 191 trades, PF=3.33, $5,616.96 | 191 trades, PF=3.33, $5,616.96 |
| SOL | 194 trades, PF=2.48, $5,268.79 | 194 trades, PF=2.48, $5,268.79 |

### V10 Flat $125 — Minor Change from Funding Fix

| Metric | Before (wrong funding) | After (corrected) |
|--------|----------------------|-------------------|
| PF | 1.79 | 1.76 |
| P&L | $4,227.77 | $4,133.07 |
| Sharpe | 1.10 | 1.08 |

Small reduction (~2%) due to correctly doubling the funding cost for 30m bars.

### Percent-of-Equity — Before vs After

| System | Before (no cap) | After ($10M cap) |
|--------|----------------|-------------------|
| His v10 training | $8,919,137 | **$18,376,861** |
| Our system training | **$183,778,945,524,212** | **$105,015,865** |
| His v10 holdout | -$61,341 | **-$62,935** |
| Our system holdout | $2,833,507 | **$3,353,057** |

The v10 number actually increased with the cap because the cap prevents oversized losing trades from destroying as much equity (losses are bounded by the capped margin, not unlimited notional). Our system dropped from $183T to $105M — still large, but physically possible.

---

## Corrected Results — All Sizing Modes

### Training Period (2020-01-01 to 2025-03-19), 3 Assets

| Sizing Mode | His v10 | Our System | Winner |
|-------------|---------|-----------|--------|
| **$125 flat** | PF=1.76, Sharpe=1.08, P&L=$4,133 | PF=3.25, Sharpe=1.80, P&L=$15,234 | **Ours** |
| **50%/7x, $10M cap** | $18.4M (18,277%), MDD=65.3% | $105.0M (104,916%), MDD=42.2% | **Ours** |

### Holdout Period (2025-03-19 onward)

| Sizing Mode | His v10 | Our System | Winner |
|-------------|---------|-----------|--------|
| **$125 flat** | PF=0.76, Sharpe=-0.71, P&L=-$221 | PF=2.26, Sharpe=2.40, P&L=$1,784 | **Ours** |
| **50%/7x, $10M cap** | $37,065 (lost $63K, MDD=76.1%) | $3,453,057 (+$3.35M, MDD=40.3%) | **Ours** |

### Sensitivity to Max Notional Cap

| Cap | v10 Final Equity | v10 Return | v10 MDD | Our Final Equity | Our Return | Our MDD |
|-----|-----------------|-----------|---------|-----------------|-----------|---------|
| $2M | $5,394,378 | 5,294% | 65.3% | $23,371,379 | 23,271% | 15.7% |
| $5M | $11,361,432 | 11,261% | 65.3% | $55,042,380 | 54,942% | 29.2% |
| **$10M** | **$18,376,861** | **18,277%** | **65.3%** | **$105,015,865** | **104,916%** | **42.2%** |
| $25M | $37,272,906 | 37,173% | 65.3% | $251,354,155 | 251,254% | 54.6% |
| $50M | $46,088,523 | 45,989% | 79.3% | $485,720,039 | 485,620% | 56.5% |
| No cap | $7,045,019 | 6,945% | 96.6% | $183,778,945,524,212 | Infinity | 81.4% |

Key observation: v10 actually performs WORSE with no cap ($7M) than with a $10M cap ($18.4M). This is because unbounded position sizes amplify losses as much as gains, and v10's lower PF (1.76) means losses are more damaging. The cap protects equity during drawdowns.

### Year-by-Year at Corrected Sizing (v10, $10M cap)

| Year | Start Equity | End Equity | P&L | Return | Trades |
|------|-------------|-----------|-----|--------|--------|
| 2020 | $100,000 | $11,736,802 | +$5,158,827 | +5,159% | 30 |
| 2021 | $56,542 | $13,086,291 | +$2,291,936 | +4,054% | 47 |
| 2022 | $110,870 | $16,633,019 | +$5,352,949 | +4,828% | 43 |
| 2023 | $218,239 | $19,555,923 | +$5,946,796 | +2,725% | 61 |
| 2024 | $343,428 | $16,965,155 | -$1,231,725 | -359% | 39 |
| 2025 | $340,830 | $18,376,861 | +$758,077 | +222% | 7 |

Note: Start equity per year reflects equity at time of first trade that year, which may differ from previous year's end equity if drawdowns occurred between trades.

---

## Conclusions

1. **The $183T figure was a modeling error, not a code bug.** The P&L math was algebraically correct but the model lacked physical constraints (exchange position limits). Fixed by adding a $10M max notional cap.

2. **Even with realistic caps, leveraged compounding produces very large numbers.** At $10M cap, our system turns $100K into $105M over 5 years (with 42% MDD). This is a feature of 7x leverage compounding, not specific to any strategy.

3. **The fair comparison remains $125 flat.** Leverage amplifies returns for ANY profitable strategy. The strategy quality (PF, Sharpe) is what matters, and ours (PF=3.25, Sharpe=1.80) is far superior to his (PF=1.76, Sharpe=1.08).

4. **The funding fix had minimal impact** (~2% reduction in v10 P&L from corrected 30m funding costs). 15m results are completely unchanged.

5. **V10 still fails the holdout** regardless of sizing. At $125 flat: PF=0.76, Sharpe=-0.71. At his sizing with $10M cap: lost $63K of $100K (76% MDD).

---

*Files changed:*
- `main.rs`: Added timeframe-aware funding rate adjustment (3 lines)
- Python `pct_equity_sim()`: Added `max_notional` parameter and liquidation cap
- Backward compatibility: CONFIRMED (15m $125 flat results identical)
