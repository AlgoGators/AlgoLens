"use client";

import * as React from "react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu"; // adjust the import path as needed
import { Settings } from "lucide-react";

interface SettingsDropdownProps {
  preferences: Record<string, boolean>;
  updatePreference: (name: string, checked: boolean) => void;
  handleSubmitPreferences: () => void;
}

export default function SettingsDropdown({
  preferences,
  updatePreference,
  handleSubmitPreferences,
}: SettingsDropdownProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="fixed top-4 left-4 z-50 w-10 h-10 flex items-center justify-center bg-gray-200 rounded-full">
          <Settings className="w-6 h-6" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" sideOffset={4}>
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
            updatePreference("SPY_cumulative", Boolean(checked))
          }
        >
          S&P 500 Cumulative Returns
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={preferences.percentage_change_vs_SPY}
          onCheckedChange={(checked) =>
            updatePreference("percentage_change_vs_SPY", Boolean(checked))
          }
        >
          Percentage Change vs. S&P 500
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
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => handleSubmitPreferences()}>
          Submit Preferences
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
