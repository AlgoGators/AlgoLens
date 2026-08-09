import type { PortfolioData, Strategy } from '../../domain/portfolio/portfolioData';
import type { IncubatingStrategy, IncubationPerformance } from '../../domain/portfolio/incubationData';
import { PortfolioApiService } from '../../infrastructure/api/portfolioApi';

export class PortfolioApplicationService {
  static async testConnectivity(): Promise<void> {
    return PortfolioApiService.testConnectivity();
  }

  static async getStrategy(strategyId: string): Promise<Strategy> {
    return PortfolioApiService.getStrategy(strategyId);
  }

  static async getAllStrategies(): Promise<Strategy[]> {
    return PortfolioApiService.getAllStrategies();
  }

  static async getPortfolioData(): Promise<PortfolioData> {
    return PortfolioApiService.getPortfolioData();
  }

  static async getIncubationStrategies(): Promise<IncubatingStrategy[]> {
    return PortfolioApiService.getIncubationStrategies();
  }

  static async getIncubationPerformance(strategyId: string): Promise<IncubationPerformance> {
    return PortfolioApiService.getIncubationPerformance(strategyId);
  }
}
