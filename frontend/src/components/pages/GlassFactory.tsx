"use client";

import { useState, useEffect } from "react";
import { Menubar, MenubarMenu, MenubarTrigger } from "@/components/ui/menubar";
import Link from "next/link";
import Image from "next/image";
import CodeEditor from "@/components/glassfactory/CodeEditor";
import ChartDisplay from "@/components/glassfactory/ChartDisplay";
import DebugPanel from "@/components/glassfactory/DebugPanel";
import SavedChartsList from "@/components/glassfactory/SavedChartsList";
import ServerMetricsList from "@/components/glassfactory/ServerMetricsList";

// Example code template
const EXAMPLE_CODE = `# Available modules and functions:
# - pd (pandas)
# - np (numpy)
# - system() - returns strategy groups data
# - quant_stats(strategy_name, strategy_data, benchmark_name, benchmark_data)

import pandas as pd
import numpy as np

# Get data from system
strategy_groups = system()
portfolio_data = strategy_groups.get("portfolio")

# Process the data
processed_data = pd.to_numeric(portfolio_data, errors='coerce')
processed_data = processed_data.dropna().pct_change().dropna()

# Create chart data structure for Chart.js
dates = processed_data.index.strftime('%Y-%m-%d').tolist()
values = processed_data.values.tolist()

# Define the chart_data object that will be displayed
chart_data = {
    "labels": dates,
    "datasets": [
        {
            "label": "My Custom Portfolio Metric",
            "data": values,
            "borderColor": "#ff5c00",
            "backgroundColor": "#ff5c00",
            "borderWidth": 2,
            "tension": 0,
            "pointRadius": 0,
        }
    ]
}

print(f"Created chart with {len(dates)} data points")
print(f"Date range: {dates[0]} to {dates[-1]}")
`;

