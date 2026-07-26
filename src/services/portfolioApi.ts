import { Strategy, PortfolioData, HistoricalDataPoint } from '../data/portfolioData';
import type { RiskCheck } from '../lib/positionEdit';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

export type CreatePositionInput = {
  strategy_id: string;
  symbol: string;
  quantity: number;
  average_price?: number | null;
  reason: string;
  acknowledge_risk?: boolean;
};

export type CreatePositionResult = {
  position: { symbol: string; quantity: number; average_price: number | null };
  override_id: number;
  risk_check: RiskCheck;
};

export type OverrideRecord = {
  id: number;
  user_id: number;
  source_app: string;
  strategy_id: string;
  symbol: string;
  before_state: Record<string, unknown>;
  after_state: Record<string, unknown>;
  reason: string;
  risk_check_result: RiskCheck;
  overrode_risk: boolean;
  created_at: string;
};

/**
 * The backend answered 409 WITH a risk_check: the write is allowed, but only
 * after the user explicitly acknowledges the breach. Distinct from a plain
 * rejection, which carries no risk_check and cannot be overridden at all.
 */
export class RiskBreachError extends Error {
  risk_check: RiskCheck;
  constructor(message: string, risk_check: RiskCheck) {
    super(message);
    this.name = 'RiskBreachError';
    this.risk_check = risk_check;
  }
}

// Environment detection
const isDev = import.meta.env.DEV;
const isProd = import.meta.env.PROD;
const mode = import.meta.env.MODE;

// Verbose logging helper
const log = (level: 'info' | 'error' | 'warn', message: string, data?: unknown) => {
  const timestamp = new Date().toISOString();
  const prefix = `[PortfolioAPI ${timestamp}]`;
  if (data !== undefined) {
    console[level](`${prefix} ${message}`, data);
  } else {
    console[level](`${prefix} ${message}`);
  }
};

// Log API configuration on load
log('info', '=== PortfolioApiService Initialized ===');
log('info', `Environment: isDev=${isDev}, isProd=${isProd}, mode=${mode}`);
log('info', `API_BASE_URL: ${API_BASE_URL}`);
log('info', `VITE_API_URL env: ${import.meta.env.VITE_API_URL || '(not set, using default)'}`);
log('info', `Current origin: ${window.location.origin}`);
log('info', `Protocol: ${window.location.protocol}`);
log('info', `Full URL: ${window.location.href}`);

// Check for common production issues
if (isProd) {
  log('warn', '=== PRODUCTION MODE CHECKS ===');
  if (!import.meta.env.VITE_API_URL) {
    log('error', 'VITE_API_URL is NOT SET in production! Using default localhost which will fail.');
  }
  if (window.location.protocol === 'https:' && API_BASE_URL.startsWith('http://')) {
    log('error', 'MIXED CONTENT WARNING: Page served over HTTPS but API_BASE_URL uses HTTP. Browser will block requests.');
  }
  if (API_BASE_URL.includes('localhost')) {
    log('error', 'API_BASE_URL contains "localhost" in production - this will not work on deployed site.');
  }
}

