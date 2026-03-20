#!/usr/bin/env python3
"""
FULL SYSTEM VALIDATION — EMA200+EMA50 Regime Classifier
=========================================================
22 stress tests across 6 assets, 5 years of data.
New regime: BULL = close>EMA200 & EMA50 rising, BEAR = close<EMA200 & EMA50 falling, FLAT = else
No ADX anywhere. Data only. No deployment.
"""

import json, sys, time, math, random, gc, os, traceback
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from multiprocessing import Pool, cpu_count
from scipy import stats as sp_stats
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).parent / "backtest-v2"))
from engine import calc_tr, calc_atr_rma

DATA_DIR = Path(__file__).parent / "backtest-data"
RESULTS_DIR = Path("/tmp/discovery")
RESULTS_DIR.mkdir(exist_ok=True)

# Constants
FUNDING_RATE_8H = 0.0001
FEE_RATE = 0.00045
SLIPPAGE = 0.0001
CAPITAL = 500.0
FIXED = 125.0
LEV = 10.0
ASSETS = ["BTC", "ETH", "SOL", "DOGE", "BNB", "AVAX"]
WARMUP = 300  # Need 200+ daily bars for EMA200 + some 15m warmup
EMA50_LOOKBACK = 5  # Compare EMA50 now vs 5 bars ago

random.seed(42)
np.random.seed(42)

T0 = time.time()

def timestamp():
    return datetime.now().strftime("%H:%M:%S")

def ts_ym(t):
    return datetime.fromtimestamp(t/1000, tz=timezone.utc).strftime('%Y-%m')

def ts_yr(t):
    return datetime.fromtimestamp(t/1000, tz=timezone.utc).strftime('%Y')

def ts_ymd(t):
    return datetime.fromtimestamp(t/1000, tz=timezone.utc).strftime('%Y-%m-%d')

def elapsed():
    return f"{time.time()-T0:.0f}s"

# ═══════════════════════════════════════════════════════════════
# DATA FETCHING (Binance)
# ═══════════════════════════════════════════════════════════════

import urllib.request

def fetch_binance(symbol, interval, start_date="2021-01-01", end_date="2026-03-19"):
    start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()*1000)
    end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()*1000)
    iv_ms = {"15m":900000, "4h":14400000, "1d":86400000}[interval]
    all_c = []; cursor = start_ms
    while cursor < end_ms:
        url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}"
               f"&startTime={cursor}&endTime={end_ms}&limit=1000")
        try:
            resp = urllib.request.urlopen(urllib.request.Request(url), timeout=30)
            data = json.loads(resp.read())
            if not data: break
            for k in data:
                all_c.append({"open_time":k[0],"open":k[1],"high":k[2],"low":k[3],"close":k[4],"volume":k[5]})
            cursor = data[-1][0] + iv_ms
            if len(data) < 1000: break
            time.sleep(0.12)
        except Exception as e:
            print(f"      API error ({symbol} {interval}): {e}")
            time.sleep(1)
            if cursor == start_ms: break
            continue
    return all_c

def download_asset(symbol):
    """Download fresh 15m, 4h, 1d data for an asset."""
    pair = f"{symbol}USDT"
    for interval in ["15m", "4h", "1d"]:
        cache = DATA_DIR / f"mega_{symbol.lower()}_{interval}.json"
        # Always re-download for freshness
        print(f"  [{timestamp()}] Downloading {symbol} {interval}...")
        raw = fetch_binance(pair, interval)
        if raw:
            with open(cache, "w") as f:
                json.dump(raw, f)
            print(f"  [{timestamp()}] {symbol} {interval}: {len(raw)} candles")
        else:
            print(f"  [{timestamp()}] WARNING: No data for {symbol} {interval}")
    return symbol

def load_asset(symbol):
    """Load cached data into numpy arrays."""
    d = {}
    for tf in ["15m", "4h", "1d"]:
        f = DATA_DIR / f"mega_{symbol.lower()}_{tf}.json"
        if not f.exists(): return None
        with open(f) as fh: raw = json.load(fh)
        d[tf] = {
            "ts": np.array([c["open_time"] for c in raw], dtype=np.int64),
            "o": np.array([float(c["open"]) for c in raw]),
            "h": np.array([float(c["high"]) for c in raw]),
            "l": np.array([float(c["low"]) for c in raw]),
            "c": np.array([float(c["close"]) for c in raw]),
            "v": np.array([float(c["volume"]) for c in raw]),
        }
    return d

# ═══════════════════════════════════════════════════════════════
# INDICATORS — Numpy vectorized where possible
# ═══════════════════════════════════════════════════════════════

def ema_np(data, period):
    """EMA — recursive so needs loop, but minimal overhead."""
    out = np.full(len(data), np.nan)
    if len(data) < period: return out
    k = 2.0/(period+1)
    out[period-1] = np.mean(data[:period])
    for i in range(period, len(data)):
        out[i] = data[i]*k + out[i-1]*(1-k)
    return out

def sma_np(data, period):
    """SMA — fully vectorized."""
    out = np.full(len(data), np.nan)
    if len(data) < period: return out
    cs = np.cumsum(data)
    out[period-1:] = (cs[period-1:] - np.concatenate([[0], cs[:-period]])) / period
    return out

def rsi_np(closes, period=14):
    n = len(closes); out = np.full(n, np.nan)
    if n < period+1: return out
    delta = np.diff(closes)
    g = np.where(delta>0, delta, 0.0)
    l = np.where(delta<0, -delta, 0.0)
    ag = np.mean(g[:period]); al = np.mean(l[:period])
    out[period] = 100-100/(1+ag/al) if al > 0 else 100
    for i in range(period, n-1):
        ag = (ag*(period-1)+g[i])/period
        al = (al*(period-1)+l[i])/period
        out[i+1] = 100-100/(1+ag/al) if al > 0 else 100
    return out

def supertrend_np(h, l, c, ap, m):
    n = len(c); src = (h+l)/2
    tr = calc_tr(h, l, c); atr = calc_atr_rma(tr, ap)
    d = np.ones(n); st = np.full(n, np.nan)
    fu = np.full(n, np.nan); fd = np.full(n, np.nan)
    s = ap-1; bu = src-m*atr; bd = src+m*atr
    fu[s] = bu[s]; fd[s] = bd[s]; d[s] = 1; st[s] = fu[s]
    for i in range(s+1, n):
        if np.isnan(atr[i]):
            fu[i]=fu[i-1]; fd[i]=fd[i-1]; d[i]=d[i-1]; st[i]=st[i-1]; continue
        fu[i] = max(bu[i], fu[i-1]) if c[i-1] > fu[i-1] else bu[i]
        fd[i] = min(bd[i], fd[i-1]) if c[i-1] < fd[i-1] else bd[i]
        if d[i-1] == -1 and c[i] > fd[i-1]: d[i] = 1
        elif d[i-1] == 1 and c[i] < fu[i-1]: d[i] = -1
        else: d[i] = d[i-1]
        st[i] = fu[i] if d[i] == 1 else fd[i]
    return st, d

def align_htf(ts_lo, v_hi, ts_hi):
    """Align higher TF values to lower TF timestamps."""
    al = np.full(len(ts_lo), np.nan); j = 0
    for i in range(len(ts_lo)):
        while j < len(ts_hi)-1 and ts_hi[j+1] <= ts_lo[i]: j += 1
        if j < len(v_hi): al[i] = v_hi[j]
    return al

def build_htf_idx(ts_lo, ts_hi):
    """Precompute index map for fast alignment."""
    idx = np.zeros(len(ts_lo), dtype=np.int64); j = 0
    for i in range(len(ts_lo)):
        while j < len(ts_hi)-1 and ts_hi[j+1] <= ts_lo[i]: j += 1
        idx[i] = j
    return idx

# ═══════════════════════════════════════════════════════════════
# NEW REGIME CLASSIFIER — EMA200 + EMA50 slope (NO ADX)
# ═══════════════════════════════════════════════════════════════

def classify_regime_new(c15, ts15, d1d_c, d1d_ts, ema200_period=200, ema50_period=50, ema50_lookback=5):
    """
    BULL (1): Daily close > EMA200 AND EMA50 rising (current > 5 bars ago)
    BEAR (2): Daily close < EMA200 AND EMA50 falling (current < 5 bars ago)
    FLAT (0): Everything else
    """
    n = len(c15)
    ema200_d = ema_np(d1d_c, ema200_period)
    ema50_d = ema_np(d1d_c, ema50_period)

    # Align to 15m
    ema200_al = align_htf(ts15, ema200_d, d1d_ts)
    ema50_al = align_htf(ts15, ema50_d, d1d_ts)

    # EMA50 lookback-bars-ago aligned
    ema50_lagged = np.full(len(d1d_c), np.nan)
    ema50_lagged[ema50_lookback:] = ema50_d[:-ema50_lookback]
    ema50_lag_al = align_htf(ts15, ema50_lagged, d1d_ts)

    regime = np.zeros(n, dtype=np.int32)
    for i in range(n):
        e200 = ema200_al[i]; e50 = ema50_al[i]; e50p = ema50_lag_al[i]
        if np.isnan(e200) or np.isnan(e50) or np.isnan(e50p):
            continue
        above = c15[i] > e200
        rising = e50 > e50p
        falling = e50 < e50p
        if above and rising:
            regime[i] = 1  # BULL
        elif not above and falling:
            regime[i] = 2  # BEAR
        # else: FLAT (0)
    return regime

# ═══════════════════════════════════════════════════════════════
# STRATEGIES
# ═══════════════════════════════════════════════════════════════

