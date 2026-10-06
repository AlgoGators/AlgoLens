import { describe, expect, it } from 'vitest';

import {
  breaksWithin,
  latestSegment,
  splitAtBreaks,
  withBreakGaps,
  type HistoryBreak,
} from './historySegments';

function br(date: string, from = 'BASE', to = 'CONSERVATIVE'): HistoryBreak {
  return { date, fromPortfolioId: from, toPortfolioId: to, reason: 'book_change' };
}

function curve(...dates: string[]) {
  return dates.map(date => ({ date, value: 100 }));
}

describe('splitting the curve at a book change', () => {
  it('leaves an unbroken curve as one segment', () => {
    const points = curve('2026-01-01', '2026-01-02');
    expect(splitAtBreaks(points, [])).toEqual([points]);
    expect(splitAtBreaks(points, undefined)).toEqual([points]);
  });

  it('starts the new segment on the day of the move', () => {
    const points = curve('2026-02-28', '2026-03-01', '2026-03-02', '2026-03-03');
    const [before, after] = splitAtBreaks(points, [br('2026-03-02')]);

    expect(before.map(p => p.date)).toEqual(['2026-02-28', '2026-03-01']);
    expect(after.map(p => p.date)).toEqual(['2026-03-02', '2026-03-03']);
  });

  it('makes three segments from two moves', () => {
    const points = curve('2026-01-01', '2026-02-01', '2026-03-01');
    const segments = splitAtBreaks(points, [br('2026-02-01'), br('2026-03-01')]);

    expect(segments.map(s => s.length)).toEqual([1, 1, 1]);
  });

  it('always returns at least one segment', () => {
    expect(splitAtBreaks([], [])).toEqual([[]]);
  });
});

describe('a window return may not span a break', () => {
  it('measures only the newest stretch', () => {
    const points = curve('2026-02-28', '2026-03-02', '2026-03-03');
    const segment = latestSegment(points, [br('2026-03-02')]);

    expect(segment.map(p => p.date)).toEqual(['2026-03-02', '2026-03-03']);
  });

  it('falls back over a segment the move left empty', () => {
    const points = curve('2026-01-01', '2026-02-01');
    const segment = latestSegment(points, [br('2026-02-01'), br('2026-03-01')]);

    expect(segment.map(p => p.date)).toEqual(['2026-02-01']);
  });

  it('measures an unbroken curve whole', () => {
    const points = curve('2026-01-01', '2026-01-02');
    expect(latestSegment(points, [])).toEqual(points);
  });
});

describe('the line lifts the pen at the break', () => {
  it('inserts one null-valued spacer between the two books', () => {
    const points = curve('2026-03-01', '2026-03-02', '2026-03-03');
    const plotted = withBreakGaps(points, [br('2026-03-02')]);

    expect(plotted.map(p => p.value)).toEqual([100, null, 100, 100]);
  });

  it('puts the spacer in the gap, not on the first day of the new book', () => {
    const points = curve('2026-03-01', '2026-03-02');
    const plotted = withBreakGaps(points, [br('2026-03-02')]);

    expect(plotted[1]).toEqual({ date: '2026-03-01', value: null });
    expect(plotted[2].date).toBe('2026-03-02');
  });

  it('adds nothing when there is no break', () => {
    const points = curve('2026-03-01', '2026-03-02');
    expect(withBreakGaps(points, [])).toEqual(points);
  });

  it('adds nothing when a break falls outside the points it was given', () => {
    // A window showing only the new book has one segment, so no pen lifting.
    const points = curve('2026-03-02', '2026-03-03');
    expect(withBreakGaps(points, [br('2026-01-01')])).toEqual(points);
  });
});

describe('only the breaks a reader can see get labelled', () => {
  it('keeps a break inside the window', () => {
    const points = curve('2026-02-28', '2026-03-02');
    expect(breaksWithin(points, [br('2026-03-02')])).toHaveLength(1);
  });

  it('drops a break older than everything on screen', () => {
    const points = curve('2026-03-02', '2026-03-03');
    expect(breaksWithin(points, [br('2026-01-01')])).toEqual([]);
  });

  it('drops a break newer than everything on screen', () => {
    const points = curve('2026-01-01', '2026-01-02');
    expect(breaksWithin(points, [br('2026-03-01')])).toEqual([]);
  });

  it('handles no breaks and no points', () => {
    expect(breaksWithin(curve('2026-01-01'), undefined)).toEqual([]);
    expect(breaksWithin([], [br('2026-01-01')])).toEqual([]);
  });
});
