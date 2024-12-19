"use client";

import { useState, useEffect } from "react";
import { useStrategyContext } from "@/components/StrategyContext";

interface StrategyConfig {
  strategy: string;
  dataRange: string;
  capital: number;
  volatility: number;
}

export default function StrategyManager({ onSubmit }: { onSubmit: () => void }) {
  const { setConfigurations, setMetrics, setPositions } = useStrategyContext();
  const [strategies, setStrategies] = useState<string[]>([]); // List of available strategies
  const [configurations, setConfigurationsState] = useState<StrategyConfig[]>([]); // Local state for user-added strategies

  // Fetch available strategies from the server
  useEffect(() => {
    const fetchStrategies = async () => {
      try {
        const res = await fetch("http://127.0.0.1:5000/api/strategies");
        const data = await res.json();
        setStrategies(data);
      } catch (error) {
        console.error("Error fetching strategies:", error);
      }
    };
    fetchStrategies();
  }, []);

  // Add a new strategy configuration
  const addStrategy = () => {
    setConfigurationsState((prev) => [
      ...prev,
      { strategy: strategies[0] || "Mean Reversion", dataRange: "", capital: 0, volatility: 0 },
    ]);
  };

  // Update a specific configuration field
  const handleConfigChange = (index: number, field: keyof StrategyConfig, value: string | number) => {
    setConfigurationsState((prev) => {
      const updatedConfigurations = [...prev];
      updatedConfigurations[index] = { ...updatedConfigurations[index], [field]: value };
      return updatedConfigurations;
    });
  };

  // Remove a strategy configuration
  const removeStrategy = (index: number) => {
    setConfigurationsState((prev) => prev.filter((_, i) => i !== index));
  };

  // Submit configurations to backend and update context
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const response = await fetch("http://127.0.0.1:5000/api/submit-strategies", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(configurations),
      });
      console.log(response.ok);
      if (response.ok) {
        const data = await response.json();
        setConfigurations(configurations); // Update context with configurations
        setMetrics(data.metrics); // Update context with metrics
        setPositions(data.positions); // Update context with positions
        onSubmit(); // Notify parent that submission is complete
      } else {
        console.error("Error submitting configurations:", response.statusText);
      }
    } catch (error) {
      console.error("Error submitting configurations:", error);
    }
  };  

  return (
    <div className="container mx-auto p-4">
      <button
        onClick={addStrategy}
        className="bg-blue-500 text-white py-2 px-4 rounded-md shadow hover:bg-blue-600 mb-4"
      >
        Add Strategy
      </button>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {configurations.map((config, index) => (
          <div key={index} className="border p-4 rounded-md shadow relative">
            {/* Remove Button */}
            <button
              type="button"
              onClick={() => removeStrategy(index)}
              className="absolute top-2 right-2 bg-red-500 text-white py-1 px-2 rounded-md shadow hover:bg-red-600"
            >
              Remove
            </button>

            <div>
              <label className="block text-sm font-medium text-gray-700">Select Strategy:</label>
              <select
                value={config.strategy}
                onChange={(e) => handleConfigChange(index, "strategy", e.target.value)}
                className="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
              >
                {strategies.map((strategy) => (
                  <option key={strategy} value={strategy}>
                    {strategy}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Data Range:</label>
              <input
                type="text"
                value={config.dataRange}
                onChange={(e) => handleConfigChange(index, "dataRange", e.target.value)}
                placeholder="e.g., 2020-01-01 to 2023-01-01"
                className="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Capital:</label>
              <input
                type="number"
                value={config.capital}
                onChange={(e) => handleConfigChange(index, "capital", parseFloat(e.target.value))}
                placeholder="e.g., 100000"
                className="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Target Volatility:</label>
              <input
                type="number"
                value={config.volatility}
                onChange={(e) => handleConfigChange(index, "volatility", parseFloat(e.target.value))}
                placeholder="e.g., 0.2"
                step="0.01"
                className="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
          </div>
        ))}
        <button
          type="submit"
          className="w-full bg-green-500 text-white py-2 rounded-md shadow hover:bg-green-600 focus:outline-none focus:ring-2 focus:ring-green-500"
        >
          Submit
        </button>
      </form>
    </div>
  );
}
