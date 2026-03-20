# HyperTrader Regime MTF v3 — Pre-Deployment Checklist

Generated: 2026-03-20

---

## Indicator Setup

- [ ] Pine Script compiled without errors on TradingView
- [ ] Indicator applied to **BTCUSDT.P** 15m chart — regime background visible
- [ ] Indicator applied to **ETHUSDT.P** 15m chart
- [ ] Indicator applied to **SOLUSDT.P** 15m chart
- [ ] Status table shows on all 3 charts with current regime

## Signal Verification

- [ ] Historical **LONG** markers visible on BTC chart
- [ ] Historical **SHORT** markers visible on BTC chart
- [ ] **CLOSE** markers visible on BTC chart
- [ ] First BTC LONG signal on chart appears near **2020-07-22**
  - Rust trade log: entry `2020-07-22T01:15:00` @ $9,366.33
- [ ] First BTC SHORT signal on chart appears near **2021-05-19**
  - Rust trade log: entry `2021-05-19T01:30:00` @ $41,472.59
- [ ] If dates match within ±1 bar: indicator generates correct signals
- [ ] If dates DON'T match: **DO NOT GO LIVE** — investigate discrepancy

## Alert Setup

- [ ] All **9 alerts** created (3 per asset)
- [ ] Each alert set to **Once Per Bar Close** trigger
- [ ] Webhook URL configured: `https://[EC2_IP]/webhook`
- [ ] Alert messages contain correct JSON with your secret
- [ ] Test webhook received by EC2 — check: `sudo tail -20 /var/log/nginx/access.log`

### Alert Messages (copy per chart)

**BTCUSDT.P:**

| Alert | Message |
|-------|---------|
| BUY   | `{"secret": "[SECRET]", "strategy": "BTC Regime MTF", "action": "buy", "symbol": "BTCUSDT.P", "price": "{{close}}", "message": "MTF Pyramid long entry — regime BULL"}` |
| SELL  | `{"secret": "[SECRET]", "strategy": "BTC Regime MTF", "action": "sell", "symbol": "BTCUSDT.P", "price": "{{close}}", "message": "EMA cross short entry — regime BEAR"}` |
| CLOSE | `{"secret": "[SECRET]", "strategy": "BTC Regime MTF", "action": "close", "symbol": "BTCUSDT.P", "price": "{{close}}", "message": "Exit signal — close position"}` |

**ETHUSDT.P:**

| Alert | Message |
|-------|---------|
| BUY   | `{"secret": "[SECRET]", "strategy": "ETH Regime MTF", "action": "buy", "symbol": "ETHUSDT.P", "price": "{{close}}", "message": "MTF Pyramid long entry — regime BULL"}` |
| SELL  | `{"secret": "[SECRET]", "strategy": "ETH Regime MTF", "action": "sell", "symbol": "ETHUSDT.P", "price": "{{close}}", "message": "EMA cross short entry — regime BEAR"}` |
| CLOSE | `{"secret": "[SECRET]", "strategy": "ETH Regime MTF", "action": "close", "symbol": "ETHUSDT.P", "price": "{{close}}", "message": "Exit signal — close position"}` |

**SOLUSDT.P:**

| Alert | Message |
|-------|---------|
| BUY   | `{"secret": "[SECRET]", "strategy": "SOL Regime MTF", "action": "buy", "symbol": "SOLUSDT.P", "price": "{{close}}", "message": "MTF Pyramid long entry — regime BULL"}` |
| SELL  | `{"secret": "[SECRET]", "strategy": "SOL Regime MTF", "action": "sell", "symbol": "SOLUSDT.P", "price": "{{close}}", "message": "EMA cross short entry — regime BEAR"}` |
| CLOSE | `{"secret": "[SECRET]", "strategy": "SOL Regime MTF", "action": "close", "symbol": "SOLUSDT.P", "price": "{{close}}", "message": "Exit signal — close position"}` |

## Bot Readiness

- [ ] Bot is running: `systemctl status hypertrader`
- [ ] Hyperliquid leverage set: BTC=10x, ETH=10x, SOL=5x (all isolated)
- [ ] Telegram bot responding: `/status` command returns OK
- [ ] No open positions on Hyperliquid (clean start)

## Regime Sanity Check

- [ ] BTC regime shows ______ — does this match current market?
- [ ] ETH regime shows ______ — plausible?
- [ ] SOL regime shows ______ — plausible?
- [ ] Compare with Rust engine's latest output if available

## Live Monitoring (first 24 hours)

- [ ] Check Telegram for any alerts
- [ ] If a signal fires: verify position opened on Hyperliquid
- [ ] If no signals: verify the status table shows expected condition states
- [ ] Check EC2 logs for any errors: `journalctl -u hypertrader --since "1 hour ago"`

---

## Parameter Reference

| Parameter | Value | Source |
|-----------|-------|--------|
| Regime EMA200 period | 200 | `params.ema200_period` |
| Regime EMA50 period | 50 | `params.ema50_period` |
| Regime rising lookback | 5 | `params.ema50_rising_lookback` |
| 4H SuperTrend ATR period | 10 | `params.st_4h_atr_period` |
| 4H SuperTrend multiplier | 3.0 | `params.st_4h_multiplier` |
| 15m SuperTrend ATR period | 10 | `params.st_15m_atr_period` |
| 15m SuperTrend multiplier | 2.0 | `params.st_15m_multiplier` |
| Near band pct | 0.005 | `params.near_band_pct` |
| RSI period | 14 | `params.rsi_period` |
| RSI dip threshold | 45.0 | `params.rsi_threshold` |
| RSI lookback bars | 2 | `params.rsi_lookback` |
| Short EMA fast | 21 | `params.ema_fast` |
| Short EMA slow | 55 | `params.ema_slow` |
| Volume multiplier | 2.0 | `params.vol_mult` |
| Volume SMA period | 20 | `params.vol_sma_period` |

## Bot Configuration

| Asset | Leverage | Margin | Mode |
|-------|----------|--------|------|
| BTC | 10x | $125 | Isolated |
| ETH | 10x | $125 | Isolated |
| SOL | 5x | $125 | Isolated |
