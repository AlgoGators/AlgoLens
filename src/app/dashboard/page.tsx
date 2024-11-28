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
      id: "2",
      symbol: "CL",
      quantity: 100,
      entryPrice: 3000.0,
      currentPrice: 3010.0,
      pnl: 1000.0,
      returnPercent: 0.2,
    },
    {
      id: "3",
      symbol: "NQ",
      quantity: 100,
      entryPrice: 3000.0,
      currentPrice: 3010.0,
      pnl: 1000.0,
      returnPercent: 0.2,
    },
  ];

  return (
    <div className="container mx-auto p-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="w-full">
          <PortfolioValuation
            value={portfolioValue}
            totalReturn={totalReturn}
          />
        </div>
        <div className="w-full lg:col-span-2">
          <PositionsTable positions={positions} />
        </div>
      </div>
    </div>
  );
}
