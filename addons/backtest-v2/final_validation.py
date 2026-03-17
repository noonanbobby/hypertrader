#!/usr/bin/env python3
"""
FINAL validation: walk-forward, starting points, parameter robustness.
"""

import numpy as np
from pathlib import Path
import json
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_supertrend, calc_tr


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
    n = len(closes); adx = np.full(n, np.nan)
    if n < period*2+1: return adx
    plus_dm = np.zeros(n); minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i]-highs[i-1]; down = lows[i-1]-lows[i]
        if up > down and up > 0: plus_dm[i] = up
        if down > up and down > 0: minus_dm[i] = down
    tr = calc_tr(highs, lows, closes)
    def rma(data, p):
        out = np.full(len(data), np.nan); out[p] = np.sum(data[1:p+1])
        for i in range(p+1, len(data)): out[i] = out[i-1]-out[i-1]/p+data[i]
        return out
    s_tr = rma(tr, period); s_pdm = rma(plus_dm, period); s_mdm = rma(minus_dm, period)
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if s_tr[i] and not np.isnan(s_tr[i]) and s_tr[i] > 0:
            pdi = 100*s_pdm[i]/s_tr[i]; mdi = 100*s_mdm[i]/s_tr[i]; s = pdi+mdi
            if s > 0: dx[i] = 100*abs(pdi-mdi)/s
    fv = period
    while fv < n and np.isnan(dx[fv]): fv += 1
    if fv+period >= n: return adx
    adx[fv+period-1] = np.nanmean(dx[fv:fv+period])
    for i in range(fv+period, n):
        if not np.isnan(dx[i]) and not np.isnan(adx[i-1]):
            adx[i] = (adx[i-1]*(period-1)+dx[i])/period
    return adx


def run(data_15m, data_1h, entry_atr, entry_mult, entry_src,
        start_bar, end_bar, adx_values,
        fixed_size=125.0, leverage=10.0, taker_fee=0.00045, slippage=0.0001,
        starting_capital=500.0, adx_min=15, adx_rising_check=True):
    d = data_15m; n = min(end_bar, d["n"])
    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"], 10, 4.0, "close")
    h_ts = data_1h["timestamps"]
    htf_dir = np.ones(n); h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts)-1 and h_ts[h_idx+1] <= d["timestamps"][i]: h_idx += 1
        if h_idx < len(h_dirs): htf_dir[i] = h_dirs[h_idx]
    o,h,l,c,ts = d["opens"][:n],d["highs"][:n],d["lows"][:n],d["closes"][:n],d["timestamps"][:n]
    st_line, st_dir = calc_supertrend(h,l,c,entry_atr,entry_mult,entry_src)
    notional = fixed_size*leverage
    equity = starting_capital; position = 0; entry_price = 0.0; entry_bar = 0
    trades = []; equity_curve = []; pending = None
    lb = 4

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending; pending = None; ep = o[i]
            if action == "close" and position != 0:
                fill = ep-ep*slippage*position
                pnl = (fill-entry_price)*position*(notional/entry_price)-notional*taker_fee
                trades.append({"pnl": pnl, "entry_time": int(ts[entry_bar]), "exit_time": int(ts[i])})
                equity += pnl; position = 0
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_c = ep-ep*slippage*position
                    pnl = (fill_c-entry_price)*position*(notional/entry_price)-notional*taker_fee
                    trades.append({"pnl": pnl, "entry_time": int(ts[entry_bar]), "exit_time": int(ts[i])})
                    equity += pnl
                nd = 1 if "long" in action else -1
                equity -= notional*taker_fee
                position = nd; entry_price = ep+ep*slippage*nd; entry_bar = i
        if position != 0:
            equity_curve.append(equity+(c[i]-entry_price)*position*(notional/entry_price))
        else:
            equity_curve.append(equity)
        if i >= n-1:
            if position != 0: pending = "close"
            continue
        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]): continue
        if st_dir[i] == st_dir[i-1]: continue
        nd = 1 if st_dir[i] == 1 else -1
        if htf_dir[i] != nd:
            if position != 0: pending = "close"
            continue
        av = adx_values[i]
        if np.isnan(av) or av < adx_min:
            if position != 0: pending = "close"
            continue
        if adx_rising_check and i >= lb:
            prev = adx_values[i-lb]
            if np.isnan(prev) or av <= prev:
                if position != 0: pending = "close"
                continue
        if position == 0: pending = "open_long" if nd == 1 else "open_short"
        elif position != nd: pending = "flip_long" if nd == 1 else "flip_short"

    if pending == "close" and position != 0:
        fill = c[n-1]*(1-slippage*position)
        pnl = (fill-entry_price)*position*(notional/entry_price)-notional*taker_fee
        trades.append({"pnl": pnl, "entry_time": int(ts[entry_bar]), "exit_time": int(ts[n-1])})
        equity += pnl
    return trades, equity_curve, equity