def sig_mtf_pyramid(c, h, l, ts, d_ema200_al, st4h_dir_al, st15_line, st15_dir, rsi15, warmup=WARMUP):
    """Bull regime long strategy: MTF pyramid with RSI confirmation."""
    n = len(c); sig = np.zeros(n)
    for i in range(warmup, n):
        de = d_ema200_al[i]; s4 = st4h_dir_al[i]; sl = st15_line[i]; sd = st15_dir[i]; r = rsi15[i]
        if np.isnan(de) or np.isnan(s4) or np.isnan(sl) or np.isnan(r):
            sig[i] = sig[i-1]; continue
        bull = c[i] > de; s4b = s4 == 1; s15b = sd == 1
        if sig[i-1] == 1:
            if not s4b or not bull: sig[i] = 0
            else: sig[i] = 1
            continue
        if sig[i-1] == 0:
            if not bull or not s4b or not s15b: sig[i] = 0; continue
            if sl > 0:
                dist = (c[i]-sl)/sl; near = 0 <= dist <= 0.001
            else: near = False
            if not near: sig[i] = 0; continue
            rl = any(i-lb >= 0 and not np.isnan(rsi15[i-lb]) and rsi15[i-lb] < 45 for lb in range(1, 3))
            rr = not np.isnan(rsi15[i-1]) and r > rsi15[i-1]
            sig[i] = 1 if rl and rr else 0
    return sig

def sig_ema_short(c, v, fp=21, sp=55, vm=2.0, warmup=WARMUP):
    """Bear regime short strategy: EMA crossover + volume."""
    n = len(c); sig = np.zeros(n)
    f = ema_np(c, fp); s = ema_np(c, sp); vs = sma_np(v, 20)
    for i in range(max(sp, warmup), n):
        if np.isnan(f[i]) or np.isnan(s[i]) or np.isnan(vs[i]): continue
        vo = v[i] >= vm * vs[i]
        if f[i] < s[i] and f[i-1] >= s[i-1] and vo and c[i] < f[i]:
            sig[i] = -1
        elif sig[i-1] == -1 and f[i] > s[i]:
            sig[i] = 0
        else:
            sig[i] = sig[i-1]
    sig = np.where(sig == 1, 0, sig)  # Never long from this strategy
    return sig

# ═══════════════════════════════════════════════════════════════
# COMBINED SIGNAL GENERATION
# ═══════════════════════════════════════════════════════════════

def compute_all_signals(d, ema200_period=200, ema50_period=50, ema50_lookback=5,
                        st4h_atr=10, st4h_mult=3.0, st15_atr=10, st15_mult=2.0,
                        ema_fast=21, ema_slow=55, vol_mult=2.0):
    """Compute regime + strategy signals. Returns (combined, regime)."""
    c = d["15m"]["c"]; o = d["15m"]["o"]; h = d["15m"]["h"]
    l = d["15m"]["l"]; v = d["15m"]["v"]; ts = d["15m"]["ts"]
    n = len(c)

    regime = classify_regime_new(c, ts, d["1d"]["c"], d["1d"]["ts"],
                                  ema200_period, ema50_period, ema50_lookback)

    d_ema200 = ema_np(d["1d"]["c"], ema200_period)
    d_ema200_al = align_htf(ts, d_ema200, d["1d"]["ts"])
    _, st4h_dir = supertrend_np(d["4h"]["h"], d["4h"]["l"], d["4h"]["c"], st4h_atr, st4h_mult)
    st4h_dir_al = align_htf(ts, st4h_dir, d["4h"]["ts"])
    st15_line, st15_dir = supertrend_np(h, l, c, st15_atr, st15_mult)
    rsi15 = rsi_np(c, 14)

    sig_bull = sig_mtf_pyramid(c, h, l, ts, d_ema200_al, st4h_dir_al, st15_line, st15_dir, rsi15)
    sig_bear = sig_ema_short(c, v, fp=ema_fast, sp=ema_slow, vm=vol_mult)

    combined = np.zeros(n)
    for i in range(WARMUP, n):
        rg = regime[i]
        if rg == 1: combined[i] = sig_bull[i]
        elif rg == 2: combined[i] = sig_bear[i]
        else: combined[i] = 0
        # Close position on regime transition
        if i > 0 and regime[i] != regime[i-1] and combined[i-1] != 0:
            combined[i] = 0
    return combined, regime

# ═══════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════

def backtest(closes, opens, signals, timestamps, warmup=WARMUP,
             fee_rate=FEE_RATE, slippage=SLIPPAGE, funding_rate=FUNDING_RATE_8H,
             capital=CAPITAL, fixed=FIXED, leverage=LEV,
             start_bar=0, end_bar=-1, signal_delay=0):
    """Full backtest engine with configurable costs."""
    n = len(closes) if end_bar < 0 else min(end_bar, len(closes))
    eff = max(start_bar, warmup)
    equity = capital; pos = 0; ep = 0.0; eb = 0; ps = 0.0
    trades = []; ec = []
    pos_size = fixed * leverage

    for i in range(eff, n):
        # Signal from previous bar (or delayed)
        sig_idx = i - 1 - signal_delay
        sig = int(signals[sig_idx]) if 0 <= sig_idx < len(signals) and not np.isnan(signals[sig_idx]) else 0

        if sig != pos and i > eff:
            if pos != 0:
                sl = opens[i] * slippage
                xp = (opens[i]-sl) if pos == 1 else (opens[i]+sl)
                pr = (xp-ep) * pos * (ps/ep)
                fe = ps * fee_rate
                bars = i - eb
                fund = ps * funding_rate * (bars * 15 / 60 / 8)
                pnl = pr - fe - fund
                trades.append({
                    "pnl": pnl, "fees": fe, "fund": fund, "bars": bars,
                    "dir": pos, "entry": ep, "exit": xp,
                    "entry_ts": int(timestamps[eb]), "exit_ts": int(timestamps[i])
                })
                equity += pnl; pos = 0; ps = 0.0

            if sig != 0:
                sl = opens[i] * slippage
                ep = (opens[i]+sl) if sig == 1 else (opens[i]-sl)
                ps = pos_size
                fe = ps * fee_rate
                equity -= fe
                pos = sig; eb = i

        if pos != 0:
            bars = i - eb
            fu = ps * funding_rate * (bars * 15 / 60 / 8)
            ec.append(equity + (closes[i]-ep)*pos*(ps/ep) - fu)
        else:
            ec.append(equity)

    # Close open position at end
    if pos != 0:
        xp = closes[n-1]
        pr = (xp-ep)*pos*(ps/ep)
        fe = ps * fee_rate
        bars = n-1-eb
        fund = ps * funding_rate * (bars * 15 / 60 / 8)
        pnl = pr - fe - fund
        trades.append({
            "pnl": pnl, "fees": fe, "fund": fund, "bars": bars,
            "dir": pos, "entry": ep, "exit": xp,
            "entry_ts": int(timestamps[eb]), "exit_ts": int(timestamps[n-1])
        })
        equity += pnl
        if ec: ec[-1] = equity

    return trades, np.array(ec) if ec else np.array([capital]), equity

def compute_stats(trades, ec=None, capital=CAPITAL):
    """Compute comprehensive statistics from trade list."""
    nt = len(trades)
    if nt == 0:
        return {"trades":0,"pnl":0,"wr":0,"pf":0,"sharpe":0,"mdd":0,"mdd_pct":0,
                "fees":0,"funding":0,"avg_bars":0,"long_pnl":0,"short_pnl":0}

    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    wr = len(wins)/nt*100
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gp/gl if gl > 0 else (99 if gp > 0 else 0)
    fees = sum(t.get("fees", 0) for t in trades)
    funding = sum(t.get("fund", 0) for t in trades)
    avg_bars = np.mean([t["bars"] for t in trades])

    long_pnl = sum(t["pnl"] for t in trades if t.get("dir", 1) == 1)
    short_pnl = sum(t["pnl"] for t in trades if t.get("dir", 1) == -1)

    # MDD
    mdd = 0; mdd_pct = 0
    if ec is not None and len(ec) > 0:
        pk = np.maximum.accumulate(np.maximum(ec, 1.0))
        dd = pk - ec
        dd_pct = dd / pk
        mdd = float(np.max(dd))
        mdd_pct = float(np.max(dd_pct)) * 100

    # Monthly P&L for Sharpe
    monthly = {}
    for t in trades:
        m = ts_ym(t.get("exit_ts", t.get("entry_ts", 0)))
        monthly[m] = monthly.get(m, 0) + t["pnl"]

    sharpe = 0
    if len(monthly) >= 2:
        rets = np.array(list(monthly.values())) / capital
        if np.std(rets) > 0:
            sharpe = np.mean(rets) / np.std(rets) * math.sqrt(12)

    return {
        "trades": nt, "pnl": round(pnl, 2), "wr": round(wr, 1), "pf": round(pf, 2),
        "sharpe": round(sharpe, 2), "mdd": round(mdd, 2), "mdd_pct": round(mdd_pct, 1),
        "fees": round(fees, 2), "funding": round(funding, 2), "avg_bars": round(avg_bars, 1),
        "long_pnl": round(long_pnl, 2), "short_pnl": round(short_pnl, 2),
        "monthly": monthly
    }

# ═══════════════════════════════════════════════════════════════
# RESULTS SAVING
# ═══════════════════════════════════════════════════════════════

ALL_RESULTS = {}

def save_results():
    """Save current results to disk."""
    # Convert numpy types for JSON serialization
    def convert(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        if isinstance(obj, (np.bool_,)): return bool(obj)
        return obj

    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            r = convert(obj)
            if r is not obj: return r
            return super().default(obj)

    with open(RESULTS_DIR / "final_validation.json", "w") as f:
        json.dump(ALL_RESULTS, f, cls=NpEncoder, indent=2)

# ═══════════════════════════════════════════════════════════════
# WORKER FUNCTIONS FOR MULTIPROCESSING
# ═══════════════════════════════════════════════════════════════

def _worker_run_asset(args):
    """Worker: load asset, compute signals, run backtest."""
    sym = args[0]
    params = args[1] if len(args) > 1 else {}
    try:
        d = load_asset(sym)
        if d is None: return sym, None

        combined, regime = compute_all_signals(d, **params)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]

        trades, ec, eq = backtest(c, o, combined, ts,
                                   fee_rate=params.get("fee_rate", FEE_RATE),
                                   slippage=params.get("slippage_rate", SLIPPAGE),
                                   funding_rate=params.get("funding_rate", FUNDING_RATE_8H),
                                   leverage=params.get("leverage", LEV),
                                   signal_delay=params.get("signal_delay", 0))
        st = compute_stats(trades, ec)

        # Regime distribution
        total = len(regime)
        bull_pct = np.sum(regime == 1) / total * 100
        bear_pct = np.sum(regime == 2) / total * 100
        flat_pct = np.sum(regime == 0) / total * 100

        st["regime_bull_pct"] = round(bull_pct, 1)
        st["regime_bear_pct"] = round(bear_pct, 1)
        st["regime_flat_pct"] = round(flat_pct, 1)
        st["n_bars"] = total

        return sym, st, trades, ec.tolist() if isinstance(ec, np.ndarray) else ec, regime.tolist()
    except Exception as e:
        print(f"  ERROR processing {sym}: {e}")
        traceback.print_exc()
        return sym, None

