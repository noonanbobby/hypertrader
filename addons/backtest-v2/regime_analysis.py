#!/usr/bin/env python3
"""
Regime analysis: ADX-based market regime breakdown + quarterly P&L for both configs.
Runs on FULL 730 days (not just validation) for maximum data.
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


def calc_adx(highs, lows, closes, period=14):
    """ADX calculation matching TradingView's ta.adx / DMI."""
    n = len(closes)
    adx = np.full(n, np.nan)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)

    if n < period + 1:
        return adx, plus_di, minus_di

    # +DM and -DM
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # True Range
    tr = calc_tr(highs, lows, closes)

    # Smoothed with RMA (Wilder's)
    def rma(data, period):
        out = np.full(len(data), np.nan)
        out[period] = np.sum(data[1:period+1])  # first value is sum of first `period`
        for i in range(period + 1, len(data)):
            out[i] = out[i-1] - out[i-1] / period + data[i]
        return out

    smooth_tr = rma(tr, period)
    smooth_plus_dm = rma(plus_dm, period)
    smooth_minus_dm = rma(minus_dm, period)

    # +DI and -DI
    for i in range(period, n):
        if smooth_tr[i] and not np.isnan(smooth_tr[i]) and smooth_tr[i] > 0:
            plus_di[i] = 100 * smooth_plus_dm[i] / smooth_tr[i]
            minus_di[i] = 100 * smooth_minus_dm[i] / smooth_tr[i]

    # DX
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if not np.isnan(plus_di[i]) and not np.isnan(minus_di[i]):
            s = plus_di[i] + minus_di[i]
            if s > 0:
                dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / s

    # ADX = RMA of DX
    # Find first valid DX
    first_valid = period
    while first_valid < n and np.isnan(dx[first_valid]):
        first_valid += 1

    if first_valid + period >= n:
        return adx, plus_di, minus_di

    # First ADX = mean of first `period` valid DX values
    adx[first_valid + period - 1] = np.nanmean(dx[first_valid:first_valid + period])
    for i in range(first_valid + period, n):
        if not np.isnan(dx[i]) and not np.isnan(adx[i-1]):
            adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period

    return adx, plus_di, minus_di


