import type { Strategy } from '../../domain/portfolio/portfolioData';
import { API_BASE_URL, fetchWithAuth, log } from './httpClient';

export async function testPortfolioConnectivity(): Promise<void> {
  log('info', '=== CONNECTIVITY TEST START ===');
  log('info', `Testing connection to: ${API_BASE_URL}`);

  try {
    log('info', 'Test 1: Attempting health check...');
    const response = await fetch(`${API_BASE_URL}/health`, { method: 'GET' });
    log('info', `Health check response: ${response.status} ${response.statusText}`);
    const data = await response.json();
    log('info', 'Health check data:', data);
  } catch (e) {
    log('error', 'Health check FAILED:', e);
  }

  try {
    log('info', 'Test 2: Testing auth endpoint (should get 401 without token)...');
    const response = await fetch(`${API_BASE_URL}/portfolio/strategies`, { method: 'GET' });
    log('info', `Auth test response: ${response.status} - Expected 401 if no token, 200 if CORS misconfigured`);
  } catch (e) {
    log('error', 'Auth endpoint test FAILED (likely CORS issue):', e);
  }

  try {
    log('info', 'Test 3: Testing authenticated request with session cookie...');
    const response = await fetch(`${API_BASE_URL}/portfolio/strategies`, {
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

export async function getStrategy(strategyId: string): Promise<Strategy> {
  log('info', `getStrategy(${strategyId}) called`);
  const url = `${API_BASE_URL}/portfolio/strategy/${strategyId}`;
  log('info', `Fetching strategy from: ${url}`);

  const response = await fetchWithAuth(url);
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

export async function getStrategySummaries(): Promise<Strategy[]> {
  const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/strategies`);
  const data = await response.json();
  return data.strategies;
}
