"use client";

import { useState, useEffect } from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  Legend,
  Title,
} from "chart.js";

ChartJS.register(CategoryScale, LinearScale, LineElement, PointElement, Tooltip, Legend, Title);

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [isFetching, setIsFetching] = useState(true);

  // Fetch metrics from the backend
  useEffect(() => {
    const fetchMetrics = async () => {
      setIsFetching(true);
      try {
        const response = await fetch("http://localhost:5000/api/quantstats", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });

        if (response.ok) {
          const data = await response.json();
          console.log("Fetched metrics:", data);
          setMetrics(data);
        } else {
          const error = await response.json();
          console.error("Backend error response:", error);
          alert(error.error || "Failed to fetch metrics.");
        }
      } catch (error) {
        console.error("Network or parsing error:", error);
        alert("An error occurred while fetching metrics.");
      } finally {
        setIsFetching(false);
      }
    };

    fetchMetrics();
  }, []);

  // Helper function to format titles
  const formatTitle = (title: string): string => {
    return title
      .replace(/_/g, " ") // Replace underscores with spaces
      .replace(/\b\w/g, (char) => char.toUpperCase()); // Capitalize the first letter of each word
  };

  // Helper function to parse chart data for implied volatility
  const parseImpliedVolatilityData = (data: any) => {
    if (!data) return { labels: [], datasets: [] }; // Fallback for undefined data

    const labels = Object.keys(data);
    const values = Object.values(data);

    return {
      labels,
      datasets: [
        {
          label: "Implied Volatility",
          data: values,
          borderColor: "#4C78A8", // Seaborn-like blue
          backgroundColor: "rgba(76, 120, 168, 0.1)", // Light blue for fill
          borderWidth: 2,
          tension: 0, // Smooth line
          pointRadius: 0, // Small points for simplicity
          pointBackgroundColor: "#4C78A8",
        },
      ],
    };
  };

  const parseComparisonData = (data: any) => {
    if (!data) return { labels: [], datasets: [] };
  
    const labels = Object.keys(data).map((key) => key); // Dates
    const ticker1Data = Object.values(data).map((entry: any) => entry.META); // Replace "META" dynamically
    const ticker2Data = Object.values(data).map((entry: any) => entry.AAPL); // Replace "AAPL" dynamically
  
    return {
      labels,
      datasets: [
        {
          label: "META Returns",
          data: ticker1Data,
          borderColor: "#4C78A8",
          backgroundColor: "rgba(76, 120, 168, 0.1)",
          borderWidth: 2,
          tension: 0.4,
        },
        {
          label: "AAPL Returns",
          data: ticker2Data,
          borderColor: "#F58518",
          backgroundColor: "rgba(245, 133, 24, 0.1)",
          borderWidth: 2,
          tension: 0.4,
        },
      ],
    };
  };

  if (isFetching) {
    return <div className="text-center text-gray-500">Loading metrics...</div>;
  }

  if (!metrics) {
    return <div className="text-center text-gray-500">No metrics available.</div>;
  }

  return (
    <div className="container mx-auto p-4">
      {/* Page Title */}
      <h1 className="text-3xl font-bold text-center mb-8">Strategy Dashboard</h1>

      {/* Implied Volatility Section */}
      <div className="bg-white shadow rounded-lg p-6 mb-8">
        <h2 className="text-xl font-bold mb-4">Implied Volatility</h2>
        <Line
          data={parseImpliedVolatilityData(metrics.implied_volatility)}
          options={{
            responsive: true,
            plugins: {
              legend: {
                display: true,
                position: "top",
              },
              title: {
                display: true,
                text: "Implied Volatility Over Time",
                color: "#333333",
                font: {
                  size: 16,
                  weight: "bold",
                },
              },
            },
            scales: {
              x: {
                title: {
                  display: true,
                  text: "Date",
                  color: "#333333",
                  font: {
                    size: 14,
                    weight: "bold",
                  },
                },
              },
              y: {
                title: {
                  display: true,
                  text: "Implied Volatility (%)",
                  color: "#333333",
                  font: {
                    size: 14,
                    weight: "bold",
                  },
                },
              },
            },
          }}
        />
      </div>

      {/* Key Performance Metrics Section */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-xl font-bold mb-4">Key Performance Metrics</h2>
        <ul>
          {Object.entries(metrics)
            .filter(([key, value]) => typeof value === "number")
            .map(([key, value]) => (
              <li key={key} className="mb-2">
                <strong>{formatTitle(key)}:</strong> {value.toFixed(2)}
              </li>
            ))}
        </ul>
      </div>
    </div>
  );
}

