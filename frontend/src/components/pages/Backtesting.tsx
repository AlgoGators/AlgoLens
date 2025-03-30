"use client";

import { useState, useEffect, useCallback } from "react";
import Chart from "../Chart";
import Metrics from "../Metrics";
import SettingsDropdown from "../SettingsDropdown";
import { Button } from "@/components/ui/button";
import { Menubar, MenubarMenu, MenubarTrigger } from "@/components/ui/menubar";
import Link from "next/link";
import Image from "next/image";

// Keys for localStorage persistence.
const LS_PREFERENCES = "backtesting_preferences";
const LS_DATE_RANGE = "backtesting_dateRange";

export default function Backtesting() {
  const defaultPreferences = {
    portfolio: true,
    stock_price: true,
    Index_cumulative: true,
    percentage_change_vs_Index: true,
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
  // dateRange, minDate and maxDate are stored as millisecond timestamps.
  const [dateRange, setDateRange] = useState<number[]>([0, 0]);
  const [minDate, setMinDate] = useState<number>(0);
  const [maxDate, setMaxDate] = useState<number>(0);
  // Add a key to force chart re-renders
  const [chartKey, setChartKey] = useState(0);
  
  const [_availableCustomMetrics, setAvailableCustomMetrics] = useState<Array<{
    filename: string;
    name: string;
    description: string;
    created_at: string;
  }>>([]);
  const [selectedCustomMetrics, setSelectedCustomMetrics] = useState<string[]>([]);

  // Add this to your component
  useEffect(() => {
    async function fetchCustomMetrics() {
      try {
        const response = await fetch("http://127.0.0.1:5000/api/custom-metrics");
        if (response.ok) {
          const metrics = await response.json();
          setAvailableCustomMetrics(metrics);
        }
      } catch (error) {
        console.error("Failed to fetch custom metrics", error);
      }
    }
    
    fetchCustomMetrics();
  }, []);



  // On mount, load stored preferences and dateRange from localStorage.
  useEffect(() => {
    const storedPrefs = localStorage.getItem(LS_PREFERENCES);
    const storedRange = localStorage.getItem(LS_DATE_RANGE);
    if (storedPrefs) {
      try {
        setPreferences(JSON.parse(storedPrefs));
      } catch (e) {
        console.error("Error parsing stored preferences", e);
      }
    }
    if (storedRange) {
      try {
        setDateRange(JSON.parse(storedRange));
      } catch (e) {
        console.error("Error parsing stored date range", e);
      }
    }
  }, []);

  // Fetch metrics from the backend.
  const fetchMetrics = useCallback(async (
    prefs = preferences,
    category = selectedCategory,
    range = dateRange
  ) => {
    setIsFetching(true);
    try {
      console.log("Fetching with date range:", range);
      console.log("Selected custom metrics:", selectedCustomMetrics);
      
      const response = await fetch("http://127.0.0.1:5000/api/quantstats", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          preferences: prefs, 
          category: category, 
          dateRange: range,
          customMetrics: selectedCustomMetrics
        }),
      });
  
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || "Failed to fetch metrics.");
      }
  
      const data = await response.json();
      console.log("Fetched metrics:", data);
      setMetrics(data);
      // Increment chart key to force re-render
      setChartKey(prev => prev + 1);
    } catch (error: any) {
      console.error(error);
      alert(error.message || "An error occurred.");
    } finally {
      setIsFetching(false);
    }
  }, [preferences, selectedCategory, dateRange, selectedCustomMetrics]); // Add selectedCustomMetrics to dependency array
  
  
  // Do an initial fetch on mount.
  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  // Compute the global date range from all available metric data.
  // We run this once when metrics are loaded (or updated) to set the slider's min and max.
  useEffect(() => {
    if (metrics) {
      const timestamps: number[] = [];
      // Iterate over every metric property (assumed to be objects with date keys)
      Object.values(metrics).forEach((value) => {
        if (value && typeof value === "object") {
          Object.keys(value).forEach((key) => {
            const t = new Date(key).getTime();
            if (!isNaN(t) && t > 0) {
              timestamps.push(t);
            }
          });
        }
      });
      
      if (timestamps.length > 0) {
        const computedMin = Math.min(...timestamps);
        const computedMax = Math.max(...timestamps);
        console.log(
          "Computed global date range:",
          new Date(computedMin).toISOString(),
          new Date(computedMax).toISOString()
        );
        setMinDate(computedMin);
        setMaxDate(computedMax);
        // If dateRange is still [0,0], initialize it.
        if (dateRange[0] === 0 && dateRange[1] === 0) {
          setDateRange([computedMin, computedMax]);
        }
      } else {
        console.warn("No valid date keys found in metrics. Defaulting to current date.");
        const now = new Date().getTime();
        setMinDate(now);
        setMaxDate(now);
        setDateRange([now, now]);
      }
    }
  }, [metrics]);

  // Handle submit: store settings in localStorage and fetch metrics with the new filter.
  const handleSubmitPreferences = async () => {
    localStorage.setItem(LS_PREFERENCES, JSON.stringify(preferences));
    localStorage.setItem(LS_DATE_RANGE, JSON.stringify(dateRange));
    await fetchMetrics(preferences, selectedCategory, dateRange);
  };

  const handleCategoryChange = async (newCategory: string) => {
    setSelectedCategory(newCategory);
    await fetchMetrics(preferences, newCategory, dateRange);
  };


  // Helper: parse chart data.
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
          tension: 0,
          pointRadius: 0,
        },
      ],
    };
  };

  const updatePreference = (name: string, checked: boolean) => {
    setPreferences((prev) => ({ ...prev, [name]: checked }));
  };

  if (!metrics) {
    return <div className="text-center text-gray-500">No metrics available.</div>;
  }
  console.log("these are the metrics");
  console.log(metrics.charts);

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

      {isFetching && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white p-6 rounded-lg shadow-lg">
            <p className="text-lg font-semibold">Loading data...</p>
            <p className="text-sm text-gray-500">This may take a moment</p>
          </div>
        </div>
      )}

      <SettingsDropdown
        preferences={preferences}
        updatePreference={updatePreference}
        handleSubmitPreferences={handleSubmitPreferences}
        minDate={minDate}
        maxDate={maxDate}
        dateRange={dateRange}
        setDateRange={setDateRange}
        selectedCustomMetrics={selectedCustomMetrics}
        setSelectedCustomMetrics={setSelectedCustomMetrics}
      />

      <div className="flex justify-center space-x-4 pt-4">
        <Button
          type="button" // Explicitly set type to button
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
          type="button" // Explicitly set type to button
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
          type="button" // Explicitly set type to button
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
          type="button" // Explicitly set type to button
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
        <div className="grid grid-cols-2 gap-6">
          {preferences.portfolio && metrics?.portfolio && (
            <Chart
              data={parseChartData(metrics.portfolio, "Portfolio", "#ff5c00")}
              title="Portfolio"
              key={`portfolio-${chartKey}`}
            />
          )}
          {preferences.stock_price && metrics?.stock_price && (
            <Chart
              data={parseChartData(metrics.stock_price, "Stock Cumulative Returns", "#ff5c00")}
              title="Stock Cumulative Returns"
              key={`stock-${chartKey}`}
            />
          )}
          {preferences.Index_cumulative && metrics?.Index_cumulative && (
            <Chart
              data={parseChartData(metrics.Index_cumulative, "Index Cumulative Returns", "#ff5c00")}
              title="Index Cumulative Returns"
              key={`index-${chartKey}`}
            />
          )}
          {preferences.percentage_change_vs_Index && metrics?.percentage_change_vs_Index && (
            <Chart
              data={parseChartData(metrics.percentage_change_vs_Index, "Percentage Change vs. Index", "#ff5c00")}
              title="Percentage Change vs. Index"
              key={`pct-${chartKey}`}
            />
          )}
          {preferences.implied_volatility && metrics?.implied_volatility && (
            <Chart
              data={parseChartData(metrics.implied_volatility, "Implied Volatility", "#ff5c00")}
              title="Implied Volatility"
              key={`iv-${chartKey}`}
            />
          )}
          {preferences.rolling_volatility && metrics?.rolling_volatility && (
            <Chart
              data={parseChartData(metrics.rolling_volatility, "Rolling Volatility", "#ff5c00")}
              title="Rolling Volatility"
              key={`rv-${chartKey}`}
            />
          )}
          {preferences.rolling_sharpe && metrics?.rolling_sharpe && (
            <Chart
              data={parseChartData(metrics.rolling_sharpe, "Rolling Sharpe", "#ff5c00")}
              title="Rolling Sharpe"
              key={`rs-${chartKey}`}
            />
          )}
          {preferences.rolling_sortino && metrics?.rolling_sortino && (
            <Chart
              data={parseChartData(metrics.rolling_sortino, "Rolling Sortino", "#ff5c00")}
              title="Rolling Sortino"
              key={`rsortino-${chartKey}`}
            />
          )}
        </div>

        {/* Custom Charts Section */}
        {metrics?.charts && Object.keys(metrics.charts).length > 0 && (
        <div className="mt-6">
          <h2 className="text-xl font-bold mb-4">Custom Metrics</h2>
          <div className="grid grid-cols-2 gap-6">
            {Object.entries(metrics.charts).map(([chartName, chartData]) => {
              // Skip rendering charts with error objects
              if (chartData && typeof chartData === 'object' && 'error' in chartData) {
                return (
                  <div key={`error-${chartName}-${chartKey}`} className="bg-red-50 p-4 rounded-md">
                    <h3 className="text-lg font-semibold text-red-700">{chartName} - Error</h3>
                    <p className="text-red-600">{chartData.error}</p>
                  </div>
                );
              }
              
              return (
                <Chart
                  key={`custom-${chartName}-${chartKey}`}
                  data={chartData}
                  title={chartName}
                />
              );
            })}
          </div>
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
