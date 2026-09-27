// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import type { Strategy } from '../../domain/portfolio/portfolioData';
import { computeCombinedMetrics } from '../../domain/portfolio/computeCombinedMetrics';
import { StrategySummary } from './StrategySummary';

it('discloses that a selected position-only strategy is missing from the measured subset', () => {
  const priced = {
    id: 'priced', name: 'Priced', invested: 100, currentValue: 110,
    dataAvailable: true, positions: [], historicalData: [], finalizedPositions: [],
    executions: [], metrics: {},
  } as unknown as Strategy;
  const positionOnly = {
    id: 'position-only', name: 'Position Only', invested: 100,
    currentValue: null, dataAvailable: false, positions: [],
    historicalData: [], finalizedPositions: [], executions: [], metrics: {},
  } as unknown as Strategy;
  const metrics = computeCombinedMetrics([priced, positionOnly], ['priced', 'position-only']);
  render(<StrategySummary metrics={metrics} theme="light" />);

  expect(screen.getByText(/partial.*1 selected strategy.*QT performance unavailable/i)).toBeTruthy();
  expect(screen.queryByText('Position Only')).toBeNull();
});
