import type { Strategy, PortfolioData, HistoricalDataPoint } from '../../domain/portfolio/portfolioData';
import { API_BASE_URL, log } from './httpClient';

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

    // Test 3: Check the authenticated request using the session cookie
    try {
      log('info', 'Test 3: Testing authenticated request with session cookie...');
      const authTestUrl = `${API_BASE_URL}/portfolio/strategies`;
      const response = await fetch(authTestUrl, {
        method: 'GET',
        credentials: 'include',
      });
      log('info', `Authenticated request response: ${response.status} ${response.statusText} (200 if logged in, 401 if not)`);
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

    log('info', '=== CONNECTIVITY TEST COMPLETE ===');
  }

  private static async fetchWithAuth(url: string): Promise<Response> {
    log('info', `fetchWithAuth called for URL: ${url}`);

    // Auth now travels in an httpOnly cookie, sent automatically by the browser
    // when `credentials: 'include'` is set. There is no token for JS to read or
    // attach; a missing/expired cookie simply comes back as 401 (handled below).
    log('info', `Making credentialed fetch request to: ${url}`);

    try {
      const startTime = performance.now();
      const response = await fetch(url, {
        credentials: 'include',
        headers: {
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
        // Handle 401 Unauthorized or 422 JWT decode errors (e.g., expired/invalid cookie)
        if (response.status === 401 || response.status === 422) {
          log('warn', `Session error (${response.status}) - redirecting to login`);
          // The cookie is httpOnly, so there is nothing for JS to clear; a full
          // navigation re-runs AuthContext's /verify check, which will find no
          // session and render the login view.
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
}
