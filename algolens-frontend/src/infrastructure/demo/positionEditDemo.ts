import fixtures from '../../../../contracts/qt-workflow-v1.json';
import configurationFixture from '../api/__fixtures__/configurationInspectionHttp.json';

import type { PositionStream, Strategy } from '../../domain/portfolio/portfolioData';

const BOOK = 'synthetic-book-A';
const STRATEGY_ID = 'component-1';
const DEMO_DECISION_KEY = 'algolens.demo.position-edit.decision.v1';

const demoUser = {
  // Production account IDs are decimal strings. Keeping the demo actor in
  // that shape exercises the same recovery and idempotency guards as real UI.
  id: '9000001',
  email: 'demo.reviewer@localhost',
  first_name: 'Demo',
  last_name: 'Reviewer',
  role: 'admin',
};

const curve = [
  500000, 501250, 499800, 503100, 505600, 504900, 508200, 510400,
  509500, 513800, 516100, 515300, 519900, 521400, 520700, 524800,
  527300, 526500, 530200, 532100, 531400, 534820,
].map((value, index) => ({
  date: new Date(Date.UTC(2026, 7, 27 + index)).toISOString().slice(0, 10),
  value,
}));

function demoStrategy(stream: PositionStream): Strategy {
  const quantity = stream === 'qt' ? 5 : 4;
  return {
    id: STRATEGY_ID,
    name: 'Synthetic Alpha',
    description: 'LOCAL VISUAL DEMO — mock data only; no connected database writes.',
    dataAvailable: true,
    resultSource: 'system',
    resultDate: '2026-09-25',
    invested: 500000,
    currentValue: 534820,
    return: 34820,
    returnPercent: 6.964,
    positions: [{
      symbol: 'SYN',
      strategyName: 'synthetic-alpha',
      positionDate: '2026-09-25',
      name: 'Synthetic equity basket',
      shares: quantity,
      quantity,
      quantity_exact: String(quantity),
      costBasis: 100,
      average_price_exact: '100',
      marketPrice: 104.6,
      currentValue: quantity * 104.6,
      notional: quantity * 104.6,
      percentOfTotal: 100,
      contractMultiplier: 1,
    }],
    positionStream: stream,
    positionStrategyNames: ['synthetic-alpha'],
    positionDate: '2026-09-25',
    positionsEditable: stream === 'qt',
    positionEditUnavailableReason: stream === 'qt'
      ? null
      : 'Select the QT stream before changing a position.',
    historicalData: curve,
    equityByStream: {
      qt: curve,
      system: curve.map((point, index) => ({ ...point, value: point.value + index * 135 })),
      benchmark: curve.map((point, index) => ({ ...point, value: point.value - index * 90 })),
    },
    bestDay: 0.84,
    worstDay: -0.62,
    metrics: {
      volatility: 11.8,
      sharpeRatio: 1.24,
      sortinoRatio: 1.71,
      downsideDeviation: 7.3,
      maxDrawdown: 3.9,
      winRate: 58.4,
      executionsToday: 2,
      avgWin: 0.47,
      avgLoss: 0.31,
      profitFactor: 1.62,
      dailyReturn: 0.64,
      cumulativeReturn: 6.964,
      annualizedReturn: 14.6,
      grossLeverage: 1.42,
      netLeverage: 0.74,
      portfolioLeverage: 1.42,
      marginPosted: 62400,
      equityToMarginRatio: 8.57,
      marginCushion: 0.83,
      totalNotional: 759444,
      unrealizedPnL: 2300,
      realizedPnL: 910,
      totalCommissions: 42.5,
      netPnL: 3167.5,
      cashAvailable: 472420,
      currentPortfolioValue: 534820,
      totalReturn: 34820,
    },
    executions: [{
      symbol: 'SYN', side: 'BUY', quantity: 1, price: 103.8,
      notional: 103.8, commission: 1.25, date: '2026-09-25',
    }],
    executionsAvailable: true,
    executionDate: '2026-09-25',
    finalizedPositions: [],
    activityStream: 'qt',
    finalizedPositionsAvailable: true,
    managers: ['Demo Reviewer'],
    lastUpdate: 'Local visual demo snapshot',
    portfolio_id: BOOK,
    books: [BOOK],
  };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function demoConfigurationInspection() {
  const inspection = structuredClone(configurationFixture);
  inspection.scope.registry_id = STRATEGY_ID;
  inspection.scope.portfolio_id = BOOK;
  inspection.read_at = new Date().toISOString();
  inspection.publication.identity.registry_id = STRATEGY_ID;
  inspection.publication.identity.portfolio_id = BOOK;
  inspection.publication.identity.engine_strategy_id = 'LIVE_SYNTHETIC_TREND';
  inspection.publication.identity.run_date = '2026-09-25';
  inspection.publication.identity.producer_version = 'local-position-edit-demo';
  inspection.publication.captured_at = '2026-09-25T20:01:12.120000Z';
  inspection.publication.publication_recorded_at = '2026-09-25T20:01:15.440000Z';
  return inspection;
}

function rememberDemoDecision(): void {
  window.sessionStorage.setItem(DEMO_DECISION_KEY, fixtures.decision_processed.decision_id);
}

function demoBookDecision() {
  const confirmed = window.sessionStorage.getItem(DEMO_DECISION_KEY) === fixtures.decision_processed.decision_id;
  return {
    schema_version: 'qt-workflow/v1',
    book_id: BOOK,
    source_day: '2026-09-25',
    decision: confirmed ? fixtures.decision_processed : null,
    preview: confirmed ? fixtures.preview_clean : null,
  };
}

function requestUrl(input: RequestInfo | URL): URL {
  const raw = input instanceof Request ? input.url : String(input);
  return new URL(raw, window.location.origin);
}

function methodOf(input: RequestInfo | URL, init?: RequestInit): string {
  return (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
}

/** Opt-in demo data is deliberately impossible to activate away from loopback. */
export function positionEditDemoEnabled(location: Location = window.location): boolean {
  return (location.hostname === 'localhost' || location.hostname === '127.0.0.1' || location.hostname === '::1')
    && new URLSearchParams(location.search).get('demo') === 'position-edit';
}

/**
 * Return one production-contract-shaped demo response, or null so the real
 * transport remains authoritative. The demo is read from the repository's QT
 * contract vectors and never contacts or mutates the configured API.
 */
export function positionEditDemoResponse(
  input: RequestInfo | URL,
  init?: RequestInit,
): Response | null {
  if (!positionEditDemoEnabled()) return null;

  const url = requestUrl(input);
  const method = methodOf(input, init);
  const path = url.pathname;

  if (method === 'GET' && path === '/auth/verify') {
    return response({ user: demoUser });
  }
  if (method === 'POST' && path === '/auth/logout') return response({});

  if (method === 'GET' && path === '/portfolio/strategies') {
    return response({ strategies: [{
      id: STRATEGY_ID,
      name: 'Synthetic Alpha',
      description: 'Local position-edit visual demo',
      portfolio_id: BOOK,
      books: [BOOK],
    }] });
  }

  if (method === 'GET' && path === `/portfolio/strategy/${STRATEGY_ID}`) {
    const stream = url.searchParams.get('position_stream') === 'system' ? 'system' : 'qt';
    return response(demoStrategy(stream));
  }

  if (method === 'GET' && path === '/portfolio/portfolios') {
    return response({ portfolios: [{
      portfolio_id: BOOK,
      total_value: 534820,
      strategy_count: 1,
      strategies_awaiting_data: 0,
      strategies: [{
        id: STRATEGY_ID,
        name: 'Synthetic Alpha',
        strategy_type: 'LOCAL_QT_EDIT_DEMO',
        lifecycle: 'live',
        current_value: 534820,
        is_primary: true,
      }],
    }] });
  }

  if (method === 'GET' && path === '/portfolio/correlations') {
    return response({ symbols: ['SYN'], matrix: [[1]], observations: 21, symbolsWithoutPrices: [] });
  }

  if (method === 'GET' && path === `/portfolio/overrides/${STRATEGY_ID}`) {
    return response({ overrides: [] });
  }

  if (method === 'GET' && path === `/portfolio/strategies/${STRATEGY_ID}/configuration`) {
    return response(demoConfigurationInspection());
  }

  if (method === 'GET' && path === `/portfolio/qt-books/${BOOK}/proposal`) {
    return response(fixtures.proposal_ready);
  }
  if (method === 'GET' && path === `/portfolio/qt-books/${BOOK}/draft`) {
    return response(fixtures.draft_saved);
  }
  if (method === 'GET' && path === `/portfolio/qt-books/${BOOK}/decision`) {
    return response(demoBookDecision());
  }
  if (method === 'PUT' && path === `/portfolio/qt-books/${BOOK}/draft`) {
    return response(fixtures.draft_saved);
  }
  if (method === 'POST' && path === '/portfolio/qt-previews') {
    return response(fixtures.preview_clean);
  }
  if (method === 'POST' && path === `/portfolio/qt-previews/${fixtures.preview_clean.preview_id}/confirm`) {
    rememberDemoDecision();
    return response(fixtures.decision_processed);
  }
  if (method === 'GET' && path === `/portfolio/qt-decisions/${fixtures.decision_processed.decision_id}`) {
    return response(fixtures.decision_processed);
  }

  return response({
    error: 'This local visual demo does not provide that endpoint.',
    path,
  }, 404);
}
