import { createContext, useContext, useState, ReactNode } from "react";

interface StrategyConfig {
  strategy: string;
  dataRange: string;
  capital: number;
  volatility: number;
}

interface Metric {
  strategy: string;
  Portfolio_Volatility: number;
  Sharpe_Ratio: number;
  Sortino_Ratio: number;
  Value_at_Risk: number;
  Beta: number;
  Conditional_Value_at_Risk: number;
  Upside_Potential_Ratio: number;
  CAGR: number;
  Annualized_Returns: number;
  Profit_Factor: number;
  Win_Rate: number;
  Max_Drawdown: number;
}

interface Asset {
  ticker: string;
  Ideal_Positions: number;
  Realized_Capital: number;
}

interface Summary {
  Assets: Asset[];
  Realized_Capital: number;
  Ideal_Capital: number;
}

interface LastPosition {
  date: string;
  Summary: Summary;
}

interface StrategyData {
  proportion?: number;
  last_position: LastPosition;
}

interface StrategyContextType {
  configurations: StrategyConfig[];
  metrics: Metric[];
  positions: {
    strategies: Record<string, StrategyData>;
    portfolio: { positions: Record<string, number> };
  } | null;
  setConfigurations: (configs: StrategyConfig[]) => void;
  setMetrics: (metrics: Metric[]) => void;
  setPositions: (positions: StrategyContextType["positions"]) => void;
}


const StrategyContext = createContext<StrategyContextType | undefined>(undefined);

export const StrategyProvider = ({ children }: { children: ReactNode }) => {
  const [configurations, setConfigurations] = useState<StrategyConfig[]>([]);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [positions, setPositions] = useState<StrategyContextType["positions"]>(null);

  return (
    <StrategyContext.Provider
      value={{ configurations, metrics, positions, setConfigurations, setMetrics, setPositions }}
    >
      {children}
    </StrategyContext.Provider>
  );
};

export const useStrategyContext = () => {
  const context = useContext(StrategyContext);
  if (!context) {
    throw new Error("useStrategyContext must be used within a StrategyProvider");
  }
  return context;
};
