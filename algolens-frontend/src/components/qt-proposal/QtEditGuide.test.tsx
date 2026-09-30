// @vitest-environment jsdom
//
// The guide beside the quantity boxes. It is presentation only: the workspace
// works out which step the reader is on and how many boxes differ from MODEL,
// and this component says so in words. It has no way to enable anything.

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { QtEditGuide, type QtEditStep } from './QtEditGuide';

const titles = ['Change quantity', 'Save draft', 'Evaluate', 'Confirm'];

const tracker = () => screen.getAllByRole('list')[0];
const items = () => within(tracker()).getAllByRole('listitem');
const current = () => items().filter(item => item.getAttribute('aria-current') === 'step');

describe('the four-step tracker', () => {
  it.each([1, 2, 3, 4] as QtEditStep[])('marks step %i as the current one and the earlier steps done', step => {
    render(<QtEditGuide step={step} changed={0} editable={2} lockedReason={null} />);
    expect(items()).toHaveLength(4);
    expect(current()).toHaveLength(1);
    expect(current()[0].textContent).toContain(titles[step - 1]);
    items().forEach((item, index) => {
      const done = index + 1 < step;
      expect(item.textContent?.startsWith('✓')).toBe(done);
      expect(item.textContent).toContain(`${index + 1}. ${titles[index]}`);
    });
  });

  it('shows every step done and none current once a decision exists (step 5)', () => {
    render(<QtEditGuide step={5} changed={1} editable={2} lockedReason={null} />);
    expect(current()).toHaveLength(0);
    expect(items().every(item => item.textContent?.startsWith('✓'))).toBe(true);
  });

  it('describes what each step does in plain words', () => {
    render(<QtEditGuide step={1} changed={0} editable={2} lockedReason={null} />);
    expect(screen.getByText(/Type the exact quantity QT wants/)).toBeTruthy();
    expect(screen.getByText(/Saving keeps your choice; nothing reaches the report yet/)).toBeTruthy();
    expect(screen.getByText(/Checks your choice against risk limits/)).toBeTruthy();
    expect(screen.getByText(/A risk breach needs two different approvers/)).toBeTruthy();
  });
});

describe('the live difference summary', () => {
  it('says nothing differs yet, in the singular and the plural', () => {
    const { rerender } = render(<QtEditGuide step={1} changed={0} editable={1} lockedReason={null} />);
    expect(screen.getByRole('status').textContent)
      .toBe('No quantity differs from the MODEL recommendation yet (1 editable component).');
    rerender(<QtEditGuide step={1} changed={0} editable={3} lockedReason={null} />);
    expect(screen.getByRole('status').textContent)
      .toBe('No quantity differs from the MODEL recommendation yet (3 editable components).');
  });

  it('counts the changed components with the right verb', () => {
    const { rerender } = render(<QtEditGuide step={2} changed={1} editable={1} lockedReason={null} />);
    expect(screen.getByRole('status').textContent)
      .toBe('1 of 1 editable component differs from the MODEL recommendation.');
    rerender(<QtEditGuide step={2} changed={2} editable={5} lockedReason={null} />);
    expect(screen.getByRole('status').textContent)
      .toBe('2 of 5 editable components differ from the MODEL recommendation.');
  });

  it('says so when the book has nothing to edit', () => {
    render(<QtEditGuide step={1} changed={0} editable={0} lockedReason={null} />);
    expect(screen.getByRole('status').textContent).toBe('There are no editable components in this book.');
  });

  it('is announced politely rather than interrupting', () => {
    render(<QtEditGuide step={1} changed={0} editable={2} lockedReason={null} />);
    expect(screen.getByRole('status').getAttribute('aria-live')).toBe('polite');
  });
});

describe('when editing is locked', () => {
  it('replaces the tracker and the summary with the reason', () => {
    render(<QtEditGuide step={5} changed={1} editable={2}
      lockedReason="A decision already exists for this source day, so these quantities can no longer be changed." />);
    expect(screen.getByText(/A decision already exists for this source day/)).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.queryByText('1. Change quantity')).toBeNull();
    expect(screen.queryByText(/Change quantity/)).toBeNull();
  });
});

describe('the rules', () => {
  it.each([null, 'Locked for a synthetic reason.'])('always lists the three rules (locked reason: %s)', lockedReason => {
    render(<QtEditGuide step={1} changed={0} editable={2} lockedReason={lockedReason} />);
    const region = screen.getByRole('region', { name: 'How QT position changes work' });
    expect(within(region).getByText('Changing positions')).toBeTruthy();
    expect(within(region).getByText(/Futures trade in whole contracts; equities may be fractional. Nothing is rounded for you/)).toBeTruthy();
    expect(within(region).getByText(/investor report shows exactly the quantities you confirm/)).toBeTruthy();
    expect(within(region).getByText(/confirming asks for two different approvers/)).toBeTruthy();
  });

  it('adds no button or input: it cannot enable an action', () => {
    render(<QtEditGuide step={3} changed={1} editable={2} lockedReason={null} />);
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('textbox')).toBeNull();
  });
});

describe('the optional note', () => {
  const note = 'A previous decision for this source day was processed. Editing starts a new choice; the previous decision stays in the audit history below.';

  it('is shown under the summary while editing is open, without touching the steps or the summary', () => {
    render(<QtEditGuide step={3} changed={1} editable={2} lockedReason={null} note={note} />);
    expect(screen.getByText(note)).toBeTruthy();
    expect(items()).toHaveLength(4);
    expect(current()[0].textContent).toContain('Evaluate');
    expect(screen.getByRole('status').textContent).toBe('1 of 2 editable components differ from the MODEL recommendation.');
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it('is absent by default and whenever editing is locked', () => {
    const { rerender } = render(<QtEditGuide step={3} changed={1} editable={2} lockedReason={null} />);
    expect(screen.queryByText(/A previous decision/)).toBeNull();
    rerender(<QtEditGuide step={5} changed={1} editable={2} lockedReason="Locked for a synthetic reason." note={note} />);
    expect(screen.queryByText(note)).toBeNull();
    expect(screen.getByText('Locked for a synthetic reason.')).toBeTruthy();
  });
});
