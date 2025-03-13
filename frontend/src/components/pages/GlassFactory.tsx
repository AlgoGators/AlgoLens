"use client";

import { useState, useEffect } from "react";
import { Menubar, MenubarMenu, MenubarTrigger } from "@/components/ui/menubar";
import Link from "next/link";
import Image from "next/image";
import Chart from "../Chart";

export default function GlassFactory() {
  const [pythonCode, setPythonCode] = useState("");
  const [response, setResponse] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [chartData, setChartData] = useState(null);
  const [chartTitle, setChartTitle] = useState("Custom Chart");
  const [savedCharts, setSavedCharts] = useState([]);
  const [errorMessage, setErrorMessage] = useState("");

  // Load saved charts on component mount
  useEffect(() => {
    const storedCharts = localStorage.getItem("glassfactory_charts");
    if (storedCharts) {
      try {
        setSavedCharts(JSON.parse(storedCharts));
      } catch (e) {
        console.error("Error loading saved charts:", e);
      }
    }
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    setResponse("");
    setChartData(null);
    setErrorMessage("");
    
    try {
      const res = await fetch("http://localhost:5000/api/glassfactory", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ code: pythonCode }),
      });
      
      const data = await res.json();
      
      if (data.error) {
        setErrorMessage(data.error);
        setResponse(JSON.stringify(data, null, 2));
      } else if (data.result) {
        setResponse(data.result);
        
        // Try to parse chart data from the result
        try {
          // Look for chart_data in the response
          if (data.chart_data) {
            setChartData(data.chart_data);
          }
        } catch (err) {
          console.error("Error parsing chart data:", err);
        }
      }
    } catch (err) {
      setErrorMessage("Error: " + err.message);
      setResponse("Error: " + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const saveChart = () => {
    if (!chartData) {
      setErrorMessage("No valid chart data to save");
      return;
    }

    const newChart = {
      title: chartTitle,
      code: pythonCode,
      data: chartData,
      createdAt: new Date().toISOString()
    };

    const updatedCharts = [...savedCharts, newChart];
    setSavedCharts(updatedCharts);
    localStorage.setItem("glassfactory_charts", JSON.stringify(updatedCharts));
    setErrorMessage("");
  };

  const loadChart = (chart) => {
    setPythonCode(chart.code);
    setChartData(chart.data);
    setChartTitle(chart.title);
  };

  const deleteChart = (index) => {
    const updatedCharts = [...savedCharts];
    updatedCharts.splice(index, 1);
    setSavedCharts(updatedCharts);
    localStorage.setItem("glassfactory_charts", JSON.stringify(updatedCharts));
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
          <form onSubmit={handleSubmit} className="flex flex-col flex-grow">
            <textarea
              className="flex-grow w-full p-2 border border-gray-300 rounded resize-none font-mono"
              placeholder="Enter Python code here to create a chart_data object..."
              value={pythonCode}
              onChange={(e) => setPythonCode(e.target.value)}
            />
            <div className="mt-4 flex space-x-4">
              <button
                type="submit"
                className="px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-50"
                disabled={isSubmitting}
              >
                {isSubmitting ? "Running..." : "Run Code"}
              </button>
              
              {chartData && (
                <div className="flex-1 flex space-x-2">
                  <input
                    type="text"
                    placeholder="Chart title"
                    className="flex-1 px-2 border border-gray-300 rounded"
                    value={chartTitle}
                    onChange={(e) => setChartTitle(e.target.value)}
                  />
                  <button
                    type="button"
                    onClick={saveChart}
                    className="px-4 py-2 bg-green-600 text-white rounded"
                  >
                    Save Chart
                  </button>
                </div>
              )}
            </div>
          </form>
          
          {/* Saved Charts Section */}
          {savedCharts.length > 0 && (
            <div className="mt-4">
              <h2 className="text-xl font-bold mb-2">Saved Charts</h2>
              <div className="border border-gray-300 rounded p-2 max-h-60 overflow-y-auto">
                {savedCharts.map((chart, index) => (
                  <div 
                    key={index} 
                    className="p-2 hover:bg-gray-100 cursor-pointer flex justify-between items-center border-b last:border-b-0"
                  >
                    <span 
                      className="flex-1"
                      onClick={() => loadChart(chart)}
                    >
                      {chart.title}
                    </span>
                    <div className="flex space-x-2">
                      <span className="text-xs text-gray-500">
                        {new Date(chart.createdAt).toLocaleDateString()}
                      </span>
                      <button 
                        onClick={() => deleteChart(index)}
                        className="text-red-500 text-xs"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        
        {/* Right Pane: Output and Chart Preview */}
        <div className="w-1/2 p-4 flex flex-col">
          {errorMessage && (
            <div className="mb-4 p-2 bg-red-100 border border-red-300 text-red-700 rounded">
              {errorMessage}
            </div>
          )}
          
          {chartData ? (
            <div className="flex-grow flex flex-col">
              <h1 className="text-2xl font-bold mb-4">Chart Preview</h1>
              <div className="flex-grow border border-gray-300 rounded p-4">
                <Chart 
                  data={chartData}
                  title={chartTitle}
                />
              </div>
            </div>
          ) : (
            <div className="flex-grow flex flex-col">
              <h1 className="text-2xl font-bold mb-4">Console Output</h1>
              <div className="flex-grow p-2 border border-gray-300 rounded bg-gray-100 overflow-auto whitespace-pre-wrap font-mono">
                {response}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
