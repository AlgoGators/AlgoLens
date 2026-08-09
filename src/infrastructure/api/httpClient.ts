export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

const isDev = import.meta.env.DEV;
const isProd = import.meta.env.PROD;
const mode = import.meta.env.MODE;
const devAuthEnabled = import.meta.env.VITE_DEV_MODE === '1';

export const log = (level: 'info' | 'error' | 'warn', message: string, data?: unknown) => {
  const timestamp = new Date().toISOString();
  const prefix = `[PortfolioAPI ${timestamp}]`;
  if (data !== undefined) {
    console[level](`${prefix} ${message}`, data);
  } else {
    console[level](`${prefix} ${message}`);
  }
};

log('info', '=== Portfolio API transport initialized ===');
log('info', `Environment: isDev=${isDev}, isProd=${isProd}, mode=${mode}`);
log('info', `API_BASE_URL: ${API_BASE_URL}`);
log('info', `VITE_API_URL env: ${import.meta.env.VITE_API_URL || '(not set, using default)'}`);
log('info', `Current origin: ${window.location.origin}`);
log('info', `Protocol: ${window.location.protocol}`);
log('info', `Full URL: ${window.location.href}`);

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

async function requestDevSession(): Promise<boolean> {
  const response = await fetch(`${API_BASE_URL}/auth/dev-login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    log('warn', `dev-login unavailable during authenticated retry (status ${response.status})`);
    return false;
  }

  log('info', 'Dev session established during authenticated retry');
  return true;
}

export async function fetchWithAuth(url: string, hasRetriedDevLogin = false): Promise<Response> {
  log('info', `fetchWithAuth called for URL: ${url}`);
  log('info', `Making credentialed fetch request to: ${url}`);

  try {
    const startTime = performance.now();
    const response = await fetch(url, {
      credentials: 'include',
    });
    const elapsed = (performance.now() - startTime).toFixed(2);

    log('info', `Response received in ${elapsed}ms`);
    log('info', `Response status: ${response.status} ${response.statusText}`);
    log('info', 'Response headers:', Object.fromEntries(response.headers.entries()));
    log('info', `Content-Type: ${response.headers.get('content-type')}`);

    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('text/html')) {
      const htmlBody = await response.clone().text();
      log('error', '=== RECEIVED HTML INSTEAD OF JSON ===');
      log('error', 'This usually means nginx/proxy is NOT forwarding this route to Flask');
      log('error', `URL attempted: ${url}`);
      log('error', `HTML preview: ${htmlBody.substring(0, 200)}...`);
      log('error', '>>> FIX: Update your nginx config to proxy /portfolio/* to Flask backend');
      throw new Error('Server returned HTML instead of JSON. Your nginx/proxy is not forwarding /portfolio routes to Flask. Check nginx config.');
    }

    if (!response.ok) {
      if (response.status === 401 || response.status === 422) {
        if (devAuthEnabled && !hasRetriedDevLogin) {
          log('warn', `Session error (${response.status}) - requesting dev session and retrying`);
          const devSessionReady = await requestDevSession();
          if (devSessionReady) {
            return fetchWithAuth(url, true);
          }
        }

        if (devAuthEnabled) {
          throw new Error('Dev session is unavailable. Check that the backend is running with DEV_MODE=1 and open the app on http://localhost:5173.');
        }

        log('warn', `Session error (${response.status}) - redirecting to login`);
        window.location.href = '/login';
        throw new Error('Session expired or invalid. Please log in again.');
      }

      let errorBody = '';
      try {
        errorBody = await response.clone().text();
        log('error', `Error response body: ${errorBody}`);
      } catch {
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
