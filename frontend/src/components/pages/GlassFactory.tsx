"use client";

import { useState, useEffect } from "react";
import { Menubar, MenubarMenu, MenubarTrigger } from "@/components/ui/menubar";
import Link from "next/link";
import Image from "next/image";
import Chart from "../Chart";
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { vscodeDark } from '@uiw/codemirror-theme-vscode';

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

// Allowed imports and functions - used for validation
const ALLOWED_IMPORTS = ['pandas', 'numpy', 'pd', 'np'];
const ALLOWED_FUNCTIONS = ['system', 'quant_stats'];

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

  // Load saved charts on component mount
  useEffect(() => {
    const storedCharts = localStorage.getItem("glassfactory_charts");
    if (storedCharts) {
      try {
        setSavedCharts(JSON.parse(storedCharts));
      } catch (e) {
        addDebugMessage("Error", `Failed to load saved charts: ${e.message}`);
      }
    }
  }, []);

  // Validate code for security issues
  useEffect(() => {
    validateCode(pythonCode);
  }, [pythonCode]);

  const validateCode = (code) => {
    const errors = [];
    
    // Check for unauthorized imports
    const importRegex = /^\s*import\s+([^\s]+)|^\s*from\s+([^\s]+)\s+import/gm;
    let match;
    while ((match = importRegex.exec(code)) !== null) {
      const importName = match[1] || match[2];
      if (!ALLOWED_IMPORTS.includes(importName)) {
        errors.push({
          line: code.substring(0, match.index).split('\n').length - 1,
          message: `Unauthorized import: ${importName}. Only pandas and numpy are allowed.`,
          severity: 'error'
        });
      }
    }
    
    // Check for potentially dangerous functions
    const dangerousFunctions = [
      'eval', 'exec', 'compile', 'open', 'file', '__import__', 
      'globals', 'locals', 'getattr', 'setattr', 'delattr', 
      'os', 'sys', 'subprocess', 'shutil'
    ];
    
    dangerousFunctions.forEach(func => {
      const funcRegex = new RegExp(`\\b${func}\\s*\\(`, 'g');
      let funcMatch;
      while ((funcMatch = funcRegex.exec(code)) !== null) {
        errors.push({
          line: code.substring(0, funcMatch.index).split('\n').length - 1,
          message: `Unauthorized function: ${func}() is not allowed for security reasons.`,
          severity: 'error'
        });
      }
    });
    
    setCodeErrors(errors);
  };

  const addDebugMessage = (type, message) => {
    const timestamp = new Date().toLocaleTimeString();
    setDebugOutput(prev => [...prev, { type, message, timestamp }]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Don't submit if there are security errors
    if (codeErrors.length > 0) {
      setErrorMessage("Please fix all security errors before running code.");
      addDebugMessage("Error", "Code contains security violations. Execution blocked.");
      return;
    }
    
    setIsSubmitting(true);
    setResponse("");
    setChartData(null);
    setErrorMessage("");
    setDebugOutput([]);
    
    addDebugMessage("Info", "Executing code...");
    
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
          addDebugMessage("Warning", "No chart_data object found in your code. Create a chart_data dictionary to visualize data.");
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

  const saveChart = () => {
    if (!chartData) {
      setErrorMessage("No valid chart data to save");
      addDebugMessage("Error", "No valid chart data to save");
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
    addDebugMessage("Success", `Chart "${chartTitle}" saved successfully`);
    setErrorMessage("");
  };

  const loadChart = (chart) => {
    setPythonCode(chart.code);
    setChartData(chart.data);
    setChartTitle(chart.title);
    addDebugMessage("Info", `Loaded chart: ${chart.title}`);
  };

  const deleteChart = (index, e) => {
    e.stopPropagation();
    const chartToDelete = savedCharts[index];
    const updatedCharts = [...savedCharts];
    updatedCharts.splice(index, 1);
    setSavedCharts(updatedCharts);
    localStorage.setItem("glassfactory_charts", JSON.stringify(updatedCharts));
    addDebugMessage("Info", `Deleted chart: ${chartToDelete.title}`);
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
            <div className="flex-grow relative">
              <CodeMirror
                value={pythonCode}
                height="100%"
                theme={vscodeDark}
                extensions={[python()]}
                onChange={(value) => setPythonCode(value)}
                className="border border-gray-300 rounded"
              />
              {codeErrors.length > 0 && (
                <div className="absolute top-2 right-2 bg-red-100 border border-red-300 text-red-700 px-2 py-1 rounded text-xs">
                  {codeErrors.length} security {codeErrors.length === 1 ? 'error' : 'errors'}
                </div>
              )}
            </div>
            <div className="mt-4 flex space-x-4">
              <button
                type="submit"
                className={`px-4 py-2 text-white rounded ${codeErrors.length > 0 ? 'bg-red-600' : 'bg-blue-600'}`}
                disabled={isSubmitting || codeErrors.length > 0}
              >
                {isSubmitting ? "Running..." : codeErrors.length > 0 ? "Fix Errors to Run" : "Run Code"}
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
                        onClick={(e) => deleteChart(index, e)}
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
        
        {/* Right Pane: Output, Chart Preview, and Debug Console */}
        <div className="w-1/2 p-4 flex flex-col">
          {errorMessage && (
            <div className="mb-4 p-2 bg-red-100 border border-red-300 text-red-700 rounded">
              {errorMessage}
            </div>
          )}
          
          {codeErrors.length > 0 && (
            <div className="mb-4">
              <h2 className="text-xl font-bold mb-2 text-red-600">Security Errors</h2>
              <div className="border border-red-300 rounded bg-red-50 p-2 max-h-40 overflow-y-auto">
                {codeErrors.map((error, index) => (
                  <div key={index} className="mb-1 text-red-700">
                    <strong>Line {error.line + 1}:</strong> {error.message}
                  </div>
                ))}
              </div>
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
              
              {/* Debug Console below chart */}
              <div className="mt-4">
                <h2 className="text-xl font-bold mb-2">Debug Console</h2>
                <div className="border border-gray-300 rounded bg-gray-100 p-2 h-40 overflow-y-auto font-mono text-sm">
                  {debugOutput.map((item, index) => (
                    <div key={index} className={`mb-1 ${
                      item.type === 'Error' ? 'text-red-600' : 
                      item.type === 'Warning' ? 'text-amber-600' : 
                      item.type === 'Success' ? 'text-green-600' : 
                      'text-gray-800'
                    }`}>
                      <span className="text-gray-500">[{item.timestamp}]</span> <strong>{item.type}:</strong> {item.message}
                    </div>
                  ))}
                  {debugOutput.length === 0 && (
                    <div className="text-gray-500 italic">No output yet. Run your code to see results here.</div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-grow flex flex-col">
              <h1 className="text-2xl font-bold mb-4">Console Output</h1>
              <div className="flex-grow p-2 border border-gray-300 rounded bg-gray-100 overflow-auto whitespace-pre-wrap font-mono">
                {response || "No output yet. Run your code to see results here."}
              </div>
              
              {/* Debug Console */}
              <div className="mt-4">
                <h2 className="text-xl font-bold mb-2">Debug Console</h2>
                <div className="border border-gray-300 rounded bg-gray-100 p-2 h-40 overflow-y-auto font-mono text-sm">
                  {debugOutput.map((item, index) => (
                    <div key={index} className={`mb-1 ${
                      item.type === 'Error' ? 'text-red-600' : 
                      item.type === 'Warning' ? 'text-amber-600' : 
                      item.type === 'Success' ? 'text-green-600' : 
                      'text-gray-800'
                    }`}>
                      <span className="text-gray-500">[{item.timestamp}]</span> <strong>{item.type}:</strong> {item.message}
                    </div>
                  ))}
                  {debugOutput.length === 0 && (
                    <div className="text-gray-500 italic">No output yet. Run your code to see results here.</div>
                  )}
                </div>
              </div>
              
              {/* Available Resources Section */}
              <div className="mt-4">
                <h2 className="text-xl font-bold mb-2">Available Resources</h2>
                <div className="border border-gray-300 rounded bg-gray-50 p-3">
                  <h3 className="font-bold mb-1">Modules:</h3>
                  <ul className="list-disc pl-5 mb-2">
                    <li>pandas (as pd)</li>
                    <li>numpy (as np)</li>
                  </ul>
                  
                  <h3 className="font-bold mb-1">Functions:</h3>
                  <ul className="list-disc pl-5 mb-2">
                    <li><code className="bg-gray-200 px-1 rounded">system()</code> - Returns strategy groups data</li>
                    <li><code className="bg-gray-200 px-1 rounded">quant_stats(strategy_name, strategy_data, benchmark_name, benchmark_data)</code> - Calculate quantitative statistics</li>
                  </ul>
                  
                  <h3 className="font-bold mb-1">Required Output:</h3>
                  <p>To create a chart, define a <code className="bg-gray-200 px-1 rounded">chart_data</code> variable with the following structure:</p>
                  <pre className="bg-gray-200 p-2 rounded text-xs mt-1">
{`chart_data = {
    "labels": ["2023-01-01", "2023-01-02", ...],  # Date labels
    "datasets": [
        {
            "label": "My Chart Title",
            "data": [1.2, 1.3, ...],              # Values to plot
            "borderColor": "#ff5c00",             # Line color
            "backgroundColor": "#ff5c00",         # Fill color
            "borderWidth": 2,
            "tension": 0.4,
            "pointRadius": 0,
        }
    ]
}`}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
