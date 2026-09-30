// @vitest-environment jsdom
//
// The "Edit positions" entry point. When the QT proposal workflow is required,
// the page shows this button as the way into the editing window. It must be there
// for every internal reader on every strategy page -- enabled when it can take
// them somewhere, disabled with the reason written on the page when it cannot,
// and absent for everyone else.
//
// It only navigates. Nothing here can make a write succeed that the server
// would refuse, so these tests pin what it offers and what it never offers.

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PositionBreakdown } from './PositionBreakdown';
import type { Position } from '../domain/portfolio/portfolioData';

vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light' }),
}));

let role = 'admin';
vi.mock('../adapters/react/useAuth', () => ({
  useAuth: () => ({ user: { id: 'internal-one', role } }),
}));

function position(): Position {
  return {
    symbol: 'ES.v.0', name: 'ES', shares: 12, quantity: 12, marketPrice: 5310.75,
    notional: 3186450, costBasis: 5280.25, currentValue: 3186450,
    strategyName: 'Engine A', quantity_exact: '12', average_price_exact: '5280.25',
  } as Position;
}

const editButton = () => screen.queryByRole('button', { name: 'Edit positions' }) as HTMLButtonElement | null;

/** The text an element's aria-describedby points at. */
function describedBy(button: HTMLElement): string {
  const ids = (button.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
  return ids.map(id => document.getElementById(id)?.textContent ?? '').join(' ').trim();
}

describe('Edit positions: internal reader', () => {
  it('is an enabled button that runs the supplied action when there is somewhere to go', () => {
    role = 'admin';
    const go = vi.fn();
    render(<PositionBreakdown positions={[position()]} positionStream="qt" strategyId="s1"
      positionsEditable={false} onEditInWorkspace={go} />);
    const button = editButton()!;
    expect(button).toBeTruthy();
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('is offered on the Model / System stream too, where it is the way to QT', () => {
    role = 'general_member';
    const go = vi.fn();
    render(<PositionBreakdown positions={[position()]} positionStream="system" strategyId="s1"
      positionEditUnavailableReason="Model/system positions are read-only. Select QT to edit its current snapshot."
      onEditInWorkspace={go} />);
    const button = editButton()!;
    expect(button.disabled).toBe(false);
    expect(screen.getByText(/Select QT to edit its current snapshot/)).toBeTruthy();
    fireEvent.click(button);
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('is disabled when the caller says why, shows that reason as text and points at it', () => {
    role = 'admin';
    const go = vi.fn();
    render(<PositionBreakdown positions={[position()]} positionStream="qt" strategyId="s1"
      positionsEditable={false} onEditInWorkspace={go}
      workspaceEditUnavailableReason="Synthetic workflow unavailable" />);
    const button = editButton()!;
    expect(button.disabled).toBe(true);
    // Visible on the page, not only in a tooltip or an attribute.
    expect(screen.getByText('Synthetic workflow unavailable')).toBeTruthy();
    expect(describedBy(button)).toBe('Synthetic workflow unavailable');
    expect(button.getAttribute('title')).toBeNull();
    fireEvent.click(button);
    expect(go).not.toHaveBeenCalled();
  });

  it('is disabled even when no action was supplied, as long as a reason was', () => {
    role = 'admin';
    render(<PositionBreakdown positions={[position()]} positionStream="qt" strategyId="s1"
      workspaceEditUnavailableReason="Loading QT workflow capability. Position changes are disabled." />);
    const button = editButton()!;
    expect(button.disabled).toBe(true);
    expect(describedBy(button)).toBe('Loading QT workflow capability. Position changes are disabled.');
  });

  it('reuses the grey status box as the description when it already states the same reason', () => {
    role = 'admin';
    const reason = 'Sign in before changing QT positions.';
    render(<PositionBreakdown positions={[position()]} positionStream="qt" strategyId="s1"
      positionEditUnavailableReason={reason} workspaceEditUnavailableReason={reason} />);
    // One sentence on the page, not two, and the button still points at it.
    expect(screen.getAllByText(reason)).toHaveLength(1);
    expect(describedBy(editButton()!)).toBe(reason);
  });

  it('gives an enabled button no description when there is nothing to explain', () => {
    role = 'admin';
    render(<PositionBreakdown positions={[position()]} positionStream="qt" strategyId="s1"
      onEditInWorkspace={() => {}} />);
    expect(editButton()!.getAttribute('aria-describedby')).toBeNull();
  });

  it('is absent when neither an action nor a reason was supplied', () => {
    role = 'admin';
    render(<PositionBreakdown positions={[position()]} positionStream="qt" strategyId="s1" />);
    expect(editButton()).toBeNull();
  });
});

describe('Edit positions: nobody else', () => {
  it.each(['subscriber', 'subscriber_individual', 'viewer', undefined as unknown as string])(
    'is never shown to role %s, enabled or disabled', badRole => {
      role = badRole;
      const { unmount } = render(<PositionBreakdown positions={[position()]} positionStream="qt" strategyId="s1"
        onEditInWorkspace={() => {}} />);
      expect(editButton()).toBeNull();
      unmount();
      render(<PositionBreakdown positions={[position()]} positionStream="system" strategyId="s1"
        workspaceEditUnavailableReason="Anything" />);
      expect(editButton()).toBeNull();
      expect(screen.queryByText('Anything')).toBeNull();
    });

  it('leaves the old editor alone when legacy editing is allowed: no duplicate button, adjust controls intact', () => {
    role = 'admin';
    render(<PositionBreakdown positions={[position()]} positionStream="qt" strategyId="s1"
      portfolioId="BOOK" positionsEditable positionStrategyNames={['Engine A']}
      onEditInWorkspace={() => {}} workspaceEditUnavailableReason="Should never appear" />);
    expect(editButton()).toBeNull();
    expect(screen.queryByText('Should never appear')).toBeNull();
    expect(screen.getByRole('button', { name: /Adjust ES\.v\.0/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add position' })).toBeTruthy();
  });
});
