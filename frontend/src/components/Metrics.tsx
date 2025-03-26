"use client";

export default function Metrics({ metrics }: { metrics: any }) {
  const categorizeMetrics = (metrics: any) => {
    const riskMetrics = [
      "max_drawdown",
      "value_at_risk",
      "tail_ratio",
      "ulcer_index",
      "cvar",
      "conditional_value_at_risk",
    ];
    const performanceMetrics = [
      "sharpe",
      "sortino",
      "volatility",
      "cagr",
      "calmar",
      "avg_return",
      "avg_loss",
      "avg_win",
      "omega",
    ];
    const greeksMetrics = ["beta", "alpha", "delta", "gamma", "theta"];

    const risk = {};
    const performance = {};
    const greeks = {};
    const unclassified = {};

    const redundantMetrics = [
      "extended_metrics_error",
      "outliers",
      "rolling_sharpe",
      "rolling_sortino",
      "rolling_volatility",
      "implied_volatility",
      "Index_cumulative",
      "distribution",
      "percentage_change_vs_Index",
      "stock_price",
      "greeks", // for now
    ];

    for (const key in metrics) {
      if (riskMetrics.includes(key)) {
        risk[key] = metrics[key];
      } else if (performanceMetrics.includes(key)) {
        performance[key] = metrics[key];
      } else if (greeksMetrics.includes(key)) {
        greeks[key] = metrics[key];
      } else {
        if (!redundantMetrics.includes(key)) {
          unclassified[key] = metrics[key];
        }
      }
    }

    return { risk, performance, greeks, unclassified };
  };

  const { risk, performance, greeks, unclassified } = categorizeMetrics(metrics);

  const renderMetric = (key: string, value: any) => {
    const formattedKey = key
      .replace(/_/g, " ") // Replace underscores with spaces
      .replace(/\b(?:[A-Z]+)\b/g, (match) => match.toUpperCase()) // Fully capitalize acronyms
      .replace(/\b\w/g, (char) => char.toUpperCase()) // Capitalize the first letter of each word
      .replace(/^([a-z])/i, (char) => char.toUpperCase()); // Ensure the first letter is always capitalized.

    if (typeof value === "number") {
      return `${formattedKey}: ${value.toFixed(3)}`;
    }

    return `${formattedKey}: ${value ?? "N/A"}`; // Fallback to "N/A" if value is null or undefined
  };

  const renderSection = (title: string, data: any) => (
    <div>
      <h2 className="text-xl font-bold mb-4">{title}</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
        {Object.entries(data).map(([key, value]) => (
          <div key={key} className="bg-white shadow rounded-lg p-4">
            {renderMetric(key, value)}
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      {Object.keys(risk).length > 0 && renderSection("Risk Metrics", risk)}
      {Object.keys(performance).length > 0 && renderSection("Performance Metrics", performance)}
      {Object.keys(greeks).length > 0 && renderSection("Greeks", greeks)}
      {Object.keys(unclassified).length > 0 && renderSection("Other Metrics", unclassified)}
    </div>
  );
}
