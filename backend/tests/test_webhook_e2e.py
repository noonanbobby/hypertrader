"""End-to-end tests for the webhook flow including Hyperliquid constraint hardening."""

import asyncio

from tests.conftest import _webhook


# ── 1. Basic BUY opens a long position ────────────────────────────────

async def test_buy_opens_long(setup):
    client, price_mock, _ = setup

    resp = await client.post("/api/webhook", json=_webhook("buy"))
    data = resp.json()

    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}"
    assert data["success"] is True, f"Webhook failed: {data['message']}"
    assert data["trade_id"] is not None
    assert "buy" in data["message"].lower() or "long" in data["message"].lower()


# ── 2. SELL opens a short position ────────────────────────────────────

async def test_sell_opens_short(setup):
    client, price_mock, _ = setup

    resp = await client.post("/api/webhook", json=_webhook("sell"))
    data = resp.json()

    assert resp.status_code == 200
    assert data["success"] is True, f"Webhook failed: {data['message']}"
    assert data["trade_id"] is not None


# ── 3. BUY then SELL flips position (close long, open short) ─────────

async def test_buy_then_sell_flips(setup):
    client, price_mock, _ = setup

    # Open long at $100,000
    r1 = await client.post("/api/webhook", json=_webhook("buy"))
    assert r1.json()["success"] is True, f"BUY failed: {r1.json()['message']}"

    # Price rises to $101,000
    price_mock.return_value = 101000.0

    # SELL → should flip (close long with profit, open short)
    r2 = await client.post("/api/webhook", json=_webhook("sell"))
    d2 = r2.json()

    assert d2["success"] is True, f"SELL flip failed: {d2['message']}"
    assert "Closed long" in d2["message"]
    assert "P&L" in d2["message"]


# ── 4. SELL then BUY flips position (close short, open long) ─────────

async def test_sell_then_buy_flips(setup):
    client, price_mock, _ = setup

    # Open short at $100,000
    r1 = await client.post("/api/webhook", json=_webhook("sell"))
    assert r1.json()["success"] is True, f"SELL failed: {r1.json()['message']}"

    # Price drops to $99,000 → short in profit
    price_mock.return_value = 99000.0

    # BUY → should flip (close short with profit, open long)
    r2 = await client.post("/api/webhook", json=_webhook("buy"))
    d2 = r2.json()

    assert d2["success"] is True, f"BUY flip failed: {d2['message']}"
    assert "Closed short" in d2["message"]
    assert "P&L" in d2["message"]


# ── 5. Minimum $10 notional rejects tiny orders ──────────────────────

async def test_min_notional_rejection(setup):
    client, price_mock, _ = setup

    # Tiny quantity: 0.00001 BTC * $100,000 = $1 → below $10 minimum
    resp = await client.post(
        "/api/webhook",
        json=_webhook("buy", quantity=0.00001),
    )
    data = resp.json()

    assert data["success"] is False
    assert "minimum" in data["message"].lower() or "$10" in data["message"]


# ── 6. szDecimals rounding ────────────────────────────────────────────

async def test_sz_decimals_rounding(setup):
    """Quantity should be rounded to szDecimals (mocked to 2 here)."""
    client, price_mock, sz_mock = setup

    # Override szDecimals to 2
    sz_mock.return_value = 2

    # Use a price that creates an ugly quantity:
    price_mock.return_value = 33333.0
    # margin = 10000 * 0.02 = 200, notional = 200 * 10 = 2000
    # qty = 2000 / 33333 = 0.060001... → round(_, 2) = 0.06
    # check notional: 0.06 * 33333 = $1999.98 ≥ $10 ✓

    resp = await client.post("/api/webhook", json=_webhook("buy"))
    data = resp.json()

    assert data["success"] is True, f"Webhook failed: {data['message']}"
    assert "0.06" in data["message"]


# ── 7. Integer leverage ──────────────────────────────────────────────

async def test_integer_leverage(setup):
    """Leverage 10.7 rounds to 11, affecting position size."""
    client, price_mock, _ = setup
    from app.config import settings

    settings.leverage = 10.7  # int(round(10.7)) = 11

    # margin = 10000 * 0.02 = 200, notional = 200 * 11 = 2200
    # qty = 2200 / 100000 = 0.022
    resp = await client.post("/api/webhook", json=_webhook("buy"))
    data = resp.json()

    assert data["success"] is True, f"Webhook failed: {data['message']}"
    assert "0.022" in data["message"]

    # Reset
    settings.leverage = 10.0


# ── 8. Invalid secret is rejected ────────────────────────────────────

async def test_invalid_secret_rejected(setup):
    client, _, _ = setup

    payload = _webhook("buy")
    payload["secret"] = "wrong-secret"

    resp = await client.post("/api/webhook", json=payload)
    data = resp.json()

    assert data["success"] is False
    assert "secret" in data["message"].lower()


# ── 9. close_long closes an open long ────────────────────────────────

async def test_close_long(setup):
    client, price_mock, _ = setup

    # Open long
    r1 = await client.post("/api/webhook", json=_webhook("buy"))
    assert r1.json()["success"] is True, f"BUY failed: {r1.json()['message']}"

    # Close it
    r2 = await client.post("/api/webhook", json=_webhook("close_long"))
    d2 = r2.json()

    assert d2["success"] is True, f"close_long failed: {d2['message']}"
    assert "closed" in d2["message"].lower() or "P&L" in d2["message"]


