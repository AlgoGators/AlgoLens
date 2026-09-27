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

import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PositionBreakdown } from './PositionBreakdown';
import type { Position } from '../domain/portfolio/portfolioData';

// The component reads theme and identity from context. Neither is what these
// tests are about, and a real provider would drag the whole app in.
vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light' }),
}));

let role = 'subscriber';
let userId = 'internal-one';
vi.mock('../adapters/react/useAuth', () => ({
  useAuth: () => ({ user: { id: userId, role } }),
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
      screen.getByText(/Total excludes 1 position with unknown notional/),
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
  it('keeps an identified model snapshot read-only even if editability is accidentally true', () => {
    role = 'admin';
    render(<PositionBreakdown positions={[position({ strategyName: 'MODEL_A' })]}
      strategyId="trendfollowing" portfolioId="CONSERVATIVE_PORTFOLIO"
      positionStream="system" positionStrategyNames={['MODEL_A']} positionsEditable={true} />);

    expect(screen.getByText(/Model \/ System positions/i)).toBeTruthy();
    expect(screen.queryByLabelText(/^Adjust /)).toBeNull();
    expect(screen.queryByText('Add position')).toBeNull();
  });

  it('unmounts an open QT editor when the current role loses internal access', () => {
    role = 'admin';
    const props = {
      positions: [position({ strategyName: 'QT_A' })], strategyId: 'trendfollowing',
      portfolioId: 'CONSERVATIVE_PORTFOLIO', positionStream: 'qt' as const,
      positionsEditable: true,
    };
    const view = render(<PositionBreakdown {...props} />);
    fireEvent.click(screen.getByLabelText('Adjust ES.v.0 (QT_A)'));
    expect(screen.getByRole('dialog')).toBeTruthy();

    role = 'subscriber_individual';
    view.rerender(<PositionBreakdown {...props} />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it.each(['strategy', 'book', 'stream', 'reader'] as const)(
    'clears an open QT editor when the %s identity changes', change => {
      role = 'admin';
      userId = 'internal-one';
      const props = {
        positions: [position({ strategyName: 'QT_A' })],
        strategyId: 'trendfollowing',
        portfolioId: 'CONSERVATIVE_PORTFOLIO',
        positionStream: 'qt' as 'qt' | 'system',
        positionsEditable: true,
      };
      const view = render(<PositionBreakdown {...props} />);
      fireEvent.click(screen.getByLabelText('Adjust ES.v.0 (QT_A)'));
      expect(screen.getByRole('dialog')).toBeTruthy();

      if (change === 'reader') userId = 'internal-two';
      const changed = {
        ...props,
        strategyId: change === 'strategy' ? 'newstrategy' : props.strategyId,
        portfolioId: change === 'book' ? 'AGGRESSIVE_PORTFOLIO' : props.portfolioId,
        positionStream: change === 'stream' ? 'system' as const : props.positionStream,
      };
      view.rerender(<PositionBreakdown {...changed} />);
      expect(screen.queryByRole('dialog')).toBeNull();
    },
  );

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
        positionStream="qt"
        positionsEditable={true}
      />,
    );
    expect(screen.getByLabelText('Adjust AA.v.0')).toBeTruthy();
    expect(screen.getByLabelText('Adjust BB.v.0')).toBeTruthy();
  });

  it('fails closed when a legacy payload omits editability', () => {
    role = 'admin';
    render(
      <PositionBreakdown
        positions={[position({ strategyName: 'Engine A' } as Partial<Position>)]}
        strategyId="trendfollowing"
        portfolioId="CONSERVATIVE_PORTFOLIO"
      />,
    );

    expect(screen.queryByLabelText(/^Adjust /)).toBeNull();
    expect(screen.queryByText('Add position')).toBeNull();
  });

  it('does not invent an Add identity for an editable but empty snapshot', () => {
    role = 'admin';
    render(
      <PositionBreakdown
        positions={[]}
        strategyId="trendfollowing"
        portfolioId="CONSERVATIVE_PORTFOLIO"
        positionsEditable={true}
      />,
    );

    // The backend currently preserves zero-row identity internally but does
    // not serialize it. No row means no engine-owned strategyName to send.
    expect(screen.queryByText('Add position')).toBeNull();
  });

  it('uses the explicit server identity to add to an editable flat snapshot', () => {
    role = 'admin';
    render(
      <PositionBreakdown
        positions={[]}
        strategyId="trendfollowing"
        portfolioId="CONSERVATIVE_PORTFOLIO"
        positionStream="qt"
        positionsEditable={true}
        positionStrategyNames={['Engine A']}
      />,
    );

    expect(screen.getByText('Add position')).toBeTruthy();
  });

  it('fails closed when the server supplies more than one add identity', () => {
    role = 'admin';
    render(
      <PositionBreakdown
        positions={[]}
        strategyId="trendfollowing"
        portfolioId="CONSERVATIVE_PORTFOLIO"
        positionsEditable={true}
        positionStrategyNames={['Engine A', 'Engine B']}
      />,
    );

    expect(screen.queryByText('Add position')).toBeNull();
  });

  it('fails the whole add capability closed when one identity entry is malformed', () => {
    role = 'admin';
    render(
      <PositionBreakdown
        positions={[]}
        strategyId="trendfollowing"
        portfolioId="CONSERVATIVE_PORTFOLIO"
        positionsEditable={true}
        positionStrategyNames={['Engine A', null] as unknown as string[]}
      />,
    );

    expect(screen.queryByText('Add position')).toBeNull();
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
    expect(heading.textContent).toContain('Unknown position stream snapshot (date unavailable)');
    expect(within(heading).getByText('CONSERVATIVE_PORTFOLIO')).toBeTruthy();
  });

  it('puts a book box in place of the name when one is supplied', () => {
    role = 'subscriber';
    render(
      <PositionBreakdown
        positions={[position()]}
        portfolioId="CONSERVATIVE_PORTFOLIO"
        books={['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO']}
        bookControl={<select aria-label="Book for these positions" />}
      />,
    );
    const heading = document.querySelector('h3') as HTMLElement;
    // The name is not printed twice -- the box shows it.
    expect(within(heading).queryByText('CONSERVATIVE_PORTFOLIO')).toBeNull();
    expect(screen.getByRole('combobox', { name: 'Book for these positions' })).toBeTruthy();
    // And the partial-view notice points at the box rather than elsewhere.
    expect(document.body.textContent).toContain(
      'This strategy is also registered in AGGRESSIVE_PORTFOLIO for AlgoLens reporting. Positions and risk limits appear for a book only when published by the trading runtime; choose the book in the box above to see them.',
    );
  });

  it('does not claim that registry membership proves a flat strategy trades there', () => {
    role = 'subscriber';
    render(
      <PositionBreakdown
        positions={[]}
        portfolioId="AUDIT_BOOK_A"
        books={['AUDIT_BOOK_A', 'AUDIT_BOOK_B']}
      />,
    );

    expect(document.body.textContent).toContain(
      'This strategy is also registered in AUDIT_BOOK_B for AlgoLens reporting. Positions and risk limits appear for a book only when published by the trading runtime',
    );
    expect(document.body.textContent).not.toContain('also trades in');
  });
});

describe('snapshot identity and edit availability', () => {
  it('renders exact quantity in the existing cell and seeds the editor from exact companions', () => {
    role = 'admin';
    render(<PositionBreakdown
      positions={[position({ strategyName: 'Engine A', shares: 92233720368.12346,
        quantity_exact: '92233720368.12345678', costBasis: 92233720368.12346,
        average_price_exact: '92233720368.12345678' })]}
      strategyId="trendfollowing" portfolioId="MACRO_BOOK" positionStream="qt"
      positionsEditable={true}
    />);
    expect(cells('ES.v.0')[1]).toBe('92233720368.12345678');
    fireEvent.click(screen.getByRole('button', { name: 'Adjust ES.v.0 (Engine A)' }));
    expect((screen.getByLabelText('Quantity') as HTMLInputElement).value).toBe('92233720368.12345678');
    expect((screen.getByLabelText(/Average price/) as HTMLInputElement).value).toBe('92233720368.12345678');
  });

  it('shows invalid present exact evidence instead of a rounded number and prevents that row edit', () => {
    role = 'admin';
    render(<PositionBreakdown
      positions={[position({ strategyName: 'Engine A', shares: 3, quantity_exact: '3.000000001' })]}
      strategyId="trendfollowing" portfolioId="MACRO_BOOK" positionStream="qt"
      positionsEditable={true}
    />);
    expect(cells('ES.v.0')[1]).toMatch(/invalid position evidence/i);
    expect(screen.queryByRole('button', { name: 'Adjust ES.v.0 (Engine A)' })).toBeNull();
    expect(cells('ES.v.0')).toHaveLength(6);
  });

  it('blocks a malformed price companion even when quantity evidence is valid', () => {
    role = 'admin';
    render(<PositionBreakdown
      positions={[position({ strategyName: 'Engine A', quantity_exact: '12',
        average_price_exact: '5280.250000001' })]}
      strategyId="trendfollowing" portfolioId="MACRO_BOOK" positionStream="qt"
      positionsEditable={true}
    />);
    expect(cells('ES.v.0')[1]).toMatch(/invalid position evidence/i);
    expect(screen.queryByRole('button', { name: 'Adjust ES.v.0 (Engine A)' })).toBeNull();
  });

  it('accepts a null price companion only with a genuinely unknown basis', () => {
    role = 'admin';
    render(<PositionBreakdown
      positions={[position({ strategyName: 'Engine A', costBasis: null,
        quantity_exact: '12', average_price_exact: null })]}
      strategyId="trendfollowing" portfolioId="MACRO_BOOK" positionStream="qt"
      positionsEditable={true}
    />);
    expect(cells('ES.v.0')[1]).toBe('12');
    fireEvent.click(screen.getByRole('button', { name: 'Adjust ES.v.0 (Engine A)' }));
    expect((screen.getByLabelText(/Average price/) as HTMLInputElement).value).toBe('');
  });

  it('treats a null exact price as invalid when the legacy basis is known', () => {
    role = 'admin';
    render(<PositionBreakdown
      positions={[position({ strategyName: 'Engine A', costBasis: 2,
        quantity_exact: '12', average_price_exact: null })]}
      strategyId="trendfollowing" portfolioId="MACRO_BOOK" positionStream="qt"
      positionsEditable={true}
    />);
    expect(cells('ES.v.0')[1]).toMatch(/invalid position evidence/i);
    expect(screen.queryByRole('button', { name: 'Adjust ES.v.0 (Engine A)' })).toBeNull();
    expect(cells('ES.v.0')).toHaveLength(6);
  });

  it('labels the actual snapshot and explains why an older snapshot is read-only', () => {
    role = 'admin';
    render(
      <PositionBreakdown
        positions={[position({ strategyName: 'Trend Engine A' } as Partial<Position>)]}
        strategyId="trendfollowing"
        portfolioId="MACRO_BOOK"
        positionStream="qt"
        positionDate="2026-09-18"
        positionsEditable={false}
        positionEditUnavailableReason="Only the current engine snapshot can be edited."
      />,
    );
    expect(screen.getByRole('heading', { name: /QT positions snapshot 2026-09-18/i })).toBeTruthy();
    expect(screen.queryByLabelText(/^Adjust /)).toBeNull();
    expect(screen.getByText('Only the current engine snapshot can be edited.')).toBeTruthy();
  });

  it('renders same-symbol engine rows independently', () => {
    render(
      <PositionBreakdown
        positions={[
          position({ strategyName: 'Engine A' } as Partial<Position>),
          position({ strategyName: 'Engine B', shares: 7 } as Partial<Position>),
        ]}
      />,
    );
    expect(screen.getAllByText('ES.v.0')).toHaveLength(2);
  });
});

describe('the footer never promotes partial exposure to a complete total', () => {
  function footer(): HTMLElement {
    return screen.getByText('Total Notional').closest('div.grid') as HTMLElement;
  }

  it('renders unknown total and percentage when every notional is unknown', () => {
    render(
      <PositionBreakdown
        positions={[
          position({ symbol: 'AA.v.0', notional: null, marketPrice: null }),
          position({ symbol: 'BB.v.0', notional: null, marketPrice: null }),
        ]}
      />,
    );

    expect(footer().textContent).not.toContain('$0.00');
    expect(screen.getByText(/with unknown notional/)).toBeTruthy();
    expect(footer().textContent).not.toContain('100.00%');
    expect(footer().textContent).toContain('—');
  });

  it('marks a priced subtotal partial and makes no 100% completeness claim', () => {
    render(
      <PositionBreakdown
        positions={[
          position({ symbol: 'AA.v.0', notional: 600_000 }),
          position({ symbol: 'BB.v.0', notional: null, marketPrice: null }),
        ]}
      />,
    );

    expect(footer().textContent).toContain('$600,000.00');
    expect(within(footer()).getByText('partial')).toBeTruthy();
    expect(footer().textContent).not.toContain('100.00%');
    expect(screen.getByText('Share of known displayed exposure')).toBeTruthy();
    expect(screen.queryByText('Share of displayed exposure')).toBeNull();
  });

  it('retains the complete total when every row is priced', () => {
    render(<PositionBreakdown positions={[position({ notional: 600_000 })]} />);
    expect(footer().textContent).toContain('$600,000.00');
    expect(footer().textContent).toContain('100.00%');
  });
});

describe('the position table remains aligned on a narrow viewport', () => {
  it('scrolls a fixed minimum-width table instead of compressing its columns', () => {
    render(<PositionBreakdown positions={[position()]} />);

    const header = screen.getByText('Market Price').closest('div.grid') as HTMLElement;
    const table = header.parentElement as HTMLElement;
    expect(table.className).toContain('min-w-[760px]');
    expect(table.parentElement?.className).toContain('overflow-x-auto');
  });
});
