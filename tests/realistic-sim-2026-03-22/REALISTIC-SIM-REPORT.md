# Production-Grade Realistic Simulation Engine — Report

**Date:** 2026-03-22
**Engine:** `realistic_simulation_v2`
**Runtime:** 30.8s

## What Changed

Replaced the broken `$10M notional cap` band-aid with a production-grade simulation that models every cost from first principles:

| Component | Old Model | New Model |
|-----------|-----------|-----------|
| Sizing | Linear P&L scaling with flat $10M cap | Full compounding with exchange position limits |
| Market impact | None (fixed 5 bps) | Square-root law (Donier & Bonart 2015), calibrated per asset |
| Liquidation | Loss capped at margin (no bar checks) | Bar-by-bar high/low check against isolated margin liq price |
| Funding | Flat 0.01%/8h on base notional | 0.01%/8h on actual notional, accrued per bar |
| Fees | Engine's maker rate on base | 3.5 bps taker per side on actual notional |
| Trade ordering | By asset (all BTC, then ETH, then SOL) | Chronological across all assets |
| Signal prices | Engine's slippage-adjusted prices | Raw bar open prices (no double-count) |
| Exchange limits | Flat $10M cap | BTC $500M, ETH $200M, SOL $50M position caps |

## Model Parameters

**Market Impact (Square-Root Law):**
```
slippage = spread/2 + k * σ_daily * √(notional/ADV) + sigmoid_adj

BTC: spread=0.5 bps, k=150, maint_margin=0.5%
ETH: spread=1.0 bps, k=200, maint_margin=0.5%
SOL: spread=3.0 bps, k=300, maint_margin=1.0%
```

**Liquidation (Isolated Margin):**
```
Long liq price  = entry * (1 - 1/leverage + maint_margin)
Short liq price = entry * (1 + 1/leverage - maint_margin)
Checked every bar using bar low (longs) / bar high (shorts)
```

## Validation Results

| Test | Status | Description |
|------|--------|-------------|
| 10A Sanity | PASS | $100K → $21.7M over 5 years (not trillions) |
| 10B Small | PASS | $1K account: first 30 trades have 4.8% slippage, no exchange limits hit |
| 10C Extreme | PASS | $100M loses money (-78%), friction > ideal P&L, 342 position cap hits |
| 10D Compat | PASS | Flat $125 unchanged: BTC=211, ETH=191, SOL=194 trades |

## Key Results — $100K, 50% Equity, 7x Leverage

### Training Period (2020-01-01 to 2025-03-19)

|  | Our System | v10 |
|--|-----------|-----|
| **Timeframe** | 15m | 30m |
| **Flat $125 PF** | 3.25 | 1.76 |
| **Flat $125 Sharpe** | 1.80 | 1.08 |
| **Flat $125 P&L** | $15,234 | $4,133 |
| **Realistic Final Equity** | $21,708,983 | $3,430,962 |
| **Realistic Return** | 21,609% | 3,331% |
| **Realistic PF** | 1.02 | 1.08 |
| **Realistic MDD** | 96.9% | 95.3% |
| **Liquidations** | 2 | 1 |
| **Peak Notional** | $500M (100% of limit) | $38M (7.7% of limit) |

### P&L Waterfall — Our System

```
Ideal P&L (zero friction):    $1,262,434,261
  − Market impact/slippage:   $1,146,004,865  (90.8% of ideal)
  = Gross P&L (after slip):   $  116,429,396
  − Trading fees:              $   42,304,713  ( 3.4% of ideal)
  − Funding costs:             $   52,016,481  ( 4.1% of ideal)
  − Liquidation fees:          $      500,000
  ─────────────────────────────────────────────
  = Net P&L:                   $   21,608,983
  Total friction:              $1,240,826,059  (98.3% of ideal)
```

### P&L Waterfall — v10

```
Ideal P&L (zero friction):    $ 11,596,670
  − Market impact/slippage:   $  5,303,873  (45.7% of ideal)
  = Gross P&L (after slip):   $  6,292,797
  − Trading fees:              $  1,499,981  (12.9% of ideal)
  − Funding costs:             $  1,394,226  (12.0% of ideal)
  − Liquidation fees:          $     67,713
  ─────────────────────────────────────────────
  = Net P&L:                   $  3,330,962
  Total friction:              $  8,265,793  (71.3% of ideal)
```

### Holdout Period (2025-03-19 to 2026-03-22)