def metrics(trades, ec=None, cap=500.0):
    if not trades: return {"n":0,"pnl":0,"pf":0,"wr":0,"mdd":0}
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"]>0]; gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"]<=0))
    pf = gp/gl if gl>0 else 9999; mdd = 0
    if ec:
        ea = np.array(ec); pk = np.maximum.accumulate(ea)
        if len(ea) > 0: mdd = float(np.max((pk-ea)/pk*100))
    return {"n":len(trades),"pnl":round(pnl,2),"pf":round(pf,2),
            "wr":round(len(wins)/len(trades)*100,1),"mdd":round(mdd,1)}


def main():
    print("="*100)
    print("FINAL VALIDATION — BTC Pure MTF + ADX>=15 + Rising")
    print("Config: ST(8, 4.0, hlc3) entry, ST(10, 4.0, close) 1H confirm")
    print("        Fixed $125, 10x leverage, 0.045% taker fees")
    print("="*100)

    btc_15m = load_klines("binance_btc_15m.json")
    btc_1h = load_klines("binance_btc_1h.json")
    n = btc_15m["n"]
    adx = calc_adx(btc_15m["highs"], btc_15m["lows"], btc_15m["closes"])
    warmup = 200

    ts = btc_15m["timestamps"]
    train_end = int(n * 0.7)
    train_dt = datetime.fromtimestamp(ts[train_end]/1000, tz=timezone.utc)

    # ═══════════════════════════════════════════════════════════
    # FULL PERIOD BASELINE
    # ═══════════════════════════════════════════════════════════
    trades_full, ec_full, eq_full = run(btc_15m, btc_1h, 8, 4.0, "hlc3",
                                         warmup, n, adx)
    m_full = metrics(trades_full, ec_full)
    print(f"\n  FULL 730 DAYS: {m_full['n']} trades, P&L ${m_full['pnl']:.0f} ({m_full['pnl']/500*100:.1f}%), "
          f"PF={m_full['pf']:.2f}, Win={m_full['wr']:.1f}%, MDD={m_full['mdd']:.1f}%")

    # ═══════════════════════════════════════════════════════════
    # 1. WALK-FORWARD
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print(f"1. WALK-FORWARD — Train: bars 0-{train_end} | Validate: bars {train_end}-{n}")
    print(f"   Split date: {train_dt.strftime('%Y-%m-%d')}")
    print(f"{'='*100}")

    t_train, ec_train, _ = run(btc_15m, btc_1h, 8, 4.0, "hlc3", warmup, train_end, adx)
    t_val, ec_val, _ = run(btc_15m, btc_1h, 8, 4.0, "hlc3", train_end, n, adx)
    m_train = metrics(t_train, ec_train)
    m_val = metrics(t_val, ec_val)

    print(f"\n  {'Period':>12s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s}")
    print(f"  {'─'*12} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6}")
    print(f"  {'TRAIN 70%':>12s} | {m_train['n']:>6d} ${m_train['pnl']:>7.0f} {m_train['pf']:>6.2f} {m_train['wr']:>5.1f}% {m_train['mdd']:>5.1f}%")
    print(f"  {'VALIDATE 30%':>12s} | {m_val['n']:>6d} ${m_val['pnl']:>7.0f} {m_val['pf']:>6.2f} {m_val['wr']:>5.1f}% {m_val['mdd']:>5.1f}%")

    wf_pass = m_val["pnl"] > 0 and m_val["pf"] > 1.0
    print(f"\n  WALK-FORWARD: {'PASS' if wf_pass else 'FAIL'} — Validation PF={m_val['pf']:.2f}, P&L=${m_val['pnl']:.0f}")

    # ═══════════════════════════════════════════════════════════
    # 2. STARTING POINT SENSITIVITY
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("2. STARTING POINT SENSITIVITY — 6 points, 120 days apart")
    print(f"{'='*100}")

    bars_120d = 120*24*4
    all_profitable = True

    print(f"\n  {'#':>3s} {'Start Date':>12s} {'Days':>5s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s}")
    print(f"  {'─'*3} {'─'*12} {'─'*5} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6}")

    for idx in range(6):
        sb = warmup + idx * bars_120d
        if sb >= n - 1000: break
        start_dt = datetime.fromtimestamp(ts[sb]/1000, tz=timezone.utc)
        days = (n - sb) / (24*4)
        trades_s, ec_s, _ = run(btc_15m, btc_1h, 8, 4.0, "hlc3", sb, n, adx)
        m = metrics(trades_s, ec_s)
        if m["pnl"] <= 0: all_profitable = False
        marker = "PASS" if m["pnl"] > 0 else "FAIL"
        print(f"  {idx+1:>3d} {start_dt.strftime('%Y-%m-%d'):>12s} {days:>5.0f} | {m['n']:>6d} ${m['pnl']:>7.0f} {m['pf']:>6.2f} {m['wr']:>5.1f}% {m['mdd']:>5.1f}% {marker}")

    print(f"\n  STARTING POINTS: {'PASS — all 6 profitable' if all_profitable else 'FAIL — some starting points lose money'}")

    # ═══════════════════════════════════════════════════════════
    # 3. PARAMETER ROBUSTNESS
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("3. PARAMETER ROBUSTNESS — +/-20% on multiplier and ATR period")
    print(f"{'='*100}")

    base_atr = 8; base_mult = 4.0
    all_robust = True

    print(f"\n  {'Variation':>25s} {'ATR':>4s} {'Mult':>5s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s}")
    print(f"  {'─'*25} {'─'*4} {'─'*5} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6}")

    variations = [
        ("BASE", base_atr, base_mult),
        ("Mult +10%", base_atr, round(base_mult * 1.1, 1)),
        ("Mult -10%", base_atr, round(base_mult * 0.9, 1)),
        ("Mult +20%", base_atr, round(base_mult * 1.2, 1)),
        ("Mult -20%", base_atr, round(base_mult * 0.8, 1)),
        ("ATR +1 (9)", 9, base_mult),
        ("ATR -1 (7)", 7, base_mult),
        ("ATR +2 (10)", 10, base_mult),
        ("ATR -2 (6)", 6, base_mult),
        ("Both +20%", round(base_atr * 1.2), round(base_mult * 1.2, 1)),
        ("Both -20%", round(base_atr * 0.8), round(base_mult * 0.8, 1)),
        ("ATR+20% Mult-20%", round(base_atr * 1.2), round(base_mult * 0.8, 1)),
        ("ATR-20% Mult+20%", round(base_atr * 0.8), round(base_mult * 1.2, 1)),
    ]

    for label, atr_p, mult in variations:
        trades_v, ec_v, _ = run(btc_15m, btc_1h, atr_p, mult, "hlc3", warmup, n, adx)
        m = metrics(trades_v, ec_v)
        if m["pnl"] <= 0: all_robust = False
        marker = "" if label == "BASE" else ("PASS" if m["pnl"] > 0 else "FAIL")
        print(f"  {label:>25s} {atr_p:>4d} {mult:>5.1f} | {m['n']:>6d} ${m['pnl']:>7.0f} {m['pf']:>6.2f} {m['wr']:>5.1f}% {m['mdd']:>5.1f}% {marker}")

    print(f"\n  PARAMETER ROBUSTNESS: {'PASS — all variations profitable' if all_robust else 'FAIL — some variations lose money'}")

    # ═══════════════════════════════════════════════════════════
    # OVERALL VERDICT
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("OVERALL VERDICT")
    print(f"{'='*100}")

    checks = [
        ("Walk-forward validation", wf_pass),
        ("All starting points profitable", all_profitable),
        ("All parameter variations profitable", all_robust),
    ]

    all_pass = True
    for label, passed in checks:
        status = "PASS" if passed else "FAIL"
        if not passed: all_pass = False
        print(f"  [{status}] {label}")

    if all_pass:
        print(f"\n  ALL THREE CHECKS PASS. Strategy is validated for deployment.")
    else:
        print(f"\n  SOME CHECKS FAILED. Review failures before deploying.")

    # ═══════════════════════════════════════════════════════════
    # TRADINGVIEW IMPLEMENTATION
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("TRADINGVIEW ALERT IMPLEMENTATION")
    print(f"{'='*100}")

    print(f"""
  The ADX rising check compares ADX now vs ADX 4 bars ago.
  In TradingView Pine Script, this is simply:

    adxValue = ta.adx(14)
    adxRising = adxValue > adxValue[4]

  For TradingView ALERTS (without Pine Script):

  OPTION A — Built-in alert conditions:
    TradingView's built-in alert on ADX doesn't support "rising" directly.
    You CAN set "ADX is Greater Than 15" as a condition, but NOT
    "ADX is Greater Than ADX 4 bars ago."

  OPTION B — Pine Script indicator alert (RECOMMENDED):
    Create a simple indicator that plots the combined signal:

    //@version=6
    indicator("MTF Supertrend + ADX Filter", overlay=true)

    // 15m Supertrend
    [st, dir] = ta.supertrend(4.0, 8)  // mult, atr_period — note: Pine order is reversed

    // ADX filter
    adxVal = ta.adx(14)
    adxRising = adxVal > adxVal[4]
    adxOk = adxVal >= 15 and adxRising

    // 1H Supertrend confirmation (request 1H data)
    [st1h, dir1h] = request.security(syminfo.tickerid, "60", ta.supertrend(4.0, 10))

    // Combined signals
    longSignal = dir == 1 and dir[1] == -1 and dir1h == 1 and adxOk
    shortSignal = dir == -1 and dir[1] == 1 and dir1h == -1 and adxOk

    // Plot signals
    plotshape(longSignal, "Long", shape.triangleup, location.belowbar, color.green, size=size.small)
    plotshape(shortSignal, "Short", shape.triangledown, location.abovebar, color.red, size=size.small)

    // Alert conditions
    alertcondition(longSignal, "MTF Long", "Long entry signal")
    alertcondition(shortSignal, "MTF Short", "Short entry signal")

  OPTION C — Implement at bot level only:
    Keep TradingView alerts on plain Supertrend flips.
    Add the ADX >= 15 + rising check in the webhook handler.
    The bot fetches the current ADX from Hyperliquid/Binance candles
    and only executes if the ADX condition is met.

  RECOMMENDATION: Option B (Pine Script) is cleanest — the alert only fires
  when ALL conditions are met, so the bot executes every alert without
  additional logic. Option C works but adds a dependency on the bot
  fetching candle data for ADX calculation.
""")

    # ═══════════════════════════════════════════════════════════
    # FINAL DEPLOYMENT CONFIG
    # ═══════════════════════════════════════════════════════════
    if all_pass:
        config = {
            "strategy_name": "Pure MTF Supertrend + ADX Rising",
            "validated": True,
            "validation_date": datetime.now(timezone.utc).isoformat(),

            "entry_supertrend": {
                "timeframe": "15m",
                "atr_period": 8,
                "multiplier": 4.0,
                "source": "hlc3",
            },
            "confirmation_supertrend": {
                "timeframe": "1h",
                "atr_period": 10,
                "multiplier": 4.0,
                "source": "close",
            },
            "adx_filter": {
                "period": 14,
                "minimum": 15,
                "require_rising": True,
                "rising_lookback_bars": 4,
                "note": "ADX(14) must be >= 15 AND current ADX > ADX 4 bars ago",
            },
            "position_sizing": {
                "type": "fixed_dollar",
                "size_usd": 125,
                "leverage": 10,
                "notional_per_trade_usd": 1250,
                "NEVER_USE_COMPOUNDING": True,
            },
            "fees": {
                "taker_pct": 0.045,
                "maker_pct": 0.020,
                "prefer_limit_orders": True,
                "limit_timeout_seconds": 15,
            },
            "risk": {
                "stop_loss": "none — Supertrend flip handles exits",
                "take_profit": "none — cuts winners short",
                "max_drawdown_before_pause_pct": 50,
            },
            "backtest_results": {
                "period": "730 days (2024-03-16 to 2026-03-16)",
                "total_trades": m_full["n"],
                "pnl_usd": m_full["pnl"],
                "pnl_pct": round(m_full["pnl"]/500*100, 1),
                "profit_factor": m_full["pf"],
                "win_rate_pct": m_full["wr"],
                "max_drawdown_pct": m_full["mdd"],
                "validation_pf": m_val["pf"],
                "validation_pnl": m_val["pnl"],
                "all_6_starting_points_profitable": all_profitable,
                "all_13_parameter_variations_profitable": all_robust,
            },
        }

        out_path = Path(__file__).parent / "FINAL_DEPLOYMENT_CONFIG.json"
        with open(out_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"\n  Config saved to {out_path}")


if __name__ == "__main__":
    main()
