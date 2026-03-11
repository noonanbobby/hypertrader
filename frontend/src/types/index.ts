export interface Strategy {
  id: number;
  name: string;
  description: string;
  allocated_capital: number;
  current_equity: number;
  max_position_pct: number;
  max_drawdown_pct: number;
  status: "active" | "paused";
  total_trades: number;
  winning_trades: number;
  total_pnl: number;
  peak_equity: number;
  win_rate: number;
  current_drawdown: number;
  created_at: string;
  updated_at: string;
}

export interface Trade {
  id: number;
  strategy_id: number;
  strategy_name: string;
  symbol: string;
  side: "long" | "short";
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  notional_value: number;
  margin_used: number;
  leverage: number;
  realized_pnl: number;
  fees: number;
  status: "open" | "closed";
  entry_time: string;
  exit_time: string | null;
  message: string;
}

export interface Position {
  id: number;
  strategy_id: number;
  strategy_name: string;
  symbol: string;
  side: "long" | "short";
  entry_price: number;
  quantity: number;
  current_price: number;
  unrealized_pnl: number;
  pnl_pct: number;
  notional_value: number;
  margin_used: number;
  leverage: number;
  opened_at: string;
}

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

export interface PnlDataPoint {
  timestamp: string;
  equity: number;
  drawdown: number;
}

export interface Analytics {
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

export interface WSEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface AppSettings {
  trading_mode: "paper" | "live";
  webhook_secret: string;
  leverage: number;
  initial_balance: number;
  slippage_pct: number;
  maker_fee_pct: number;
  taker_fee_pct: number;
  default_max_position_pct: number;
  default_max_drawdown_pct: number;
  default_daily_loss_limit: number;
  hl_api_key: string;
  hl_api_secret: string;
  hl_vault_address: string;
  updated_at: string;
}

export type AppSettingsUpdate = Partial<Omit<AppSettings, "updated_at">>;
