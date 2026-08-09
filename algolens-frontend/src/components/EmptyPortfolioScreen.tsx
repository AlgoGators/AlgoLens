import React from 'react';
import { TrendingUp, BarChart3, PieChart } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';

interface EmptyPortfolioScreenProps {
  onClose?: () => void;
}

export function EmptyPortfolioScreen({ onClose }: EmptyPortfolioScreenProps) {
  const { theme } = useTheme();

  return (
    <div className={`min-h-screen flex items-center justify-center p-4 ${
      theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
    }`}>
      <div className="max-w-md w-full text-center">
        {/* Icon */}
        <div className="mb-8 flex justify-center">
          <div className={`relative w-32 h-32 rounded-full flex items-center justify-center ${
            theme === 'dark' ? 'bg-gray-900' : 'bg-gray-100'
          }`}>
            <div className="absolute inset-0 rounded-full border-4 border-orange-500 opacity-20"></div>
            <TrendingUp className="w-16 h-16 text-orange-500" />
          </div>
        </div>

        {/* Title */}
        <h1 className="text-2xl md:text-3xl mb-4">
          No Active Positions
        </h1>

        {/* Description */}
        <p className={`text-base md:text-lg mb-8 ${
          theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
        }`}>
          Your portfolio is currently empty. Add positions to start tracking your investment performance.
        </p>

        {/* Features */}
        <div className="space-y-4 mb-8">
          <div className={`p-4 rounded-lg border text-left ${
            theme === 'dark' 
              ? 'bg-gray-950 border-gray-800' 
              : 'bg-gray-50 border-gray-200'
          }`}>
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-full bg-orange-500 bg-opacity-10 flex items-center justify-center flex-shrink-0">
                <BarChart3 className="w-5 h-5 text-orange-500" />
              </div>
              <div className="flex-1">
                <h3 className="text-sm mb-1">Track Multiple Strategies</h3>
                <p className={`text-xs ${
                  theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
                }`}>
                  Monitor Growth, Dividend, and Value strategies independently
                </p>
              </div>
            </div>
          </div>

          <div className={`p-4 rounded-lg border text-left ${
            theme === 'dark' 
              ? 'bg-gray-950 border-gray-800' 
              : 'bg-gray-50 border-gray-200'
          }`}>
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-full bg-orange-500 bg-opacity-10 flex items-center justify-center flex-shrink-0">
                <PieChart className="w-5 h-5 text-orange-500" />
              </div>
              <div className="flex-1">
                <h3 className="text-sm mb-1">Detailed Analytics</h3>
                <p className={`text-xs ${
                  theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
                }`}>
                  View performance metrics, risk analysis, and P&L breakdowns
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Action Button */}
        <button
          onClick={onClose}
          className="w-full py-4 px-6 bg-orange-500 hover:bg-orange-600 text-white rounded-lg transition-colors"
        >
          Get Started
        </button>

        {/* Helper Text */}
        <p className={`text-xs mt-6 ${
          theme === 'dark' ? 'text-gray-600' : 'text-gray-400'
        }`}>
          Contact your fund manager to add positions to your portfolio
        </p>
      </div>
    </div>
  );
}