def run_mtf_with_trade_regimes(data_15m, data_1h, adx_15m,
                                entry_atr, entry_mult, entry_src,
                                confirm_atr, confirm_mult, confirm_src,
                                position_pct, leverage, start_bar, end_bar,
                                vol_enabled=False, vol_threshold=1.25,
                                time_enabled=False, time_block_start=22, time_block_end=6,
                                sl_enabled=False, sl_atr_mult=5.0,
                                starting_capital=500.0, taker_fee=0.00045, slippage=0.0001):
    """MTF backtest that tags each trade with the ADX regime at entry."""
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

    o, h, l, c, v, ts = d["opens"][:n], d["highs"][:n], d["lows"][:n], d["closes"][:n], d["volumes"][:n], d["timestamps"][:n]
    st_line, st_dir = calc_supertrend(h, l, c, entry_atr, entry_mult, entry_src)

    vol_sma = calc_sma(v, 20) if vol_enabled else None
    atr = calc_atr(h, l, c, entry_atr) if sl_enabled else None

    equity = starting_capital
    position = 0
    entry_price = 0.0
    position_size = 0.0
    entry_bar_idx = 0
    entry_adx = 0.0
    trades = []
    equity_curve = []
    pending = None

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending
            pending = None

            if action == "close" and position != 0:
                fill = o[i] - o[i] * slippage * position
                pnl = (fill - entry_price) * position * (position_size / entry_price)
                fee = position_size * taker_fee
                net = pnl - fee
                trades.append({
                    "pnl": net, "direction": position,
                    "entry_bar": entry_bar_idx, "exit_bar": i,
                    "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                    "adx_at_entry": entry_adx,
                    "entry_price": entry_price, "exit_price": fill,
                })
                equity += net
                position = 0
                position_size = 0.0

            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_close = o[i] - o[i] * slippage * position
                    pnl = (fill_close - entry_price) * position * (position_size / entry_price)
                    fee = position_size * taker_fee
                    net = pnl - fee
                    trades.append({
                        "pnl": net, "direction": position,
                        "entry_bar": entry_bar_idx, "exit_bar": i,
                        "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                        "adx_at_entry": entry_adx,
                        "entry_price": entry_price, "exit_price": fill_close,
                    })
                    equity += net

                if equity <= 0:
                    position = 0
                    continue

                new_dir = 1 if "long" in action else -1
                fill_open = o[i] + o[i] * slippage * new_dir
                position_size = equity * position_pct * leverage
                fee = position_size * taker_fee
                equity -= fee
                position = new_dir
                entry_price = fill_open
                entry_bar_idx = i
                entry_adx = adx_15m[i] if not np.isnan(adx_15m[i]) else 0.0

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

        # Stop loss
        if sl_enabled and position != 0 and atr is not None and not np.isnan(atr[i]):
            sl_dist = (sl_atr_mult * atr[i]) / entry_price
            if (position == 1 and c[i] < entry_price * (1 - sl_dist)) or \
               (position == -1 and c[i] > entry_price * (1 + sl_dist)):
                pending = "close"
                continue

        if st_dir[i] == st_dir[i-1]:
            continue

        new_dir = 1 if st_dir[i] == 1 else -1

        if htf_dir[i] != new_dir:
            if position != 0:
                pending = "close"
            continue

        if vol_enabled and vol_sma is not None and not np.isnan(vol_sma[i]):
            if v[i] < vol_threshold * vol_sma[i]:
                continue

        if time_enabled:
            hour_utc = (int(ts[i]) // 3600000) % 24
            if time_block_start > time_block_end:
                if hour_utc >= time_block_start or hour_utc < time_block_end:
                    continue
            else:
                if time_block_start <= hour_utc < time_block_end:
                    continue

        if position == 0:
            pending = "open_long" if new_dir == 1 else "open_short"
        elif position != new_dir:
            pending = "flip_long" if new_dir == 1 else "flip_short"

    # Close remaining
    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - slippage * position)
        pnl = (fill - entry_price) * position * (position_size / entry_price)
        fee = position_size * taker_fee
        net = pnl - fee
        trades.append({
            "pnl": net, "direction": position,
            "entry_bar": entry_bar_idx, "exit_bar": n-1,
            "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[n-1]),
            "adx_at_entry": entry_adx,
            "entry_price": entry_price, "exit_price": fill,
        })
        equity += net

    return trades, equity_curve, equity


def regime_stats(trades, label):
    """Break down trades by ADX regime."""
    trending = [t for t in trades if t["adx_at_entry"] >= 25]
    ranging = [t for t in trades if t["adx_at_entry"] < 20]
    neutral = [t for t in trades if 20 <= t["adx_at_entry"] < 25]

    def stats(tlist, name):
        if not tlist:
            return {"regime": name, "trades": 0, "pnl": 0, "win_rate": 0, "pf": 0, "avg_pnl": 0,
                    "wins": 0, "losses": 0, "gross_profit": 0, "gross_loss": 0}
        pnl = sum(t["pnl"] for t in tlist)
        wins = [t for t in tlist if t["pnl"] > 0]
        losses = [t for t in tlist if t["pnl"] <= 0]
        gp = sum(t["pnl"] for t in wins)
        gl = abs(sum(t["pnl"] for t in losses))
        pf = gp / gl if gl > 0 else 9999.0
        return {
            "regime": name, "trades": len(tlist), "pnl": round(pnl, 2),
            "win_rate": round(len(wins)/len(tlist)*100, 1),
            "pf": round(pf, 2), "avg_pnl": round(pnl/len(tlist), 2),
            "wins": len(wins), "losses": len(losses),
            "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
        }

    return {
        "trending": stats(trending, "Trending (ADX>=25)"),
        "ranging": stats(ranging, "Ranging (ADX<20)"),
        "neutral": stats(neutral, "Neutral (ADX 20-25)"),
        "all": stats(trades, "ALL"),
    }


