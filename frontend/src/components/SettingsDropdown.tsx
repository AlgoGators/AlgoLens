"use client";

import * as React from "react";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuGroup,
} from "@/components/ui/dropdown-menu";
import { Settings } from "lucide-react";
import { Slider } from "@/components/ui/slider";

const toggleCustomMetric = (metricId: string) => {
  if (selectedCustomMetrics.includes(metricId)) {
    setSelectedCustomMetrics(selectedCustomMetrics.filter(id => id !== metricId));
  } else {
    setSelectedCustomMetrics([...selectedCustomMetrics, metricId]);
  }
};

// Helper: convert a timestamp to "YYYY-MM-DD" (or empty if invalid)
const formatDate = (time: number): string => {
  const d = new Date(time);
  return isNaN(d.getTime()) ? "" : d.toISOString().split("T")[0];
};

interface SettingsDropdownProps {
  preferences: Record<string, boolean>;
  updatePreference: (name: string, checked: boolean) => void;
  handleSubmitPreferences: () => void;
  minDate: number;
  maxDate: number;
  dateRange: number[];
  setDateRange: (value: number[]) => void;
  selectedCustomMetrics: string[];
  setSelectedCustomMetrics: (metrics: string[]) => void;
}

export default function SettingsDropdown({
  preferences,
  updatePreference,
  handleSubmitPreferences,
  minDate,
  maxDate,
  dateRange,
  setDateRange,
  selectedCustomMetrics,
  setSelectedCustomMetrics,
}: SettingsDropdownProps) {
  const [availableCustomMetrics, setAvailableCustomMetrics] = useState<Array<{id: string, name: string}>>([]);

  // Fetch available custom metrics when component mounts
  useEffect(() => {
    async function fetchCustomMetrics() {
      try {
        const response = await fetch("http://localhost:5000/api/custom-metrics");
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

  const handleStartDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault(); // Prevent default form submission
    const newTime = new Date(e.target.value).getTime();
    if (!isNaN(newTime)) {
      setDateRange([newTime, dateRange[1]]);
    }
  };

  const handleEndDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault(); // Prevent default form submission
    const newTime = new Date(e.target.value).getTime();
    if (!isNaN(newTime)) {
      setDateRange([dateRange[0], newTime]);
    }
  };

  const toggleCustomMetric = (metricId: string) => {
    if (selectedCustomMetrics.includes(metricId)) {
      setSelectedCustomMetrics(selectedCustomMetrics.filter(id => id !== metricId));
    } else {
      setSelectedCustomMetrics([...selectedCustomMetrics, metricId]);
    }
  };

  console.log(availableCustomMetrics);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button 
          type="button" // Explicitly set type to button to prevent form submission
          className="fixed top-4 left-4 z-50 w-10 h-10 flex items-center justify-center bg-gray-200 rounded-full"
        >
          <Settings className="w-6 h-6" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        sideOffset={4}
        className="bg-white bg-opacity-90 shadow-lg p-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Preference checkboxes */}
        <DropdownMenuLabel>Chart Preferences</DropdownMenuLabel>
        <DropdownMenuGroup>
          <DropdownMenuCheckboxItem
            checked={preferences.stock_price}
            onCheckedChange={(checked) =>
              updatePreference("stock_price", Boolean(checked))
            }
          >
            Stock Cumulative Returns
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={preferences.SPY_cumulative}
            onCheckedChange={(checked) =>
              updatePreference("Index_cumulative", Boolean(checked))
            }
          >
            Index Cumulative Returns
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={preferences.percentage_change_vs_SPY}
            onCheckedChange={(checked) =>
              updatePreference("percentage_change_vs_Index", Boolean(checked))
            }
          >
            Percentage Change vs. Index
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={preferences.implied_volatility}
            onCheckedChange={(checked) =>
              updatePreference("implied_volatility", Boolean(checked))
            }
          >
            Implied Volatility
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={preferences.rolling_volatility}
            onCheckedChange={(checked) =>
              updatePreference("rolling_volatility", Boolean(checked))
            }
          >
            Rolling Volatility
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={preferences.rolling_sharpe}
            onCheckedChange={(checked) =>
              updatePreference("rolling_sharpe", Boolean(checked))
            }
          >
            Rolling Sharpe
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={preferences.rolling_sortino}
            onCheckedChange={(checked) =>
              updatePreference("rolling_sortino", Boolean(checked))
            }
          >
            Rolling Sortino
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={preferences.metrics}
            onCheckedChange={(checked) =>
              updatePreference("metrics", Boolean(checked))
            }
          >
            Show Metrics Section
          </DropdownMenuCheckboxItem>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />
        
        {/* Custom Metrics Section */}
        <DropdownMenuLabel>Custom Metrics</DropdownMenuLabel>
        <DropdownMenuGroup>
          {availableCustomMetrics.map((metric) => (
            <DropdownMenuCheckboxItem
              key={metric.filename}
              checked={selectedCustomMetrics.includes(metric.filename)}
              onCheckedChange={() => toggleCustomMetric(metric.filename)}
            >
              {metric.name || metric.filename}
            </DropdownMenuCheckboxItem>
          ))}
          <DropdownMenuItem asChild>
            <Link href="/glassfactory" className="cursor-pointer">
              <span className="text-blue-600">+ Create New Metric</span>
            </Link>
          </DropdownMenuItem>
        </DropdownMenuGroup>
        
        <DropdownMenuSeparator />

        {/* Date Filter Section */}
        <DropdownMenuLabel>Date Filter</DropdownMenuLabel>
        <div className="mt-2">
          {/* Range Slider with explicit prevention of form submission */}
          <div 
            onClick={(e) => e.stopPropagation()} 
            className="px-2"
          >
            <Slider
              value={dateRange}
              onValueChange={setDateRange}
              min={minDate}
              max={maxDate}
              step={86400000} // one day in milliseconds
              className="mb-2"
            />
          </div>
          {/* Text Inputs for start and end dates */}
          <div className="flex items-center space-x-2 text-xs">
            <input
              type="date"
              value={formatDate(dateRange[0])}
              onChange={handleStartDateChange}
              className="border p-1 rounded"
              onClick={(e) => e.stopPropagation()}
            />
            <span>to</span>
            <input
              type="date"
              value={formatDate(dateRange[1])}
              onChange={handleEndDateChange}
              className="border p-1 rounded"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>

        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <button 
            type="button" 
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              handleSubmitPreferences();
            }}
            className="w-full text-left cursor-pointer px-2 py-1.5 text-sm"
          >
            Apply Settings
          </button>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
