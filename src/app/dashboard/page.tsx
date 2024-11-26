import { PortfolioValuation } from "@/components/portfolio-metrics/portfolio-valuation";

export default function DashboardPage() {
  // TODO: This is a dummy data
  const portfolioValue = 10000;
  const totalReturn = 0.05;

  return (
    <div className="flex min-h-screen items-center justify-center">
      <PortfolioValuation value={portfolioValue} totalReturn={totalReturn} />
    </div>
  );
}