def quarterly_breakdown(trades, timestamps):
    """Break trades into calendar quarters."""
    quarters = {}
    for t in trades:
        dt = datetime.fromtimestamp(t["entry_time"]/1000, tz=timezone.utc)
        q_key = f"{dt.year}-Q{(dt.month-1)//3+1}"
        if q_key not in quarters:
            quarters[q_key] = []
        quarters[q_key].append(t)

    results = {}
    for q_key in sorted(quarters.keys()):
        tlist = quarters[q_key]
        pnl = sum(t["pnl"] for t in tlist)
        wins = [t for t in tlist if t["pnl"] > 0]
        losses = [t for t in tlist if t["pnl"] <= 0]
        gp = sum(t["pnl"] for t in wins)
        gl = abs(sum(t["pnl"] for t in losses))
        pf = gp / gl if gl > 0 else 9999.0

        # ADX distribution this quarter
        adx_vals = [t["adx_at_entry"] for t in tlist if t["adx_at_entry"] > 0]
        avg_adx = np.mean(adx_vals) if adx_vals else 0

        results[q_key] = {
            "trades": len(tlist), "pnl": round(pnl, 2),
            "win_rate": round(len(wins)/len(tlist)*100, 1) if tlist else 0,
            "pf": round(pf, 2), "avg_adx": round(avg_adx, 1),
            "trending_pct": round(sum(1 for a in adx_vals if a >= 25)/len(adx_vals)*100, 0) if adx_vals else 0,
        }
    return results


def print_regime_table(regimes, label):
    print(f"\n  {label}")
    print(f"  {'Regime':>22s} | {'Trades':>6s} {'Wins':>5s} {'Loss':>5s} {'Win%':>6s} | {'P&L $':>9s} {'Avg P&L':>9s} {'PF':>6s} | {'Gross+':>9s} {'Gross-':>9s}")
    print(f"  {'─'*22} | {'─'*6} {'─'*5} {'─'*5} {'─'*6} | {'─'*9} {'─'*9} {'─'*6} | {'─'*9} {'─'*9}")
    for key in ["trending", "ranging", "neutral", "all"]:
        r = regimes[key]
        marker = " <--" if key == "all" else ""
        print(f"  {r['regime']:>22s} | {r['trades']:>6d} {r['wins']:>5d} {r['losses']:>5d} {r['win_rate']:>5.1f}% | "
              f"${r['pnl']:>8.2f} ${r['avg_pnl']:>8.2f} {r['pf']:>6.2f} | "
              f"${r['gross_profit']:>8.2f} ${r['gross_loss']:>8.2f}{marker}")


