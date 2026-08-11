import { useState, useMemo } from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import type { Strategy } from '@/models';
import { computeCombinedMetrics } from '@/lib/computeCombinedMetrics';
import { StrategySelection } from './strategy-builder/StrategySelection';
import { PerformanceOverview } from './strategy-builder/PerformanceOverview';
import { PerformanceCharts } from './strategy-builder/PerformanceCharts';
import { AllocationCharts } from './strategy-builder/AllocationCharts';
import { HoldingsConcentration } from './strategy-builder/HoldingsConcentration';
import { AdvancedSections, type ExpandedSections, type SectionKey } from './strategy-builder/AdvancedSections';
import { StrategySummary } from './strategy-builder/StrategySummary';
import { HoldingsModal } from './strategy-builder/HoldingsModal';

interface StrategyBuilderProps {
  strategies: Strategy[];
  onClose: () => void;
}

export function StrategyBuilder({ strategies, onClose }: StrategyBuilderProps) {
  const { theme } = useTheme();
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(strategies.map(s => s.id));
  const [showHoldingsModal, setShowHoldingsModal] = useState(false);
  const [expandedSections, setExpandedSections] = useState<ExpandedSections>({
    diversification: false,
    trading: false,
    leverage: false
  });

  const toggleSection = (section: SectionKey) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const toggleStrategy = (id: string) => {
    setSelectedStrategies(prev => {
      // Prevent deselecting if it's the last selected strategy
      if (prev.includes(id) && prev.length === 1) {
        return prev;
      }
      return prev.includes(id)
        ? prev.filter(s => s !== id)
        : [...prev, id];
    });
  };

  // Derive the combined view model from the selected strategies' real data.
  const combinedMetrics = useMemo(
    () => computeCombinedMetrics(strategies, selectedStrategies),
    [selectedStrategies, strategies]
  );

  return (
    <div className={`min-h-screen ${theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
      }`}>
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-4">
        <StrategySelection
          strategies={strategies}
          selectedStrategies={selectedStrategies}
          onToggle={toggleStrategy}
          theme={theme}
        />

        <PerformanceOverview metrics={combinedMetrics} theme={theme} />

        <PerformanceCharts metrics={combinedMetrics} theme={theme} />

        <AllocationCharts metrics={combinedMetrics} theme={theme} />

        <HoldingsConcentration
          metrics={combinedMetrics}
          theme={theme}
          onShowAll={() => setShowHoldingsModal(true)}
        />

        <AdvancedSections
          metrics={combinedMetrics}
          theme={theme}
          expanded={expandedSections}
          onToggle={toggleSection}
        />

        <StrategySummary metrics={combinedMetrics} theme={theme} />

        {showHoldingsModal && (
          <HoldingsModal
            metrics={combinedMetrics}
            theme={theme}
            onClose={() => setShowHoldingsModal(false)}
          />
        )}
      </div>
    </div>
  );
}
