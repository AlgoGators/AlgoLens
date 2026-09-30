// @vitest-environment jsdom
//
// The modal that holds the QT proposal workspace. It is opened by the strategy
// page's "Edit positions" button, so the things worth pinning are the ones a
// reader (and a keyboard) depends on: it is a real modal dialog, it can always
// be left, focus goes in on open and back to the opener on close, Tab cannot
// leave it, the page behind does not scroll, and (keepMounted) typed-but-unsaved
// quantities survive a close and reopen because the children are never remounted.

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { QtEditDialog } from './QtEditDialog';

const theme = vi.hoisted(() => ({ current: 'light' as 'light' | 'dark' }));
vi.mock('../../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: theme.current, toggleTheme: () => undefined }) }));
afterEach(() => { cleanup(); theme.current = 'light'; document.body.style.overflow = ''; });

const Body = () => <div>
  <input aria-label="Chosen quantity ES" defaultValue="4" />
  <input aria-label="Chosen quantity NQ" defaultValue="2" />
  <button type="button">Save draft</button>
</div>;

function show(props: Partial<Parameters<typeof QtEditDialog>[0]> = {}) {
  const onClose = vi.fn();
  const view = render(<QtEditDialog open title="Edit QT positions" onClose={onClose} {...props}><Body /></QtEditDialog>);
  return { onClose, ...view };
}
const dialog = () => screen.getByRole('dialog');

describe('closed', () => {
  it('renders nothing when closed and not kept mounted', () => {
    const { container } = show({ open: false });
    expect(container.innerHTML).toBe('');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByLabelText('Chosen quantity ES')).toBeNull();
  });

  it('keeps the children in the DOM, hidden and unreachable, when kept mounted', () => {
    const { container } = show({ open: false, keepMounted: true });
    const box = container.querySelector('input[aria-label="Chosen quantity ES"]')!;
    expect(box).toBeTruthy();
    const wrapper = box.closest('[hidden]')!;
    expect(wrapper).toBeTruthy();
    expect(wrapper.getAttribute('aria-hidden')).toBe('true');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Close QT editor' })).toBeNull();
  });

  it('does not lock the page scroll while closed', () => {
    show({ open: false, keepMounted: true });
    expect(document.body.style.overflow).toBe('');
  });
});