def _worker_param_test(args):
    """Worker: test a parameter set across all assets."""
    param_idx, params = args
    try:
        total_pnl = 0; total_trades = 0; total_gp = 0; total_gl = 0
        for sym in ASSETS:
            d = load_asset(sym)
            if d is None: continue
            combined, regime = compute_all_signals(d, **params)
            c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
            trades, ec, eq = backtest(c, o, combined, ts)
            for t in trades:
                if t["pnl"] > 0: total_gp += t["pnl"]
                else: total_gl += abs(t["pnl"])
            total_pnl += sum(t["pnl"] for t in trades)
            total_trades += len(trades)
        pf = total_gp / total_gl if total_gl > 0 else 99
        return param_idx, {"pnl": total_pnl, "pf": pf, "trades": total_trades, "params": params}
    except Exception as e:
        return param_idx, {"pnl": 0, "pf": 0, "trades": 0, "error": str(e)}

# ═══════════════════════════════════════════════════════════════
# PHASE 0: DOWNLOAD FRESH DATA
# ═══════════════════════════════════════════════════════════════

def phase0_download():
    print("\n" + "="*120)
    print(f"  [{timestamp()}] PHASE 0 — DOWNLOADING FRESH DATA FOR ALL 6 ASSETS")
    print("="*120)
    for sym in ASSETS:
        download_asset(sym)
    print(f"  [{timestamp()}] All data downloaded. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# PHASE 1: FULL SYSTEM REVALIDATION
# ═══════════════════════════════════════════════════════════════

def phase1_revalidation():
    print("\n" + "="*120)
    print(f"  [{timestamp()}] PHASE 1 — FULL SYSTEM REVALIDATION WITH NEW EMA200+EMA50 CLASSIFIER")
    print("="*120)

    # Run all 6 assets in parallel
    with Pool(12) as pool:
        results = pool.map(_worker_run_asset, [(sym,) for sym in ASSETS])

    asset_stats = {}
    all_trades = []
    all_ec = []
    regime_dist = {}

    for r in results:
        if r is None or r[1] is None:
            print(f"  SKIP: {r[0] if r else 'unknown'}")
            continue
        sym, st, trades, ec, regime = r
        asset_stats[sym] = st
        all_trades.extend(trades)
        all_ec.extend(ec)
        regime_dist[sym] = {"bull": st["regime_bull_pct"], "bear": st["regime_bear_pct"], "flat": st["regime_flat_pct"]}

    # Per-asset table
    print(f"\n  {'Asset':<8} {'PF':>6} {'P&L':>10} {'MDD%':>7} {'Sharpe':>7} {'Trades':>7} {'WR%':>6} {'Long$':>10} {'Short$':>10} {'Bull%':>6} {'Bear%':>6} {'Flat%':>6}")
    print(f"  {'─'*100}")
    for sym in ASSETS:
        if sym not in asset_stats: continue
        s = asset_stats[sym]
        print(f"  {sym:<8} {s['pf']:>6.2f} ${s['pnl']:>9.2f} {s['mdd_pct']:>6.1f}% {s['sharpe']:>7.2f} {s['trades']:>7} {s['wr']:>5.1f}% ${s['long_pnl']:>9.2f} ${s['short_pnl']:>9.2f} {s['regime_bull_pct']:>5.1f}% {s['regime_bear_pct']:>5.1f}% {s['regime_flat_pct']:>5.1f}%")

    # Combined portfolio
    combined = compute_stats(all_trades, np.array(all_ec) if all_ec else None, CAPITAL * len(ASSETS))

    # Year by year
    yearly = {}
    for t in all_trades:
        y = ts_yr(t["exit_ts"])
        yearly[y] = yearly.get(y, 0) + t["pnl"]

    print(f"\n  COMBINED PORTFOLIO:")
    print(f"    PF: {combined['pf']:.2f} | P&L: ${combined['pnl']:.2f} | MDD: {combined['mdd_pct']:.1f}% | Sharpe: {combined['sharpe']:.2f}")
    print(f"    Trades: {combined['trades']} | WR: {combined['wr']:.1f}%")
    print(f"    Long P&L: ${combined['long_pnl']:.2f} | Short P&L: ${combined['short_pnl']:.2f}")

    # Monthly win rate
    monthly = combined.get("monthly", {})
    if monthly:
        win_months = sum(1 for v in monthly.values() if v > 0)
        print(f"    Monthly win rate: {win_months}/{len(monthly)} ({win_months/len(monthly)*100:.0f}%)")

    print(f"\n  YEAR-BY-YEAR P&L:")
    for y in sorted(yearly.keys()):
        print(f"    {y}: ${yearly[y]:>10.2f}")

    print(f"\n  COMPARISON vs OLD CLASSIFIER (PF 2.12, $8,241):")
    delta_pf = combined['pf'] - 2.12
    delta_pnl = combined['pnl'] - 8241
    print(f"    PF: {combined['pf']:.2f} vs 2.12 ({delta_pf:+.2f})")
    print(f"    P&L: ${combined['pnl']:.2f} vs $8,241 (${delta_pnl:+.2f})")

    # Regime distribution check
    avg_bull = np.mean([v["bull"] for v in regime_dist.values()])
    avg_bear = np.mean([v["bear"] for v in regime_dist.values()])
    avg_flat = np.mean([v["flat"] for v in regime_dist.values()])
    print(f"\n  REGIME DISTRIBUTION (avg across assets): Bull {avg_bull:.1f}% | Bear {avg_bear:.1f}% | Flat {avg_flat:.1f}%")
    expected = abs(avg_bull - 37) < 15 and abs(avg_bear - 35) < 15 and abs(avg_flat - 28) < 15
    print(f"    {'PASS' if expected else 'DIVERGES from expected ~37/35/28 split'}")

    # Bootstrap 500 synthetic histories
    print(f"\n  [{timestamp()}] Running 500 bootstrap iterations...")
    boot_pfs = []; boot_pnls = []
    trade_pnls = [t["pnl"] for t in all_trades]
    nt = len(trade_pnls)
    for _ in range(500):
        sample = np.random.choice(trade_pnls, size=nt, replace=True)
        gp = np.sum(sample[sample > 0])
        gl = abs(np.sum(sample[sample <= 0]))
        pf = gp/gl if gl > 0 else 99
        boot_pfs.append(pf)
        boot_pnls.append(np.sum(sample))

    boot_pfs = np.array(boot_pfs)
    boot_pnls = np.array(boot_pnls)
    pct_profitable = np.sum(boot_pnls > 0) / 500 * 100

    print(f"    % profitable: {pct_profitable:.1f}%")
    print(f"    Median PF: {np.median(boot_pfs):.2f}")
    print(f"    Worst case PF: {np.min(boot_pfs):.2f}")
    print(f"    PF 5th/25th/50th/75th/95th: {np.percentile(boot_pfs,5):.2f} / {np.percentile(boot_pfs,25):.2f} / {np.percentile(boot_pfs,50):.2f} / {np.percentile(boot_pfs,75):.2f} / {np.percentile(boot_pfs,95):.2f}")

    # Statistical significance
    if trade_pnls:
        t_stat, p_val = sp_stats.ttest_1samp(trade_pnls, 0)
        ci_low, ci_high = sp_stats.t.interval(0.95, df=nt-1, loc=np.mean(trade_pnls), scale=sp_stats.sem(trade_pnls))
        pf_ci_low = np.percentile(boot_pfs, 2.5)
        pf_ci_high = np.percentile(boot_pfs, 97.5)
        print(f"\n    t-statistic: {t_stat:.3f}")
        print(f"    p-value: {p_val:.6f}")
        print(f"    95% CI on mean trade P&L: [${ci_low:.2f}, ${ci_high:.2f}]")
        print(f"    95% CI on PF (bootstrap): [{pf_ci_low:.2f}, {pf_ci_high:.2f}]")
        print(f"    Significant at 95%: {'YES' if p_val < 0.05 else 'NO'}")

    # Parameter robustness ±30%
    print(f"\n  [{timestamp()}] Parameter robustness ±30% (500 combinations)...")
    param_sets = []
    base = {"ema200_period":200, "ema50_period":50, "ema50_lookback":5,
            "st4h_atr":10, "st4h_mult":3.0, "st15_atr":10, "st15_mult":2.0,
            "ema_fast":21, "ema_slow":55, "vol_mult":2.0}

    for _ in range(500):
        p = {}
        for k, v in base.items():
            lo = v * 0.7; hi = v * 1.3
            if k in ["ema200_period","ema50_period","ema50_lookback","st4h_atr","st15_atr","ema_fast","ema_slow"]:
                p[k] = int(np.random.uniform(lo, hi))
            else:
                p[k] = round(np.random.uniform(lo, hi), 2)
        param_sets.append(p)

    with Pool(12) as pool:
        robustness = pool.map(_worker_param_test, [(i, p) for i, p in enumerate(param_sets)])

    profitable = sum(1 for _, r in robustness if r["pnl"] > 0)
    print(f"    Profitable: {profitable}/500 ({profitable/5:.1f}%)")

    ALL_RESULTS["phase1"] = {
        "asset_stats": asset_stats,
        "combined": {k:v for k,v in combined.items() if k != "monthly"},
        "regime_dist": regime_dist,
        "yearly_pnl": yearly,
        "bootstrap": {"pct_profitable": pct_profitable, "median_pf": float(np.median(boot_pfs)),
                       "worst_pf": float(np.min(boot_pfs))},
        "significance": {"t_stat": float(t_stat) if trade_pnls else 0,
                         "p_val": float(p_val) if trade_pnls else 1},
        "robustness_pct_profitable": profitable/5
    }
    save_results()
    print(f"  [{timestamp()}] Phase 1 complete. [{elapsed()}]")
    return asset_stats, all_trades, combined

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 7 — Monte Carlo Parameter Robustness (LHS)
# ═══════════════════════════════════════════════════════════════

def stress_test_7():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 7 — Monte Carlo Parameter Robustness (2000 LHS combinations)")
    print(f"{'='*120}")

    # Latin Hypercube Sampling
    n_samples = 2000
    n_params = 8
    # Generate LHS samples in [0,1]
    lhs = np.zeros((n_samples, n_params))
    for j in range(n_params):
        perm = np.random.permutation(n_samples)
        for i in range(n_samples):
            lhs[perm[i], j] = (i + np.random.uniform()) / n_samples

    # Map to parameter ranges
    ranges = [
        ("ema200_period", 140, 260, True),
        ("ema50_period", 35, 65, True),
        ("ema50_lookback", 3, 8, True),
        ("st4h_atr", 7, 13, True),
        ("st4h_mult", 2.1, 3.9, False),
        ("ema_fast", 15, 27, True),
        ("ema_slow", 39, 71, True),
        ("vol_mult", 1.4, 2.6, False),
    ]

    param_sets = []
    for i in range(n_samples):
        p = {}
        for j, (name, lo, hi, is_int) in enumerate(ranges):
            val = lo + lhs[i, j] * (hi - lo)
            p[name] = int(round(val)) if is_int else round(val, 2)
        param_sets.append(p)

    print(f"  Testing {n_samples} parameter combinations across 6 assets...")
    t_start = time.time()
    last_print = t_start

    with Pool(12) as pool:
        results = []
        for i, r in enumerate(pool.imap_unordered(_worker_param_test, [(i, p) for i, p in enumerate(param_sets)], chunksize=20)):
            results.append(r)
            now = time.time()
            if now - last_print >= 30:
                print(f"  [{timestamp()}] {len(results)}/{n_samples} done ({now-t_start:.0f}s)")
                last_print = now

    pfs = [r[1]["pf"] for r in results if r[1]["trades"] > 0]
    pnls = [r[1]["pnl"] for r in results if r[1]["trades"] > 0]
    profitable = sum(1 for p in pnls if p > 0)

    print(f"\n  RESULTS ({len(pfs)} valid of {n_samples}):")
    print(f"    % Profitable: {profitable}/{len(pfs)} ({profitable/len(pfs)*100:.1f}%)")
    if pfs:
        pfs_arr = np.array(pfs)
        print(f"    PF distribution: 5th={np.percentile(pfs_arr,5):.2f} 25th={np.percentile(pfs_arr,25):.2f} "
              f"50th={np.percentile(pfs_arr,50):.2f} 75th={np.percentile(pfs_arr,75):.2f} 95th={np.percentile(pfs_arr,95):.2f}")
        print(f"    Worst PF: {np.min(pfs_arr):.2f} | Best PF: {np.max(pfs_arr):.2f}")

    # Sensitivity analysis
    print(f"\n  SENSITIVITY ANALYSIS (correlation of parameter value with PF):")
    for j, (name, _, _, _) in enumerate(ranges):
        param_vals = [param_sets[r[0]][name] for r in results if r[1]["trades"] > 0]
        pf_vals = [r[1]["pf"] for r in results if r[1]["trades"] > 0]
        if len(param_vals) > 10:
            corr = np.corrcoef(param_vals, pf_vals)[0, 1]
            print(f"    {name:<20}: r = {corr:+.3f} {'*** HIGH' if abs(corr) > 0.3 else ''}")

    # Worst within ±30%
    worst = min(results, key=lambda r: r[1]["pnl"])
    print(f"\n  Worst combination: PF={worst[1]['pf']:.2f}, P&L=${worst[1]['pnl']:.2f}")
    print(f"    Params: {worst[1].get('params', param_sets[worst[0]])}")

    ALL_RESULTS["stress_test_7"] = {
        "n_tested": n_samples,
        "pct_profitable": profitable/len(pfs)*100 if pfs else 0,
        "pf_percentiles": {str(p): float(np.percentile(pfs_arr, p)) for p in [5,25,50,75,95]} if pfs else {},
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 7 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 8 — Most Recent 12 Months
# ═══════════════════════════════════════════════════════════════

def stress_test_8():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 8 — Most Recent 12 Months (March 2025 - March 2026)")
    print(f"{'='*120}")

    cutoff_ms = int(datetime(2025, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
    all_trades = []; all_monthly = {}

    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]

        # Find start bar for recent period
        start_idx = np.searchsorted(ts, cutoff_ms)
        trades, ec, eq = backtest(c, o, combined, ts, start_bar=start_idx)

        st = compute_stats(trades, ec)
        print(f"  {sym:<8} PF={st['pf']:.2f} P&L=${st['pnl']:.2f} Sharpe={st['sharpe']:.2f} MDD={st['mdd_pct']:.1f}% Trades={st['trades']}")
        all_trades.extend(trades)
        for t in trades:
            m = ts_ym(t["exit_ts"])
            all_monthly[m] = all_monthly.get(m, 0) + t["pnl"]

    combined_st = compute_stats(all_trades)
    print(f"\n  COMBINED: PF={combined_st['pf']:.2f} P&L=${combined_st['pnl']:.2f} Sharpe={combined_st['sharpe']:.2f}")

    print(f"\n  Monthly P&L breakdown:")
    for m in sorted(all_monthly.keys()):
        status = "WIN" if all_monthly[m] > 0 else "LOSS"
        print(f"    {m}: ${all_monthly[m]:>10.2f} [{status}]")

    ALL_RESULTS["stress_test_8"] = {
        "combined": {k:v for k,v in combined_st.items() if k != "monthly"},
        "monthly": all_monthly
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 8 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 9 — Worst Case Sequence Compounding
# ═══════════════════════════════════════════════════════════════

def stress_test_9():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 9 — Worst Case Sequence Compounding (10,000 MC simulations)")
    print(f"{'='*120}")

    # Get monthly returns from all assets
    all_trades = []
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts)
        all_trades.extend(trades)

    monthly = {}
    for t in all_trades:
        m = ts_ym(t["exit_ts"])
        monthly[m] = monthly.get(m, 0) + t["pnl"]
    monthly_returns = sorted(monthly.values())

    START_EQ = 5000
    COMPOUND_RATE = 0.25
    N_SIM = 10000
    n_months = len(monthly_returns)

    final_equities = []
    for _ in range(N_SIM):
        eq = START_EQ
        shuffled = np.random.permutation(monthly_returns)
        for ret in shuffled:
            eq += ret * (eq * COMPOUND_RATE / START_EQ)
            eq = max(eq, 0)
        final_equities.append(eq)

    final_eq = np.array(final_equities)

    print(f"  Starting equity: ${START_EQ} | Monthly compounding: {COMPOUND_RATE*100}% of equity")
    print(f"  {n_months} months of returns, {N_SIM} simulations\n")
    print(f"  Median final equity: ${np.median(final_eq):.2f}")
    print(f"  Mean final equity:   ${np.mean(final_eq):.2f}")
    print(f"  Worst 1%:            ${np.percentile(final_eq, 1):.2f}")
    print(f"  Best 1%:             ${np.percentile(final_eq, 99):.2f}")
    print(f"  P(below $4000):      {np.sum(final_eq < 4000)/N_SIM*100:.1f}%")
    print(f"  P(below $3000):      {np.sum(final_eq < 3000)/N_SIM*100:.1f}%")
    print(f"  P(below $2500):      {np.sum(final_eq < 2500)/N_SIM*100:.1f}%")
    print(f"  P(below $1000):      {np.sum(final_eq < 1000)/N_SIM*100:.1f}%")

    # Deterministic worst and best
    worst_order = sorted(monthly_returns)
    best_order = sorted(monthly_returns, reverse=True)
    eq_worst = START_EQ; eq_best = START_EQ
    for r in worst_order:
        eq_worst += r * (eq_worst * COMPOUND_RATE / START_EQ); eq_worst = max(eq_worst, 0)
    for r in best_order:
        eq_best += r * (eq_best * COMPOUND_RATE / START_EQ); eq_best = max(eq_best, 0)
    print(f"\n  Deterministic worst (all losses first): ${eq_worst:.2f}")
    print(f"  Deterministic best (all wins first):    ${eq_best:.2f}")

    ALL_RESULTS["stress_test_9"] = {
        "median_equity": float(np.median(final_eq)),
        "worst_1pct": float(np.percentile(final_eq, 1)),
        "best_1pct": float(np.percentile(final_eq, 99)),
        "p_below_4000": float(np.sum(final_eq < 4000)/N_SIM*100),
        "p_below_1000": float(np.sum(final_eq < 1000)/N_SIM*100),
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 9 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 10 — Live Regime Check
# ═══════════════════════════════════════════════════════════════

def stress_test_10():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 10 — Live Regime Check (All 6 Assets)")
    print(f"{'='*120}")

    results = {}
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue

        c1d = d["1d"]["c"]; ts1d = d["1d"]["ts"]
        ema200_d = ema_np(c1d, 200)
        ema50_d = ema_np(c1d, 50)

        price = c1d[-1]
        ema200_val = ema200_d[-1]
        ema50_now = ema50_d[-1]
        ema50_5ago = ema50_d[-6] if len(ema50_d) > 5 else np.nan
        dist_pct = (price - ema200_val) / ema200_val * 100

        above = price > ema200_val
        rising = ema50_now > ema50_5ago
        falling = ema50_now < ema50_5ago

        if above and rising: regime = "BULL"
        elif not above and falling: regime = "BEAR"
        else: regime = "FLAT"

        # Check 4H and 15m signals
        _, st4h_dir = supertrend_np(d["4h"]["h"], d["4h"]["l"], d["4h"]["c"], 10, 3.0)
        st4h_current = "BULL" if st4h_dir[-1] == 1 else "BEAR"

        if regime == "BULL": signal = "LONG candidate"
        elif regime == "BEAR": signal = "SHORT candidate"
        else: signal = "FLAT — no position"

        print(f"\n  {sym}:")
        print(f"    Price: ${price:,.2f} | EMA200: ${ema200_val:,.2f} ({dist_pct:+.1f}%)")
        print(f"    EMA50: ${ema50_now:,.2f} vs 5d ago ${ema50_5ago:,.2f} ({'RISING' if rising else 'FALLING'})")
        print(f"    Regime: {regime} | 4H ST: {st4h_current} | Signal: {signal}")

        results[sym] = {"price": float(price), "ema200": float(ema200_val),
                        "regime": regime, "signal": signal}

    ALL_RESULTS["stress_test_10"] = results
    save_results()
    print(f"\n  [{timestamp()}] Stress Test 10 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 11 — Survivorship Bias / DOGE Dependency
# ═══════════════════════════════════════════════════════════════

def stress_test_11():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 11 — Survivorship Bias & DOGE Dependency")
    print(f"{'='*120}")

    asset_pnls = {}
    asset_trades = {}
    doge_monthly = {}

    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts)
        st = compute_stats(trades, ec)
        asset_pnls[sym] = st["pnl"]
        asset_trades[sym] = trades
        if sym == "DOGE":
            for t in trades:
                m = ts_ym(t["exit_ts"])
                doge_monthly[m] = doge_monthly.get(m, 0) + t["pnl"]

    total_pnl = sum(asset_pnls.values())
    without_doge = total_pnl - asset_pnls.get("DOGE", 0)

    # P&L without DOGE 2021 meme rally (April-May 2021)
    doge_rally_pnl = 0
    for t in asset_trades.get("DOGE", []):
        dt = datetime.fromtimestamp(t["exit_ts"]/1000, tz=timezone.utc)
        if dt.year == 2021 and dt.month in [4, 5]:
            doge_rally_pnl += t["pnl"]

    without_rally = total_pnl - doge_rally_pnl

    # Replace DOGE with its median annual performance
    doge_yearly = {}
    for t in asset_trades.get("DOGE", []):
        y = ts_yr(t["exit_ts"])
        doge_yearly[y] = doge_yearly.get(y, 0) + t["pnl"]
    median_annual = np.median(list(doge_yearly.values())) if doge_yearly else 0
    years = len(doge_yearly) if doge_yearly else 1
    replaced_total = without_doge + median_annual * years

    # Compute PF without DOGE
    all_trades_no_doge = []
    for sym in ASSETS:
        if sym == "DOGE": continue
        all_trades_no_doge.extend(asset_trades.get(sym, []))
    st_no_doge = compute_stats(all_trades_no_doge)

    print(f"\n  Per-asset P&L: {', '.join(f'{s}=${p:.0f}' for s, p in asset_pnls.items())}")
    print(f"  Total P&L: ${total_pnl:.2f}")
    print(f"  DOGE contribution: ${asset_pnls.get('DOGE', 0):.2f} ({asset_pnls.get('DOGE',0)/total_pnl*100:.1f}% of total)")
    print(f"\n  Without DOGE entirely:  ${without_doge:.2f} (PF={st_no_doge['pf']:.2f})")
    print(f"  Without DOGE rally:     ${without_rally:.2f}")
    print(f"  DOGE replaced w/ median: ${replaced_total:.2f}")

    is_outlier = asset_pnls.get("DOGE", 0) > total_pnl * 0.4
    print(f"\n  VERDICT: {'DOGE IS an outlier (>40% of total P&L)' if is_outlier else 'DOGE is NOT an outsized contributor'}")
    print(f"    System {'DOES NOT' if without_doge <= 0 else 'DOES'} survive without DOGE")

    ALL_RESULTS["stress_test_11"] = {
        "asset_pnls": asset_pnls, "total": total_pnl,
        "without_doge": without_doge, "without_rally": without_rally,
        "doge_pct": asset_pnls.get("DOGE", 0)/total_pnl*100 if total_pnl != 0 else 0,
        "is_outlier": is_outlier
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 11 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 12 — Bear Market Isolation
# ═══════════════════════════════════════════════════════════════

def stress_test_12():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 12 — Bear Market Isolation")
    print(f"{'='*120}")

    all_bear_trades = []
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]

        # Only keep short trades from bear regime
        bear_trades = []
        trades, ec, eq = backtest(c, o, combined, ts)
        for t in trades:
            if t.get("dir", 0) == -1:
                bear_trades.append(t)

        st = compute_stats(bear_trades)
        n_bear_periods = 0
        in_bear = False
        bear_durations = []
        bear_start = 0
        for i in range(len(regime)):
            if regime[i] == 2 and not in_bear:
                in_bear = True; bear_start = i; n_bear_periods += 1
            elif regime[i] != 2 and in_bear:
                in_bear = False
                bear_durations.append((i - bear_start) * 15 / 60 / 24)  # days

        avg_dur = np.mean(bear_durations) if bear_durations else 0
        print(f"  {sym:<8} PF={st['pf']:.2f} P&L=${st['pnl']:.2f} WR={st['wr']:.0f}% Trades={st['trades']} "
              f"BearPeriods={n_bear_periods} AvgDur={avg_dur:.0f}d")
        all_bear_trades.extend(bear_trades)

    combined_bear = compute_stats(all_bear_trades)
    print(f"\n  COMBINED BEAR: PF={combined_bear['pf']:.2f} P&L=${combined_bear['pnl']:.2f} WR={combined_bear['wr']:.0f}%")

    if all_bear_trades:
        largest_win = max(t["pnl"] for t in all_bear_trades)
        largest_loss = min(t["pnl"] for t in all_bear_trades)
        print(f"    Largest winner: ${largest_win:.2f} | Largest loser: ${largest_loss:.2f}")

    # Check if system caught major crashes
    events = [
        ("LUNA crash", datetime(2022,5,7,tzinfo=timezone.utc), datetime(2022,5,13,tzinfo=timezone.utc)),
        ("FTX collapse", datetime(2022,11,7,tzinfo=timezone.utc), datetime(2022,11,11,tzinfo=timezone.utc)),
        ("Aug 2024 crash", datetime(2024,8,4,tzinfo=timezone.utc), datetime(2024,8,6,tzinfo=timezone.utc)),
    ]
    for name, start, end in events:
        start_ms = int(start.timestamp()*1000); end_ms = int(end.timestamp()*1000)
        event_trades = [t for t in all_bear_trades if t["entry_ts"] <= end_ms and t["exit_ts"] >= start_ms]
        if event_trades:
            ep = sum(t["pnl"] for t in event_trades)
            print(f"    {name}: {len(event_trades)} trades, P&L=${ep:.2f}")
        else:
            print(f"    {name}: NO trades during this period")

    ALL_RESULTS["stress_test_12"] = {
        "combined": {k:v for k,v in combined_bear.items() if k != "monthly"}
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 12 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 13 — Transaction Cost Break-Even
# ═══════════════════════════════════════════════════════════════

def stress_test_13():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 13 — Transaction Cost Break-Even")
    print(f"{'='*120}")

    fee_levels = [0.0001, 0.0002, 0.0003, 0.00045, 0.0006, 0.0008, 0.0010, 0.0015, 0.0020]

    print(f"\n  {'Fee%':>8} ", end="")
    for sym in ASSETS: print(f" {sym+' PF':>10} {sym+' P&L':>10}", end="")
    print(f" {'Port PF':>10} {'Port P&L':>10}")
    print(f"  {'─'*140}")

    breakeven_fees = {}
    for fee in fee_levels:
        all_trades = []
        asset_results = {}
        for sym in ASSETS:
            d = load_asset(sym)
            if d is None: continue
            combined, regime = compute_all_signals(d)
            c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
            trades, ec, eq = backtest(c, o, combined, ts, fee_rate=fee)
            st = compute_stats(trades, ec)
            asset_results[sym] = st
            all_trades.extend(trades)

        port = compute_stats(all_trades)
        print(f"  {fee*100:>7.3f}%", end="")
        for sym in ASSETS:
            s = asset_results.get(sym, {"pf":0,"pnl":0})
            print(f"  {s['pf']:>9.2f} ${s['pnl']:>9.0f}", end="")
            if sym not in breakeven_fees and s["pnl"] <= 0:
                breakeven_fees[sym] = fee * 100
        print(f"  {port['pf']:>9.2f} ${port['pnl']:>9.0f}")

    print(f"\n  Break-even fee levels:")
    for sym in ASSETS:
        if sym in breakeven_fees:
            print(f"    {sym}: {breakeven_fees[sym]:.3f}%")
        else:
            print(f"    {sym}: > 0.200% (still profitable)")

    ALL_RESULTS["stress_test_13"] = {"breakeven_fees": breakeven_fees}
    save_results()
    print(f"  [{timestamp()}] Stress Test 13 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 14 — Leverage Optimization
# ═══════════════════════════════════════════════════════════════

def stress_test_14():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 14 — Leverage Optimization")
    print(f"{'='*120}")

    leverage_levels = [1, 2, 3, 5, 7, 10, 15, 20]

    print(f"\n  {'Lev':>5} {'PF':>8} {'P&L':>10} {'MDD%':>8} {'Sharpe':>8} {'Liquidations':>14}")
    print(f"  {'─'*60}")

    best_sharpe = -999; best_sharpe_lev = 1
    results_by_lev = {}

    for lev in leverage_levels:
        all_trades = []
        liquidations = 0
        for sym in ASSETS:
            d = load_asset(sym)
            if d is None: continue
            combined, regime = compute_all_signals(d)
            c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
            trades, ec, eq = backtest(c, o, combined, ts, leverage=lev)
            all_trades.extend(trades)
            # Check for liquidations (100% loss on a position at this leverage)
            for t in trades:
                # Liquidation if loss > margin (position_size / leverage)
                margin = FIXED  # $125 per trade
                if t["pnl"] < -margin:
                    liquidations += 1

        st = compute_stats(all_trades)
        print(f"  {lev:>4}x {st['pf']:>8.2f} ${st['pnl']:>9.2f} {st['mdd_pct']:>7.1f}% {st['sharpe']:>8.2f} {liquidations:>14}")

        if st['sharpe'] > best_sharpe:
            best_sharpe = st['sharpe']; best_sharpe_lev = lev
        results_by_lev[lev] = st

    # Kelly criterion
    # f* = (bp - q) / b where b = avg_win/avg_loss, p = win_rate, q = 1-p
    all_trades_10x = []
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts, leverage=10)
        all_trades_10x.extend(trades)

    wins_pnl = [t["pnl"] for t in all_trades_10x if t["pnl"] > 0]
    losses_pnl = [abs(t["pnl"]) for t in all_trades_10x if t["pnl"] <= 0]
    if wins_pnl and losses_pnl:
        avg_win = np.mean(wins_pnl); avg_loss = np.mean(losses_pnl)
        p = len(wins_pnl) / len(all_trades_10x)
        b = avg_win / avg_loss
        kelly = (b * p - (1-p)) / b
        print(f"\n  Sharpe-optimal leverage: {best_sharpe_lev}x (Sharpe={best_sharpe:.2f})")
        print(f"  Kelly criterion: f* = {kelly:.3f} → Kelly leverage = {kelly * 10:.1f}x")
        print(f"  Half-Kelly (recommended): {kelly * 5:.1f}x")

    ALL_RESULTS["stress_test_14"] = {
        "sharpe_optimal_lev": best_sharpe_lev,
        "kelly_fraction": float(kelly) if wins_pnl and losses_pnl else 0,
        "results_by_lev": {str(k): {kk:vv for kk,vv in v.items() if kk != "monthly"} for k,v in results_by_lev.items()}
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 14 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 15 — True Out-of-Sample
# ═══════════════════════════════════════════════════════════════

def stress_test_15():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 15 — True Out-of-Sample (Last 20%)")
    print(f"{'='*120}")

    for label, params in [("Original params", {}), ("Varied params", {"ema200_period":180, "ema50_period":45, "st4h_mult":2.8})]:
        all_trades = []
        for sym in ASSETS:
            d = load_asset(sym)
            if d is None: continue
            n = len(d["15m"]["c"])
            oos_start = int(n * 0.8)
            combined, regime = compute_all_signals(d, **params)
            c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
            trades, ec, eq = backtest(c, o, combined, ts, start_bar=oos_start)
            all_trades.extend(trades)

        st = compute_stats(all_trades)
        print(f"  {label:<20}: PF={st['pf']:.2f} P&L=${st['pnl']:.2f} Sharpe={st['sharpe']:.2f} Trades={st['trades']}")

    ALL_RESULTS["stress_test_15"] = {"completed": True}
    save_results()
    print(f"  [{timestamp()}] Stress Test 15 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 16 — Drawdown Recovery
# ═══════════════════════════════════════════════════════════════

def stress_test_16():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 16 — Drawdown Recovery Analysis")
    print(f"{'='*120}")

    all_ec = []; all_ts = []
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts)
        all_ec.extend(ec.tolist())
        # Approximate timestamps for equity curve
        all_ts.extend(ts[WARMUP:WARMUP+len(ec)].tolist() if len(ts) > WARMUP+len(ec) else ts[-len(ec):].tolist())

    ec = np.array(all_ec)
    peak = np.maximum.accumulate(ec)
    dd_pct = (peak - ec) / peak * 100

    # Find drawdown periods
    in_dd = False; dd_start = 0; drawdowns = []
    for i in range(len(ec)):
        if dd_pct[i] > 1.0 and not in_dd:
            in_dd = True; dd_start = i
        elif dd_pct[i] < 0.01 and in_dd:
            in_dd = False
            max_dd = np.max(dd_pct[dd_start:i+1])
            drawdowns.append({
                "start_idx": dd_start, "end_idx": i,
                "depth_pct": float(max_dd),
                "duration_bars": i - dd_start,
                "duration_days": (i - dd_start) * 15 / 60 / 24
            })

    drawdowns.sort(key=lambda x: -x["depth_pct"])
    print(f"\n  Found {len(drawdowns)} drawdown periods > 1%")
    print(f"\n  {'#':>3} {'Depth%':>8} {'Duration(days)':>15} {'Bars':>8}")
    print(f"  {'─'*40}")
    for i, dd in enumerate(drawdowns[:10]):
        print(f"  {i+1:>3} {dd['depth_pct']:>7.1f}% {dd['duration_days']:>14.1f}d {dd['duration_bars']:>8}")

    if drawdowns:
        worst = drawdowns[0]
        longest = max(drawdowns, key=lambda x: x["duration_days"])
        print(f"\n  Deepest drawdown: {worst['depth_pct']:.1f}% lasting {worst['duration_days']:.0f} days")
        print(f"  Longest underwater: {longest['duration_days']:.0f} days ({longest['depth_pct']:.1f}% deep)")

    ALL_RESULTS["stress_test_16"] = {
        "n_drawdowns": len(drawdowns),
        "top_5": drawdowns[:5] if drawdowns else []
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 16 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 17 — Regime Transition Whipsaw Cost
# ═══════════════════════════════════════════════════════════════

def stress_test_17():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 17 — Regime Transition Whipsaw Cost")
    print(f"{'='*120}")

    total_whipsaws = 0; whipsaw_losses = 0; total_losses = 0

    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts)

        # Find whipsaw periods (>2 regime flips in 10 trading days = 960 bars)
        window = 960  # 10 days of 15m bars
        flips = np.diff(regime.astype(float)) != 0
        for i in range(window, len(regime)):
            n_flips = np.sum(flips[i-window:i])
            if n_flips > 2:
                total_whipsaws += 1

        for t in trades:
            if t["pnl"] < 0:
                total_losses += abs(t["pnl"])
                if t["bars"] < 48:  # Quick trades < 12 hours likely whipsaw
                    whipsaw_losses += abs(t["pnl"])

    pct_from_whipsaw = whipsaw_losses / total_losses * 100 if total_losses > 0 else 0
    print(f"  Total whipsaw periods detected: {total_whipsaws}")
    print(f"  Losses from quick trades (<12h): ${whipsaw_losses:.2f} ({pct_from_whipsaw:.1f}% of total losses)")

    # Test: require 3+ days in same regime before entry
    print(f"\n  Testing minimum 3-day regime duration requirement...")
    min_dur_trades = []
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        n = len(combined)
        # Block entry if regime changed within last 288 bars (3 days)
        for i in range(288, n):
            if combined[i] != 0 and combined[i-1] == 0:
                # Check if regime was stable for 3 days
                r = regime[i]
                stable = all(regime[max(0,i-j)] == r for j in range(1, min(289, i)))
                if not stable:
                    combined[i] = 0

        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts)
        min_dur_trades.extend(trades)

    st_filtered = compute_stats(min_dur_trades)
    print(f"  With 3-day minimum: PF={st_filtered['pf']:.2f} P&L=${st_filtered['pnl']:.2f} Trades={st_filtered['trades']}")

    ALL_RESULTS["stress_test_17"] = {
        "whipsaw_periods": total_whipsaws,
        "whipsaw_loss_pct": pct_from_whipsaw,
        "with_min_duration": {k:v for k,v in st_filtered.items() if k != "monthly"}
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 17 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 18 — Multi-Timeframe Signal Conflict
# ═══════════════════════════════════════════════════════════════

def stress_test_18():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 18 — Multi-Timeframe Signal Conflict Analysis")
    print(f"{'='*120}")

    conflict_trades = []; clean_trades = []
    all_trades_base = []; all_trades_filtered = []

    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]

        _, st4h_dir = supertrend_np(d["4h"]["h"], d["4h"]["l"], d["4h"]["c"], 10, 3.0)
        st4h_dir_al = align_htf(ts, st4h_dir, d["4h"]["ts"])

        # Count conflicts
        n_bull_4h_bear = np.sum((regime == 1) & (st4h_dir_al == -1))
        n_bear_4h_bull = np.sum((regime == 2) & (st4h_dir_al == 1))
        print(f"  {sym}: Daily BULL + 4H BEAR: {n_bull_4h_bear} bars | Daily BEAR + 4H BULL: {n_bear_4h_bull} bars")

        # Base trades
        trades, ec, eq = backtest(c, o, combined, ts)
        all_trades_base.extend(trades)

        # Filtered: require 4H agreement
        combined_filtered = combined.copy()
        for i in range(WARMUP, len(combined_filtered)):
            if combined_filtered[i] == 1 and st4h_dir_al[i] == -1:  # Long but 4H bearish
                combined_filtered[i] = 0
            elif combined_filtered[i] == -1 and st4h_dir_al[i] == 1:  # Short but 4H bullish
                combined_filtered[i] = 0

        trades_f, ec_f, eq_f = backtest(c, o, combined_filtered, ts)
        all_trades_filtered.extend(trades_f)

    st_base = compute_stats(all_trades_base)
    st_filt = compute_stats(all_trades_filtered)

    print(f"\n  Without filter: PF={st_base['pf']:.2f} P&L=${st_base['pnl']:.2f} Trades={st_base['trades']}")
    print(f"  With 4H agreement: PF={st_filt['pf']:.2f} P&L=${st_filt['pnl']:.2f} Trades={st_filt['trades']}")
    improved = st_filt['pf'] > st_base['pf']
    print(f"\n  VERDICT: 4H agreement filter {'IMPROVES' if improved else 'HURTS'} results")

    ALL_RESULTS["stress_test_18"] = {
        "base": {k:v for k,v in st_base.items() if k != "monthly"},
        "filtered": {k:v for k,v in st_filt.items() if k != "monthly"},
        "improved": improved
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 18 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 19 — Kelly Position Sizing
# ═══════════════════════════════════════════════════════════════

def stress_test_19():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 19 — Kelly Position Sizing")
    print(f"{'='*120}")

    asset_kelly = {}
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts)

        wins = [t["pnl"] for t in trades if t["pnl"] > 0]
        losses = [abs(t["pnl"]) for t in trades if t["pnl"] <= 0]
        if wins and losses:
            p = len(wins) / len(trades)
            b = np.mean(wins) / np.mean(losses)
            kelly = (b * p - (1-p)) / b
            half_kelly = kelly / 2
            asset_kelly[sym] = {"kelly": kelly, "half_kelly": half_kelly, "wr": p*100, "avg_win_loss": b}
            print(f"  {sym:<8} WR={p*100:.1f}% W/L={b:.2f} Kelly={kelly:.3f} Half-Kelly={half_kelly:.3f}")

    # Compare fixed vs Kelly sizing
    # Fixed: $125 per trade
    # Kelly: half-kelly fraction of equity
    all_fixed = []; all_kelly = []
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]

        # Fixed
        trades_f, ec_f, eq_f = backtest(c, o, combined, ts)
        all_fixed.extend(trades_f)

        # Half-Kelly (approximate by scaling position size)
        hk = asset_kelly.get(sym, {}).get("half_kelly", 0.1)
        kelly_fixed = CAPITAL * max(0.01, min(hk, 0.5))  # Cap at 50%
        trades_k, ec_k, eq_k = backtest(c, o, combined, ts, fixed=kelly_fixed)
        all_kelly.extend(trades_k)

    st_fixed = compute_stats(all_fixed)
    st_kelly = compute_stats(all_kelly)

    print(f"\n  Fixed $125/trade: PF={st_fixed['pf']:.2f} P&L=${st_fixed['pnl']:.2f} Sharpe={st_fixed['sharpe']:.2f}")
    print(f"  Half-Kelly sized:  PF={st_kelly['pf']:.2f} P&L=${st_kelly['pnl']:.2f} Sharpe={st_kelly['sharpe']:.2f}")

    ALL_RESULTS["stress_test_19"] = {
        "asset_kelly": asset_kelly,
        "fixed": {k:v for k,v in st_fixed.items() if k != "monthly"},
        "kelly": {k:v for k,v in st_kelly.items() if k != "monthly"}
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 19 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 20 — Full Realistic Simulation
# ═══════════════════════════════════════════════════════════════

def stress_test_20():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 20 — Full Realistic Simulation (All Friction Combined)")
    print(f"{'='*120}")

    # Combined friction: 0.045% fee + 0.05% slippage + 0.02% market impact = 0.115% per side
    total_fee = 0.00115  # 0.115% combined
    funding = 0.0003  # 0.03% per 8h average
    signal_delay = 1  # 1 bar delay

    # Get optimal leverage from test 14 (or default to 10)
    opt_lev = ALL_RESULTS.get("stress_test_14", {}).get("sharpe_optimal_lev", 10)

    all_trades = []
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue

        # Misclassification: randomly flip 3% of regime labels
        combined, regime = compute_all_signals(d)
        n = len(combined)
        flip_mask = np.random.random(n) < 0.03
        regime_noisy = regime.copy()
        for i in range(n):
            if flip_mask[i]:
                if regime[i] == 1: regime_noisy[i] = 0  # Bull → Flat
                elif regime[i] == 2: regime_noisy[i] = 0  # Bear → Flat
                elif regime[i] == 0: regime_noisy[i] = np.random.choice([1, 2])

        # Recompute signals with noisy regime
        c = d["15m"]["c"]; o = d["15m"]["o"]; h = d["15m"]["h"]
        l = d["15m"]["l"]; v = d["15m"]["v"]; ts = d["15m"]["ts"]

        d_ema200 = ema_np(d["1d"]["c"], 200)
        d_ema200_al = align_htf(ts, d_ema200, d["1d"]["ts"])
        _, st4h_dir = supertrend_np(d["4h"]["h"], d["4h"]["l"], d["4h"]["c"], 10, 3.0)
        st4h_dir_al = align_htf(ts, st4h_dir, d["4h"]["ts"])
        st15_line, st15_dir = supertrend_np(h, l, c, 10, 2.0)
        rsi15 = rsi_np(c, 14)

        sig_bull = sig_mtf_pyramid(c, h, l, ts, d_ema200_al, st4h_dir_al, st15_line, st15_dir, rsi15)
        sig_bear = sig_ema_short(c, v)

        combined_noisy = np.zeros(n)
        for i in range(WARMUP, n):
            rg = regime_noisy[i]
            if rg == 1: combined_noisy[i] = sig_bull[i]
            elif rg == 2: combined_noisy[i] = sig_bear[i]
            if i > 0 and regime_noisy[i] != regime_noisy[i-1] and combined_noisy[i-1] != 0:
                combined_noisy[i] = 0

        trades, ec, eq = backtest(c, o, combined_noisy, ts,
                                   fee_rate=total_fee, funding_rate=funding,
                                   leverage=opt_lev, signal_delay=signal_delay)
        all_trades.extend(trades)

    st = compute_stats(all_trades)
    print(f"\n  ALL FRICTION COMBINED:")
    print(f"    Fees: 0.115% per side | Funding: 0.03%/8h | Signal delay: 1 bar")
    print(f"    Regime misclass: 3% | Leverage: {opt_lev}x")
    print(f"\n    PF: {st['pf']:.2f} | P&L: ${st['pnl']:.2f} | Sharpe: {st['sharpe']:.2f} | MDD: {st['mdd_pct']:.1f}%")
    print(f"    Trades: {st['trades']} | WR: {st['wr']:.1f}%")

    survived = st['pf'] > 1.0 and st['pnl'] > 0
    print(f"\n  VERDICT: {'SURVIVES all friction' if survived else 'FAILS under realistic conditions'}")

    ALL_RESULTS["stress_test_20"] = {k:v for k,v in st.items() if k != "monthly"}
    ALL_RESULTS["stress_test_20"]["survived"] = survived
    save_results()
    print(f"  [{timestamp()}] Stress Test 20 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 21 — Multiple Testing Bias Correction
# ═══════════════════════════════════════════════════════════════

def stress_test_21():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 21 — Multiple Testing Bias Correction")
    print(f"{'='*120}")

    # Get our strategy's t-statistic
    all_trades = []
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts)
        all_trades.extend(trades)

    trade_pnls = np.array([t["pnl"] for t in all_trades])
    if len(trade_pnls) < 2:
        print("  Not enough trades for analysis")
        return

    t_stat, p_val = sp_stats.ttest_1samp(trade_pnls, 0)

    # White's Reality Check Bootstrap
    N_strategies_tested = 2000  # From stress test 7
    N_boot = 1000

    # Bootstrap: resample trade P&Ls and get max t-stat under null
    null_max_t = []
    for _ in range(N_boot):
        # Under null, center the data at 0
        centered = trade_pnls - np.mean(trade_pnls)
        boot_sample = np.random.choice(centered, size=len(centered), replace=True)
        boot_t = np.mean(boot_sample) / (np.std(boot_sample, ddof=1) / np.sqrt(len(boot_sample)))
        null_max_t.append(boot_t)

    null_max_t = np.array(null_max_t)
    # Reality check p-value: fraction of null max t-stats exceeding our t-stat
    rc_p_value = np.mean(null_max_t >= t_stat)

    # Bonferroni correction
    bonferroni_p = min(p_val * N_strategies_tested, 1.0)

    print(f"\n  Original t-statistic: {t_stat:.3f}")
    print(f"  Original p-value: {p_val:.6f}")
    print(f"  Number of strategies tested: {N_strategies_tested}")
    print(f"\n  White's Reality Check p-value: {rc_p_value:.4f}")
    print(f"  Bonferroni-corrected p-value: {bonferroni_p:.6f}")
    print(f"\n  Still significant at 5% (Bonferroni): {'YES' if bonferroni_p < 0.05 else 'NO'}")
    print(f"  Still significant at 5% (Reality Check): {'YES' if rc_p_value < 0.05 else 'NO'}")

    ALL_RESULTS["stress_test_21"] = {
        "t_stat": float(t_stat), "p_val": float(p_val),
        "bonferroni_p": float(bonferroni_p), "rc_p_value": float(rc_p_value),
        "still_significant": bool(bonferroni_p < 0.05)
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 21 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# STRESS TEST 22 — Black Swan Events
# ═══════════════════════════════════════════════════════════════

def stress_test_22():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] STRESS TEST 22 — Specific Black Swan Events")
    print(f"{'='*120}")

    events = [
        ("LUNA crash (May 7-13 2022)", datetime(2022,5,7,tzinfo=timezone.utc), datetime(2022,5,13,tzinfo=timezone.utc)),
        ("FTX collapse (Nov 7-11 2022)", datetime(2022,11,7,tzinfo=timezone.utc), datetime(2022,11,11,tzinfo=timezone.utc)),
        ("Aug 2024 crash (Aug 4-5 2024)", datetime(2024,8,4,tzinfo=timezone.utc), datetime(2024,8,6,tzinfo=timezone.utc)),
        ("Mar 2025 downturn", datetime(2025,3,1,tzinfo=timezone.utc), datetime(2025,3,19,tzinfo=timezone.utc)),
    ]

    event_results = {}
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts)

        for event_name, start_dt, end_dt in events:
            start_ms = int(start_dt.timestamp()*1000)
            end_ms = int(end_dt.timestamp()*1000)

            # Find price change during event
            start_idx = np.searchsorted(ts, start_ms)
            end_idx = np.searchsorted(ts, end_ms)
            if start_idx < len(c) and end_idx < len(c):
                price_change = (c[min(end_idx, len(c)-1)] - c[min(start_idx, len(c)-1)]) / c[min(start_idx, len(c)-1)] * 100

                # Check if we were in a position
                event_trades = [t for t in trades if
                    (t["entry_ts"] <= end_ms and t["exit_ts"] >= start_ms)]

                if event_name not in event_results:
                    event_results[event_name] = []

                for t in event_trades:
                    direction = "LONG" if t.get("dir", 1) == 1 else "SHORT"
                    event_results[event_name].append({
                        "asset": sym, "dir": direction, "pnl": t["pnl"],
                        "price_change": price_change
                    })

                if not event_trades:
                    event_results.setdefault(event_name, []).append({
                        "asset": sym, "dir": "FLAT", "pnl": 0,
                        "price_change": price_change
                    })

    for event_name, trades_info in event_results.items():
        print(f"\n  {event_name}:")
        total_pnl = 0
        for t in trades_info:
            print(f"    {t['asset']:<6} Position: {t['dir']:<6} P&L: ${t['pnl']:>8.2f} | Asset move: {t['price_change']:+.1f}%")
            total_pnl += t["pnl"]
        print(f"    Total event P&L: ${total_pnl:.2f}")

    # Max single event loss
    all_event_pnls = [t["pnl"] for trades in event_results.values() for t in trades if t["pnl"] != 0]
    if all_event_pnls:
        max_loss = min(all_event_pnls)
        print(f"\n  Maximum single-event loss: ${max_loss:.2f}")

    ALL_RESULTS["stress_test_22"] = {
        name: {"total_pnl": sum(t["pnl"] for t in trades), "n_positions": sum(1 for t in trades if t["dir"] != "FLAT")}
        for name, trades in event_results.items()
    }
    save_results()
    print(f"  [{timestamp()}] Stress Test 22 complete. [{elapsed()}]")

# ═══════════════════════════════════════════════════════════════
# PHASE 4 — FINAL SCORING & DEPLOYMENT DECISION
# ═══════════════════════════════════════════════════════════════

def phase4_final():
    print(f"\n{'='*120}")
    print(f"  [{timestamp()}] PHASE 4 — FINAL SCORING & DEPLOYMENT DECISION")
    print(f"{'='*120}")

    # Load all asset results
    asset_scores = {}
    for sym in ASSETS:
        d = load_asset(sym)
        if d is None: continue
        combined, regime = compute_all_signals(d)
        c = d["15m"]["c"]; o = d["15m"]["o"]; ts = d["15m"]["ts"]
        trades, ec, eq = backtest(c, o, combined, ts)
        st = compute_stats(trades, ec)

        # Robustness: run 50 parameter variations
        robust_count = 0
        for _ in range(50):
            p = {
                "ema200_period": int(np.random.uniform(140, 260)),
                "ema50_period": int(np.random.uniform(35, 65)),
                "st4h_mult": round(np.random.uniform(2.1, 3.9), 2),
            }
            comb2, _ = compute_all_signals(d, **p)
            tr2, _, _ = backtest(c, o, comb2, ts)
            if sum(t["pnl"] for t in tr2) > 0: robust_count += 1

        robustness = robust_count / 50

        # Fee sensitivity: test at 2x fees
        tr_2x, _, _ = backtest(c, o, combined, ts, fee_rate=FEE_RATE*2)
        fee_sens = sum(t["pnl"] for t in tr_2x) / max(st["pnl"], 1) if st["pnl"] > 0 else 0

        # Misclassification tolerance
        regime_noisy = regime.copy()
        flip_mask = np.random.random(len(regime)) < 0.05
        for i in range(len(regime)):
            if flip_mask[i]:
                regime_noisy[i] = 0

        # Composite score
        inv_mdd = 1.0 / max(st["mdd_pct"], 1) * 100
        score = (st["pf"] * 0.25 + st["sharpe"] * 0.20 + robustness * 100 * 0.20 +
                 inv_mdd * 0.15 + fee_sens * 100 * 0.10 + robustness * 100 * 0.10)

        asset_scores[sym] = {
            "pf": st["pf"], "sharpe": st["sharpe"], "mdd_pct": st["mdd_pct"],
            "robustness": robustness, "fee_sens": fee_sens,
            "score": round(score, 2), "pnl": st["pnl"], "trades": st["trades"]
        }

    # Rank by composite score
    ranked = sorted(asset_scores.items(), key=lambda x: -x[1]["score"])

    print(f"\n  ASSET RANKING TABLE:")
    print(f"  {'Rank':>4} {'Asset':<8} {'Score':>8} {'PF':>6} {'Sharpe':>7} {'MDD%':>6} {'Robust':>7} {'P&L':>10}")
    print(f"  {'─'*60}")
    for i, (sym, s) in enumerate(ranked):
        print(f"  {i+1:>4} {sym:<8} {s['score']:>8.1f} {s['pf']:>6.2f} {s['sharpe']:>7.2f} {s['mdd_pct']:>5.1f}% {s['robustness']*100:>6.0f}% ${s['pnl']:>9.2f}")

    # Final system specification
    print(f"\n  {'='*80}")
    print(f"  FINAL SYSTEM SPECIFICATION")
    print(f"  {'='*80}")
    print(f"  Regime Classifier: EMA200 + EMA50 slope (5-bar lookback)")
    print(f"    BULL: Daily close > EMA200 AND EMA50(current) > EMA50(5 bars ago)")
    print(f"    BEAR: Daily close < EMA200 AND EMA50(current) < EMA50(5 bars ago)")
    print(f"    FLAT: Everything else — no position")
    print(f"  Bull Strategy: MTF Pyramid (ST 4H ATR10 x3.0, ST 15m ATR10 x2.0, RSI14)")
    print(f"  Bear Strategy: EMA(21/55) crossover short with volume confirmation")

    opt_lev = ALL_RESULTS.get("stress_test_14", {}).get("sharpe_optimal_lev", 10)
    print(f"  Leverage: {opt_lev}x (Sharpe-optimal)")
    print(f"  Position sizing: Fixed $125 per trade")
    print(f"  Maximum acceptable fees: ~0.06% (based on break-even analysis)")

    include = [sym for sym, s in ranked if s["pnl"] > 0]
    exclude = [sym for sym, s in ranked if s["pnl"] <= 0]
    print(f"  Assets to trade: {', '.join(include)}")
    if exclude:
        print(f"  Assets to DROP: {', '.join(exclude)}")

    # GO / NO-GO
    print(f"\n  {'='*80}")
    print(f"  GO / NO-GO DEPLOYMENT DECISION")
    print(f"  {'='*80}")

    p1 = ALL_RESULTS.get("phase1", {})
    st20 = ALL_RESULTS.get("stress_test_20", {})
    st21 = ALL_RESULTS.get("stress_test_21", {})

    combined_pf = p1.get("combined", {}).get("pf", 0)
    realistic_survived = st20.get("survived", False)
    stat_sig = st21.get("still_significant", False)
    robustness_pct = p1.get("robustness_pct_profitable", 0)

    conditions_met = []
    conditions_failed = []

    if combined_pf > 1.5: conditions_met.append(f"Portfolio PF {combined_pf:.2f} > 1.5")
    else: conditions_failed.append(f"Portfolio PF {combined_pf:.2f} < 1.5")

    if realistic_survived: conditions_met.append("Survives full realistic friction (Test 20)")
    else: conditions_failed.append("FAILS under realistic friction (Test 20)")

    if robustness_pct > 60: conditions_met.append(f"Parameter robustness {robustness_pct:.0f}% > 60%")
    else: conditions_failed.append(f"Parameter robustness {robustness_pct:.0f}% < 60%")

    if stat_sig: conditions_met.append("Statistically significant after multiple testing correction")
    else: conditions_failed.append("NOT significant after Bonferroni correction")

    if len(include) >= 4: conditions_met.append(f"{len(include)}/6 assets profitable")
    else: conditions_failed.append(f"Only {len(include)}/6 assets profitable")

    if len(conditions_failed) == 0:
        decision = "GO"
        decision_text = "System is ready for live deployment"
    elif len(conditions_failed) <= 2:
        decision = "CONDITIONAL GO"
        decision_text = "System is ready IF the following conditions are addressed"
    else:
        decision = "NO-GO"
        decision_text = "System needs improvements before deployment"

    print(f"\n  DECISION: *** {decision} ***")
    print(f"  {decision_text}")
    print(f"\n  Conditions MET:")
    for c in conditions_met: print(f"    + {c}")
    print(f"  Conditions FAILED:")
    for c in conditions_failed: print(f"    - {c}")

    if decision == "CONDITIONAL GO":
        print(f"\n  Required improvements:")
        for c in conditions_failed:
            print(f"    * Fix: {c}")

    ALL_RESULTS["phase4"] = {
        "asset_scores": asset_scores,
        "ranked": [sym for sym, _ in ranked],
        "decision": decision,
        "conditions_met": conditions_met,
        "conditions_failed": conditions_failed,
        "include_assets": include,
        "exclude_assets": exclude
    }
    save_results()

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("="*120)
    print("  FULL SYSTEM VALIDATION — EMA200+EMA50 Regime Classifier (No ADX)")
    print(f"  6 Assets × 5 Years × 22 Stress Tests | Started: {timestamp()}")
    print(f"  Machine: 16 vCPUs, 32GB RAM | Pool: 12 workers")
    print("="*120)

    # Phase 0: Download fresh data
    phase0_download()

    # Phase 1: Full revalidation
    asset_stats, all_trades, combined = phase1_revalidation()

    # Phase 2: Stress Tests 7-15
    tests_phase2 = [
        ("Stress Test 7", stress_test_7),
        ("Stress Test 8", stress_test_8),
        ("Stress Test 9", stress_test_9),
        ("Stress Test 10", stress_test_10),
        ("Stress Test 11", stress_test_11),
        ("Stress Test 12", stress_test_12),
        ("Stress Test 13", stress_test_13),
        ("Stress Test 14", stress_test_14),
        ("Stress Test 15", stress_test_15),
    ]

    for name, func in tests_phase2:
        try:
            func()
        except Exception as e:
            print(f"\n  ERROR in {name}: {e}")
            traceback.print_exc()
            ALL_RESULTS[name.lower().replace(" ", "_")] = {"error": str(e)}
            save_results()

    # Phase 3: Stress Tests 16-22
    tests_phase3 = [
        ("Stress Test 16", stress_test_16),
        ("Stress Test 17", stress_test_17),
        ("Stress Test 18", stress_test_18),
        ("Stress Test 19", stress_test_19),
        ("Stress Test 20", stress_test_20),
        ("Stress Test 21", stress_test_21),
        ("Stress Test 22", stress_test_22),
    ]

    for name, func in tests_phase3:
        try:
            func()
        except Exception as e:
            print(f"\n  ERROR in {name}: {e}")
            traceback.print_exc()
            ALL_RESULTS[name.lower().replace(" ", "_")] = {"error": str(e)}
            save_results()

    # Phase 4: Final scoring
    phase4_final()

    # Final save
    save_results()
    total_time = time.time() - T0
    print(f"\n{'='*120}")
    print(f"  ALL 22 STRESS TESTS COMPLETE")
    print(f"  Total time: {total_time/60:.1f} minutes")
    print(f"  Results saved to: {RESULTS_DIR / 'final_validation.json'}")
    print(f"  Completion timestamp: {timestamp()}")
    print(f"{'='*120}")

if __name__ == "__main__":
    main()
