export interface IncubatingStrategy {
  id: string;
  name: string;
  description?: string;
  strategy_type: string;
  portfolio_id: string;
  mock_capital: number | null;
  incubation_started_at: string | null;
  days_elapsed: number;
  window_days: number;
  progress?: number;
}

export interface IncubationPosition {
  date: string;
  symbol: string;
  quantity: number | null;
  entry_price: number | null;
}

export interface IncubationEquityPoint {
  date: string;
  equity: number | null;
}

export interface IncubationPerformance {
  positions: IncubationPosition[];
  equity_curve: IncubationEquityPoint[];
}