export class PortfolioApiService {
  // Debug method to test backend connectivity (call from browser console)
  static async testConnectivity(): Promise<void> {
    log('info', '=== CONNECTIVITY TEST START ===');
    log('info', `Testing connection to: ${API_BASE_URL}`);

    // Test 1: Check if we can reach the backend at all (health endpoint)
    try {
      log('info', 'Test 1: Attempting health check...');
      const healthUrl = `${API_BASE_URL}/health`;
      const response = await fetch(healthUrl, { method: 'GET' });
      log('info', `Health check response: ${response.status} ${response.statusText}`);
      const data = await response.json();
      log('info', 'Health check data:', data);
    } catch (e) {
      log('error', 'Health check FAILED:', e);
    }

    // Test 2: Check auth endpoint
    try {
      log('info', 'Test 2: Testing auth endpoint (should get 401 without token)...');
      const authTestUrl = `${API_BASE_URL}/portfolio/strategies`;
      const response = await fetch(authTestUrl, { method: 'GET' });
      log('info', `Auth test response: ${response.status} - Expected 401 if no token, 200 if CORS misconfigured`);
    } catch (e) {
      log('error', 'Auth endpoint test FAILED (likely CORS issue):', e);
    }

    // Test 3: Check with token
    const token = localStorage.getItem('token');
    if (token) {
      try {
        log('info', 'Test 3: Testing with auth token...');
        const authTestUrl = `${API_BASE_URL}/portfolio/strategies`;
        const response = await fetch(authTestUrl, {
          method: 'GET',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        log('info', `Authenticated request response: ${response.status} ${response.statusText}`);
        if (response.ok) {
          const data = await response.json();
          log('info', 'Response data:', data);
        } else {
          const text = await response.text();
          log('error', 'Error response body:', text);
        }
      } catch (e) {
        log('error', 'Authenticated request FAILED:', e);
      }
    } else {
      log('warn', 'Test 3 skipped: No auth token found');
    }

    log('info', '=== CONNECTIVITY TEST COMPLETE ===');
  }

  private static getAuthToken(): string | null {
    const token = localStorage.getItem('token');
    log('info', `Auth token ${token ? 'found' : 'NOT FOUND'} (length: ${token?.length || 0})`);
    return token;
  }

  private static async fetchWithAuth(url: string): Promise<Response> {
    log('info', `fetchWithAuth called for URL: ${url}`);

    const token = this.getAuthToken();

    if (!token) {
      log('error', 'No authentication token found in localStorage');
      throw new Error('No authentication token found');
    }

    log('info', `Making fetch request to: ${url}`);
    log('info', `Request headers: Authorization: Bearer ${token.substring(0, 20)}...`);

    try {
      const startTime = performance.now();
      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      const elapsed = (performance.now() - startTime).toFixed(2);

      log('info', `Response received in ${elapsed}ms`);
      log('info', `Response status: ${response.status} ${response.statusText}`);
      log('info', `Response headers:`, Object.fromEntries(response.headers.entries()));
      log('info', `Content-Type: ${response.headers.get('content-type')}`);

      // Check if we got HTML instead of JSON (common proxy misconfiguration)
      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('text/html')) {
        const htmlBody = await response.clone().text();
        log('error', '=== RECEIVED HTML INSTEAD OF JSON ===');
        log('error', 'This usually means nginx/proxy is NOT forwarding this route to Flask');
        log('error', `URL attempted: ${url}`);
        log('error', `HTML preview: ${htmlBody.substring(0, 200)}...`);
        log('error', '>>> FIX: Update your nginx config to proxy /portfolio/* to Flask backend');
        throw new Error(`Server returned HTML instead of JSON. Your nginx/proxy is not forwarding /portfolio routes to Flask. Check nginx config.`);
      }

      if (!response.ok) {
        // Handle 401 Unauthorized or 422 JWT decode errors (e.g., old tokens with non-string subject)
        if (response.status === 401 || response.status === 422) {
          log('warn', `Token error (${response.status}) - clearing credentials and redirecting to login`);
          localStorage.removeItem('token');
          localStorage.removeItem('user');
          window.location.href = '/login';
          throw new Error('Session expired or invalid. Please log in again.');
        }

        // Try to get error body for more details
        let errorBody = '';
        try {
          errorBody = await response.clone().text();
          log('error', `Error response body: ${errorBody}`);
        } catch (e) {
          log('warn', 'Could not read error response body');
        }
        throw new Error(`API request failed: ${response.status} ${response.statusText}. Body: ${errorBody}`);
      }

      return response;
    } catch (error) {
      log('error', '=== FETCH ERROR DETAILS ===');
      log('error', `Error type: ${error instanceof Error ? error.constructor.name : typeof error}`);
      log('error', `Error message: ${error instanceof Error ? error.message : String(error)}`);

      if (error instanceof TypeError) {
        log('error', 'TypeError detected - analyzing possible causes...');

        // Check for specific error patterns
        const errMsg = error.message.toLowerCase();

        if (errMsg.includes('failed to fetch') || errMsg.includes('networkerror')) {
          log('error', '>>> DIAGNOSIS: Network/CORS error');
          log('error', 'Possible causes:');
          log('error', '  1. Backend server not running or unreachable');
          log('error', '  2. CORS not configured for this origin on backend');
          log('error', '  3. Mixed content (HTTPS page calling HTTP API)');
          log('error', '  4. Firewall/security group blocking the request');
          log('error', '  5. DNS resolution failed for API host');
          log('error', `  Current origin: ${window.location.origin}`);
          log('error', `  API target: ${url}`);

          throw new Error(`Network error: Cannot reach ${API_BASE_URL}. Possible CORS issue or backend not running. Check browser Network tab for details.`);
        }

        if (errMsg.includes('cors')) {
          log('error', '>>> DIAGNOSIS: Explicit CORS error');
          throw new Error(`CORS error: Backend at ${API_BASE_URL} is not allowing requests from ${window.location.origin}`);
        }
      }

      throw error;
    }
  }

  static async getStrategy(strategyId: string): Promise<Strategy> {
    log('info', `getStrategy(${strategyId}) called`);
    const url = `${API_BASE_URL}/portfolio/strategy/${strategyId}`;
    log('info', `Fetching strategy from: ${url}`);

    const response = await this.fetchWithAuth(url);
    const data = await response.json();

    log('info', `Strategy ${strategyId} response:`, {
      id: data.id,
      name: data.name,
      invested: data.invested,
      currentValue: data.currentValue,
      positionsCount: data.positions?.length,
      historicalDataCount: data.historicalData?.length,
    });

    return data;
  }

  static async getAllStrategies(): Promise<Strategy[]> {
    const response = await this.fetchWithAuth(`${API_BASE_URL}/portfolio/strategies`);
    const data = await response.json();
    return data.strategies;
  }

  static async getPortfolioData(): Promise<PortfolioData> {
    log('info', '=== getPortfolioData() START ===');

    // Fetch all strategies
    log('info', `Fetching strategies from: ${API_BASE_URL}/portfolio/strategies`);
    const strategiesResponse = await this.fetchWithAuth(`${API_BASE_URL}/portfolio/strategies`);

    log('info', 'Parsing strategies response JSON...');
    const strategiesData = await strategiesResponse.json();
    log('info', 'Strategies data received:', strategiesData);

    const strategySummaries = strategiesData.strategies;
    log('info', `Found ${strategySummaries?.length || 0} strategy summaries`);

    if (!strategySummaries || strategySummaries.length === 0) {
      log('warn', 'No strategies found in response');
    }

    // Fetch detailed data for each strategy
    log('info', 'Fetching detailed data for each strategy...');
    const strategies: Strategy[] = await Promise.all(
      strategySummaries.map(async (summary: any, index: number) => {
        log('info', `Fetching strategy ${index + 1}/${strategySummaries.length}: ${summary.id}`);
        const strategy = await this.getStrategy(summary.id);
        log('info', `Strategy ${summary.id} fetched successfully`);
        return strategy;
      })
    );
    log('info', `All ${strategies.length} strategies fetched`);

    // Calculate portfolio totals
    log('info', 'Calculating portfolio totals...');
    const totalInvested = strategies.reduce((sum, s) => sum + s.invested, 0);
    const totalValue = strategies.reduce((sum, s) => sum + s.currentValue, 0);
    const totalReturn = totalValue - totalInvested;
    const totalReturnPercent = totalInvested > 0 ? (totalReturn / totalInvested) * 100 : 0;

    // Aggregate historical data
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

  static async createPosition(input: CreatePositionInput): Promise<CreatePositionResult> {
    const token = this.getAuthToken();
    if (!token) throw new Error('No authentication token found');

    const response = await fetch(`${API_BASE_URL}/portfolio/positions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(input),
    });

    const payload = await response.json().catch(() => ({}));

    if (response.status === 409 && payload.risk_check) {
      // Overridable. The caller must surface the breaches and require a second,
      // deliberate submit with acknowledge_risk. Never retry here.
      throw new RiskBreachError(
        payload.error ?? 'This position breaches a risk limit',
        payload.risk_check,
      );
    }

    if (!response.ok) {
      throw new Error(payload.error ?? `Request failed (${response.status})`);
    }

    return payload as CreatePositionResult;
  }

  static async getOverrides(strategyId: string): Promise<OverrideRecord[]> {
    const url = `${API_BASE_URL}/portfolio/overrides/${strategyId}`;
    const response = await this.fetchWithAuth(url);
    const payload = await response.json();
    return payload.overrides ?? [];
  }
}
