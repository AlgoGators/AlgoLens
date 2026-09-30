// @vitest-environment jsdom
import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { QtEditDialog } from './QtEditDialog';

// Focus target when the element that opened the dialog is gone.
function Harness({ withTarget }: { withTarget: boolean }) {
  const [open, setOpen] = useState(false);
  return <div>
    <button type="button" data-testid="fallback">fallback</button>
    <button type="button" onClick={() => setOpen(true)}>open</button>
    <QtEditDialog open={open} title="Edit" onClose={() => setOpen(false)} keepMounted
      returnFocusTo={withTarget ? () => document.querySelector<HTMLElement>('[data-testid="fallback"]') : undefined}>
      <input aria-label="Chosen quantity X" defaultValue="1" />
    </QtEditDialog>
  </div>;
}

describe('QtEditDialog returnFocusTo', () => {
  it('focuses the caller target when focus was on the page body when it opened', () => {
    render(<Harness withTarget />);
    (document.activeElement as HTMLElement | null)?.blur();
    fireEvent.click(screen.getByText('open'));
    fireEvent.click(screen.getByLabelText('Close QT editor'));
    expect(document.activeElement).toBe(screen.getByTestId('fallback'));
  });

  it('prefers the element that opened it while that element is still on the page', () => {
    render(<Harness withTarget />);
    const opener = screen.getByText('open'); opener.focus();
    fireEvent.click(opener);
    fireEvent.click(screen.getByLabelText('Close QT editor'));
    expect(document.activeElement).toBe(opener);
  });

  it('without a target it blurs a box left focused inside the closed dialog', () => {
    render(<Harness withTarget={false} />);
    (document.activeElement as HTMLElement | null)?.blur();
    fireEvent.click(screen.getByText('open'));
    const box = screen.getByLabelText('Chosen quantity X'); box.focus();
    fireEvent.click(screen.getByLabelText('Close QT editor'));
    expect(document.activeElement).not.toBe(box);
  });
});
