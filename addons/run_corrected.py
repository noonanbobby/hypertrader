#!/usr/bin/env python3
"""
Run corrected Phase 1 + ST20 only.
Saves results to /tmp/discovery/corrected_results.json
"""
import sys, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from full_validation import (
    phase0_download, phase1_revalidation, stress_test_20,
    ALL_RESULTS, save_results, timestamp, elapsed, T0, RESULTS_DIR
)

import numpy as np

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        if isinstance(obj, (np.bool_,)): return bool(obj)
        return super().default(obj)

def main():
    print("="*120)
    print("  CORRECTED VALIDATION — Phase 1 + ST20 Only")
    print(f"  Started: {timestamp()}")
    print("="*120)
    print()
    print("  FIXES APPLIED:")
    print("    1. Portfolio equity: align by timestamp and SUM (not concatenate)")
    print("    2. ST20 misclass: only flip ACTIVE bars (1→{2,0}, 2→{1,0}), never FLAT")
    print("    3. ST14 leverage: use P&L/MDD/liquidations, not Sharpe")
    print("    4. MTF Pyramid near-band: 0.5% (was 0.1%)")
    print("    5. Data start: 2020-01-01 (200-day EMA warmup)")
    print("    6. Slippage: 0.0005 (was 0.0001)")
    print("    7. ST16 drawdown: uses corrected portfolio equity curve")
    print("    8. Bootstrap: 2-week block resampling (was individual trades)")
    print()

    # Phase 0: Download fresh data (now from 2020)
    phase0_download()

    # Phase 1: Full revalidation with all fixes
    asset_stats, all_trades, combined, portfolio_ec, portfolio_ts = phase1_revalidation()

    # ST20: Full realistic simulation with corrected misclassification
    stress_test_20()

    # Save corrected results
    corrected = {
        "fixes_applied": [
            "1. Portfolio equity: timestamp-aligned sum",
            "2. ST20 misclass: only flip ACTIVE regime bars",
            "3. ST14: P&L/MDD/liquidations instead of Sharpe",
            "4. Near-band 0.5% (was 0.1%)",
            "5. Data from 2020-01-01 (EMA200 warmup)",
            "6. Slippage 0.0005 (was 0.0001)",
            "7. ST16 uses corrected portfolio equity",
            "8. Bootstrap: 2-week block resampling",
        ],
        "phase1": ALL_RESULTS.get("phase1", {}),
        "stress_test_20": ALL_RESULTS.get("stress_test_20", {}),
    }

    with open(RESULTS_DIR / "corrected_results.json", "w") as f:
        json.dump(corrected, f, cls=NpEncoder, indent=2)

    total_time = time.time() - T0
    print(f"\n{'='*120}")
    print(f"  CORRECTED VALIDATION COMPLETE")
    print(f"  Results saved to: {RESULTS_DIR / 'corrected_results.json'}")
    print(f"  Total time: {total_time/60:.1f} minutes")
    print(f"{'='*120}")

if __name__ == "__main__":
    main()
