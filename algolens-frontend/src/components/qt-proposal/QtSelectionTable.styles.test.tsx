// @vitest-environment jsdom
//
// How the quantity table marks rows the reader cannot edit, and how it colours
// the "Change from MODEL" column. The colours themselves are checked for
// contrast in qtStyles.test.ts; here we check the right token lands on the
// right cell, in both themes, and that a locked row is locked for real
// (disabled, announced as read-only) and not merely drawn dim.

import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import fixtures from '../../../../contracts/qt-workflow-v1.json';
import { decodeQtProposal, qtComponentKey, type QtSelectionRow } from '../../domain/portfolio/qtPreview';
import { QtSelectionTable } from './QtSelectionTable';
import { qtStyles } from './qtStyles';

const theme = vi.hoisted(() => ({ current: 'light' as 'light' | 'dark' }));
vi.mock('../../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: theme.current, toggleTheme: () => undefined }) }));
afterEach(cleanup);

const base = decodeQtProposal(structuredClone(fixtures.proposal_ready)).seed_rows[0];
const row = (symbol: string, quantity: string, extra: Partial<QtSelectionRow> = {}): QtSelectionRow =>
  ({ ...base, key: { ...base.key, symbol }, quantity_exact: quantity, ...extra });

// One MODEL seed of 4 per symbol; the QT side starts at the same 4.
const symbols = ['UP', 'DOWN', 'SAME', 'BAD', 'HELD'];
const source = symbols.filter(symbol => symbol !== 'HELD').map(symbol => row(symbol, '4'));
const chosen = [
  ...symbols.filter(symbol => symbol !== 'HELD').map(symbol => row(symbol, '4', { origin: 'qt_draft' })),
  row('HELD', '9', { editable: false, origin: 'immutable' }),
];
const selection = Object.fromEntries([
  [qtComponentKey(chosen[0].key), '6'], [qtComponentKey(chosen[1].key), '1'],
  [qtComponentKey(chosen[2].key), '4'], [qtComponentKey(chosen[3].key), 'abc'],
]);

function show(mode: 'light' | 'dark', locked = false, onEdit = vi.fn()) {
  theme.current = mode;
  render(<QtSelectionTable sourceRows={source} chosenRows={chosen} selection={selection} onEdit={onEdit} locked={locked} />);
  const rowFor = (symbol: string) => screen.getAllByRole('row').find(tr => tr.children[1]?.textContent?.startsWith(symbol + ' (')) as HTMLTableRowElement;
  return { rowFor, input: (symbol: string) => within(rowFor(symbol)).getByRole('textbox') as HTMLInputElement,
    delta: (symbol: string) => rowFor(symbol).lastElementChild as HTMLElement, onEdit };
}

describe.each(['light', 'dark'] as const)('%s theme', mode => {
  const ui = qtStyles(mode === 'dark');

  it('an immutable row is disabled and announced read-only, and looks unavailable', () => {
    const { input, rowFor } = show(mode);
    const held = input('HELD');
    expect(held.disabled).toBe(true);
    expect(held.getAttribute('aria-readonly')).toBe('true');
    expect(held.className).toBe(ui.input(true));
    expect(held.className).toContain('cursor-not-allowed');
    expect(held.value).toBe('9');
    expect(within(rowFor('HELD')).getByText('Immutable holdings')).toBeTruthy();
    expect(held.closest('td')?.className).not.toContain('bg-blue-500/10');
  });

  it('an editable row is enabled, not read-only, and marks its edit cell', () => {
    const { input, onEdit } = show(mode);
    const up = input('UP');
    expect(up.disabled).toBe(false);
    expect(up.getAttribute('aria-readonly')).toBe('false');
    expect(up.className).toBe(ui.input(false));
    expect(up.closest('td')?.className).toContain('bg-blue-500/10');
    expect(onEdit).not.toHaveBeenCalled();
  });

  it('a locked table disables every box, including the editable ones', () => {
    const { input } = show(mode, true);
    for (const symbol of symbols) expect(input(symbol).disabled).toBe(true);
    expect(input('UP').className).toBe(ui.input(true));
  });

  it('colours Change from MODEL: green up, amber down, red invalid, muted when unchanged or unavailable', () => {
    const { delta } = show(mode);
    expect(delta('UP').textContent).toBe('+2');
    expect(delta('UP').className).toContain(ui.delta.increase);
    expect(delta('DOWN').textContent).toBe('-3');
    expect(delta('DOWN').className).toContain(ui.delta.decrease);
    expect(delta('BAD').textContent).toBe('Invalid quantity');
    expect(delta('BAD').className).toContain(ui.delta.invalid);
    expect(delta('SAME').textContent).toBe('0');
    expect(delta('SAME').className).toContain(ui.muted);
    expect(delta('HELD').textContent).toBe('Unavailable');
    expect(delta('HELD').className).toContain(ui.muted);
  });

  it('keeps the meaning of each colour', () => {
    expect(ui.delta.increase).toContain('emerald');
    expect(ui.delta.decrease).toContain('amber');
    expect(ui.delta.invalid).toContain('red');
  });
});
