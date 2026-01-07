import { Strategy, PortfolioData, HistoricalDataPoint } from '../data/portfolioData';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

export class PortfolioApiService {
  private static getAuthToken(): string | null {
    return localStorage.getItem('token');
  }

  private static async fetchWithAuth(url: string): Promise<Response> {
    const token = this.getAuthToken();

    if (!token) {
      throw new Error('No authentication token found');
    }

    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`API request failed: ${response.status}`);
    }

    return response;
  }

  static async getStrategy(strategyId: string): Promise<Strategy> {
    const response = await this.fetchWithAuth(`${API_BASE_URL}/portfolio/strategy/${strategyId}`);
    const data = await response.json();
    return data;
  }

  static async getAllStrategies(): Promise<Strategy[]> {
    const response = await this.fetchWithAuth(`${API_BASE_URL}/portfolio/strategies`);
    const data = await response.json();
    return data.strategies;
  }

  static async getPortfolioData(): Promise<PortfolioData> {
    // Fetch all strategies
    const strategiesResponse = await this.fetchWithAuth(`${API_BASE_URL}/portfolio/strategies`);
    const strategiesData = await strategiesResponse.json();
    const strategySummaries = strategiesData.strategies;

    // Fetch detailed data for each strategy
    const strategies: Strategy[] = await Promise.all(
      strategySummaries.map(async (summary: any) => {
        const strategy = await this.getStrategy(summary.id);
        return strategy;
      })
    );

    // Calculate portfolio totals
    const totalInvested = strategies.reduce((sum, s) => sum + s.invested, 0);
    const totalValue = strategies.reduce((sum, s) => sum + s.currentValue, 0);
    const totalReturn = totalValue - totalInvested;
    const totalReturnPercent = totalInvested > 0 ? (totalReturn / totalInvested) * 100 : 0;

    // Aggregate historical data
    const historicalData = this.aggregateHistoricalData(strategies);

    return {
      totalValue,
      totalInvested,
      totalReturn,
      totalReturnPercent,
      strategies,
      historicalData,
    };
  }

  private static aggregateHistoricalData(strategies: Strategy[]): HistoricalDataPoint[] {
    if (strategies.length === 0) return [];

    // Create a map of dates to total values
    const dateMap = new Map<string, number>();

    // For each strategy, add its historical values to the corresponding dates
    strategies.forEach(strategy => {
      strategy.historicalData.forEach(point => {
        const currentValue = dateMap.get(point.date) || 0;
        dateMap.set(point.date, currentValue + point.value);
      });
    });

    // Convert map to array and sort by date
    const aggregated: HistoricalDataPoint[] = Array.from(dateMap.entries())
      .map(([date, value]) => ({ date, value }))
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());

    return aggregated;
  }
}
