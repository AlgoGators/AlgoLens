import type { HistoricalDataPoint, PortfolioData, Strategy } from '../../domain/portfolio/portfolioData';
import {
  API_BASE_URL,
  fetchWithAuth,
  log,
} from '../../infrastructure/api/httpClient';
import {
  getStrategy,
  getStrategySummaries,
  testPortfolioConnectivity,
} from '../../infrastructure/api/portfolioApi';

export class PortfolioApplicationService {
  static async testConnectivity(): Promise<void> {
    return testPortfolioConnectivity();
  }

  static async getStrategy(strategyId: string): Promise<Strategy> {
    return getStrategy(strategyId);
  }

  static async getAllStrategies(): Promise<Strategy[]> {
    return getStrategySummaries();
  }

  static async getPortfolioData(): Promise<PortfolioData> {
    log('info', '=== getPortfolioData() START ===');
    log('info', `Fetching strategies from: ${API_BASE_URL}/portfolio/strategies`);

    const strategiesResponse = await fetchWithAuth(`${API_BASE_URL}/portfolio/strategies`);
    log('info', 'Parsing strategies response JSON...');
    const strategiesData = await strategiesResponse.json();
    log('info', 'Strategies data received:', strategiesData);

    const strategySummaries = strategiesData.strategies;
    log('info', `Found ${strategySummaries?.length || 0} strategy summaries`);

    if (!strategySummaries || strategySummaries.length === 0) {
      log('warn', 'No strategies found in response');
    }

    log('info', 'Fetching detailed data for each strategy...');
    const strategies: Strategy[] = await Promise.all(
      strategySummaries.map(async (summary: any, index: number) => {
        log('info', `Fetching strategy ${index + 1}/${strategySummaries.length}: ${summary.id}`);
        const strategy = await getStrategy(summary.id);
        log('info', `Strategy ${summary.id} fetched successfully`);
        return strategy;
      })
    );
    log('info', `All ${strategies.length} strategies fetched`);

    log('info', 'Calculating portfolio totals...');
    const totalInvested = strategies.reduce((sum, s) => sum + s.invested, 0);
    const totalValue = strategies.reduce((sum, s) => sum + s.currentValue, 0);
    const totalReturn = totalValue - totalInvested;
    const totalReturnPercent = totalInvested > 0 ? (totalReturn / totalInvested) * 100 : 0;

    log('info', 'Aggregating historical data...');
    const historicalData = this.aggregateHistoricalData(strategies);

    const result = {
      totalValue,
      totalInvested,
      totalReturn,
      totalReturnPercent,
      strategies,
      historicalData,
    };

    log('info', '=== getPortfolioData() SUCCESS ===', {
      totalValue,
      totalInvested,
      totalReturn,
      totalReturnPercent,
      strategiesCount: strategies.length,
      historicalDataPoints: historicalData.length,
    });

    return result;
  }

  private static aggregateHistoricalData(strategies: Strategy[]): HistoricalDataPoint[] {
    if (strategies.length === 0) return [];

    const dateMap = new Map<string, number>();
    strategies.forEach(strategy => {
      strategy.historicalData.forEach(point => {
        const currentValue = dateMap.get(point.date) || 0;
        dateMap.set(point.date, currentValue + point.value);
      });
    });

    return Array.from(dateMap.entries())
      .map(([date, value]) => ({ date, value }))
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
  }
}
