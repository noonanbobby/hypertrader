/* ── Hyperliquid Candle Data ── */
export interface HLCandle {
  t: number; // open time ms
  T: number; // close time ms
  s: string; // symbol
  i: string; // interval
  o: string; // open
  c: string; // close
  h: string; // high
  l: string; // low
  v: string; // volume
  n: number; // number of trades
}

export interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/* ── Indicators ── */
export interface SupertrendPoint {
  time: number;
  value: number;
  direction: "bullish" | "bearish";
}

export interface SupertrendSignal {
  time: number;
  type: "buy" | "sell";
  price: number;
  label: string;
}

export interface SqueezePoint {
  time: number;
  value: number;
  color: "brightGreen" | "darkGreen" | "brightRed" | "darkRed";
  squeezeOn: boolean;
}

export interface MacdRsiPoint {
  time: number;
  rsi: number;
  macdSignal: number;
  histogram: number;
  histogramColor: "brightGreen" | "paleGreen" | "brightRed" | "paleRed";
}

export interface EnrichedSTPoint {
  time: number;
  value: number;
  direction: "bullish" | "bearish";
  lineColor: "green" | "red" | "gray" | "orange";  // green=all filters pass, red=all pass bear, gray=filters fail, orange=recovery active
  lineStyle: "solid" | "dotted";  // dotted when recovery tightening
  htfDir: "bullish" | "bearish" | null;
  adxPass: boolean;
  squeezeOff: boolean;
  recoveryActive: boolean;
}

export interface ChartMarker {
  time: number;
  type: "buy" | "sell" | "exit" | "unfilteredBull" | "unfilteredBear" | "execBuy" | "execSell";
  price: number;
  label: string;
}

/* ── Backend API Types ── */
export interface DashboardStats {
  total_equity: number;
  total_pnl: number;
  daily_pnl: number;
  weekly_pnl: number;
  monthly_pnl: number;
  open_positions: number;
  active_strategies: number;
  total_trades: number;
  win_rate: number;
  best_trade: number;
  worst_trade: number;
  trading_mode: string;
}

export interface HLPortfolio {
  account_value: number;
  total_margin_used: number;
  total_unrealized_pnl: number;
  available_balance: number;
  perps_balance: number;
  spot_balance: number;
}

export interface HLPosition {
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  mark_price: number;
  unrealized_pnl: number;
  leverage: number;
  liquidation_price: number;
  margin_used: number;
  notional: number;
}

export interface HLFill {
  symbol: string;
  side: string;
  size: number;
  price: number;
  fee: number;
  time: string;
  closed_pnl: number;
}

export interface Trade {
  id: number;
  strategy_id: number;
  strategy_name: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  notional_value: number;
  margin_used: number;
  leverage: number;
  realized_pnl: number | null;
  fees: number;
  status: "open" | "closed";
  entry_time: string;
  exit_time: string | null;
  message: string | null;
  fill_type: string | null;
}

export interface AnalyticsResponse {
  equity_curve: PnlDataPoint[];
  monthly_returns: Record<string, number>;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  max_drawdown: number;
  sharpe_ratio: number;
  total_trades: number;
  avg_trade_duration_hours: number;
}

export interface PnlDataPoint {
  timestamp: string;
  equity: number;
  pnl: number;
}

export interface AssetConfig {
  id: number;
  coin: string;
  display_name: string;
  enabled: boolean;
  fixed_trade_amount_usd: number;
  leverage: number;
  max_leverage: number;
  max_position_pct: number;
  st_atr_period: number;
  st_multiplier: number;
  st_source: string;
  htf_timeframe: string;
  htf_st_atr_period: number;
  htf_st_multiplier: number;
  adx_period: number;
  adx_minimum: number;
  adx_rising_required: boolean;
  squeeze_block: boolean;
  sqz_bb_length: number;
  sqz_bb_mult: number;
  sqz_kc_length: number;
  sqz_kc_mult: number;
  total_trades: number;
  winning_trades: number;
  total_pnl: number;
  last_trade_at: string | null;
  last_trade_direction: string | null;
  last_trade_price: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppSettings {
  trading_mode: string;
  leverage: number;
  use_limit_orders: boolean;
  limit_order_timeout_sec: number;
  limit_order_offset_pct: number;
  use_max_size: boolean;
  default_size_pct: number;
  default_max_position_pct: number;
  default_max_drawdown_pct: number;
  default_daily_loss_limit: number;
  initial_balance: number;
  slippage_pct: number;
  maker_fee_pct: number;
  taker_fee_pct: number;
  webhook_url: string;
  telegram_enabled: boolean;
  notify_trade_open: boolean;
  notify_trade_close: boolean;
  notify_risk_breach: boolean;
  trading_paused: boolean;
}

export interface SystemStatus {
  backend: ServiceStatus;
  ngrok: ServiceStatus;
  websocket: ServiceStatus;
  telegram: ServiceStatus;
}

export interface ServiceStatus {
  name: string;
  status: "ok" | "degraded" | "down";
  message: string;
  url?: string;
}

export interface HealthCheck {
  status: string;
  trading_mode: string;
  version: string;
}

/* ── WebSocket Events ── */
export interface PnlUpdate {
  id: number;
  current_price: number;
  unrealized_pnl: number;
  pnl_pct: number;
  notional_value: number;
}

export interface WsEvent {
  type: "pnl_update" | "position_update" | "trade_fill";
  data: PnlUpdate[] | PositionEvent | TradeEvent;
}

export interface PositionEvent {
  action: "opened";
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  strategy_id: number;
}

export interface TradeEvent {
  action: "closed";
  symbol: string;
  side: string;
  pnl: number;
  exit_price: number;
  strategy_id: number;
}

/* ── Auth ── */
export interface AuthState {
  isSetup: boolean;
  isLocked: boolean;
  pinHash: string | null;
  biometricsEnabled: boolean;
  autoLockMinutes: number;
}

/* ── Tab Config ── */
export type TabKey = "chart" | "dashboard" | "trades" | "analytics" | "settings";
