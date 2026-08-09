import React, { useState } from 'react';
import { X, ChevronDown, ChevronUp, ExternalLink } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';

interface NewsViewProps {
  onClose: () => void;
}

export function NewsView({ onClose }: NewsViewProps) {
  const { theme } = useTheme();
  const [expandedItems, setExpandedItems] = useState<{ [key: string]: boolean }>({});

  const toggleExpand = (id: string) => {
    setExpandedItems(prev => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className={`min-h-screen ${
      theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
    }`}>
      {/* Header */}
      <div className={`sticky top-0 z-10 border-b ${
        theme === 'dark' ? 'bg-black border-gray-800' : 'bg-white border-gray-200'
      }`}>
        <div className="max-w-5xl mx-auto px-4 md:px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-xl md:text-2xl">News & Updates</h2>
            <p className={`text-sm ${
              theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
            }`}>
              Fund updates, market analysis, and newsletters
            </p>
          </div>
          <button
            onClick={onClose}
            className={`p-2 rounded-full transition-colors md:hidden ${
              theme === 'dark' ? 'hover:bg-gray-900' : 'hover:bg-gray-100'
            }`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-4 md:px-6 py-6 space-y-4 pb-24 md:pb-6">
        {/* Latest Fund Update */}
        <div className={`p-4 rounded-lg border ${
          theme === 'dark'
            ? 'bg-orange-950 border-orange-900'
            : 'bg-orange-50 border-orange-200'
        }`}>
          <div className={`text-xs uppercase tracking-wider mb-2 ${
            theme === 'dark' ? 'text-orange-400' : 'text-orange-600'
          }`}>
            Latest Update • 2 hours ago
          </div>
          <h3 className="text-lg mb-2">Q4 Portfolio Rebalancing Complete</h3>
          
          {!expandedItems['update1'] ? (
            <>
              <p className={`text-sm mb-3 ${
                theme === 'dark' ? 'text-orange-100' : 'text-orange-900'
              }`}>
                New positions added to Growth Strategy. The fund has successfully completed its quarterly rebalancing...
              </p>
              <button
                onClick={() => toggleExpand('update1')}
                className={`text-sm flex items-center gap-1 ${
                  theme === 'dark' ? 'text-orange-400' : 'text-orange-600'
                } hover:underline`}
              >
                Read more <ChevronDown className="w-4 h-4" />
              </button>
            </>
          ) : (
            <>
              <p className={`text-sm mb-3 ${
                theme === 'dark' ? 'text-orange-100' : 'text-orange-900'
              }`}>
                New positions added to Growth Strategy. The fund has successfully completed its quarterly rebalancing with the following key changes:
              </p>
              <ul className={`list-disc list-inside space-y-2 mb-3 text-sm ${
                theme === 'dark' ? 'text-orange-100' : 'text-orange-900'
              }`}>
                <li>Added 3 new positions in AI and cloud computing sectors</li>
                <li>Increased allocation to semiconductor stocks by 5%</li>
                <li>Trimmed overweight positions in consumer discretionary</li>
                <li>Maintained dividend strategy positions for stability</li>
              </ul>
              <p className={`text-sm mb-3 ${
                theme === 'dark' ? 'text-orange-100' : 'text-orange-900'
              }`}>
                These changes align with our Q1 2026 outlook and position the fund to capitalize on emerging tech trends while maintaining balanced risk exposure.
              </p>
              <button
                onClick={() => toggleExpand('update1')}
                className={`text-sm flex items-center gap-1 ${
                  theme === 'dark' ? 'text-orange-400' : 'text-orange-600'
                } hover:underline`}
              >
                Show less <ChevronUp className="w-4 h-4" />
              </button>
            </>
          )}
        </div>

        {/* Weekly Macro Report */}
        <div className={`p-4 rounded-lg border ${
          theme === 'dark'
            ? 'bg-gray-900 border-gray-800'
            : 'bg-gray-50 border-gray-200'
        }`}>
          <div className={`text-xs uppercase tracking-wider mb-2 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            Weekly Macro Report • Dec 17, 2025
          </div>
          <h3 className="text-lg mb-2">Fed Holds Rates Steady, Tech Sector Leads Rally</h3>
          
          {!expandedItems['macro1'] ? (
            <>
              <p className={`text-sm mb-3 ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                The Federal Reserve maintained interest rates at current levels this week, citing controlled inflation...
              </p>
              <div className="flex flex-wrap gap-2 mb-3">
                <span className={`px-2 py-1 rounded text-xs ${
                  theme === 'dark'
                    ? 'bg-gray-800 text-gray-300'
                    : 'bg-gray-200 text-gray-700'
                }`}>
                  #MacroEconomics
                </span>
                <span className={`px-2 py-1 rounded text-xs ${
                  theme === 'dark'
                    ? 'bg-gray-800 text-gray-300'
                    : 'bg-gray-200 text-gray-700'
                }`}>
                  #FederalReserve
                </span>
                <span className={`px-2 py-1 rounded text-xs ${
                  theme === 'dark'
                    ? 'bg-gray-800 text-gray-300'
                    : 'bg-gray-200 text-gray-700'
                }`}>
                  #TechStocks
                </span>
              </div>
              <button
                onClick={() => toggleExpand('macro1')}
                className={`text-sm flex items-center gap-1 ${
                  theme === 'dark' ? 'text-orange-500' : 'text-orange-600'
                } hover:underline`}
              >
                Read more <ChevronDown className="w-4 h-4" />
              </button>
            </>
          ) : (
            <>
              <p className={`text-sm mb-3 ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                The Federal Reserve maintained interest rates at current levels this week, citing controlled inflation and stable employment. Tech stocks surged 3.2% as AI companies reported strong Q4 earnings.
              </p>
              <h4 className="text-base mb-2">Key Takeaways:</h4>
              <ul className={`list-disc list-inside space-y-2 mb-3 text-sm ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                <li><strong>Interest Rates:</strong> Fed holds rates at 4.5-4.75%, signaling confidence in current economic trajectory</li>
                <li><strong>Inflation:</strong> CPI at 2.8%, continuing downward trend toward Fed's 2% target</li>
                <li><strong>Employment:</strong> Unemployment remains stable at 3.7%, labor market showing resilience</li>
                <li><strong>Tech Sector:</strong> Nasdaq up 3.2% on strong AI and cloud computing earnings</li>
                <li><strong>Semiconductor Rally:</strong> Chip stocks leading gains on improved supply chain outlook</li>
              </ul>
              <h4 className="text-base mb-2">Impact on Our Portfolio:</h4>
              <p className={`text-sm mb-3 ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                Our Growth Strategy is well-positioned to capitalize on continued momentum in cloud computing and semiconductor sectors. The stable rate environment benefits our Dividend Strategy holdings. We're maintaining our current allocation with selective additions in AI infrastructure.
              </p>
              <div className="flex flex-wrap gap-2 mb-3">
                <span className={`px-2 py-1 rounded text-xs ${
                  theme === 'dark'
                    ? 'bg-gray-800 text-gray-300'
                    : 'bg-gray-200 text-gray-700'
                }`}>
                  #MacroEconomics
                </span>
                <span className={`px-2 py-1 rounded text-xs ${
                  theme === 'dark'
                    ? 'bg-gray-800 text-gray-300'
                    : 'bg-gray-200 text-gray-700'
                }`}>
                  #FederalReserve
                </span>
                <span className={`px-2 py-1 rounded text-xs ${
                  theme === 'dark'
                    ? 'bg-gray-800 text-gray-300'
                    : 'bg-gray-200 text-gray-700'
                }`}>
                  #TechStocks
                </span>
              </div>
              <button
                onClick={() => toggleExpand('macro1')}
                className={`text-sm flex items-center gap-1 ${
                  theme === 'dark' ? 'text-orange-500' : 'text-orange-600'
                } hover:underline`}
              >
                Show less <ChevronUp className="w-4 h-4" />
              </button>
            </>
          )}
        </div>

        {/* Monthly Newsletter */}
        <div className={`p-4 rounded-lg border ${
          theme === 'dark'
            ? 'bg-gray-900 border-gray-800'
            : 'bg-gray-50 border-gray-200'
        }`}>
          <div className={`text-xs uppercase tracking-wider mb-2 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            Monthly Newsletter • December 2025
          </div>
          <h3 className="text-lg mb-2">Year-End Market Review & 2026 Outlook</h3>
          
          {!expandedItems['newsletter1'] ? (
            <>
              <p className={`text-sm mb-3 ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                As we close 2025, the fund has achieved a 27.3% return, outperforming the S&P 500 by 8.1%...
              </p>
              <button
                onClick={() => toggleExpand('newsletter1')}
                className={`text-sm flex items-center gap-1 ${
                  theme === 'dark' ? 'text-orange-500' : 'text-orange-600'
                } hover:underline`}
              >
                Read more <ChevronDown className="w-4 h-4" />
              </button>
            </>
          ) : (
            <>
              <p className={`text-sm mb-3 ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                As we close 2025, the fund has achieved a 27.3% return, outperforming the S&P 500 by 8.1%. Read our comprehensive year-end analysis and strategic positioning for Q1 2026.
              </p>
              <h4 className="text-base mb-2">2025 Performance Highlights:</h4>
              <ul className={`list-disc list-inside space-y-2 mb-3 text-sm ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                <li>Growth Strategy: +35.6% (best performing)</li>
                <li>Value Strategy: +29.5%</li>
                <li>Dividend Strategy: +17.8%</li>
                <li>Combined Fund Return: +27.3%</li>
                <li>Alpha vs S&P 500: +8.1%</li>
              </ul>
              <h4 className="text-base mb-2">2026 Strategic Focus:</h4>
              <ul className={`list-disc list-inside space-y-2 mb-3 text-sm ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                <li>Continue AI and cloud computing exposure</li>
                <li>Selective expansion in emerging markets</li>
                <li>Maintain risk management through diversification</li>
                <li>Quarterly rebalancing based on market conditions</li>
              </ul>
              <div className="flex items-center gap-3 mb-3">
                <button className={`text-sm ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                } hover:underline`}>
                  View archive
                </button>
              </div>
              <button
                onClick={() => toggleExpand('newsletter1')}
                className={`text-sm flex items-center gap-1 ${
                  theme === 'dark' ? 'text-orange-500' : 'text-orange-600'
                } hover:underline`}
              >
                Show less <ChevronUp className="w-4 h-4" />
              </button>
            </>
          )}
        </div>

        {/* Previous Week Report */}
        <div className={`p-4 rounded-lg border ${
          theme === 'dark'
            ? 'bg-gray-900 border-gray-800'
            : 'bg-gray-50 border-gray-200'
        }`}>
          <div className={`text-xs uppercase tracking-wider mb-2 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            Weekly Macro Report • Dec 10, 2025
          </div>
          <h3 className="text-lg mb-2">Holiday Spending Signals Strong Consumer Sentiment</h3>
          <p className={`text-sm mb-3 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
          }`}>
            Holiday retail sales exceeded expectations, rising 5.2% year-over-year. E-commerce continues to gain market share...
          </p>
          <div className="flex flex-wrap gap-2">
            <span className={`px-2 py-1 rounded text-xs ${
              theme === 'dark'
                ? 'bg-gray-800 text-gray-300'
                : 'bg-gray-200 text-gray-700'
            }`}>
              #RetailSales
            </span>
            <span className={`px-2 py-1 rounded text-xs ${
              theme === 'dark'
                ? 'bg-gray-800 text-gray-300'
                : 'bg-gray-200 text-gray-700'
            }`}>
              #ConsumerSentiment
            </span>
          </div>
        </div>

        {/* ALGO Gators Website Link */}
        <a
          href="https://www.algogators.com/"
          target="_blank"
          rel="noopener noreferrer"
          className={`block p-4 rounded-lg border transition-all ${
            theme === 'dark'
              ? 'bg-gray-900 border-gray-800 hover:border-orange-500 hover:bg-gray-800'
              : 'bg-gray-50 border-gray-200 hover:border-orange-500 hover:bg-white'
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={`p-2 rounded-lg ${
                theme === 'dark' ? 'bg-gray-800' : 'bg-white'
              }`}>
                <svg className="w-5 h-5 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
                </svg>
              </div>
              <div>
                <div className="mb-1">Visit ALGO Gators Official Website</div>
                <div className={`text-sm ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  www.algogators.com
                </div>
              </div>
            </div>
            <ExternalLink className="w-5 h-5 text-orange-500" />
          </div>
        </a>
      </div>
    </div>
  );
}