def main():
    print("=" * 100)
    print("REGIME ANALYSIS — Full 730-day dataset")
    print("=" * 100)

    data_15m = load_klines("binance_btc_15m.json")
    data_1h = load_klines("binance_btc_1h.json")
    n = data_15m["n"]

    # Compute ADX on 15m data
    print("\n  Computing ADX(14) on 15m data...")
    adx_15m, plus_di, minus_di = calc_adx(data_15m["highs"], data_15m["lows"], data_15m["closes"], 14)

    # ADX distribution summary
    valid_adx = adx_15m[~np.isnan(adx_15m)]
    print(f"  ADX stats: mean={np.mean(valid_adx):.1f}, median={np.median(valid_adx):.1f}, "
          f"min={np.min(valid_adx):.1f}, max={np.max(valid_adx):.1f}")
    print(f"  Trending (>=25): {np.sum(valid_adx >= 25)/len(valid_adx)*100:.1f}% of bars")
    print(f"  Ranging  (<20):  {np.sum(valid_adx < 20)/len(valid_adx)*100:.1f}% of bars")
    print(f"  Neutral  (20-25):{np.sum((valid_adx >= 20) & (valid_adx < 25))/len(valid_adx)*100:.1f}% of bars")

    ts = data_15m["timestamps"]
    start_dt = datetime.fromtimestamp(ts[0]/1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(ts[-1]/1000, tz=timezone.utc)
    print(f"  Period: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")

    # Run both configs on FULL dataset (warmup=200, so effectively from bar 200)
    warmup = 200

    configs = {
        "Filtered MTF (Vol+Time+SL)": {
            "vol_enabled": True, "vol_threshold": 1.25,
            "time_enabled": True, "time_block_start": 22, "time_block_end": 6,
            "sl_enabled": True, "sl_atr_mult": 5.0,
        },
        "Pure MTF (no filters)": {
            "vol_enabled": False, "time_enabled": False, "sl_enabled": False,
        },
    }

    all_results = {}

    for config_name, cfg in configs.items():
        print(f"\n{'='*100}")
        print(f"  {config_name} — 35% position, 10x leverage, compounding")
        print(f"{'='*100}")

        trades, eq_curve, final_eq = run_mtf_with_trade_regimes(
            data_15m, data_1h, adx_15m,
            entry_atr=8, entry_mult=4.0, entry_src="hlc3",
            confirm_atr=10, confirm_mult=4.0, confirm_src="close",
            position_pct=0.35, leverage=10.0,
            start_bar=warmup, end_bar=n,
            **cfg,
        )

        total_pnl = final_eq - 500
        print(f"  Total trades: {len(trades)}, Final equity: ${final_eq:.2f}, P&L: ${total_pnl:.2f} ({total_pnl/500*100:.1f}%)")

        # Regime breakdown
        regimes = regime_stats(trades, config_name)
        print_regime_table(regimes, config_name)

        # Quarterly breakdown
        quarters = quarterly_breakdown(trades, ts)
        print(f"\n  QUARTERLY BREAKDOWN:")
        print(f"  {'Quarter':>10s} | {'Trades':>6s} {'Win%':>6s} {'PF':>6s} {'P&L $':>9s} | {'AvgADX':>6s} {'%Trend':>7s}")
        print(f"  {'─'*10} | {'─'*6} {'─'*6} {'─'*6} {'─'*9} | {'─'*6} {'─'*7}")

        cumulative_pnl = 0
        profitable_quarters = 0
        total_quarters = 0
        for q_key, q in sorted(quarters.items()):
            cumulative_pnl += q["pnl"]
            total_quarters += 1
            if q["pnl"] > 0:
                profitable_quarters += 1
            marker = " +" if q["pnl"] > 0 else " -"
            print(f"  {q_key:>10s} | {q['trades']:>6d} {q['win_rate']:>5.1f}% {q['pf']:>6.2f} ${q['pnl']:>8.2f} | "
                  f"{q['avg_adx']:>6.1f} {q['trending_pct']:>6.0f}%{marker}")

        print(f"\n  Profitable quarters: {profitable_quarters}/{total_quarters}")

        # Long vs Short breakdown
        longs = [t for t in trades if t["direction"] == 1]
        shorts = [t for t in trades if t["direction"] == -1]
        long_pnl = sum(t["pnl"] for t in longs)
        short_pnl = sum(t["pnl"] for t in shorts)
        print(f"\n  Direction breakdown:")
        print(f"    Longs:  {len(longs)} trades, P&L ${long_pnl:.2f}")
        print(f"    Shorts: {len(shorts)} trades, P&L ${short_pnl:.2f}")

        all_results[config_name] = {
            "regimes": regimes,
            "quarters": quarters,
            "total_trades": len(trades),
            "final_equity": round(final_eq, 2),
            "total_pnl": round(total_pnl, 2),
            "profitable_quarters": profitable_quarters,
            "total_quarters": total_quarters,
            "long_pnl": round(long_pnl, 2),
            "short_pnl": round(short_pnl, 2),
        }

    # ═══════════════════════════════════════════════════════════
    # HEAD-TO-HEAD COMPARISON
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'='*100}")
    print("HEAD-TO-HEAD COMPARISON")
    print(f"{'='*100}")

    filt = all_results["Filtered MTF (Vol+Time+SL)"]
    pure = all_results["Pure MTF (no filters)"]

    print(f"\n  {'Metric':>35s} | {'Filtered':>12s} {'Pure':>12s} {'Winner':>10s}")
    print(f"  {'─'*35} | {'─'*12} {'─'*12} {'─'*10}")

    def compare(label, fv, pv, higher_is_better=True):
        fw = "Filtered" if (fv > pv if higher_is_better else fv < pv) else "Pure" if (pv > fv if higher_is_better else pv < fv) else "TIE"
        print(f"  {label:>35s} | {fv:>12s} {pv:>12s} {fw:>10s}")

    compare("Total P&L", f"${filt['total_pnl']:.0f}", f"${pure['total_pnl']:.0f}")
    compare("Total trades", str(filt['total_trades']), str(pure['total_trades']), False)

    # Regime comparison
    for regime in ["trending", "ranging", "neutral"]:
        fr = filt["regimes"][regime]
        pr = pure["regimes"][regime]
        compare(f"P&L in {fr['regime']}", f"${fr['pnl']:.0f}", f"${pr['pnl']:.0f}")
        compare(f"PF in {fr['regime']}", f"{fr['pf']:.2f}", f"{pr['pf']:.2f}")

    compare("Profitable quarters", f"{filt['profitable_quarters']}/{filt['total_quarters']}",
            f"{pure['profitable_quarters']}/{pure['total_quarters']}")

    # Which config has positive P&L in all three regimes?
    print(f"\n  POSITIVE P&L IN ALL REGIMES?")
    for name, r in all_results.items():
        trending_ok = r["regimes"]["trending"]["pnl"] > 0
        ranging_ok = r["regimes"]["ranging"]["pnl"] > 0
        neutral_ok = r["regimes"]["neutral"]["pnl"] > 0
        all_positive = trending_ok and ranging_ok and neutral_ok
        print(f"    {name}: Trending={'YES' if trending_ok else 'NO'} "
              f"Ranging={'YES' if ranging_ok else 'NO'} "
              f"Neutral={'YES' if neutral_ok else 'NO'} "
              f"-> {'ALL POSITIVE' if all_positive else 'NOT ALL POSITIVE'}")

    # Worst regime comparison
    print(f"\n  WORST REGIME LOSS:")
    for name, r in all_results.items():
        worst = min(r["regimes"][k]["pnl"] for k in ["trending", "ranging", "neutral"])
        worst_name = min(["trending", "ranging", "neutral"], key=lambda k: r["regimes"][k]["pnl"])
        print(f"    {name}: ${worst:.2f} in {r['regimes'][worst_name]['regime']}")

    # Quarterly comparison
    print(f"\n  QUARTERLY HEAD-TO-HEAD:")
    print(f"  {'Quarter':>10s} | {'Filtered $':>11s} {'Pure $':>11s} | {'Winner':>10s}")
    print(f"  {'─'*10} | {'─'*11} {'─'*11} | {'─'*10}")

    all_quarters = sorted(set(list(filt["quarters"].keys()) + list(pure["quarters"].keys())))
    filt_cum = 0
    pure_cum = 0
    for q in all_quarters:
        fq = filt["quarters"].get(q, {"pnl": 0})
        pq = pure["quarters"].get(q, {"pnl": 0})
        filt_cum += fq["pnl"]
        pure_cum += pq["pnl"]
        w = "Filtered" if fq["pnl"] > pq["pnl"] else "Pure" if pq["pnl"] > fq["pnl"] else "TIE"
        print(f"  {q:>10s} | ${fq['pnl']:>10.2f} ${pq['pnl']:>10.2f} | {w:>10s}")

    print(f"  {'CUMULATIVE':>10s} | ${filt_cum:>10.2f} ${pure_cum:>10.2f} | {'Filtered' if filt_cum > pure_cum else 'Pure':>10s}")

    # ═══════════════════════════════════════════════════════════
    # VERDICT
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("VERDICT")
    print(f"{'='*100}")

    # Score: +1 for each regime profitable, +1 for each quarter won, +1 for lower worst-regime loss
    filt_score = 0
    pure_score = 0

    for regime in ["trending", "ranging", "neutral"]:
        if filt["regimes"][regime]["pnl"] > 0: filt_score += 1
        if pure["regimes"][regime]["pnl"] > 0: pure_score += 1

    filt_worst = min(filt["regimes"][k]["pnl"] for k in ["trending", "ranging", "neutral"])
    pure_worst = min(pure["regimes"][k]["pnl"] for k in ["trending", "ranging", "neutral"])
    if filt_worst > pure_worst: filt_score += 1
    else: pure_score += 1

    if filt["profitable_quarters"] > pure["profitable_quarters"]: filt_score += 1
    elif pure["profitable_quarters"] > filt["profitable_quarters"]: pure_score += 1

    if filt["total_pnl"] > pure["total_pnl"]: filt_score += 1
    else: pure_score += 1

    print(f"\n  Filtered MTF score: {filt_score}")
    print(f"  Pure MTF score:     {pure_score}")

    winner = "Filtered MTF" if filt_score > pure_score else "Pure MTF" if pure_score > filt_score else "TIE"
    print(f"\n  WINNER: {winner}")

    # Save
    out_path = Path(__file__).parent / "regime_analysis.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")


if __name__ == "__main__":
    main()
