// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { StrategyLifecycleControls } from './StrategyLifecycleControls';

const api = vi.hoisted(() => ({ changeIncubation: vi.fn() }));
vi.mock('../infrastructure/api/portfolioApi', () => ({ PortfolioApiService: api }));

beforeEach(() => api.changeIncubation.mockReset());

describe('book strategy lifecycle controls', () => {
  it('restarts a retired strategy with positive finite mock capital and a reason', async () => {
    api.changeIncubation.mockResolvedValue({ outcome: 'ok' });
    const onChanged = vi.fn();
    render(
      <StrategyLifecycleControls
        strategyId="trend" strategyName="Trend" lifecycle="retired"
        theme="light" onChanged={onChanged}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Restart incubation for Trend' }));
    fireEvent.change(screen.getByLabelText('Mock capital'), { target: { value: '250000' } });
    fireEvent.change(screen.getByLabelText('Lifecycle reason'), { target: { value: 'new review' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start incubation' }));

    await waitFor(() => expect(api.changeIncubation).toHaveBeenCalledWith(
      'trend', 'start', { mock_capital: 250000, reason: 'new review' },
    ));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('requires capital greater than zero before starting incubation', () => {
    render(
      <StrategyLifecycleControls
        strategyId="trend" strategyName="Trend" lifecycle="live"
        theme="light" onChanged={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Start incubation for Trend' }));
    fireEvent.change(screen.getByLabelText('Mock capital'), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText('Lifecycle reason'), { target: { value: 'review' } });
    expect((screen.getByRole('button', { name: 'Start incubation' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('marks a live strategy retired with an explicit reason', async () => {
    api.changeIncubation.mockResolvedValue({ outcome: 'ok' });
    render(
      <StrategyLifecycleControls
        strategyId="trend" strategyName="Trend" lifecycle="live"
        theme="light" onChanged={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Mark Trend retired' }));
    fireEvent.change(screen.getByLabelText('Lifecycle reason'), { target: { value: 'closed review' } });
    fireEvent.click(screen.getByRole('button', { name: 'Mark retired' }));

    await waitFor(() => expect(api.changeIncubation).toHaveBeenCalledWith(
      'trend', 'retire', { reason: 'closed review' },
    ));
  });

  it('keeps a pending transition single-flight and prevents cancel', async () => {
    let finish!: (value: { outcome: 'ok' }) => void;
    api.changeIncubation.mockReturnValue(
      new Promise(resolve => { finish = resolve; }),
    );
    render(
      <StrategyLifecycleControls
        strategyId="trend" strategyName="Trend" lifecycle="live"
        theme="light" onChanged={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Mark Trend retired' }));
    fireEvent.change(screen.getByLabelText('Lifecycle reason'), { target: { value: 'closed' } });
    const submit = screen.getByRole('button', { name: 'Mark retired' });
    fireEvent.click(submit);
    fireEvent.click(submit);

    expect(api.changeIncubation).toHaveBeenCalledTimes(1);
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Cancel lifecycle change' }) as HTMLButtonElement).disabled).toBe(true);
    finish({ outcome: 'ok' });
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Mark retired' })).toBeNull());
  });

  it('does not claim the registry change immediately controls the engine', () => {
    render(
      <StrategyLifecycleControls
        strategyId="trend" strategyName="Trend" lifecycle="retired"
        theme="light" onChanged={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Restart incubation for Trend' }));
    expect(screen.getByText(/does not immediately start or stop a process or deploy capital/i)).toBeTruthy();
    expect(screen.getByText(/can block the next engine publication until.*eligible-admin.*approval/i)).toBeTruthy();
  });
});
