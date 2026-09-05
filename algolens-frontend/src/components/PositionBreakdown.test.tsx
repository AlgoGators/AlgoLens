// @vitest-environment jsdom
//
// The first component test in this repository, and it is this component on
// purpose: every honest-null decision in the audit lands on screen here.
//
// The pure functions behind it were already covered. What was not covered is
// whether the component actually renders their answers -- a formatter can
// return an em dash and the component can still print "$0.00" beside it,
// because the two are joined by JSX that no test had ever run.
//
// Three faults this file would have caught, all of which shipped and were found
// by looking at the screen instead:
//
//   - "% of Total" divided by portfolio VALUE under a header whose column sums
//     to 100%, printing 588% for a single position.
//   - An unknown market price rendered as $0.00, which states that a position
//     is worthless rather than that its price is unknown.
//   - The total silently including rows it could not price, so the footer
//     disagreed with the rows above it and nothing said why.

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PositionBreakdown } from './PositionBreakdown';
import type { Position } from '../domain/portfolio/portfolioData';

// The component reads theme and identity from context. Neither is what these
// tests are about, and a real provider would drag the whole app in.
vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light' }),
}));

let role = 'subscriber';
vi.mock('../adapters/react/useAuth', () => ({
  useAuth: () => ({ user: { role } }),
}));

function position(over: Partial<Position> = {}): Position {
  return {
    symbol: 'ES.v.0',
    name: 'ES',
    shares: 12,
    quantity: 12,
    marketPrice: 5310.75,
    notional: 3186450,
    costBasis: 5280.25,
    currentValue: 3186450,
    ...over,
  } as Position;
}

/** The row for a symbol, as an array of its cell texts. */
function cells(symbol: string): string[] {
  const label = screen.getByText(symbol);
  const row = label.closest('div.grid') as HTMLElement;
  return Array.from(row.children).map(c => (c.textContent ?? '').trim());
}

describe('an unknown figure is never rendered as a number', () => {
  it('shows an em dash for a price the pipeline does not have', () => {
    render(
      <PositionBreakdown
        positions={[position({ marketPrice: null, notional: null })]}
      />,
    );
    // $0.00 in the price or notional cell would say the position is worthless.
    // The row says nothing instead. (The FOOTER total is legitimately $0.00
    // here -- nothing could be priced -- and the banner beside it says so.)
    const row = cells('ES.v.0');
    expect(row.filter(c => c === '—')).toHaveLength(3);
    expect(row).not.toContain('$0.00');
  });

  it('shows an em dash for the share of book when the exposure is unknown', () => {
    render(
      <PositionBreakdown
        positions={[
          position(),
          position({ symbol: 'ZN.v.0', name: 'ZN', marketPrice: null, notional: null }),
        ]}
      />,
    );
    const unpriced = cells('ZN.v.0');
    expect(unpriced.filter(c => c === '—')).toHaveLength(3);
  });
});

describe('the percentage column sums to the header it sits under', () => {
  it('divides by total exposure, not by portfolio value', () => {
    // Three positions, 50/30/20 of the book. If this divided by anything else
    // the column would not total 100, which is what the footer claims.
    render(
      <PositionBreakdown
        positions={[
          position({ symbol: 'AA.v.0', name: 'Alpha', notional: 500_000 }),
          position({ symbol: 'BB.v.0', name: 'Bravo', notional: 300_000 }),
          position({ symbol: 'CC.v.0', name: 'Charlie', notional: 200_000 }),
        ]}
      />,
    );
    expect(cells('AA.v.0')).toContain('50.00%');
    expect(cells('BB.v.0')).toContain('30.00%');
    expect(cells('CC.v.0')).toContain('20.00%');
  });

  it('leaves an unpriced row out of the denominator rather than treating it as zero', () => {
    // Two priced rows at 600k and 400k, plus one that could not be priced. The
    // priced pair must read 60/40 -- not 60/40-of-something-larger, and not a
    // pair that fails to reach 100 because a zero was averaged in.
    render(
      <PositionBreakdown
        positions={[
          position({ symbol: 'AA.v.0', name: 'Alpha', notional: 600_000 }),
          position({ symbol: 'BB.v.0', name: 'Bravo', notional: 400_000 }),
          position({ symbol: 'CC.v.0', name: 'Charlie', marketPrice: null, notional: null }),
        ]}
      />,
    );
    expect(cells('AA.v.0')).toContain('60.00%');
    expect(cells('BB.v.0')).toContain('40.00%');
  });
});

