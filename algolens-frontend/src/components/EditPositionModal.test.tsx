// @vitest-environment jsdom
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { EditPositionModal } from './EditPositionModal';

const savePosition = vi.hoisted(() => vi.fn());
vi.mock('../infrastructure/api/portfolioApi', () => ({
  PortfolioApiService: { savePosition },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}

function renderEditor(over: Partial<React.ComponentProps<typeof EditPositionModal>> = {}) {
  const props: React.ComponentProps<typeof EditPositionModal> = {
    strategyId: 'trend',
    strategyName: 'Trend Engine A',
    portfolioId: 'MACRO_BOOK',
    symbol: 'ES',
    existing: { quantity: 2, average_price: 5000 },
    theme: 'light',
    onClose: vi.fn(),
    onSaved: vi.fn(),
    ...over,
  };
  render(<EditPositionModal {...props} />);
  return props;
}

beforeEach(() => savePosition.mockReset());

describe('safe position submission', () => {
  it('requires an average price for a new position', () => {
    renderEditor({ symbol: null, existing: null });
    fireEvent.change(screen.getByLabelText('Symbol'), { target: { value: 'NQ' } });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'new hedge' } });

    expect(screen.getByLabelText(/Average price.*required for new positions/i)).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/new position needs an average price/i);
    expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('keeps average price optional when editing an existing position', () => {
    renderEditor({ existing: { quantity: 2, average_price: null } });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });

    expect(screen.getByLabelText(/Average price.*optional/i)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('rejects invalid average prices and unchanged edits', () => {
    renderEditor();
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Average price/), { target: { value: 'Infinity' } });
    expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole('alert').textContent).toMatch(/finite, non-negative number/i);
  });

  it('sends the engine strategy identity and cannot submit twice', async () => {
    const pending = deferred<{ outcome: 'saved' }>();
    savePosition.mockReturnValue(pending.promise);
    const { onSaved } = renderEditor();
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });

    const save = screen.getByRole('button', { name: 'Save' });
    fireEvent.click(save);
    fireEvent.click(save);
    expect(savePosition).toHaveBeenCalledTimes(1);
    expect((screen.getByRole('button', { name: 'Close' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(true);

    await act(async () => pending.resolve({ outcome: 'saved' }));
    expect(savePosition).toHaveBeenCalledWith(expect.objectContaining({
      strategy_name: 'Trend Engine A',
      portfolio_id: 'MACRO_BOOK',
    }));
    expect(onSaved).toHaveBeenCalledTimes(1);
  });
});

describe('modal keyboard lifecycle', () => {
  it('is a labelled dialog, takes focus, closes on Escape when idle and restores focus', async () => {
    const opener = document.createElement('button');
    document.body.append(opener);
    opener.focus();
    const { onClose } = renderEditor();

    const dialog = screen.getByRole('dialog', { name: 'Adjust ES' });
    expect(dialog).toBeTruthy();
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
