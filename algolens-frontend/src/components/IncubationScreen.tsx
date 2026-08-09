import React, { useEffect, useState } from 'react';
import type {
  IncubatingStrategy,
  IncubationPerformance,
} from '../domain/portfolio/incubationData';
import { PortfolioApplicationService } from '../application/portfolio/portfolioService';
import { useTheme } from '../adapters/react/ThemeContext';
import { IncubationDetail } from './IncubationDetail';
import { IncubationList } from './IncubationList';
import { IncubationOverview } from './IncubationOverview';

export function IncubationScreen() {
  const { theme } = useTheme();
  const [strategies, setStrategies] = useState<IncubatingStrategy[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(null);
  const [performance, setPerformance] = useState<IncubationPerformance | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStrategies = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const data = await PortfolioApplicationService.getIncubationStrategies();
        setStrategies(data);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : String(err);
        setError(`Failed to load incubation data: ${errorMessage}`);
      } finally {
        setIsLoading(false);
      }
    };

    fetchStrategies();
  }, []);

  useEffect(() => {
    if (!selectedStrategyId) {
      setPerformance(null);
      setDetailError(null);
      return;
    }

    const fetchPerformance = async () => {
      try {
        setIsDetailLoading(true);
        setDetailError(null);
        const data =
          await PortfolioApplicationService.getIncubationPerformance(
            selectedStrategyId
          );
        setPerformance(data);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : String(err);
        setDetailError(`Failed to load incubation performance: ${errorMessage}`);
      } finally {
        setIsDetailLoading(false);
      }
    };

    fetchPerformance();
  }, [selectedStrategyId]);

  const selectedStrategy = strategies.find(
    strategy => strategy.id === selectedStrategyId
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
          <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}>
            Loading incubation data...
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center max-w-lg">
          <div className="mb-4 p-4 bg-red-100 dark:bg-red-900/30 rounded-lg">
            <p className="text-red-600 dark:text-red-400 text-sm font-mono break-words text-left max-h-40 overflow-auto">
              {error}
            </p>
          </div>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (selectedStrategy) {
    return (
      <IncubationDetail
        strategy={selectedStrategy}
        performance={performance}
        isLoading={isDetailLoading}
        error={detailError}
        onBack={() => setSelectedStrategyId(null)}
      />
    );
  }

  return (
    <>
      <IncubationOverview strategies={strategies} />
      <IncubationList
        strategies={strategies}
        onSelectStrategy={setSelectedStrategyId}
      />
    </>
  );
}
