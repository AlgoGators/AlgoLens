// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import fixtures from '../../../../contracts/qt-workflow-v1.json';
import { decodeQtPreview } from '../../domain/portfolio/qtPreview';
import { QtPreviewEvidence } from './QtPreviewEvidence';

afterEach(cleanup);

function preview() {
  const value = decodeQtPreview(structuredClone(fixtures.preview_clean));
  const optimizer = value.evaluation.optimizer;
  optimizer.status = 'evaluated';
  optimizer.current_weights = [{ instrument_type: 'FUTURE', symbol: 'SYN', weight_diagnostic: '0.012' }];
  optimizer.target_weights = [{ instrument_type: 'FUTURE', symbol: 'SYN', weight_diagnostic: '0.024' }];
  optimizer.solved_weights = [{ instrument_type: 'FUTURE', symbol: 'SYN', weight_diagnostic: '0.023' }];
  optimizer.cost_penalty = '0.31';
  optimizer.trace = [JSON.stringify({ buffer_branch: 'applied', solver_positions: ['0.023'],
    continuous_buffered_positions: ['0.0225'], rounded_buffered_positions: ['0.022'] }),
    'tracking_error=0.001', 'actual_iterations=7'];
  return value;
}

describe('QT optimizer recommendation diagnostics', () => {
  it('shows actual iterations and readable existing optimizer diagnostics', () => {
    render(<QtPreviewEvidence preview={preview()} />);
    const advice = within(screen.getByRole('region', { name: 'Aggregate optimizer advice' }));
    expect(advice.getByText('Actual optimizer iterations: 7.')).toBeTruthy();
    expect(advice.getByText('Tracking error: 0.001; cost penalty: 0.31.')).toBeTruthy();
    expect(advice.getByText('Buffer branch: applied.')).toBeTruthy();
    expect(advice.getByText('Solver weights: 0.023.')).toBeTruthy();
    expect(advice.getByText('Buffered weights before rounding: 0.0225.')).toBeTruthy();
    expect(advice.getByText('Buffered weights after rounding: 0.022.')).toBeTruthy();
    const weights = within(advice.getByRole('table', { name: 'Optimizer aggregate weights' }));
    expect(weights.getByRole('cell', { name: 'FUTURE SYN' })).toBeTruthy();
    for (const value of ['0.012', '0.024', '0.023']) expect(weights.getByRole('cell', { name: value })).toBeTruthy();
    expect(advice.getByText(/does not change QT component quantities/)).toBeTruthy();
    expect(advice.queryByText(/actual_iterations=/)).toBeNull();
  });

  it('preserves optimizer weight units and distinguishes proposal advice from exact chosen quantities', () => {
    render(<QtPreviewEvidence preview={preview()} />);
    const advice = within(screen.getByRole('region', { name: 'Aggregate optimizer advice' }));
    expect(advice.getByRole('columnheader', { name: 'Proposed weight' })).toBeTruthy();
    expect(advice.queryByRole('columnheader', { name: 'Chosen weight' })).toBeNull();
    expect(advice.queryByText(/Solver quantities|Buffered quantities/)).toBeNull();
    expect(advice.getByText('Solver weights: 0.023.')).toBeTruthy();
    expect(advice.getByText('Buffered weights after rounding: 0.022.')).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Selected book costs' })).toBeTruthy();
  });

  it('labels preview costs as estimates', () => {
    render(<QtPreviewEvidence preview={preview()} />);
    expect(screen.getByText(/estimated selected-book cost 0.02/)).toBeTruthy();
    expect(screen.getAllByText(/estimated cash cost 0.01/)).toHaveLength(2);
  });

  it('preserves genuine zero iterations without substituting a limit', () => {
    const value = preview();
    value.evaluation.optimizer.trace[2] = 'actual_iterations=0';
    render(<QtPreviewEvidence preview={value} />);
    expect(screen.getByText('Actual optimizer iterations: 0.')).toBeTruthy();
  });

  it.each(['disabled', 'unavailable'] as const)('does not invent diagnostics for an inactive %s stage', status => {
    const value = preview();
    value.evaluation.optimizer.status = status;
    render(<QtPreviewEvidence preview={value} />);
    expect(screen.getByText('Actual optimizer iterations: unavailable.')).toBeTruthy();
    expect(screen.queryByRole('table', { name: 'Optimizer aggregate weights' })).toBeNull();
    expect(screen.queryByText('Buffer branch: applied.')).toBeNull();
  });

  it.each(['actual_iterations=-1', 'actual_iterations=1.5', 'actual_iterations=true',
    'actual_iterations=2147483648', 'actual_iterations=07', 'unrelated=7'])('refuses malformed count display %s', count => {
    const value = preview();
    value.evaluation.optimizer.trace[2] = count;
    render(<QtPreviewEvidence preview={value} />);
    expect(screen.getByText('Actual optimizer iterations: unavailable.')).toBeTruthy();
  });

  it('keeps historical evidence without iteration trace honest and readable', () => {
    const value = preview();
    value.evaluation.optimizer.trace = ['historical opaque trace'];
    render(<QtPreviewEvidence preview={value} />);
    expect(screen.getByText('Actual optimizer iterations: unavailable.')).toBeTruthy();
    expect(screen.queryByText('historical opaque trace')).toBeNull();
  });
});
