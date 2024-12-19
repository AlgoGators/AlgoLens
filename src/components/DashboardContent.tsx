"use client";

import { useState } from "react";
import { useStrategyContext } from "@/components/StrategyContext";
import PositionsSummary from "@/components/PositionsSummary";
import StrategyManager from "@/components/StrategyManager";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export default function DashboardPage() {
  const { metrics, positions, setPositions } = useStrategyContext();
  const [isStrategySubmitted, setIsStrategySubmitted] = useState(false);

  const handleStrategySubmission = async () => {
    setIsStrategySubmitted(true);

    // Fetch positions and metrics (assuming an API call function exists)
    const response = await fetch("/api/submit-strategies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ /* strategy payload */ }),
    });
    const data = await response.json();
    setPositions(data.positions); // Save positions
  };

  return (
    <div className="container mx-auto p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card className="w-full">
        <CardHeader>
          <h2 className="text-xl font-bold mb-4">Strategy Manager</h2>
        </CardHeader>
        <CardContent>
          <StrategyManager onSubmit={handleStrategySubmission} />
        </CardContent>
      </Card>

      <Card className="w-full">
        <CardHeader>
          <h2 className="text-xl font-bold mb-4">Metrics</h2>
        </CardHeader>
        <CardContent>
          {isStrategySubmitted && metrics.length > 0 ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {metrics.map((metric, index) => {
                // Categorize metrics
                const performanceMetrics = {
                  CAGR: "Compounded Annual Growth Rate",
                  Annualized_Returns: "Annualized Returns",
                  Sharpe_Ratio: "Sharpe Ratio",
                  Sortino_Ratio: "Sortino Ratio",
                  Profit_Factor: "Profit Factor",
                  Win_Rate: "Win Rate",
                  Max_Drawdown: "Max Drawdown",
                };

                const riskMetrics = {
                  Portfolio_Volatility: "Portfolio Volatility",
                  Beta: "Beta",
                  Value_at_Risk: "Value at Risk",
                  Conditional_Value_at_Risk: "Tail Risk (CVaR)",
                  Leverage: "Leverage",
                };

                const categorizedPerformanceMetrics = Object.entries(metric)
                  .filter(([key]) => key in performanceMetrics)
                  .map(([key, value]) => ({
                    label: performanceMetrics[key],
                    value,
                  }));

                const categorizedRiskMetrics = Object.entries(metric)
                  .filter(([key]) => key in riskMetrics)
                  .map(([key, value]) => ({
                    label: riskMetrics[key],
                    value,
                  }));

                return (
                  <Card key={index} className="w-full">
                    <CardHeader>
                      <h2 className="text-lg font-bold">{metric.strategy} Metrics</h2>
                    </CardHeader>
                    <CardContent>
                      {/* Performance Metrics */}
                      <h3 className="text-md font-semibold mb-2">Performance Metrics</h3>
                      <ul className="mb-4">
                        {categorizedPerformanceMetrics.map(({ label, value }, idx) => (
                          <li key={idx}>
                            <strong>{label}:</strong> {value.toFixed(2)}
                          </li>
                        ))}
                      </ul>

                      {/* Risk Metrics */}
                      <h3 className="text-md font-semibold mb-2">Risk Metrics</h3>
                      <ul>
                        {categorizedRiskMetrics.map(({ label, value }, idx) => (
                          <li key={idx}>
                            <strong>{label}:</strong> {value.toFixed(2)}
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          ) : (
            <div>No metrics available yet. Please run a strategy.</div>
          )}
        </CardContent>
      </Card>;


      <Card className="w-full col-span-2">
        <CardHeader>
          <h2 className="text-xl font-bold mb-4">Final Positions</h2>
        </CardHeader>
        <CardContent>
          {isStrategySubmitted && positions ? (
            <PositionsSummary positions={positions} />
          ) : (
            <div>No positions available yet. Please run a strategy.</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
