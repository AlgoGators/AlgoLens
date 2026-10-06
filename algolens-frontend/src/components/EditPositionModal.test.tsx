// @vitest-environment jsdom
import { StrictMode } from 'react';
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
  const view = render(<EditPositionModal {...props} />);
  return { ...props, unmount: view.unmount };
}

beforeEach(() => savePosition.mockReset());

describe('safe position submission', () => {
  it('prefills exact quantity and price, shows an adjacent-unit diff, and submits canonical strings', async () => {
    savePosition.mockResolvedValue({ outcome: 'saved' });
    renderEditor({ existing: {
      quantity: 92233720368.12346,
      quantity_exact: '92233720368.12345678',
      average_price: 92233720368.12346,
      average_price_exact: '92233720368.12345678',
    } });
    expect((screen.getByLabelText('Quantity') as HTMLInputElement).value).toBe('92233720368.12345678');
    expect((screen.getByLabelText(/Average price/) as HTMLInputElement).value).toBe('92233720368.12345678');

    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '92233720368.12345679' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    expect(screen.getByText('92233720368.12345678 → 92233720368.12345679')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(savePosition).toHaveBeenCalledWith(expect.objectContaining({
      quantity: '92233720368.12345679',
      average_price: '92233720368.12345678',
    }));
  });

  it('resubmits the same exact text only after risk acknowledgement', async () => {
    savePosition
      .mockResolvedValueOnce({ outcome: 'needs_acknowledgement', risk_check: {
        evaluated: true, passed: false,
        breaches: [{ limit: 'max_symbol_notional', limit_value: 1, actual: 2, message: 'over' }],
      } })
      .mockResolvedValueOnce({ outcome: 'saved' });
    renderEditor({ existing: { quantity: 92233720368.12346,
      quantity_exact: '92233720368.12345678', average_price: 2, average_price_exact: '2' } });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '92233720368.12345679' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
    expect(savePosition).toHaveBeenCalledTimes(1);
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Override and save' })));
    expect(savePosition).toHaveBeenLastCalledWith(expect.objectContaining({
      quantity: '92233720368.12345679', average_price: '2', acknowledge_risk: true,
    }));
  });

  it('shows invalid present companion evidence and blocks unsafe editing', () => {
    renderEditor({ existing: { quantity: 3, quantity_exact: 'invalid', average_price: 2 } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    expect(screen.getByRole('alert').textContent).toMatch(/invalid position evidence/i);
    expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('uses legacy numeric prefill when companions are absent', () => {
    renderEditor({ existing: { quantity: 2.5, average_price: 5000.5 } });
    expect((screen.getByLabelText('Quantity') as HTMLInputElement).value).toBe('2.5');
    expect((screen.getByLabelText(/Average price/) as HTMLInputElement).value).toBe('5000.5');
  });

  it('explains fractional equities, whole futures, and server type verification at the quantity field', () => {
    renderEditor();
    const quantity = screen.getByLabelText('Quantity');
    const help = screen.getByText(/Equities may use fractional shares.*Futures require whole contracts.*server verifies the instrument type/i);
    expect(quantity.getAttribute('aria-describedby')).toBe(help.id);
  });

  it('keeps a typed futures rejection visible and submits a corrected whole quantity only on a second click', async () => {
    savePosition
      .mockResolvedValueOnce({ outcome: 'rejected', message: 'FUTURE quantity must be a whole number of contracts' })
      .mockResolvedValueOnce({ outcome: 'saved' });
    const { onSaved } = renderEditor();
    const quantity = screen.getByLabelText('Quantity') as HTMLInputElement;
    fireEvent.change(quantity, { target: { value: '2.25' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
    expect(savePosition).toHaveBeenCalledWith(expect.objectContaining({ quantity: '2.25', acknowledge_risk: false }));
    expect(screen.getByText('FUTURE quantity must be a whole number of contracts')).toBeTruthy();
    expect(quantity.value).toBe('2.25');
    expect(savePosition).toHaveBeenCalledTimes(1);
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Override and save' })).toBeNull();

    fireEvent.change(quantity, { target: { value: '3' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
    expect(savePosition).toHaveBeenCalledTimes(2);
    expect(savePosition).toHaveBeenLastCalledWith(expect.objectContaining({ quantity: '3', acknowledge_risk: false }));
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it.each([
    'Instrument type is missing from the catalog',
    'Instrument type is ambiguous in the catalog',
    'Instrument type is unsupported',
  ])('does not turn a catalog type rejection into a risk override: %s', async message => {
    savePosition.mockResolvedValue({ outcome: 'rejected', message });
    const { onSaved } = renderEditor();
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '2.5' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));

    expect(screen.getByText(message)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Override and save' })).toBeNull();
    expect(savePosition).toHaveBeenCalledTimes(1);
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('saves an exact fractional equity quantity without client-side type guessing', async () => {
    savePosition.mockResolvedValue({ outcome: 'saved' });
    const { onSaved } = renderEditor({ symbol: 'AAPL', existing: { quantity: 2, average_price: 100 } });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '2.12345678' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));

    expect(savePosition).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AAPL', quantity: '2.12345678', acknowledge_risk: false,
    }));
    expect(onSaved).toHaveBeenCalledTimes(1);
  });
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

  it('keeps submitted fields immutable until a breach verdict and acknowledges only those values', async () => {
    const pending = deferred<{ outcome: 'needs_acknowledgement'; risk_check: {
      evaluated: boolean; passed: boolean; breaches: Array<{
        limit: string; limit_value: number; actual: number; message: string;
      }>;
    } }>();
    savePosition.mockReturnValueOnce(pending.promise).mockResolvedValueOnce({ outcome: 'saved' });
    renderEditor();
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText(/Average price/), { target: { value: '5001' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    for (const label of ['Quantity', 'Reason (required)']) {
      expect((screen.getByLabelText(label) as HTMLInputElement).disabled).toBe(true);
    }
    expect((screen.getByLabelText(/Average price/) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Close' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '4' } });
    fireEvent.change(screen.getByLabelText(/Average price/), { target: { value: '6000' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'different trade' } });
    expect((screen.getByLabelText('Quantity') as HTMLInputElement).value).toBe('3');
    expect((screen.getByLabelText(/Average price/) as HTMLInputElement).value).toBe('5001');
    expect((screen.getByLabelText('Reason (required)') as HTMLTextAreaElement).value).toBe('rebalance');

    await act(async () => pending.resolve({ outcome: 'needs_acknowledgement', risk_check: {
      evaluated: true, passed: false,
      breaches: [{ limit: 'max_symbol_notional', limit_value: 1, actual: 2, message: 'over' }],
    } }));
    expect(savePosition).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Override and save' })).toBeTruthy();
    expect((screen.getByLabelText('Quantity') as HTMLInputElement).disabled).toBe(false);
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Override and save' })));
    expect(savePosition).toHaveBeenLastCalledWith(expect.objectContaining({
      quantity: '3', average_price: '5001', reason: 'rebalance', acknowledge_risk: true,
    }));
  });

  it('delivers a settled success after StrictMode effect replay', async () => {
    const pending = deferred<{ outcome: 'saved' }>();
    savePosition.mockReturnValue(pending.promise);
    const onSaved = vi.fn();
    render(<StrictMode><EditPositionModal
      strategyId="trend" strategyName="Trend Engine A" portfolioId="MACRO_BOOK"
      symbol="ES" existing={{ quantity: 2, average_price: 5000 }} theme="light"
      onClose={vi.fn()} onSaved={onSaved}
    /></StrictMode>);
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await act(async () => pending.resolve({ outcome: 'saved' }));
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('freezes a new symbol and restores all fields after a rejected response', async () => {
    const pending = deferred<{ outcome: 'rejected'; message: string }>();
    savePosition.mockReturnValue(pending.promise);
    renderEditor({ symbol: null, existing: null });
    fireEvent.change(screen.getByLabelText('Symbol'), { target: { value: 'es.v.0' } });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText(/Average price/), { target: { value: '5000' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'new hedge' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    const symbol = screen.getByLabelText('Symbol') as HTMLInputElement;
    const quantity = screen.getByLabelText('Quantity') as HTMLInputElement;
    const price = screen.getByLabelText(/Average price/) as HTMLInputElement;
    const reason = screen.getByLabelText('Reason (required)') as HTMLTextAreaElement;
    for (const field of [symbol, quantity, price, reason]) expect(field.disabled).toBe(true);
    fireEvent.change(symbol, { target: { value: 'NQ' } });
    fireEvent.change(quantity, { target: { value: '2' } });
    fireEvent.change(price, { target: { value: '6000' } });
    fireEvent.change(reason, { target: { value: 'changed' } });
    expect([symbol.value, quantity.value, price.value, reason.value]).toEqual([
      'es.v.0', '1', '5000', 'new hedge',
    ]);
    expect(savePosition).toHaveBeenCalledWith(expect.objectContaining({ symbol: 'es.v.0' }));

    await act(async () => pending.resolve({ outcome: 'rejected', message: 'Try again later' }));
    expect(screen.getByText('Try again later')).toBeTruthy();
    for (const field of [symbol, quantity, price, reason]) expect(field.disabled).toBe(false);
    fireEvent.change(symbol, { target: { value: 'NQ' } });
    expect(symbol.value).toBe('NQ');
    expect(savePosition).toHaveBeenCalledTimes(1);
  });

  it('freezes book selection during a pending save and applies the verdict to that book', async () => {
    const pending = deferred<{ outcome: 'needs_acknowledgement'; risk_check: {
      evaluated: boolean; passed: boolean; breaches: Array<{
        limit: string; limit_value: number; actual: number; message: string;
      }>;
    } }>();
    savePosition
      .mockResolvedValueOnce({ outcome: 'needs_book', books: ['MACRO_BOOK', 'HEDGE_BOOK'] })
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce({ outcome: 'saved' });
    renderEditor({ portfolioId: undefined });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
    const book = screen.getByRole('combobox', { name: 'Book' }) as HTMLSelectElement;
    expect(book.disabled).toBe(false);
    fireEvent.change(book, { target: { value: 'HEDGE_BOOK' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save to HEDGE_BOOK' }));
    expect(savePosition).toHaveBeenCalledTimes(2);
    const pendingBook = screen.getByRole('combobox', { name: 'Book' }) as HTMLSelectElement;
    expect(pendingBook.disabled).toBe(true);
    fireEvent.change(pendingBook, { target: { value: 'MACRO_BOOK' } });
    expect(pendingBook.value).toBe('HEDGE_BOOK');

    await act(async () => pending.resolve({ outcome: 'needs_acknowledgement', risk_check: {
      evaluated: true, passed: false,
      breaches: [{ limit: 'max_symbol_notional', limit_value: 1, actual: 2, message: 'over' }],
    } }));
    expect(savePosition).toHaveBeenCalledTimes(2);
    expect((screen.getByLabelText('Quantity') as HTMLInputElement).disabled).toBe(false);
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Override and save' })));
    expect(savePosition).toHaveBeenLastCalledWith(expect.objectContaining({
      portfolio_id: 'HEDGE_BOOK', acknowledge_risk: true,
    }));
  });

  it('clears acknowledgement after an edit and waits for a new explicit save', async () => {
    savePosition
      .mockResolvedValueOnce({ outcome: 'needs_acknowledgement', risk_check: {
        evaluated: true, passed: false,
        breaches: [{ limit: 'max_symbol_notional', limit_value: 1, actual: 2, message: 'over' }],
      } })
      .mockResolvedValueOnce({ outcome: 'saved' });
    renderEditor();
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
    expect(screen.getByRole('button', { name: 'Override and save' })).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '4' } });
    expect(screen.queryByText('This breaches a published risk limit')).toBeNull();
    expect(savePosition).toHaveBeenCalledTimes(1);
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
    expect(savePosition).toHaveBeenLastCalledWith(expect.objectContaining({
      quantity: '4', acknowledge_risk: false,
    }));
  });

  it('suppresses the saved callback after a genuine unmount', async () => {
    const pending = deferred<{ outcome: 'saved' }>();
    savePosition.mockReturnValue(pending.promise);
    const { onSaved, unmount } = renderEditor();
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'rebalance' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    unmount();
    await act(async () => pending.resolve({ outcome: 'saved' }));
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('submits the existing engine-owned continuous symbol unchanged', async () => {
    savePosition.mockResolvedValue({ outcome: 'saved' });
    renderEditor({ symbol: 'ES.v.0' });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), {
      target: { value: 'rebalance' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(savePosition).toHaveBeenCalledWith(expect.objectContaining({ symbol: 'ES.v.0' }));
  });

  it.each(['es', 'es.v.0'])('leaves new symbol %s for API normalization', (newSymbol) => {
    savePosition.mockResolvedValue({ outcome: 'saved' });
    renderEditor({ symbol: null, existing: null });
    fireEvent.change(screen.getByLabelText('Symbol'), { target: { value: newSymbol } });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText(/Average price/), { target: { value: '5000' } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), {
      target: { value: 'new hedge' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(savePosition).toHaveBeenCalledWith(expect.objectContaining({ symbol: newSymbol }));
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
