<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js-14-000000?style=for-the-badge&logo=next.js&logoColor=white" />
  <img src="https://img.shields.io/badge/TypeScript-5.7-3178C6?style=for-the-badge&logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/TailwindCSS-3.4-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white" />
</p>

# HyperTrader

A professional-grade automated trading system that receives **TradingView webhook signals** and executes perpetual futures trades on **Hyperliquid**. Built with a modern glassmorphism dashboard for real-time monitoring, analytics, and strategy management.

> Currently running in **paper trading mode** with real-time Hyperliquid price feeds, simulated slippage, and fee modeling.

---

## Features

**Trading Engine**
- Receive TradingView webhook alerts and auto-execute trades
- **Flip logic** — BUY signal closes any existing position and opens long; SELL signal closes and opens short
- **10x leverage** support with margin and notional tracking
- **Dynamic position sizing** via `size_pct` (percentage of strategy equity)
- Paper trading with real-time Hyperliquid mid prices, configurable slippage (0.05%), and taker fees (0.05%)
- Multi-strategy support with independent capital allocation and P&L tracking

**Dashboard**
- Real-time WebSocket-powered updates for positions, P&L, and trade fills
- Live market ticker with Hyperliquid price feeds
- Portfolio value with animated counters and trend indicators
- Daily / weekly / monthly P&L breakdown
- Open positions table with live unrealized P&L and margin info

**Analytics**
- Equity curve (TradingView Lightweight Charts)
- Drawdown visualization
- Returns distribution histogram
- Monthly returns heatmap
- Win rate, profit factor, Sharpe ratio, and more

**Trade Management**
- Full trade history with filtering (symbol, side, status, date range)
- Trade detail dialog with embedded price chart showing entry/exit markers
- Leverage, margin, and notional value tracking on every trade
- CSV export

**Strategy Management**
- Create, edit, pause/resume, and delete strategies
- Per-strategy metrics: equity, P&L, win rate, drawdown
- Risk parameters: max position size, max drawdown, daily loss limits

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy (async), SQLite, WebSockets |
| **Frontend** | Next.js 14 (App Router), TypeScript, TailwindCSS, SWR |
| **Charts** | TradingView Lightweight Charts, Recharts |
| **Real-time** | WebSocket bridge (FastAPI &rarr; Next.js client) |
| **Price Data** | Hyperliquid REST API (`allMids`, `candleSnapshot`) |
| **UI Design** | Glassmorphism, gradient borders, mesh gradient backgrounds |

---

## Project Structure

```
hypertrader/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, CORS, lifespan, WebSocket
│   │   ├── config.py               # Pydantic Settings (env-based)
│   │   ├── database.py             # Async SQLAlchemy engine + sessions
│   │   ├── models.py               # ORM models (Strategy, Trade, Position, Order, etc.)
│   │   ├── schemas.py              # Pydantic request/response schemas
│   │   ├── websocket_manager.py    # WebSocket connection manager + broadcast
│   │   ├── routers/
│   │   │   ├── webhook.py          # POST /api/webhook — TradingView receiver + flip logic
│   │   │   ├── strategies.py       # CRUD /api/strategies
│   │   │   ├── trades.py           # GET /api/trades (history + filters)
│   │   │   ├── positions.py        # GET /api/positions (live unrealized P&L)
│   │   │   ├── dashboard.py        # GET /api/dashboard (aggregated stats)
│   │   │   └── analytics.py        # GET /api/analytics (performance data)
│   │   └── services/
│   │       ├── trading_engine.py   # Abstract base + engine factory
│   │       ├── paper_trader.py     # Paper trading with slippage + fees
│   │       ├── live_trader.py      # Hyperliquid live execution (stub)
│   │       ├── position_manager.py # Position tracking, P&L calculation
│   │       ├── risk_manager.py     # Pre-trade risk checks
│   │       ├── market_data.py      # Hyperliquid price feed client
│   │       └── strategy_manager.py # Strategy lifecycle management
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── app/                    # Pages: dashboard, strategies, trades, analytics, settings
│       ├── components/
│       │   ├── dashboard/          # Portfolio value, P&L cards, positions, recent trades
│       │   ├── charts/             # Equity curve, drawdown, histogram, calendar, trade chart
│       │   ├── strategies/         # Strategy cards, create/edit dialogs, metrics
│       │   ├── trades/             # Trades table, filters, trade detail dialog
│       │   ├── layout/             # Sidebar, header, mode badge
│       │   └── ui/                 # Button, badge, card, dialog, input, toast
│       ├── hooks/                  # useWebSocket, useApi (SWR-based)
│       ├── lib/                    # API client, formatters, constants
│       └── types/                  # TypeScript interfaces
└── start.sh                        # Launch both servers
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+

### 1. Clone & Configure

```bash
git clone https://github.com/hpombo1337/hypertrader.git
cd hypertrader
cp backend/.env.example backend/.env
# Edit backend/.env with your webhook secret
```

### 2. Backend

```bash
cd backend
python -m venv venv
source venv/Scripts/activate    # Windows
# source venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend runs at `http://localhost:8000`

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard runs at `http://localhost:3000`