describe('keepMounted preserves what was typed', () => {
  function Harness() {
    const [open, setOpen] = useState(true);
    return <div>
      <button onClick={() => setOpen(true)}>Edit positions</button>
      <QtEditDialog open={open} title="Edit QT positions" onClose={() => setOpen(false)} keepMounted><Body /></QtEditDialog>
    </div>;
  }
  it('keeps the very same input element, with its typed value, across close and reopen', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const box = screen.getByLabelText('Chosen quantity ES') as HTMLInputElement;
    await user.clear(box); await user.type(box, '7');
    await user.click(screen.getByRole('button', { name: 'Close QT editor' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Edit positions' }));
    const again = screen.getByLabelText('Chosen quantity ES') as HTMLInputElement;
    expect(again).toBe(box);
    expect(again.value).toBe('7');
  });

  it('remounts the children each time when not kept mounted', async () => {
    const user = userEvent.setup();
    function Plain() {
      const [open, setOpen] = useState(true);
      return <div><button onClick={() => setOpen(true)}>Edit positions</button>
        <QtEditDialog open={open} title="T" onClose={() => setOpen(false)}><Body /></QtEditDialog></div>;
    }
    render(<Plain />);
    const box = screen.getByLabelText('Chosen quantity ES') as HTMLInputElement;
    await user.clear(box); await user.type(box, '7');
    await user.click(screen.getByRole('button', { name: 'Close QT editor' }));
    await user.click(screen.getByRole('button', { name: 'Edit positions' }));
    expect((screen.getByLabelText('Chosen quantity ES') as HTMLInputElement).value).toBe('4');
  });
});

describe('open: the modal', () => {
  it('is a labelled modal dialog whose heading is the title', () => {
    show();
    const el = dialog();
    expect(el.getAttribute('aria-modal')).toBe('true');
    const heading = screen.getByRole('heading', { level: 2, name: 'Edit QT positions' });
    expect(el.getAttribute('aria-labelledby')).toBe(heading.id);
    expect(heading.id).not.toBe('');
    expect(screen.getByRole('dialog', { name: 'Edit QT positions' })).toBe(el);
  });

  it('is a full-screen dimmed overlay above the page, with a centred, bounded, scrolling panel', () => {
    show();
    const overlay = dialog().parentElement!;
    expect(overlay.className).toMatch(/\bfixed\b/);
    expect(overlay.className).toMatch(/\binset-0\b/);
    expect(overlay.className).toMatch(/\bz-50\b/);
    expect(overlay.className).toMatch(/\bbg-black\/\d+/);
    expect(dialog().className).toMatch(/\bmax-w-5xl\b/);
    expect(dialog().className).toMatch(/max-h-\[90vh\]/);
    expect(dialog().querySelector('.overflow-y-auto')).toBeTruthy();
  });

  it('renders the children inside the panel', () => {
    show();
    expect(dialog().contains(screen.getByLabelText('Chosen quantity NQ'))).toBe(true);
  });

  it('has a visible Close button labelled for assistive technology', () => {
    show();
    const close = screen.getByRole('button', { name: 'Close QT editor' });
    expect(close.textContent).toBe('Close');
    expect(dialog().contains(close)).toBe(true);
  });
});

describe('leaving', () => {
  it('Close calls onClose', async () => {
    const { onClose } = show();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Close QT editor' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Escape calls onClose', async () => {
    const { onClose } = show();
    await userEvent.setup().keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('a click on the backdrop calls onClose', async () => {
    const { onClose } = show();
    await userEvent.setup().click(dialog().parentElement!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('a click inside the panel does not', async () => {
    const { onClose } = show();
    const user = userEvent.setup();
    await user.click(dialog());
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await user.click(screen.getByRole('heading', { name: 'Edit QT positions' }));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('a drag that starts in the panel and is released on the backdrop does not close it', () => {
    const { onClose } = show();
    fireEvent.mouseDown(screen.getByLabelText('Chosen quantity ES'));
    fireEvent.click(dialog().parentElement!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('Escape does nothing while closed', () => {
    const { onClose } = show({ open: false, keepMounted: true });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe('focus', () => {
  it('moves to the first enabled quantity box on open', () => {
    render(<QtEditDialog open title="T" onClose={vi.fn()}>
      <input aria-label="Chosen quantity ES" disabled /><input aria-label="Chosen quantity NQ" /><input aria-label="Other" />
    </QtEditDialog>);
    expect(document.activeElement).toBe(screen.getByLabelText('Chosen quantity NQ'));
  });

  it('moves to the heading, which is focusable but not a tab stop, when there is no enabled quantity box', () => {
    render(<QtEditDialog open title="Edit QT positions" onClose={vi.fn()}>
      <input aria-label="Chosen quantity ES" disabled /><button>Refresh</button>
    </QtEditDialog>);
    const heading = screen.getByRole('heading', { name: 'Edit QT positions' });
    expect(document.activeElement).toBe(heading);
    expect(heading.getAttribute('tabindex')).toBe('-1');
  });

  it('follows a quantity box that becomes enabled after opening, until the reader moves elsewhere', async () => {
    function Late({ ready }: { ready: boolean }) {
      return <QtEditDialog open title="T" onClose={vi.fn()}>
        <input aria-label="Chosen quantity ES" disabled={!ready} /><button>Refresh</button></QtEditDialog>;
    }
    const view = render(<Late ready={false} />);
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'T' }));
    view.rerender(<Late ready />);
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('Chosen quantity ES')));
  });

  it('does not steal focus from a control the reader already moved to', async () => {
    function Late({ ready }: { ready: boolean }) {
      return <QtEditDialog open title="T" onClose={vi.fn()}>
        <input aria-label="Chosen quantity ES" disabled={!ready} /><button>Refresh</button></QtEditDialog>;
    }
    const view = render(<Late ready={false} />);
    screen.getByRole('button', { name: 'Refresh' }).focus();
    view.rerender(<Late ready />);
    await new Promise(resolve => setTimeout(resolve, 20));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Refresh' }));
  });

  it('returns to the element that had focus when it opened, on close', () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return <div><button onClick={() => setOpen(true)}>Edit positions</button>
        <QtEditDialog open={open} title="T" onClose={() => setOpen(false)}><Body /></QtEditDialog></div>;
    }
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Edit positions' });
    opener.focus();
    fireEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByLabelText('Chosen quantity ES'));
    fireEvent.click(screen.getByRole('button', { name: 'Close QT editor' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('returns to the opener on close when kept mounted too', () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return <div><button onClick={() => setOpen(true)}>Edit positions</button>
        <QtEditDialog open={open} title="T" onClose={() => setOpen(false)} keepMounted><Body /></QtEditDialog></div>;
    }
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Edit positions' });
    opener.focus();
    fireEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByLabelText('Chosen quantity ES'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(document.activeElement).toBe(opener);
    // and a second round trip
    fireEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByLabelText('Chosen quantity ES'));
  });
});

describe('Tab trap', () => {
  const order = () => [screen.getByRole('button', { name: 'Close QT editor' }), screen.getByLabelText('Chosen quantity ES'),
    screen.getByLabelText('Chosen quantity NQ'), screen.getByRole('button', { name: 'Save draft' })];

  it('wraps forward from the last control to the first', async () => {
    show();
    const [first, , , last] = order();
    last.focus();
    await userEvent.setup().tab();
    expect(document.activeElement).toBe(first);
  });

  it('wraps backward from the first control to the last', async () => {
    show();
    const [first, , , last] = order();
    first.focus();
    await userEvent.setup().tab({ shift: true });
    expect(document.activeElement).toBe(last);
  });

  it('moves normally between controls in the middle', async () => {
    show();
    const [, es, nq] = order();
    es.focus();
    await userEvent.setup().tab();
    expect(document.activeElement).toBe(nq);
  });

  it('brings focus from the heading into the cycle in both directions', async () => {
    render(<QtEditDialog open title="T" onClose={vi.fn()}><button>Only</button></QtEditDialog>);
    const heading = screen.getByRole('heading', { name: 'T' });
    const user = userEvent.setup();
    heading.focus();
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close QT editor' }));
    heading.focus();
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Only' }));
  });

  it('pulls focus back if it escapes to the page behind', () => {
    render(<div><button>Behind</button><QtEditDialog open title="T" onClose={vi.fn()}><Body /></QtEditDialog></div>);
    screen.getByRole('button', { name: 'Behind' }).focus();
    expect(dialog().contains(document.activeElement)).toBe(true);
  });

  it('skips disabled controls', async () => {
    render(<QtEditDialog open title="T" onClose={vi.fn()}><button>Go</button><button disabled>Off</button></QtEditDialog>);
    screen.getByRole('button', { name: 'Go' }).focus();
    await userEvent.setup().tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close QT editor' }));
  });
});

describe('page scroll lock', () => {
  it('locks body scroll while open and restores the previous value on close', () => {
    document.body.style.overflow = 'auto';
    const view = render(<QtEditDialog open title="T" onClose={vi.fn()}><Body /></QtEditDialog>);
    expect(document.body.style.overflow).toBe('hidden');
    view.rerender(<QtEditDialog open={false} title="T" onClose={vi.fn()}><Body /></QtEditDialog>);
    expect(document.body.style.overflow).toBe('auto');
  });

  it('restores it on unmount while open', () => {
    const view = render(<QtEditDialog open title="T" onClose={vi.fn()}><Body /></QtEditDialog>);
    expect(document.body.style.overflow).toBe('hidden');
    view.unmount();
    expect(document.body.style.overflow).toBe('');
  });

  it('restores it when a kept-mounted dialog closes', () => {
    const view = render(<QtEditDialog open keepMounted title="T" onClose={vi.fn()}><Body /></QtEditDialog>);
    expect(document.body.style.overflow).toBe('hidden');
    view.rerender(<QtEditDialog open={false} keepMounted title="T" onClose={vi.fn()}><Body /></QtEditDialog>);
    expect(document.body.style.overflow).toBe('');
  });
});

describe('theme', () => {
  it('uses the light tokens by default', () => {
    show();
    expect(dialog().className).toMatch(/\bbg-white\b/);
    expect(dialog().className).not.toMatch(/\bbg-gray-950\b/);
  });

  it('uses the dark tokens in the dark theme', () => {
    theme.current = 'dark';
    show();
    expect(dialog().className).toMatch(/\bbg-gray-950\b/);
    expect(dialog().className).not.toMatch(/\bbg-white\b/);
  });
});
