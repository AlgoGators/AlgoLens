export interface Position {
  id: string;
  symbol: string;
  quantity: number;
  entryPrice: number;
  currentPrice: number;
  pnl: number;
  returnPercent: number;
}

export interface PortfolioData {
  portfolioValue: number;
  totalReturn: number;
  positions: Position[];
}