describe('the footer says what it excluded', () => {
  it('totals only the rows it could price', () => {
    render(
      <PositionBreakdown
        positions={[
          position({ symbol: 'AA.v.0', name: 'Alpha', notional: 600_000 }),
          position({ symbol: 'BB.v.0', name: 'Bravo', marketPrice: null, notional: null }),
        ]}
      />,
    );
    // Scoped to the footer, because the single priced ROW also reads
    // $600,000.00 -- and the two agreeing is the whole point: a total that
    // silently included the unpriced row would not match any row above it.
    const total = screen.getByText('Total Notional').parentElement as HTMLElement;
    expect(total.textContent).toContain('$600,000.00');
  });

  it('names the count it left out, rather than quietly dropping it', () => {
    render(
      <PositionBreakdown
        positions={[
          position({ symbol: 'AA.v.0', name: 'Alpha', notional: 600_000 }),
          position({ symbol: 'BB.v.0', name: 'Bravo', marketPrice: null, notional: null }),
        ]}
      />,
    );
    expect(
      screen.getByText(/Total excludes 1 position with no known price/),
    ).toBeTruthy();
  });

  it('says nothing when every row could be priced', () => {
    render(<PositionBreakdown positions={[position()]} />);
    expect(screen.queryByText(/Total excludes/)).toBeNull();
  });

  it('counts every position, including the ones it could not price', () => {
    render(
      <PositionBreakdown
        positions={[
          position({ symbol: 'AA.v.0', name: 'Alpha' }),
          position({ symbol: 'BB.v.0', name: 'Bravo', marketPrice: null, notional: null }),
        ]}
      />,
    );
    // The count is of positions held, not of positions priced.
    expect(screen.getByText('Active Positions: 2')).toBeTruthy();
  });
});

describe('the edit controls are offered only where a write would succeed', () => {
  it('offers nothing to a subscriber', () => {
    role = 'subscriber';
    render(<PositionBreakdown positions={[position()]} strategyId="trendfollowing" />);
    expect(screen.queryByLabelText(/^Adjust /)).toBeNull();
  });

  it('offers nothing without a strategy, whatever the role', () => {
    // The subscriber-facing views pass no strategyId at all.
    role = 'admin';
    render(<PositionBreakdown positions={[position()]} />);
    expect(screen.queryByLabelText(/^Adjust /)).toBeNull();
  });

  it('offers an adjust control per row to an internal role', () => {
    role = 'admin';
    render(
      <PositionBreakdown
        positions={[position({ symbol: 'AA.v.0', name: 'Alpha' }), position({ symbol: 'BB.v.0', name: 'Bravo' })]}
        strategyId="trendfollowing"
        portfolioId="CONSERVATIVE_PORTFOLIO"
      />,
    );
    expect(screen.getByLabelText('Adjust AA.v.0')).toBeTruthy();
    expect(screen.getByLabelText('Adjust BB.v.0')).toBeTruthy();
  });
});

describe('the table says which book it is showing', () => {
  it('names the portfolio beside the heading', () => {
    role = 'subscriber';
    render(
      <PositionBreakdown
        positions={[position()]}
        portfolioId="CONSERVATIVE_PORTFOLIO"
      />,
    );
    const heading = document.querySelector('h3') as HTMLElement;
    expect(heading.textContent).toContain("Today's Positions");
    expect(within(heading).getByText('CONSERVATIVE_PORTFOLIO')).toBeTruthy();
  });
});