export default function GlassFactory() {
  const [pythonCode, setPythonCode] = useState(EXAMPLE_CODE);
  const [response, setResponse] = useState("");
  const [debugOutput, setDebugOutput] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [chartData, setChartData] = useState(null);
  const [chartTitle, setChartTitle] = useState("Custom Chart");
  const [savedCharts, setSavedCharts] = useState([]);
  const [errorMessage, setErrorMessage] = useState("");
  const [codeErrors, setCodeErrors] = useState([]);
  const [description, setDescription] = useState("");
  const [serverMetrics, setServerMetrics] = useState([]);
  const [isLoading, setIsLoading] = useState(false);

  // Load saved charts on component mount and fetch server metrics
  useEffect(() => {
    loadSavedChartsFromStorage();
    fetchServerMetrics();
  }, []);

  const loadSavedChartsFromStorage = () => {
    const storedCharts = localStorage.getItem("glassfactory_charts");
    if (storedCharts) {
      try {
        const charts = JSON.parse(storedCharts);
        setSavedCharts(charts);
        addDebugMessage(
          "Info",
          `Loaded ${charts.length} saved charts from localStorage`
        );

        // If there are saved charts, load the most recent one
        if (charts.length > 0) {
          const mostRecent = charts[charts.length - 1];
          setPythonCode(mostRecent.code);
          setChartData(mostRecent.data);
          setChartTitle(mostRecent.title);
          setDescription(mostRecent.description || "");
          addDebugMessage(
            "Info",
            `Automatically loaded most recent chart: ${mostRecent.title}`
          );

          // Check if this chart has a server filepath
          if (mostRecent.filepath) {
            addDebugMessage(
              "Info",
              `This chart is also saved on server at: ${mostRecent.filepath}`
            );
          }
        }
      } catch (e) {
        addDebugMessage("Error", `Failed to load saved charts: ${e.message}`);
      }
    } else {
      addDebugMessage("Info", "No saved charts found in localStorage");
    }
  };

  const fetchServerMetrics = async () => {
    try {
      setIsLoading(true);
      const response = await fetch("http://127.0.0.1:5000/api/custom-metrics");
      const metrics = await response.json();
      setServerMetrics(metrics);
      addDebugMessage(
        "Info",
        `Found ${metrics.length} custom metrics on server`
      );

      // Cross-reference with local storage
      verifyLocalAndServerMetrics(metrics);
    } catch (err) {
      addDebugMessage(
        "Error",
        `Failed to fetch server metrics: ${err.message}`
      );
    } finally {
      setIsLoading(false);
    }
  };

  const verifyLocalAndServerMetrics = (metrics) => {
    const storedCharts = localStorage.getItem("glassfactory_charts");
    if (storedCharts) {
      const localCharts = JSON.parse(storedCharts);
      const serverFilenames = metrics.map((m) => m.filename);
      const localChartFilenames = localCharts
        .filter((chart) => chart.filepath)
        .map((chart) => chart.filepath.split("/").pop());

      const missingFiles = localChartFilenames.filter(
        (filename) => !serverFilenames.includes(filename)
      );

      if (missingFiles.length > 0) {
        addDebugMessage(
          "Warning",
          `${missingFiles.length} charts are missing on server but exist locally`
        );
      } else if (localChartFilenames.length > 0) {
        addDebugMessage(
          "Success",
          "All local charts are properly saved on server"
        );
      }
    }
  };

  const addDebugMessage = (type, message) => {
    const timestamp = new Date().toLocaleTimeString();
    setDebugOutput((prev) => [...prev, { type, message, timestamp }]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    // Don't submit if there are security errors
    if (codeErrors.length > 0) {
      setErrorMessage("Please fix all security errors before running code.");
      addDebugMessage(
        "Error",
        "Code contains security violations. Execution blocked."
      );
      return;
    }

    setIsSubmitting(true);
    setResponse("");
    setChartData(null);
    setErrorMessage("");

    addDebugMessage("Info", "Executing code...");

    try {
      const res = await fetch("http://127.0.0.1:5000/api/glassfactory", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ code: pythonCode }),
      });

      const data = await res.json();

      if (data.error) {
        setErrorMessage(data.error);
        addDebugMessage("Error", data.error);
        setResponse(data.error);
      } else if (data.result) {
        setResponse(data.result);
        addDebugMessage("Output", data.result);

        // Try to parse chart data from the response
        if (data.chart_data) {
          setChartData(data.chart_data);
          addDebugMessage("Success", "Chart data successfully created");
        } else {
          addDebugMessage(
            "Warning",
            "No chart_data object found in your code. Create a chart_data dictionary to visualize data."
          );
        }
      }
    } catch (err) {
      setErrorMessage("Error: " + err.message);
      addDebugMessage("Error", err.message);
      setResponse("Error: " + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const saveChart = async () => {
    if (!chartData) {
      setErrorMessage("No valid chart data to save");
      addDebugMessage("Error", "No valid chart data to save");
      return;
    }

    const newChart = {
      title: chartTitle,
      code: pythonCode,
      data: chartData,
      description: description,
      createdAt: new Date().toISOString(),
    };

    try {
      // Save to server
      const res = await fetch("http://127.0.0.1:5000/api/custom-metrics", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: chartTitle,
          description: description,
          code: pythonCode,
        }),
      });

      const data = await res.json();

      if (data.success) {
        // Update local storage with server filepath
        newChart.filepath = data.filepath;

        const updatedCharts = [...savedCharts, newChart];
        setSavedCharts(updatedCharts);
        localStorage.setItem(
          "glassfactory_charts",
          JSON.stringify(updatedCharts)
        );

        addDebugMessage(
          "Success",
          `Chart "${chartTitle}" saved successfully to server at ${data.filepath}`
        );
        setErrorMessage("");

        // Refresh server metrics list
        fetchServerMetrics();
      } else {
        throw new Error(data.error || "Failed to save to server");
      }
    } catch (err) {
      addDebugMessage(
        "Warning",
        `Saved locally but failed to save to server: ${err.message}`
      );

      // Still save locally even if server save fails
      const updatedCharts = [...savedCharts, newChart];
      setSavedCharts(updatedCharts);
      localStorage.setItem(
        "glassfactory_charts",
        JSON.stringify(updatedCharts)
      );
    }
  };

  const loadChart = (chart) => {
    setPythonCode(chart.code);
    setChartData(chart.data);
    setChartTitle(chart.title);
    setDescription(chart.description || "");
    addDebugMessage("Info", `Loaded chart: ${chart.title}`);
  };

  const deleteChart = async (index, e) => {
    e.stopPropagation();
    const chartToDelete = savedCharts[index];

    // If chart has a filepath, try to delete from server
    if (chartToDelete.filepath) {
      try {
        const filename = chartToDelete.filepath.split("/").pop();
        const res = await fetch(
          `http://127.0.0.1:5000/api/custom-metrics/${filename}`,
          {
            method: "DELETE",
          }
        );

        if (res.ok) {
          addDebugMessage(
            "Success",
            `Deleted chart from server: ${chartToDelete.title}`
          );
          // Refresh server metrics list
          fetchServerMetrics();
        } else {
          addDebugMessage(
            "Warning",
            `Failed to delete from server, but will remove from local storage`
          );
        }
      } catch (err) {
        addDebugMessage(
          "Warning",
          `Error deleting from server: ${err.message}`
        );
      }
    }

    // Remove from local storage regardless of server result
    const updatedCharts = [...savedCharts];
    updatedCharts.splice(index, 1);
    setSavedCharts(updatedCharts);
    localStorage.setItem("glassfactory_charts", JSON.stringify(updatedCharts));
    addDebugMessage(
      "Info",
      `Deleted chart from local storage: ${chartToDelete.title}`
    );
  };

  const loadServerMetric = async (filename) => {
    try {
      const res = await fetch(
        `http://127.0.0.1:5000/api/custom-metrics/${filename}`
      );
      const data = await res.json();

      if (data.code) {
        setPythonCode(data.code);
        setChartTitle(filename.replace(".py", ""));
        addDebugMessage("Info", `Loaded code from server: ${filename}`);

        // Try to extract description from code comments
        const descriptionMatch = data.code.match(/# Description: (.*)/);
        if (descriptionMatch && descriptionMatch[1]) {
          setDescription(descriptionMatch[1]);
        } else {
          setDescription("");
        }

        // Run the code automatically
        handleSubmit(new Event("submit"));
      } else {
        addDebugMessage(
          "Error",
          `Failed to load code: ${data.error || "Unknown error"}`
        );
      }
    } catch (err) {
      addDebugMessage(
        "Error",
        `Error loading metric from server: ${err.message}`
      );
    }
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
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
          <span className="text-3xl font-bold">Glass Factory</span>
        </MenubarMenu>
      </Menubar>

      {/* Main Content */}
      <div className="flex flex-grow">
        {/* Left Pane: Python Code Editor and Saved Charts */}
        <div className="w-1/2 p-4 border-r border-gray-300 flex flex-col">
          <h1 className="text-2xl font-bold mb-4">Python Code</h1>

          <CodeEditor
            pythonCode={pythonCode}
            setPythonCode={setPythonCode}
            codeErrors={codeErrors}
            setCodeErrors={setCodeErrors}
            handleSubmit={handleSubmit}
            isSubmitting={isSubmitting}
            chartData={chartData}
            chartTitle={chartTitle}
            setChartTitle={setChartTitle}
            description={description}
            setDescription={setDescription}
            saveChart={saveChart}
          />

          <div className="mt-4 grid grid-cols-1 gap-4">
            <SavedChartsList
              savedCharts={savedCharts}
              loadChart={loadChart}
              deleteChart={deleteChart}
            />

            <ServerMetricsList
              serverMetrics={serverMetrics}
              isLoading={isLoading}
              loadServerMetric={loadServerMetric}
            />
          </div>
        </div>

        {/* Right Pane: Chart Display and Debug Output */}
        <div className="w-1/2 p-4 flex flex-col">
          <ChartDisplay
            chartData={chartData}
            chartTitle={chartTitle}
            errorMessage={errorMessage}
          />

          <DebugPanel response={response} debugOutput={debugOutput} />
        </div>
      </div>
    </div>
  );
}
