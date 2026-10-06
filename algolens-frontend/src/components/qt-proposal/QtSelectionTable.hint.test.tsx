// @vitest-environment jsdom
//
// The one-line hint above the quantity boxes says what kind of number each
// editable instrument takes. It is built from the asset types actually present,
// and must never print a bare "." when none of them is one it has words for.

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import fixtures from '../../../../contracts/qt-workflow-v1.json';
import { decodeQtProposal, type QtSelectionRow } from '../../domain/portfolio/qtPreview';
import { QtSelectionTable } from './QtSelectionTable';

const rows = (types: string[], editable = true): QtSelectionRow[] => {
  const base = decodeQtProposal(structuredClone(fixtures.proposal_ready)).seed_rows;
  return types.map((type, index) => ({
    ...base[0], key: { ...base[0].key, symbol: `SYM${index}` }, asset_type: type as never, editable,
  }));
};
const hint = () => document.querySelector('p[id]');

function show(types: string[], locked = false, editable = true) {
  const chosen = rows(types, editable);
  return render(<QtSelectionTable sourceRows={chosen} chosenRows={chosen} selection={{}} onEdit={vi.fn()} locked={locked} />);
}

describe('the quantity hint', () => {
  it('names futures and equities when both are editable', () => {
    show(['FUTURE', 'EQUITY']);
    expect(hint()?.textContent).toBe('Whole contracts for futures; fractions allowed for equities.');
  });
  it('names just the type that is there', () => {
    show(['EQUITY']);
    expect(hint()?.textContent).toBe('Fractions allowed for equities.');
  });
  it('says only what it knows when a third type appears beside a known one', () => {
    show(['FUTURE', 'OPTION']);
    expect(hint()?.textContent).toBe('Whole contracts for futures.');
  });
  it('prints nothing at all, not a stray full stop, when no editable type is one it knows', () => {
    show(['OPTION']);
    expect(hint()).toBeNull();
    expect(screen.queryByText('.')).toBeNull();
  });
  it('is not shown when the table is locked or nothing is editable', () => {
    show(['FUTURE'], true);
    expect(hint()).toBeNull();
  });
  it('is not shown when nothing is editable', () => {
    show(['FUTURE'], false, false);
    expect(hint()).toBeNull();
  });
});
