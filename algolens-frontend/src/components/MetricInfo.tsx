import React, { useState } from 'react';
import { HelpCircle, X } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';

interface MetricInfoProps {
  metric: string;
  description: string;
  formula?: string;
}

export function MetricInfo({ metric, description, formula }: MetricInfoProps) {
  const [showInfo, setShowInfo] = useState(false);
  const { theme } = useTheme();

  return (
    <>
      <button
        onClick={() => setShowInfo(true)}
        className={`ml-2 inline-flex items-center justify-center w-4 h-4 rounded-full transition-colors ${
          theme === 'dark'
            ? 'text-gray-500 hover:text-orange-500'
            : 'text-gray-400 hover:text-orange-500'
        }`}
      >
        <HelpCircle className="w-4 h-4" />
      </button>

      {showInfo && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className={`w-full max-w-md rounded-lg p-6 ${
            theme === 'dark' ? 'bg-gray-900' : 'bg-white'
          }`}>
            <div className="flex items-start justify-between mb-4">
              <h3 className="text-lg">{metric}</h3>
              <button
                onClick={() => setShowInfo(false)}
                className={`p-1 rounded-full transition-colors ${
                  theme === 'dark' ? 'hover:bg-gray-800' : 'hover:bg-gray-100'
                }`}
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <p className={`mb-4 ${
              theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
            }`}>
              {description}
            </p>
            
            {formula && (
              <div className={`p-3 rounded-lg ${
                theme === 'dark' ? 'bg-gray-800' : 'bg-gray-100'
              }`}>
                <div className={`text-sm mb-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Formula:
                </div>
                <code className="text-sm font-mono">{formula}</code>
              </div>
            )}

            <button
              onClick={() => setShowInfo(false)}
              className="w-full mt-4 px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors"
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </>
  );
}