### 4. Or use the start script

```bash
chmod +x start.sh
./start.sh
```

---

## Configuration

Edit `backend/.env`:

```env
TRADING_MODE=paper              # paper | live
WEBHOOK_SECRET=your-secret-here # Must match TradingView alert payload
LEVERAGE=10.0                   # Position leverage (default 10x)
INITIAL_BALANCE=10000.0         # Starting paper balance
SLIPPAGE_PCT=0.05               # Simulated slippage %
TAKER_FEE_PCT=0.05              # Simulated taker fee %
DEFAULT_MAX_POSITION_PCT=25.0   # Max position size as % of equity
DEFAULT_MAX_DRAWDOWN_PCT=10.0   # Max drawdown before pausing
DEFAULT_DAILY_LOSS_LIMIT=500.0  # Daily loss limit in USD
```

---

## TradingView Webhook Setup

1. Expose your backend to the internet (e.g., [ngrok](https://ngrok.com/)):
   ```bash
   ngrok http 8000
   ```
2. In TradingView, create an alert on your strategy/indicator
3. Set the **Webhook URL** to your ngrok/public URL + `/api/webhook`
4. Set the **Alert message** to:

```json
{
  "secret": "your-secret-here",
  "strategy": "BTC 1H",
  "action": "buy",
  "symbol": "{{ticker}}",
  "size_pct": 10,
  "message": "{{strategy.order.comment}}"
}
```

### Webhook Fields

| Field | Type | Description |
|-------|------|-------------|
| `secret` | string | Must match `WEBHOOK_SECRET` in `.env` |
| `strategy` | string | Strategy name (auto-created if new) |
| `action` | string | `buy`, `sell`, `close_long`, `close_short`, `close_all` |
| `symbol` | string | Trading pair (e.g., `BTC`, `ETH`, `SOL`) |
| `size_pct` | float | Position size as % of strategy equity (default: 10%) |
| `quantity` | float | Fixed quantity override (optional) |
| `message` | string | Optional note attached to the trade |

### How Flip Logic Works

| Signal | Action |
|--------|--------|
| **BUY** | Close any existing position (long or short) &rarr; Open new **long** |
| **SELL** | Close any existing position (long or short) &rarr; Open new **short** |

This ensures the bot always follows the latest signal direction. P&L is recorded on each close.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check, trading mode, version |
| `POST` | `/api/webhook` | TradingView webhook receiver |
| `GET` | `/api/dashboard` | Aggregated stats (equity, P&L, win rate, etc.) |
| `GET` | `/api/strategies` | List all strategies |
| `POST` | `/api/strategies` | Create a strategy |
| `PATCH` | `/api/strategies/:id` | Update a strategy (name, capital, risk params) |
| `DELETE` | `/api/strategies/:id` | Delete a strategy |
| `GET` | `/api/trades` | Trade history with filters |
| `GET` | `/api/positions` | Open positions with live unrealized P&L |
| `GET` | `/api/analytics` | Performance metrics + equity curve data |
| `WS` | `/ws` | WebSocket for real-time events |

### Trade Filters

`GET /api/trades` supports: `strategy_id`, `symbol`, `side`, `status`, `start_date`, `end_date`, `limit`, `offset`

---

## Paper Trading

Paper mode fetches real-time mid prices from Hyperliquid and simulates:

- **Leverage**: Configurable (default 10x) — margin = notional / leverage
- **Slippage**: Applied to fill price (default 0.05%)
- **Fees**: Hyperliquid taker fee schedule (default 0.05% of notional)
- **Positions**: Tracked identically to live trades in the database
- **P&L**: Calculated on full notional, P&L % on margin used

Switching to live trading requires Hyperliquid API keys and changing `TRADING_MODE=live` in `.env`.

---

## License

MIT