# ── 10. close_short closes an open short ──────────────────────────────

async def test_close_short(setup):
    client, price_mock, _ = setup

    # Open short
    r1 = await client.post("/api/webhook", json=_webhook("sell"))
    assert r1.json()["success"] is True, f"SELL failed: {r1.json()['message']}"

    # Close it
    r2 = await client.post("/api/webhook", json=_webhook("close_short"))
    d2 = r2.json()

    assert d2["success"] is True, f"close_short failed: {d2['message']}"
    assert "closed" in d2["message"].lower() or "P&L" in d2["message"]


# ── 11. close_long with no position fails gracefully ──────────────────

async def test_close_no_position(setup):
    client, _, _ = setup

    resp = await client.post("/api/webhook", json=_webhook("close_long"))
    data = resp.json()

    assert data["success"] is False
    assert "no position" in data["message"].lower()


# ── 12. Same-side BUY→BUY closes and re-opens ────────────────────────

async def test_same_side_reopens(setup):
    client, price_mock, _ = setup

    # First BUY
    r1 = await client.post("/api/webhook", json=_webhook("buy"))
    assert r1.json()["success"] is True, f"BUY failed: {r1.json()['message']}"

    # Price changes
    price_mock.return_value = 102000.0

    # Second BUY (same side) → should close old long, open new long
    r2 = await client.post("/api/webhook", json=_webhook("buy"))
    d2 = r2.json()

    assert d2["success"] is True, f"Second BUY failed: {d2['message']}"
    assert "Closed long" in d2["message"]


# ── 13. Concurrent webhooks are serialized by lock ────────────────────

async def test_concurrent_webhooks_serialized(setup):
    """Two opposing signals fired simultaneously should not create dual positions."""
    client, price_mock, _ = setup

    buy_payload = _webhook("buy", strategy="concurrent_test")
    sell_payload = _webhook("sell", strategy="concurrent_test")

    # Fire both concurrently
    results = await asyncio.gather(
        client.post("/api/webhook", json=buy_payload),
        client.post("/api/webhook", json=sell_payload),
    )

    responses = [r.json() for r in results]
    successes = [r["success"] for r in responses]

    # Both should succeed — first creates position, second flips it
    assert all(successes), f"Not all succeeded: {responses}"

    # One of them should have flipped the other (mentions "Closed")
    messages = [r["message"] for r in responses]
    assert any("Closed" in m for m in messages), f"Expected a flip: {messages}"


# ── 14. Flip P&L is correct (long → short with price increase) ───────

async def test_flip_pnl_positive(setup):
    """When price rises and we flip long→short, P&L should be positive."""
    client, price_mock, _ = setup

    # Open long at $100,000 → qty ≈ 0.02
    r1 = await client.post("/api/webhook", json=_webhook("buy"))
    assert r1.json()["success"] is True

    # Price rises to $102,000
    price_mock.return_value = 102000.0

    # Flip to short
    r2 = await client.post("/api/webhook", json=_webhook("sell"))
    d2 = r2.json()
    assert d2["success"] is True, f"Flip failed: {d2['message']}"

    # P&L should be positive: (102000 - 100000) * 0.02 = $40 minus fees
    msg = d2["message"]
    assert "P&L: $" in msg
    pnl_str = msg.split("P&L: $")[1].split(" ")[0].split("|")[0].strip()
    pnl = float(pnl_str)
    assert pnl > 0, f"Expected positive P&L, got {pnl}"


# ── 15. Flip P&L is correct (short → long with price decrease) ───────

async def test_flip_pnl_short_profit(setup):
    """When price drops and we flip short→long, P&L should be positive."""
    client, price_mock, _ = setup

    # Open short at $100,000
    r1 = await client.post("/api/webhook", json=_webhook("sell"))
    assert r1.json()["success"] is True

    # Price drops to $98,000
    price_mock.return_value = 98000.0

    # Flip to long
    r2 = await client.post("/api/webhook", json=_webhook("buy"))
    d2 = r2.json()
    assert d2["success"] is True, f"Flip failed: {d2['message']}"

    msg = d2["message"]
    assert "P&L: $" in msg
    pnl_str = msg.split("P&L: $")[1].split(" ")[0].split("|")[0].strip()
    pnl = float(pnl_str)
    assert pnl > 0, f"Expected positive P&L, got {pnl}"


# ── 16. close_all closes everything ──────────────────────────────────

async def test_close_all(setup):
    client, price_mock, _ = setup

    # Open a position
    r1 = await client.post("/api/webhook", json=_webhook("buy"))
    assert r1.json()["success"] is True

    # Close all
    r2 = await client.post("/api/webhook", json=_webhook("close_all"))
    d2 = r2.json()

    assert d2["success"] is True, f"close_all failed: {d2['message']}"
    assert "closed all" in d2["message"].lower() or "P&L" in d2["message"]


# ── 17. Unknown action is rejected ───────────────────────────────────

async def test_unknown_action_rejected(setup):
    client, _, _ = setup

    resp = await client.post("/api/webhook", json=_webhook("invalid_action"))
    data = resp.json()

    assert data["success"] is False
    assert "unknown" in data["message"].lower()
