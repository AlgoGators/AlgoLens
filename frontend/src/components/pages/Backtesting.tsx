"use client";

import { useState, useEffect } from "react";
import Chart from "../Chart";
import Metrics from "../Metrics";
import SettingsDropdown from "../SettingsDropdown";
import { Button } from "@/components/ui/button";
import { Menubar, MenubarMenu, MenubarTrigger } from "@/components/ui/menubar";
import Link from "next/link";
import Image from "next/image";

export default function Backtesting() {
  const defaultPreferences = {
    stock_price: true,
    SPY_cumulative: true,
    percentage_change_vs_SPY: true,
    implied_volatility: true,
    rolling_volatility: true,
    rolling_sharpe: true,
    rolling_sortino: true,
    metrics: true,
  };

  const [selectedCategory, setSelectedCategory] = useState("portfolio");
  const [metrics, setMetrics] = useState<any>(null);
  const [isFetching, setIsFetching] = useState(true);
  const [preferences, setPreferences] = useState(defaultPreferences);
  const [dateRange, setDateRange] = useState<number[]>([0, 0]);
  const [minDate, setMinDate] = useState<number>(0);
  const [maxDate, setMaxDate] = useState<number>(0);

  const fetchMetrics = async (
    prefs = preferences,
    category = selectedCategory
  ) => {
    setIsFetching(true);
    try {
      const response = await fetch("http://localhost:5000/api/quantstats", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preferences: prefs, category: category }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || "Failed to fetch metrics.");
      }

      const data = await response.json();
      console.log("Fetched metrics:", data);
      setMetrics(data);
    } catch (error: any) {
      console.error(error);
      alert(error.message || "An error occurred.");
    } finally {
      setIsFetching(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
  }, []);

  // Compute the date range for portfolio category,
  // filtering out any keys that are not valid date strings.
  useEffect(() => {
    if (metrics && selectedCategory === "portfolio") {
      const keys = Object.keys(metrics);
      console.log("Keys in metrics:", keys);
      
      let timestamps: number[] = [];
      if (keys.length > 0) {
        // Check if keys are numeric (e.g., "1672531200000") 
        if (keys.every((key) => !isNaN(Number(key)))) {
          timestamps = keys.map((key) => Number(key));
        } else {
          timestamps = keys
            .map((key) => new Date(key).getTime())
            .filter((t) => !isNaN(t));
        }
      }
      
      if (timestamps.length > 0) {
        const computedMin = Math.min(...timestamps);
        const computedMax = Math.max(...timestamps);
        setMinDate(computedMin);
        setMaxDate(computedMax);
        setDateRange([computedMin, computedMax]);
      } else {
        console.warn("No valid date keys found in metrics for portfolio category.");
      }
    }
  }, [metrics, selectedCategory]);
  

  // Filter invalid timestamps in the chart data.
  const parseChartData = (data: any, label: string, color: string) => {
    if (!data) return { labels: [], datasets: [] };

    const validTimestamps = Object.keys(data).filter(
      (timestamp) => !isNaN(new Date(timestamp).getTime())
    );
    const labels = validTimestamps.map((timestamp) =>
      new Date(timestamp).toISOString().split("T")[0]
    );
    const values = validTimestamps.map((timestamp) => data[timestamp]);

    return {
      labels,
      datasets: [
        {
          label,
          data: values,
          borderColor: color,
          backgroundColor: color,
          borderWidth: 2,
          tension: 0.4,
          pointRadius: 0,
        },
      ],
    };
  };

  const updatePreference = (name: string, checked: boolean) => {
    setPreferences((prev) => ({ ...prev, [name]: checked }));
  };

  const handleSubmitPreferences = async () => {
    await fetchMetrics(preferences, selectedCategory);
  };

  const handleCategoryChange = async (newCategory: string) => {
    setSelectedCategory(newCategory);
    await fetchMetrics(preferences, newCategory);
  };

  if (isFetching) {
    return <div className="text-center text-gray-500">Fetching metrics...</div>;
  }

  if (!metrics) {
    return <div className="text-center text-gray-500">No metrics available.</div>;
  }

  return (
    <div className="relative">
      <Menubar className="h-20 px-4 bg-background shadow-sm">
        <MenubarMenu className="flex items-center space-x-4">
          <MenubarTrigger asChild>
            <Link href="/">
              <Image
                src="/images/AlgoLogo.png"
                alt="AlgoLogo"
                width={60}
                height={60}
                loading="eager"
              />
            </Link>
          </MenubarTrigger>
          <span className="text-3xl font-bold">Backtesting</span>
        </MenubarMenu>
      </Menubar>

      <SettingsDropdown
        preferences={preferences}
        updatePreference={updatePreference}
        handleSubmitPreferences={handleSubmitPreferences}
        minDate={minDate}
        maxDate={maxDate}
        dateRange={dateRange}
        setDateRange={setDateRange}
      />

      <div className="flex justify-center space-x-4 pt-4">
        <Button
          onClick={() => handleCategoryChange("portfolio")}
          className={`px-8 py-4 text-2xl font-bold ${
            selectedCategory === "portfolio"
              ? "bg-blue-600 text-white"
              : "bg-gray-200"
          }`}
        >
          Portfolio
        </Button>
        <Button
          onClick={() => handleCategoryChange("futures")}
          className={`px-8 py-4 text-2xl font-bold ${
            selectedCategory === "futures"
              ? "bg-blue-600 text-white"
              : "bg-gray-200"
          }`}
        >
          Futures
        </Button>
        <Button
          onClick={() => handleCategoryChange("stocks")}
          className={`px-8 py-4 text-2xl font-bold ${
            selectedCategory === "stocks"
              ? "bg-blue-600 text-white"
              : "bg-gray-200"
          }`}
        >
          Stocks
        </Button>
        <Button
          onClick={() => handleCategoryChange("options")}
          className={`px-8 py-4 text-2xl font-bold ${
            selectedCategory === "options"
              ? "bg-blue-600 text-white"
              : "bg-gray-200"
          }`}
        >
          Options
        </Button>
      </div>

      <div className="pt-16">
        {selectedCategory === "portfolio" ? (
          <Chart
            data={parseChartData(metrics, "Portfolio", "#ff5c00")}
            title="Portfolio"
          />
        ) : (
          <div className="grid grid-cols-2 gap-6">
            {preferences.stock_price && metrics.stock_price && (
              <Chart
                data={parseChartData(
                  metrics.stock_price,
                  "Stock Cumulative Returns",
                  "#ff5c00"
                )}
                title="Stock Cumulative Returns"
              />
            )}
            {preferences.SPY_cumulative && metrics.SPY_cumulative && (
              <Chart
                data={parseChartData(
                  metrics.SPY_cumulative,
                  "S&P 500 Cumulative Returns",
                  "#ff5c00"
                )}
                title="S&P 500 Cumulative Returns"
              />
            )}
            {preferences.percentage_change_vs_SPY &&
              metrics.percentage_change_vs_SPY && (
                <Chart
                  data={parseChartData(
                    metrics.percentage_change_vs_SPY,
                    "Percentage Change vs. S&P 500",
                    "#ff5c00"
                  )}
                  title="Percentage Change vs. S&P 500"
                />
              )}
            {preferences.implied_volatility && metrics.implied_volatility && (
              <Chart
                data={parseChartData(
                  metrics.implied_volatility,
                  "Implied Volatility",
                  "#ff5c00"
                )}
                title="Implied Volatility"
              />
            )}
            {preferences.rolling_volatility && metrics.rolling_volatility && (
              <Chart
                data={parseChartData(
                  metrics.rolling_volatility,
                  "Rolling Volatility",
                  "#ff5c00"
                )}
                title="Rolling Volatility"
              />
            )}
            {preferences.rolling_sharpe && metrics.rolling_sharpe && (
              <Chart
                data={parseChartData(
                  metrics.rolling_sharpe,
                  "Rolling Sharpe",
                  "#ff5c00"
                )}
                title="Rolling Sharpe"
              />
            )}
            {preferences.rolling_sortino && metrics.rolling_sortino && (
              <Chart
                data={parseChartData(
                  metrics.rolling_sortino,
                  "Rolling Sortino",
                  "#ff5c00"
                )}
                title="Rolling Sortino"
              />
            )}
          </div>
        )}

        {preferences.metrics && (
          <div className="mt-6 bg-white shadow rounded-lg p-6">
            <Metrics metrics={metrics} />
          </div>
        )}
      </div>
    </div>
  );
}
