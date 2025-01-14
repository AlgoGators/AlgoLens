"use client";

import { useState, useEffect } from "react";
import Chart from "./Chart";
import Metrics from "./Metrics";

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [isFetching, setIsFetching] = useState(true);

  useEffect(() => {
    const fetchMetrics = async () => {
      setIsFetching(true);
      try {
        // Fetch metrics directly from the quantstats endpoint
        const response = await fetch("http://localhost:5000/api/quantstats", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.error || "Failed to fetch metrics.");
        }

        const data = await response.json();
        console.log("Fetched metrics:", data);
        setMetrics(data);
      } catch (error) {
        console.error(error);
        alert(error.message || "An error occurred.");
      } finally {
        setIsFetching(false);
      }
    };

    fetchMetrics();
  }, []);

  const parseChartData = (data: any, label: string, color: string) => {
    if (!data) return { labels: [], datasets: [] };

    const labels = Object.keys(data).map((timestamp) =>
      new Date(timestamp).toISOString().split("T")[0]
    );

    const values = Object.values(data);

    return {
      labels,
      datasets: [
        {
          label,
          data: values,
          borderColor: color,
          backgroundColor: `${color}33`,
          borderWidth: 2,
          tension: 0.4,
          pointRadius: 0,
        },
      ],
    };
  };

  if (isFetching) {
    return <div className="text-center text-gray-500">Fetching metrics...</div>;
  }

  if (!metrics) {
    return <div className="text-center text-gray-500">No metrics available.</div>;
  }

  return (
    <div className="container mx-auto p-4 flex flex-row space-x-6">
      {/* Charts Section */}
      <div className="w-2/3 space-y-6">
        <Chart
          data={parseChartData(metrics.stock_price, "Stock Cumulative Returns", "#1f77b4")}
          title="Stock Cumulative Returns"
        />
        <Chart
          data={parseChartData(metrics.sp500_cumulative, "S&P 500 Cumulative Returns", "#ff7f0e")}
          title="S&P 500 Cumulative Returns"
        />
        <Chart
          data={parseChartData(metrics.percentage_change_vs_sp500, "Percentage Change vs. S&P 500", "#2ca02c")}
          title="Percentage Change vs. S&P 500"
        />
        <Chart
          data={parseChartData(metrics.implied_volatility, "Implied Volatility", "#d62728")}
          title="Implied Volatility"
        />
        <Chart
          data={parseChartData(metrics.rolling_volatility, "Rolling Volatility", "#9467bd")}
          title="Rolling Volatility"
        />
        <Chart
          data={parseChartData(metrics.rolling_sharpe, "Rolling Sharpe", "#8c564b")}
          title="Rolling Sharpe"
        />
        <Chart
          data={parseChartData(metrics.rolling_sortino, "Rolling Sortino", "#e377c2")}
          title="Rolling Sortino"
        />
      </div>

      {/* Metrics Section */}
      <div className="w-1/3 bg-white shadow rounded-lg p-6">
        <Metrics metrics={metrics} />
      </div>
    </div>
  );
}
