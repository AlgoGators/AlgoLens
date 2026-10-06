import { useTheme } from '../../adapters/react/ThemeContext';

/**
 * Presentation-only class tokens for the QT proposal panel.
 *
 * The app switches dark mode through ThemeContext (not the `.dark` class), so
 * the tokens follow the same mechanism as EditPositionModal / PositionBreakdown.
 * Rendered outside a ThemeProvider (isolated component tests) it falls back to
 * the light palette instead of throwing. No logic depends on any of this.
 */
export type QtTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

export function useQtDark(): boolean {
  try { return useTheme().theme === 'dark'; } catch { return false; }
}

const toneDark: Record<QtTone, string> = {
  success: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  warning: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  danger: 'border-red-500/50 bg-red-500/10 text-red-300',
  info: 'border-blue-500/40 bg-blue-500/10 text-blue-300',
  neutral: 'border-gray-700 bg-gray-900 text-gray-300',
};
const toneLight: Record<QtTone, string> = {
  success: 'border-emerald-600/30 bg-emerald-50 text-emerald-800',
  warning: 'border-amber-600/30 bg-amber-50 text-amber-800',
  danger: 'border-red-500/40 bg-red-50 text-red-700',
  info: 'border-blue-600/30 bg-blue-50 text-blue-800',
  neutral: 'border-gray-200 bg-gray-50 text-gray-700',
};

export function qtStyles(dark: boolean) {
  const tone = dark ? toneDark : toneLight;
  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  const border = dark ? 'border-gray-800' : 'border-gray-200';
  // The focus-ring offset is the colour of the panel behind the button, so the gap reads as a gap on both themes.
  // Hover colours are `enabled:` so a disabled button does not react to the pointer.
  const button = 'inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition-colors ' +
    `focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 ${dark ? 'focus-visible:ring-offset-gray-950' : 'focus-visible:ring-offset-white'} ` +
    'disabled:cursor-not-allowed disabled:opacity-40';
  return {
    tone,
    muted,
    border,
    /** Whole panel. */
    panel: `space-y-6 rounded-xl border p-4 sm:p-6 ${border} ${dark ? 'bg-gray-950 text-white' : 'bg-white text-black'}`,
    /** The same panel with the chrome removed, for when a dialog already provides it. */
    panelEmbedded: 'space-y-6',
    panelTitle: 'text-lg font-semibold',
    /** QT edit dialog: dimmed full-screen overlay, the bounded panel that scrolls inside itself, and its fixed header. */
    dialogBackdrop: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-2 sm:p-6',
    dialogPanel: `relative flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border shadow-2xl ${border} ${dark ? 'bg-gray-950 text-white' : 'bg-white text-black'}`,
    dialogHeader: `flex flex-none items-center justify-between gap-4 border-b px-4 py-3 sm:px-6 ${border}`,
    dialogTitle: 'text-lg font-semibold focus:outline-none',
    dialogBody: 'min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 sm:p-6',
    /** Section card (proposal, preview, decision review, approvals). */
    card: `space-y-4 rounded-lg border p-4 ${border} ${dark ? 'bg-gray-900/50' : 'bg-gray-50/60'}`,
    cardTitle: 'text-base font-semibold',
    subTitle: `text-xs font-semibold uppercase tracking-wider ${muted}`,
    body: 'text-sm',
    note: `text-xs ${muted}`,
    mono: 'font-mono',
    /** Pill for short states; callout for sentences. */
    // wrap-anywhere lets a long unbroken value (an id, a reason code) wrap inside the pill instead of pushing the layout wide.
    badge: (t: QtTone) => `inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium wrap-anywhere ${tone[t]}`,
    callout: (t: QtTone) => `rounded-lg border px-4 py-3 text-sm ${tone[t]}`,
    /** Buttons. */
    btnPrimary: `${button} bg-blue-600 text-white enabled:hover:bg-blue-700`,
    btnSecondary: `${button} border ${dark
      ? 'border-gray-700 bg-gray-800 text-white enabled:hover:bg-gray-700'
      : 'border-gray-300 bg-white text-black enabled:hover:bg-gray-100'}`,
    // White on amber-600 was about 3.2:1; amber-700 clears AA (4.5:1) and amber-800 keeps it on hover.
    btnWarning: `${button} bg-amber-700 text-white enabled:hover:bg-amber-800`,
    btnGhost: `${button} ${dark ? 'text-gray-300 enabled:hover:bg-gray-800' : 'text-gray-700 enabled:hover:bg-gray-100'}`,
    buttonRow: 'flex flex-wrap items-center gap-3',
    /** Table shared by every QT table. */
    tableWrap: `max-w-full overflow-x-auto rounded-lg border ${border}`,
    table: 'w-full border-collapse text-left text-sm',
    th: `border-b px-3 py-2.5 align-bottom text-xs font-medium ${border} ${dark ? 'bg-gray-900 text-gray-400' : 'bg-gray-50 text-gray-500'}`,
    thRight: `border-b px-3 py-2.5 text-right align-bottom text-xs font-medium ${border} ${dark ? 'bg-gray-900 text-gray-400' : 'bg-gray-50 text-gray-500'}`,
    tr: `border-b last:border-b-0 align-top transition-colors ${border} ${dark ? 'hover:bg-gray-900' : 'hover:bg-gray-50'}`,
    td: 'px-3 py-2.5',
    tdNum: 'px-3 py-2.5 text-right font-mono tabular-nums',
    /** "Change from MODEL" text: quantity up, quantity down, a value that could not be read. */
    delta: {
      increase: dark ? 'text-emerald-300' : 'text-emerald-700',
      decrease: dark ? 'text-amber-300' : 'text-amber-700',
      invalid: dark ? 'text-red-300' : 'text-red-700',
    },
    /** Quantity editor. */
    input: (locked: boolean) => `w-28 rounded-lg border px-3 py-1.5 text-right font-mono text-sm tabular-nums ` +
      `focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 ` +
      (locked
        ? (dark ? 'cursor-not-allowed border-gray-800 bg-gray-900/60 text-gray-300' : 'cursor-not-allowed border-gray-200 bg-gray-100 text-gray-600')
        : (dark ? 'border-gray-500 bg-gray-900 text-white hover:border-gray-400' : 'border-gray-500 bg-white text-black hover:border-gray-600')),
    textarea: (locked: boolean) => `w-full resize-y rounded-lg border px-3 py-2 text-sm ` +
      `focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 ` +
      (locked
        ? (dark ? 'cursor-not-allowed border-gray-800 bg-gray-900/60 text-gray-300' : 'cursor-not-allowed border-gray-200 bg-gray-100 text-gray-600')
        : (dark ? 'border-gray-500 bg-gray-900 text-white hover:border-gray-400' : 'border-gray-500 bg-white text-black hover:border-gray-600')),
  };
}
