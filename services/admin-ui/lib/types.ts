export type View = "runs" | "processes" | "ingestion" | "traders" | "trades";
export type Run = {
  id: string;
  operation_type: string;
  job_type: string;
  source: "MANUAL" | "SCHEDULED";
  schedule_name?: string;
  schedule_window_key?: string;
  status: string;
  attempt: number;
  successful_items: number;
  skipped_items: number;
  failed_items: number;
  retryable_failures: number;
  metrics: Record<string, unknown>;
  parameters: Record<string, unknown>;
  error_message?: string;
  enqueued_at: string;
  started_at?: string;
  completed_at?: string;
};
export type Summary = {
  total_24h: number;
  succeeded_24h: number;
  failed_24h: number;
  successful_items_24h: number;
  failed_items_24h: number;
  bot_statuses: Record<string, number>;
};
export type Trader = {
  id: string;
  bot_key: string;
  display_name: string;
  status: string;
  strategy_engine: string;
  config_key: string;
  cash_balance: string;
  position_count: number;
  last_ticked_at?: string;
};
export type Profile = {
  config_key: string;
  display_name: string;
  strategy_engine: string;
  enabled: boolean;
};
export type Position = {
  instrument_id: string;
  symbol: string;
  display_name: string;
  club?: string;
  quantity: string;
  current_price: string;
  market_value: string;
  last_trade_price?: string;
  last_trade_at?: string;
  updated_at: string;
};
export type Trade = {
  id: string;
  symbol: string;
  side: string;
  shares: string;
  execution_price: string;
  gross_amount: string;
  executed_at: string;
};
export type BotDetail = Trader & {
  account_id: string;
  portfolio_id: string;
  handle: string;
  profile_name: string;
  config_version: number;
  config: Record<string, unknown>;
  config_overrides: Record<string, unknown>;
  next_tick_after?: string;
  position_value: string;
  total_equity: string;
  positions: Position[];
  recent_trades: Trade[];
  activity: {
    trades_today: number;
    turnover_today: string;
    last_trade_at?: string;
  };
};
export type LedgerTrade = {
  id: string;
  order_id: string;
  account_id: string;
  portfolio_id: string;
  instrument_id: string;
  side: string;
  shares: string;
  execution_price: string;
  gross_amount: string;
  executed_at: string;
  symbol: string;
  instrument_name: string;
  player_name?: string;
  club?: string;
  handle: string;
  account_name: string;
  account_type: string;
  actor_name: string;
  bot_id?: string;
  bot_key?: string;
  bot_name?: string;
  strategy_engine?: string;
};
export type TradeSummary = {
  total: number;
  buys: number;
  sells: number;
  user_trades: number;
  synthetic_trades: number;
  gross_amount: string;
};
export type TradePage = {
  items: LedgerTrade[];
  total: number;
  limit: number;
  offset: number;
  summary: TradeSummary;
};
export type TradeDetail = LedgerTrade & {
  created_at: string;
  request_id: string;
  order_status: string;
  submitted_at: string;
  filled_at?: string;
  rejection_reason?: string;
  email?: string;
  account_status: string;
  current_cash_balance: string;
  current_position_quantity?: string;
  instrument_type: string;
  current_price: string;
  trading_status: string;
  player_id?: string;
  player_position?: string;
  bot_status?: string;
  last_ticked_at?: string;
  next_tick_after?: string;
  config_key?: string;
  profile_name?: string;
  config_version?: number;
  old_price?: string;
  new_price?: string;
  price_change_reason?: string;
  cash_ledger_reason?: string;
  cash_amount_delta?: string;
  cash_balance_after?: string;
};
export type ProcessJob = {
  job_type: string;
  payload: Record<string, unknown>;
  attempt: number;
  operation_run_id?: string;
  started_at?: string;
};
export type RecurringProcess = {
  name: string;
  display_name: string;
  job_type: string;
  schedule: string;
  enabled: boolean;
  default_enabled: boolean;
  running: boolean;
  queued: number;
};
export type ProcessSnapshot = {
  scheduler: {
    online: boolean;
    last_seen_at?: string;
    last_scheduled: string[];
  };
  active_job?: ProcessJob;
  queued_jobs: ProcessJob[];
  processes: RecurringProcess[];
};

export type OperationCapability = {
  operation_type: string;
  job_type: string;
  label: string;
};
