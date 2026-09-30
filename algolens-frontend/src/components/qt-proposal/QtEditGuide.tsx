import { qtStyles, useQtDark } from './qtStyles';

export type QtEditStep = 1 | 2 | 3 | 4 | 5;

const steps: { title: string; detail: string }[] = [
  { title: 'Change quantity', detail: 'Type the exact quantity QT wants in the highlighted box.' },
  { title: 'Save draft', detail: 'Saving keeps your choice; nothing reaches the report yet.' },
  { title: 'Evaluate', detail: 'Checks your choice against risk limits and shows the effect.' },
  { title: 'Confirm', detail: 'Locks the decision. A risk breach needs two different approvers.' },
];

/**
 * Explains, next to the quantity boxes, what happens after a quantity is edited.
 * Presentation only: `step` and `changed` are derived by the workspace from its
 * own state; nothing here can enable an action.
 */
export function QtEditGuide({ step, changed, editable, lockedReason, note = null }: {
  step: QtEditStep; changed: number; editable: number; lockedReason: string | null;
  /** Extra context shown under the summary while editing is open (never shown when locked). */
  note?: string | null;
}) {
  const ui = qtStyles(useQtDark());
  const summary = editable === 0 ? 'There are no editable components in this book.'
    : changed === 0 ? `No quantity differs from the MODEL recommendation yet (${editable} editable ${editable === 1 ? 'component' : 'components'}).`
      : `${changed} of ${editable} editable ${editable === 1 ? 'component differs' : 'components differ'} from the MODEL recommendation.`;
  return <section aria-label="How QT position changes work" className={`space-y-3 ${ui.callout('info')}`}>
    <p className="font-semibold">Changing positions</p>
    {lockedReason
      ? <p>{lockedReason}</p>
      : <>
        <ol className="grid gap-2 sm:grid-cols-4">
          {steps.map((item, index) => {
            const number = (index + 1) as QtEditStep;
            const state = step > number ? 'done' : step === number ? 'current' : 'todo';
            return <li key={item.title} aria-current={state === 'current' ? 'step' : undefined}
              className={`rounded-lg border px-3 py-2 text-xs ${state === 'current' ? 'border-blue-500 bg-blue-500/10 font-medium' :
                state === 'done' ? 'border-emerald-500/40 opacity-80' : 'border-transparent opacity-70'}`}>
              <span className="block font-semibold">{state === 'done' ? '✓ ' : ''}{number}. {item.title}</span>
              <span className="block">{item.detail}</span>
            </li>;
          })}
        </ol>
        <p role="status" aria-live="polite">{summary}</p>
        {note && <p className="text-xs">{note}</p>}
      </>}
    <ul className="list-disc space-y-1 pl-5 text-xs">
      <li>Futures trade in whole contracts; equities may be fractional. Nothing is rounded for you.</li>
      <li>The investor report shows exactly the quantities you confirm, not the MODEL recommendation.</li>
      <li>If the evaluation finds a risk breach, confirming asks for two different approvers before anything is published.</li>
    </ul>
  </section>;
}
