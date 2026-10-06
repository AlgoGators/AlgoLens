/** @vitest-environment jsdom */
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { afterEach, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { EquityRunConsumptionInspection } from './EquityRunConsumptionInspection';
import { adjusted, original } from '../domain/portfolio/actionFixtures';
afterEach(cleanup);
it('explains prior and next seed provenance without claiming MODEL reapplied actions', () => {
  const value = adjusted(2, 3).publication.equity_run_consumption;
  render(<EquityRunConsumptionInspection consumption={value} />);
  fireEvent.click(screen.getByRole('button', {name:/Show corporate actions observations/}));
  expect(screen.getByText('These actions were recorded in the proved prior and next MODEL seed. This MODEL run did not reapply them.')).toBeInTheDocument();
  for (const field of ['original_action_count', 'successor_action_count', 'original_action_digest', 'successor_action_digest', 'basis_frame_digest']) expect(screen.getByText(field)).toBeInTheDocument();
  expect(screen.getByText(/does not establish investor report readiness/)).toBeInTheDocument();
});
it('keeps the v1 inspection free of the adjusted-action notice', () => {
  render(<EquityRunConsumptionInspection consumption={original().publication.equity_run_consumption as any} />);
  fireEvent.click(screen.getByRole('button', {name:/Show corporate actions observations/}));
  expect(screen.queryByText(/This MODEL run did not reapply them/)).not.toBeInTheDocument();
});
