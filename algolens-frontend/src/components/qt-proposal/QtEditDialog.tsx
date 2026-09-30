import { useEffect, useId, useRef, type ReactNode } from 'react';
import { qtStyles, useQtDark } from './qtStyles';

type Props = {
  open: boolean;
  /** Shown as the dialog heading; it is also the dialog's accessible name. */
  title: string;
  onClose: () => void;
  /**
   * Keep the children mounted (hidden) while closed, so typed-but-unsaved
   * quantities and the workspace's own recovery state survive a close/reopen.
   * When false the children are unmounted while closed.
   */
  keepMounted?: boolean;
  /**
   * Where focus goes when the dialog closes if the element that opened it is
   * gone (re-rendered away, or focus was on the page body). Resolved at close time.
   */
  returnFocusTo?: () => HTMLElement | null;
  children: ReactNode;
};

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), ' +
  'textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
const FIRST_QUANTITY_BOX = 'input[aria-label^="Chosen quantity"]:not([disabled])';

function tabStops(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter(el => !el.closest('[hidden], [aria-hidden="true"]') && el.getAttribute('tabindex') !== '-1');
}

/**
 * Modal that holds the QT proposal workspace. A plain conditional render (no
 * portal). The element structure is identical open and closed, so keepMounted
 * children are never remounted: only attributes and classes change.
 */
export function QtEditDialog({ open, title, onClose, keepMounted = false, returnFocusTo, children }: Props) {
  const ui = qtStyles(useQtDark());
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const onCloseRef = useRef(onClose); onCloseRef.current = onClose;
  const returnFocusRef = useRef(returnFocusTo); returnFocusRef.current = returnFocusTo;
  // A press that started inside the panel and ends on the backdrop (a text-selection drag) is not a backdrop click.
  const pressedInPanel = useRef(false);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current, heading = headingRef.current;
    if (!panel || !heading) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // First open quantity box, else the heading. The source loads after the dialog opens, so while focus is still
    // on the heading follow the first box as it becomes editable; anywhere else means the reader has moved on.
    const firstBox = () => panel.querySelector<HTMLInputElement>(FIRST_QUANTITY_BOX);
    const box = firstBox();
    let observer: MutationObserver | null = null;
    if (box) box.focus();
    else {
      heading.focus();
      observer = new MutationObserver(() => {
        const active = document.activeElement;
        if (active !== heading && active !== document.body) { observer?.disconnect(); return; }
        const late = firstBox();
        if (late) { late.focus(); observer?.disconnect(); }
      });
      observer.observe(panel, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (event.defaultPrevented) return;
        event.preventDefault(); onCloseRef.current(); return;
      }
      if (event.key !== 'Tab') return;
      const stops = tabStops(panel);
      if (stops.length === 0) { event.preventDefault(); heading.focus(); return; }
      const first = stops[0], last = stops[stops.length - 1], active = document.activeElement;
      if (event.shiftKey && (active === first || !panel.contains(active) || active === heading)) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (active === last || !panel.contains(active) || active === heading)) {
        event.preventDefault(); first.focus();
      }
    };
    const onFocusIn = (event: FocusEvent) => {
      if (event.target instanceof Node && !panel.contains(event.target)) (tabStops(panel)[0] ?? heading).focus();
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('focusin', onFocusIn);

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('focusin', onFocusIn);
      observer?.disconnect();
      document.body.style.overflow = previousOverflow;
      // The opener can be gone (its button was re-rendered) or be the page body; then use the caller's target.
      const target = opener && opener.isConnected && opener !== document.body ? opener : returnFocusRef.current?.() ?? null;
      if (target && target.isConnected) target.focus();
      else if (document.activeElement instanceof HTMLElement && panel.contains(document.activeElement)) document.activeElement.blur();
    };
  }, [open]);

  if (!open && !keepMounted) return null;

  return <div
    hidden={!open} aria-hidden={open ? undefined : true}
    className={open ? ui.dialogBackdrop : undefined}
    onMouseDown={event => { pressedInPanel.current = event.target !== event.currentTarget; }}
    onClick={event => {
      const startedInside = pressedInPanel.current; pressedInPanel.current = false;
      if (event.target === event.currentTarget && !startedInside) onClose();
    }}
  >
    <div ref={panelRef} role="dialog" aria-modal="true" aria-labelledby={titleId} className={ui.dialogPanel}>
      <div className={ui.dialogHeader}>
        <h2 id={titleId} ref={headingRef} tabIndex={-1} className={ui.dialogTitle}>{title}</h2>
        <button type="button" aria-label="Close QT editor" className={ui.btnSecondary} onClick={onClose}>Close</button>
      </div>
      <div className={ui.dialogBody}>{children}</div>
    </div>
  </div>;
}
