export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

// Environment detection
const isDev = import.meta.env.DEV;
const isProd = import.meta.env.PROD;
const mode = import.meta.env.MODE;

// Verbose logging helper
export const log = (level: 'info' | 'error' | 'warn', message: string, data?: unknown) => {
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

export async function fetchWithAuth(url: string): Promise<Response> {
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