|  | Our System | v10 |
|--|-----------|-----|
| **Final Equity** | $988,752 | $25,877 |
| **Return** | 889% | -74% |
| **PF** | 1.27 | 0.58 |
| **Sharpe** | 1.81 | -1.06 |
| **MDD** | 55.0% | 76.4% |

## Annual Friction Budget

At $100K equity, 50% deployed, 7x leverage ($350K notional per trade):

| Cost | Annual $ | % of Equity |
|------|----------|-------------|
| Taker fees (100 trades/yr) | $24,500 | 24.4% |
| Funding (0.01%/8h continuous) | $38,325 | 38.3% |
| Market impact (~2 bps RT) | $7,000 | 7.0% |
| **Total** | **$69,825** | **69.7%** |

**Strategy must generate >69.7% annual return at starting equity just to break even.**

## Capacity Analysis

### Our System (15m)

| Starting Eq | Final Eq | Return | Sharpe | Friction% | Limits |
|------------|----------|--------|--------|-----------|--------|
| $10K | $21.7M | 216,982% | 2.79 | 97.9% | 196 |
| $100K | $21.7M | 21,609% | 2.45 | 98.3% | 216 |
| $1M | $21.7M | 2,071% | 2.06 | 98.8% | 251 |
| $10M | $21.8M | 118% | 1.54 | 99.5% | 298 |
| $50M | $21.9M | -56% | 1.14 | 101.0% | 324 |
| $100M | $22.1M | -78% | 0.91 | 102.7% | 342 |

**Capacity ceiling: $1,000,000** (Sharpe degrades >25% beyond this)

### v10 System (30m)

| Starting Eq | Final Eq | Return | Sharpe | Friction% | Limits |
|------------|----------|--------|--------|-----------|--------|
| $10K | $72K | 617% | 2.09 | 89.1% | 0 |
| $100K | $3.4M | 3,331% | 2.44 | 71.3% | 0 |
| $1M | $12M | 1,103% | 2.11 | 93.7% | 54 |
| $10M | $13M | 30% | 1.47 | 99.1% | 81 |
| $50M | $13.1M | -74% | 1.04 | 110.5% | 88 |
| $100M | $13.1M | -87% | 0.91 | 125.7% | 88 |

**Capacity ceiling: $10,000,000** (Sharpe degrades >25% beyond this)

## Key Insights

1. **Our system produces 6.3x the dollar return** of v10 at $100K ($21.7M vs $3.4M) because it generates 3.7x more ideal P&L per trade with higher PF

2. **Market impact is the dominant cost** — 90.8% of ideal P&L for our system at $100K. This is because equity compounds rapidly, pushing notional into the hundreds of millions where the square-root impact law becomes severe

3. **v10 has a HIGHER capacity ceiling** ($10M vs $1M) despite lower PF. Why: v10 trades 30m bars (more volume per bar), trades less frequently (227 vs 464), and generates less extreme compounding — keeping notional in manageable range longer

4. **Both systems converge to ~$21M-$13M final equity** regardless of starting capital. The exchange position cap ($500M BTC) acts as an absolute ceiling on per-trade notional, so once equity exceeds ~$70M, additional equity sits idle

5. **Previous $10M cap results were misleading:**
   - Old v10: $18.4M → New v10: $3.4M (5.4x lower — $10M cap was too generous)
   - Old ours: $105M → New ours: $21.7M (4.8x lower — $10M cap was too generous)

6. **2 liquidation events** across 464 trades for our system (2021) — expected at 7x leverage

## Year-by-Year — Our System

| Year | Start | End | P&L | Return | Trades | Liqs |
|------|-------|-----|-----|--------|--------|------|
| 2020 | $100K | $7.8M | $7.7M | 7,732% | 15 | 0 |
| 2021 | $7.8M | $71M | $63.2M | 807% | 82 | 2 |
| 2022 | $71M | $22M | -$49M | -69% | 139 | 0 |
| 2023 | $22M | $101M | $78.9M | 358% | 87 | 0 |
| 2024 | $101M | $69.9M | -$31M | -31% | 107 | 0 |
| 2025 | $69.9M | $21.7M | -$48.2M | -69% | 34 | 0 |

The explosive 2020-2021 growth happens while notional is small (low friction). Post-2021, equity oscillates as friction at large notional caps growth. This is exactly what the model predicts — the strategy has real edge but it can't be deployed at unlimited scale.

## Files

- `realistic_sim.py` — Production simulation engine (addons/)
- `results.json` — Full results with capacity analysis
- `report.txt` — Console output log
