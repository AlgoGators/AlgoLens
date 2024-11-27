import { PortfolioValuation } from "@/components/portfolio-metrics/portfolio-valuation";
import { PositionsTable } from "@/components/portfolio-metrics/position-table";

export default function DashboardPage() {
  // TODO: This is a dummy data
  const portfolioValue = 10000;
  const totalReturn = 0.05;

  const positions = [
    {
      id: "1",
      symbol: "ES",
      quantity: 100,
      entryPrice: 3000.0,
      currentPrice: 3010.0,
      pnl: 1000.0,
      returnPercent: 0.2,
    },
    {
      id: "1",
      symbol: "ES",
      quantity: 100,
      entryPrice: 3000.0,
      currentPrice: 3010.0,
      pnl: 1000.0,
      returnPercent: 0.2,
    },
    {
      id: "1",
      symbol: "ES",
      quantity: 100,
      entryPrice: 3000.0,
      currentPrice: 3010.0,
      pnl: 1000.0,
      returnPercent: 0.2,
    },
  ];

  return (
    <div className="flex min-h-screen items-start justify-center space-y-6">
      <PortfolioValuation value={portfolioValue} totalReturn={totalReturn} />
      <PositionsTable positions={positions} />
    </div>
  );
}
