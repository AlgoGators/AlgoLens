"use client";

import * as React from "react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Settings } from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

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
}

export default function SettingsDropdown({
  preferences,
  updatePreference,
  handleSubmitPreferences,
  minDate,
  maxDate,
  dateRange,
  setDateRange,
}: SettingsDropdownProps) {
  // When a text input is changed, update the corresponding slider value
  const handleStartDateChange = (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const newTime = new Date(e.target.value).getTime();
    if (!isNaN(newTime)) {
      setDateRange([newTime, dateRange[1]]);
    }
  };

  const handleEndDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newTime = new Date(e.target.value).getTime();
    if (!isNaN(newTime)) {
      setDateRange([dateRange[0], newTime]);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="fixed top-4 left-4 z-50 w-10 h-10 flex items-center justify-center bg-gray-200 rounded-full">
          <Settings className="w-6 h-6" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        sideOffset={4}
        className="bg-white bg-opacity-90 shadow-lg p-4"
      >
        {/* Existing preference checkboxes */}
        <DropdownMenuCheckboxItem
          checked={preferences.stock_price}
          onCheckedChange={(checked) =>
            updatePreference("stock_price", Boolean(checked))
          }
          onSelect={(event) => event.preventDefault()}
        >
          Stock Cumulative Returns
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={preferences.SPY_cumulative}
          onCheckedChange={(checked) =>
            updatePreference("SPY_cumulative", Boolean(checked))
          }
          onSelect={(event) => event.preventDefault()}
        >
          S&P 500 Cumulative Returns
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={preferences.percentage_change_vs_SPY}
          onCheckedChange={(checked) =>
            updatePreference("percentage_change_vs_SPY", Boolean(checked))
          }
          onSelect={(event) => event.preventDefault()}
        >
          Percentage Change vs. S&P 500
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={preferences.implied_volatility}
          onCheckedChange={(checked) =>
            updatePreference("implied_volatility", Boolean(checked))
          }
          onSelect={(event) => event.preventDefault()}
        >
          Implied Volatility
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={preferences.rolling_volatility}
          onCheckedChange={(checked) =>
            updatePreference("rolling_volatility", Boolean(checked))
          }
          onSelect={(event) => event.preventDefault()}
        >
          Rolling Volatility
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={preferences.rolling_sharpe}
          onCheckedChange={(checked) =>
            updatePreference("rolling_sharpe", Boolean(checked))
          }
          onSelect={(event) => event.preventDefault()}
        >
          Rolling Sharpe
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={preferences.rolling_sortino}
          onCheckedChange={(checked) =>
            updatePreference("rolling_sortino", Boolean(checked))
          }
          onSelect={(event) => event.preventDefault()}
        >
          Rolling Sortino
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={preferences.metrics}
          onCheckedChange={(checked) =>
            updatePreference("metrics", Boolean(checked))
          }
          onSelect={(event) => event.preventDefault()}
        >
          Show Metrics Section
        </DropdownMenuCheckboxItem>

        {/* Date Filter Section */}
        <div className="mt-4">
          <div className="mb-2 text-sm font-medium">Date Filter</div>
          {/* Range Slider */}
          <Slider
            value={dateRange}
            onValueChange={(value) => setDateRange(value)}
            min={minDate}
            max={maxDate}
            step={86400000} // one day (in milliseconds)
            className="mb-2"
          />
          {/* Text Inputs for start and end dates */}
          <div className="flex items-center space-x-2 text-xs">
            <input
              type="date"
              value={formatDate(dateRange[0])}
              onChange={handleStartDateChange}
              className="border p-1 rounded"
            />
            <span>to</span>
            <input
              type="date"
              value={formatDate(dateRange[1])}
              onChange={handleEndDateChange}
              className="border p-1 rounded"
            />
          </div>
        </div>

        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            handleSubmitPreferences();
          }}
        >
          Submit Preferences
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
