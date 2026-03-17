#!/usr/bin/env python3
"""
Bug investigation: 6 diagnostic tests to find where the money goes.
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_supertrend, calc_tr, calc_atr_rma, calc_sma, calc_atr


def load_klines(filename):
    with open(DATA_DIR / filename) as f:
        klines = json.load(f)
    return {
        "opens": np.array([k["open"] for k in klines], dtype=np.float64),
        "highs": np.array([k["high"] for k in klines], dtype=np.float64),
        "lows": np.array([k["low"] for k in klines], dtype=np.float64),
        "closes": np.array([k["close"] for k in klines], dtype=np.float64),
        "volumes": np.array([k["volume"] for k in klines], dtype=np.float64),
        "timestamps": np.array([k["open_time"] for k in klines], dtype=np.int64),
        "n": len(klines),
    }


def run_mtf_diagnostic(data_15m, data_1h,
                       entry_atr, entry_mult, entry_src,
                       confirm_atr, confirm_mult, confirm_src,
                       start_bar, end_bar,
                       # Diagnostic switches
                       fixed_size=None,  # If set, use this $ amount per trade instead of % equity
                       position_pct=0.25, leverage=10.0,
                       fees_enabled=True, taker_fee=0.00045,
                       slippage_enabled=True, slippage=0.0001,
                       entry_on_close=False,  # If True, enter at signal bar close instead of next open
                       starting_capital=500.0):
    """MTF backtest with diagnostic toggles."""
    d = data_15m
    n = end_bar

    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"],
                                 confirm_atr, confirm_mult, confirm_src)
    h_ts = data_1h["timestamps"]
    htf_dir = np.ones(n)
    h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts) - 1 and h_ts[h_idx + 1] <= d["timestamps"][i]:
            h_idx += 1
        if h_idx < len(h_dirs):
            htf_dir[i] = h_dirs[h_idx]

    o, h, l, c, v, ts = (d["opens"][:n], d["highs"][:n], d["lows"][:n],
                          d["closes"][:n], d["volumes"][:n], d["timestamps"][:n])
    st_line, st_dir = calc_supertrend(h, l, c, entry_atr, entry_mult, entry_src)

    equity = starting_capital
    position = 0
    entry_price = 0.0
    position_size = 0.0
    entry_bar_idx = 0
    trades = []
    equity_curve = []
    pending = None
    pending_dir = 0

    actual_fee = taker_fee if fees_enabled else 0.0
    actual_slip = slippage if slippage_enabled else 0.0

    for i in range(start_bar, n):
        # Execute pending at this bar's OPEN (or at previous bar's CLOSE if entry_on_close)
        if pending is not None and i > start_bar:
            action = pending
            pending = None

            if entry_on_close:
                exec_price = c[i-1]  # previous bar close
            else:
                exec_price = o[i]    # this bar open

            if action == "close" and position != 0:
                fill = exec_price - exec_price * actual_slip * position
                pnl_raw = (fill - entry_price) * position * (position_size / entry_price)
                fee = position_size * actual_fee
                net = pnl_raw - fee
                trades.append({
                    "pnl_before_fees": round(pnl_raw, 4),
                    "fee": round(fee, 4),
                    "pnl_after_fees": round(net, 4),
                    "direction": position,
                    "entry_price": entry_price,
                    "exit_price": fill,
                    "entry_bar": entry_bar_idx,
                    "exit_bar": i,
                    "bars_held": i - entry_bar_idx,
                })
                equity += net
                position = 0
                position_size = 0.0

            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_close = exec_price - exec_price * actual_slip * position
                    pnl_raw = (fill_close - entry_price) * position * (position_size / entry_price)
                    fee = position_size * actual_fee
                    net = pnl_raw - fee
                    trades.append({
                        "pnl_before_fees": round(pnl_raw, 4),
                        "fee": round(fee, 4),
                        "pnl_after_fees": round(net, 4),
                        "direction": position,
                        "entry_price": entry_price,
                        "exit_price": fill_close,
                        "entry_bar": entry_bar_idx,
                        "exit_bar": i,
                        "bars_held": i - entry_bar_idx,
                    })
                    equity += net

                if equity <= 0:
                    position = 0
                    continue

                new_dir = 1 if "long" in action else -1
                fill_open = exec_price + exec_price * actual_slip * new_dir

                if fixed_size is not None:
                    position_size = fixed_size * leverage
                else:
                    position_size = equity * position_pct * leverage

                fee = position_size * actual_fee
                equity -= fee
                position = new_dir
                entry_price = fill_open
                entry_bar_idx = i

        # Equity curve
        if position != 0:
            unrealized = (c[i] - entry_price) * position * (position_size / entry_price)
            equity_curve.append(equity + unrealized)
        else:
            equity_curve.append(equity)

        if i >= n - 1:
            if position != 0:
                pending = "close"
            continue

        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]):
            continue

        if st_dir[i] == st_dir[i-1]:
            continue

        new_dir = 1 if st_dir[i] == 1 else -1

        # MTF filter
        if htf_dir[i] != new_dir:
            if position != 0:
                pending = "close"
            continue

        if position == 0:
            pending = "open_long" if new_dir == 1 else "open_short"
        elif position != new_dir:
            pending = "flip_long" if new_dir == 1 else "flip_short"

    # Close remaining
    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - actual_slip * position)
        pnl_raw = (fill - entry_price) * position * (position_size / entry_price)
        fee = position_size * actual_fee
        net = pnl_raw - fee
        trades.append({
            "pnl_before_fees": round(pnl_raw, 4),
            "fee": round(fee, 4),
            "pnl_after_fees": round(net, 4),
            "direction": position,
            "entry_price": entry_price,
            "exit_price": fill,
            "entry_bar": entry_bar_idx,
            "exit_bar": n-1,
            "bars_held": n - 1 - entry_bar_idx,
        })
        equity += net

    return trades, equity_curve, equity


def run_simple_spot(data, atr_period, multiplier, source, start_bar=200):
    """
    Simplest possible backtest: spot, no leverage, no fees, no slippage.
    Buy $500 when ST flips bull, sell when ST flips bear. No shorting.
    """
    n = data["n"]
    o, h, l, c, ts = data["opens"], data["highs"], data["lows"], data["closes"], data["timestamps"]

    st_line, st_dir = calc_supertrend(h, l, c, atr_period, multiplier, source)

    equity = 500.0
    btc_held = 0.0
    entry_price = 0.0
    trades = []

    for i in range(start_bar, n):
        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]):
            continue

        if st_dir[i] != st_dir[i-1]:
            if st_dir[i] == 1 and btc_held == 0:
                # Buy
                entry_price = c[i]
                btc_held = equity / entry_price
                trades.append({"type": "BUY", "price": entry_price,
                               "time": datetime.fromtimestamp(ts[i]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')})
            elif st_dir[i] == -1 and btc_held > 0:
                # Sell
                exit_price = c[i]
                pnl = (exit_price - entry_price) * btc_held
                equity += pnl
                trades.append({"type": "SELL", "price": exit_price, "pnl": round(pnl, 2),
                               "time": datetime.fromtimestamp(ts[i]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')})
                btc_held = 0.0

    # Close if still holding
    if btc_held > 0:
        pnl = (c[-1] - entry_price) * btc_held
        equity += pnl
        trades.append({"type": "SELL (EOD)", "price": c[-1], "pnl": round(pnl, 2),
                       "time": datetime.fromtimestamp(ts[-1]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')})

    return equity, trades


def main():
    print("=" * 100)
    print("BUG INVESTIGATION — 6 DIAGNOSTIC TESTS")
    print("=" * 100)

    data_15m = load_klines("binance_btc_15m.json")
    data_1h = load_klines("binance_btc_1h.json")
    n_15m = data_15m["n"]
    warmup = 200

    # Common params for Pure MTF
    MTF_ENTRY = (8, 4.0, "hlc3")
    MTF_CONFIRM = (10, 4.0, "close")

    # ═══════════════════════════════════════════════════════════
    # TEST 1: FIXED vs COMPOUNDING position sizing
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("TEST 1: FIXED SIZE ($125/trade) vs COMPOUNDING (25% of equity)")
    print(f"{'='*100}")

    # Fixed $125 per trade
    trades_fixed, _, eq_fixed = run_mtf_diagnostic(
        data_15m, data_1h, *MTF_ENTRY, *MTF_CONFIRM,
        start_bar=warmup, end_bar=n_15m,
        fixed_size=125.0, leverage=10.0,
    )

    # Compounding 25% of equity
    trades_compound, _, eq_compound = run_mtf_diagnostic(
        data_15m, data_1h, *MTF_ENTRY, *MTF_CONFIRM,
        start_bar=warmup, end_bar=n_15m,
        position_pct=0.25, leverage=10.0,
    )

    pnl_fixed = eq_fixed - 500
    pnl_compound = eq_compound - 500

    print(f"\n  Fixed ($125/trade, 10x lev = $1250 notional):")
    print(f"    Trades: {len(trades_fixed)}, Final: ${eq_fixed:.2f}, P&L: ${pnl_fixed:.2f} ({pnl_fixed/500*100:.1f}%)")
    print(f"    Total fees: ${sum(t['fee'] for t in trades_fixed):.2f}")
    print(f"    Total P&L before fees: ${sum(t['pnl_before_fees'] for t in trades_fixed):.2f}")

    print(f"\n  Compounding (25% x 10x):")
    print(f"    Trades: {len(trades_compound)}, Final: ${eq_compound:.2f}, P&L: ${pnl_compound:.2f} ({pnl_compound/500*100:.1f}%)")
    print(f"    Total fees: ${sum(t['fee'] for t in trades_compound):.2f}")
    print(f"    Total P&L before fees: ${sum(t['pnl_before_fees'] for t in trades_compound):.2f}")

    if pnl_fixed > 0 and pnl_compound < 0:
        print(f"\n  >>> DIAGNOSIS: Compounding death spiral confirmed! Fixed sizing is profitable.")
    elif pnl_fixed < 0 and pnl_compound < 0:
        print(f"\n  >>> DIAGNOSIS: Both negative. Problem is not compounding alone.")
    else:
        print(f"\n  >>> DIAGNOSIS: Both profitable or fixed worse. Compounding not the issue.")

    # ═══════════════════════════════════════════════════════════
    # TEST 2: FEE AUDIT
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("TEST 2: FEE AUDIT — Pure MTF, fixed $125, full 730 days")
    print(f"{'='*100}")

    # With fees (already have from test 1)
    total_fees = sum(t['fee'] for t in trades_fixed)
    total_pnl_before = sum(t['pnl_before_fees'] for t in trades_fixed)
    total_pnl_after = sum(t['pnl_after_fees'] for t in trades_fixed)

    # Zero fees run
    trades_nofee, _, eq_nofee = run_mtf_diagnostic(
        data_15m, data_1h, *MTF_ENTRY, *MTF_CONFIRM,
        start_bar=warmup, end_bar=n_15m,
        fixed_size=125.0, leverage=10.0,
        fees_enabled=False, slippage_enabled=False,
    )
    pnl_nofee = eq_nofee - 500

    # Zero fees but with slippage
    trades_nofee_slip, _, eq_nofee_slip = run_mtf_diagnostic(
        data_15m, data_1h, *MTF_ENTRY, *MTF_CONFIRM,
        start_bar=warmup, end_bar=n_15m,
        fixed_size=125.0, leverage=10.0,
        fees_enabled=False, slippage_enabled=True,
    )
    pnl_nofee_slip = eq_nofee_slip - 500

    # Maker fees (0.02% instead of 0.045%)
    trades_maker, _, eq_maker = run_mtf_diagnostic(
        data_15m, data_1h, *MTF_ENTRY, *MTF_CONFIRM,
        start_bar=warmup, end_bar=n_15m,
        fixed_size=125.0, leverage=10.0,
        taker_fee=0.00020,
    )
    pnl_maker = eq_maker - 500

    print(f"\n  {'Scenario':>35s} | {'P&L':>10s} {'Fees':>10s} {'Net':>10s}")
    print(f"  {'─'*35} | {'─'*10} {'─'*10} {'─'*10}")
    print(f"  {'Zero fees, zero slippage':>35s} | ${pnl_nofee:>9.2f} ${'0.00':>9s} ${pnl_nofee:>9.2f}")
    print(f"  {'Zero fees, with slippage (0.01%)':>35s} | ${pnl_nofee_slip:>9.2f} ${'0.00':>9s} ${pnl_nofee_slip:>9.2f}")
    print(f"  {'Maker fees (0.020%)':>35s} | ${sum(t['pnl_before_fees'] for t in trades_maker):>9.2f} ${sum(t['fee'] for t in trades_maker):>9.2f} ${pnl_maker:>9.2f}")
    print(f"  {'Taker fees (0.045%)':>35s} | ${total_pnl_before:>9.2f} ${total_fees:>9.2f} ${total_pnl_after:>9.2f}")

    print(f"\n  Fee breakdown:")
    print(f"    Trades: {len(trades_fixed)}")
    print(f"    Avg notional per trade: $1,250 (fixed)")
    print(f"    Taker fee per trade: ${1250 * 0.00045:.4f}")
    print(f"    Total taker fees: ${total_fees:.2f}")
    print(f"    Fees as % of gross profit: {total_fees / total_pnl_before * 100:.1f}%" if total_pnl_before > 0 else "    Gross P&L is negative even before fees!")

    edge_pct = pnl_nofee / (len(trades_fixed) * 1250) * 100 if trades_fixed else 0
    fee_pct = total_fees / (len(trades_fixed) * 1250) * 100 if trades_fixed else 0
    print(f"\n  Edge per trade (no fees): {edge_pct:.4f}% of notional")
    print(f"  Fee per trade:            {fee_pct:.4f}% of notional")
    print(f"  Net edge per trade:       {edge_pct - fee_pct:.4f}% of notional")

    # ═══════════════════════════════════════════════════════════
    # TEST 3: ENTRY TIMING — close vs next open
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("TEST 3: ENTRY TIMING — signal bar close vs next bar open")
    print(f"{'='*100}")

    # Entry at next bar open (current behavior)
    trades_open, _, eq_open = run_mtf_diagnostic(
        data_15m, data_1h, *MTF_ENTRY, *MTF_CONFIRM,
        start_bar=warmup, end_bar=n_15m,
        fixed_size=125.0, leverage=10.0,
        entry_on_close=False,
    )

    # Entry at signal bar close
    trades_close, _, eq_close = run_mtf_diagnostic(
        data_15m, data_1h, *MTF_ENTRY, *MTF_CONFIRM,
        start_bar=warmup, end_bar=n_15m,
        fixed_size=125.0, leverage=10.0,
        entry_on_close=True,
    )

    pnl_open = eq_open - 500
    pnl_close = eq_close - 500

    print(f"\n  Entry at NEXT BAR OPEN:    P&L ${pnl_open:.2f} ({len(trades_open)} trades)")
    print(f"  Entry at SIGNAL BAR CLOSE: P&L ${pnl_close:.2f} ({len(trades_close)} trades)")
    print(f"  Difference: ${pnl_close - pnl_open:.2f} ({'close better' if pnl_close > pnl_open else 'open better'})")

    # Show slippage between close and next open
    if trades_open and trades_close:
        slip_diffs = []
        for to, tc in zip(trades_open[:20], trades_close[:20]):
            slip_diffs.append(abs(to["entry_price"] - tc["entry_price"]))
        print(f"  Avg price difference (close vs open): ${np.mean(slip_diffs):.2f} ({np.mean(slip_diffs)/trades_open[0]['entry_price']*100:.4f}%)")

    # ═══════════════════════════════════════════════════════════
    # TEST 4: SANITY CHECK — simplest possible Supertrend on 1H
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("TEST 4: SANITY CHECK — ST(10, 3.0, hl2) on 1H, SPOT, no leverage/fees/slippage")
    print(f"{'='*100}")

    eq_spot, spot_trades = run_simple_spot(data_1h, 10, 3.0, "hl2", start_bar=50)
    pnl_spot = eq_spot - 500

    wins_spot = [t for t in spot_trades if t.get("pnl", 0) > 0]
    losses_spot = [t for t in spot_trades if t.get("pnl", 0) < 0]
    sell_trades = [t for t in spot_trades if t["type"].startswith("SELL")]

    print(f"\n  Final equity: ${eq_spot:.2f}")
    print(f"  P&L: ${pnl_spot:.2f} ({pnl_spot/500*100:.1f}%)")
    print(f"  Buy/Sell cycles: {len(sell_trades)}")
    print(f"  Wins: {len(wins_spot)}, Losses: {len(losses_spot)}")
    if sell_trades:
        gp = sum(t["pnl"] for t in wins_spot)
        gl = abs(sum(t["pnl"] for t in losses_spot))
        pf = gp / gl if gl > 0 else 9999
        print(f"  PF: {pf:.2f}")

    # BTC price change over period
    btc_start = data_1h["closes"][50]
    btc_end = data_1h["closes"][-1]
    bh_return = (btc_end - btc_start) / btc_start * 100
    bh_pnl = 500 * (btc_end / btc_start) - 500
    print(f"\n  BTC buy & hold: ${btc_start:.0f} -> ${btc_end:.0f} ({bh_return:.1f}%, P&L ${bh_pnl:.2f})")

    # Also test other TFs for sanity
    for tf_name, tf_file, tf_start in [("15m", "binance_btc_15m.json", 200),
                                        ("4h", "binance_btc_4h.json", 50)]:
        tf_data = load_klines(tf_file)
        eq_tf, _ = run_simple_spot(tf_data, 10, 3.0, "hl2", start_bar=tf_start)
        print(f"  ST(10,3.0,hl2) spot on {tf_name}: ${eq_tf:.2f} (P&L ${eq_tf-500:.2f}, {(eq_tf-500)/500*100:.1f}%)")

    # ═══════════════════════════════════════════════════════════
    # TEST 5: LAST 20 SUPERTREND FLIPS on 1H
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("TEST 5: LAST 20 SUPERTREND DIRECTION CHANGES — ST(10, 3.0, hl2) on 1H")
    print(f"{'='*100}")

    h1_st, h1_dir = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"], 10, 3.0, "hl2")

    flips = []
    for i in range(1, data_1h["n"]):
        if h1_dir[i] != h1_dir[i-1] and not np.isnan(h1_dir[i]):
            dt = datetime.fromtimestamp(data_1h["timestamps"][i]/1000, tz=timezone.utc)
            flips.append({
                "idx": i,
                "time": dt.strftime('%Y-%m-%d %H:%M UTC'),
                "direction": "BULL" if h1_dir[i] == 1 else "BEAR",
                "close": data_1h["closes"][i],
                "st_line": round(h1_st[i], 2),
            })

    print(f"\n  Total flips: {len(flips)}")
    print(f"\n  Last 20 flips (verify on TradingView — BTCUSDT, 1H, Supertrend 10/3.0):")
    print(f"  {'#':>3s} {'Date/Time':>22s} {'Direction':>9s} {'Close':>12s} {'ST Line':>12s}")
    print(f"  {'─'*3} {'─'*22} {'─'*9} {'─'*12} {'─'*12}")
    for i, f in enumerate(flips[-20:]):
        print(f"  {i+1:>3d} {f['time']:>22s} {f['direction']:>9s} ${f['close']:>11.2f} ${f['st_line']:>11.2f}")

    # ═══════════════════════════════════════════════════════════
    # TEST 6: P&L PER TRADE DISTRIBUTION
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("TEST 6: P&L DISTRIBUTION — Pure MTF, fixed $125, 730 days")
    print(f"{'='*100}")

    # Use trades_fixed from test 1
    trades = trades_fixed

    pnl_before = [t["pnl_before_fees"] for t in trades]
    pnl_after = [t["pnl_after_fees"] for t in trades]
    fees = [t["fee"] for t in trades]

    print(f"\n  Total trades: {len(trades)}")

    # Before fees
    wins_before = sum(1 for p in pnl_before if p > 0)
    losses_before = sum(1 for p in pnl_before if p <= 0)
    print(f"\n  BEFORE FEES:")
    print(f"    Winners: {wins_before} ({wins_before/len(trades)*100:.1f}%)")
    print(f"    Losers:  {losses_before} ({losses_before/len(trades)*100:.1f}%)")
    print(f"    Avg P&L: ${np.mean(pnl_before):.4f}")
    print(f"    Total:   ${sum(pnl_before):.2f}")

    # After fees
    wins_after = sum(1 for p in pnl_after if p > 0)
    losses_after = sum(1 for p in pnl_after if p <= 0)
    print(f"\n  AFTER FEES:")
    print(f"    Winners: {wins_after} ({wins_after/len(trades)*100:.1f}%)")
    print(f"    Losers:  {losses_after} ({losses_after/len(trades)*100:.1f}%)")
    print(f"    Avg P&L: ${np.mean(pnl_after):.4f}")
    print(f"    Total:   ${sum(pnl_after):.2f}")

    # Trades flipped from win to loss by fees
    flipped = sum(1 for pb, pa in zip(pnl_before, pnl_after) if pb > 0 and pa <= 0)
    print(f"\n  Trades FLIPPED from win to loss by fees: {flipped} ({flipped/len(trades)*100:.1f}%)")

    # Small losses band
    small_loss_before = sum(1 for p in pnl_before if -5 < p <= 0)
    small_loss_after = sum(1 for p in pnl_after if -5 < p <= 0)
    tiny_loss_range = sum(1 for p in pnl_after if -2 < p <= 0)

    print(f"\n  Small losses (between -$5 and $0):")
    print(f"    Before fees: {small_loss_before}")
    print(f"    After fees:  {small_loss_after}")
    print(f"    Tiny losses (-$2 to $0) after fees: {tiny_loss_range}")

    # Fee per trade
    avg_fee = np.mean(fees)
    print(f"\n  Fee per trade: ${avg_fee:.4f}")
    print(f"  Avg P&L before fees: ${np.mean(pnl_before):.4f}")
    print(f"  Avg P&L after fees:  ${np.mean(pnl_after):.4f}")
    print(f"  Fee as % of avg gross P&L: {avg_fee / abs(np.mean(pnl_before)) * 100:.1f}%" if np.mean(pnl_before) != 0 else "")

    # Distribution buckets
    print(f"\n  P&L distribution (after fees):")
    buckets = [
        ("< -$50", lambda p: p < -50),
        ("-$50 to -$20", lambda p: -50 <= p < -20),
        ("-$20 to -$10", lambda p: -20 <= p < -10),
        ("-$10 to -$5", lambda p: -10 <= p < -5),
        ("-$5 to $0", lambda p: -5 <= p < 0),
        ("$0 to $5", lambda p: 0 <= p < 5),
        ("$5 to $10", lambda p: 5 <= p < 10),
        ("$10 to $20", lambda p: 10 <= p < 20),
        ("$20 to $50", lambda p: 20 <= p < 50),
        ("> $50", lambda p: p >= 50),
    ]
    for label, cond in buckets:
        count = sum(1 for p in pnl_after if cond(p))
        total_in_bucket = sum(p for p in pnl_after if cond(p))
        bar = "#" * count
        print(f"    {label:>15s}: {count:>4d} (${total_in_bucket:>8.2f}) {bar}")

    # ═══════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("SUMMARY OF FINDINGS")
    print(f"{'='*100}")

    print(f"\n  1. COMPOUNDING: Fixed ${pnl_fixed:.0f} vs Compound ${pnl_compound:.0f}")
    print(f"  2. FEES: Zero-fee P&L ${pnl_nofee:.0f}, Maker-fee P&L ${pnl_maker:.0f}, Taker-fee P&L ${pnl_fixed:.0f}")
    print(f"  3. ENTRY TIMING: Next-open ${pnl_open:.0f} vs Close ${pnl_close:.0f} (diff ${pnl_close-pnl_open:.0f})")
    print(f"  4. SANITY: 1H spot (no fees/lev) ${pnl_spot:.0f} ({pnl_spot/500*100:.1f}%), BTC buy&hold ${bh_pnl:.0f} ({bh_return:.1f}%)")
    print(f"  5. Flip dates printed above for TradingView verification")
    print(f"  6. Trades flipped win->loss by fees: {flipped}/{len(trades)} ({flipped/len(trades)*100:.1f}%)")

    if pnl_nofee > 0 and pnl_fixed < 0:
        print(f"\n  >>> ROOT CAUSE: Strategy has edge (${pnl_nofee:.0f} without fees) but fees destroy it (${total_fees:.0f} total)")
        print(f"  >>> SOLUTION: Use maker orders (0.020% vs 0.045%) -> P&L ${pnl_maker:.0f}")
    elif pnl_nofee < 0:
        print(f"\n  >>> ROOT CAUSE: Strategy has NO edge even without fees on 15m MTF over full period")
        print(f"  >>> The 1H spot sanity check returned ${pnl_spot:.0f} — {'strategy works on higher TF' if pnl_spot > 0 else 'problem may be in calculation'}")


if __name__ == "__main__":
    main()
