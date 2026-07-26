/**
 * Pure logic behind the position editor.
 *
 * Kept free of React and fetch so the acknowledge-once rule can be tested
 * directly. That rule is the reason the risk gate has any teeth: the backend
 * answers a breaching write with 409, and the user must take a second,
 * deliberate action before it goes through. A component that resubmitted
 * automatically would satisfy every visual review and quietly disable the gate.
 */

export type RiskBreach = {
  limit: string
  limit_value: number
  actual: number
  message: string
}

export type RiskCheck = {
  evaluated: boolean
  passed: boolean
  breaches: RiskBreach[]
}

export type SubmitPhase =
  | 'idle'
  | 'submitting'
  | 'needs_acknowledgement'
  | 'error'
  | 'done'

export type SubmitState = {
  phase: SubmitPhase
  breaches: RiskBreach[]
  message: string | null
}

export type SubmitEvent =
  | { type: 'submit' }
  | { type: 'breach'; risk_check: RiskCheck }
  | { type: 'rejected'; message: string }
  | { type: 'succeeded' }
  | { type: 'edited' }

export function initialState(): SubmitState {
  return { phase: 'idle', breaches: [], message: null }
}

export function reduce(state: SubmitState, event: SubmitEvent): SubmitState {
  switch (event.type) {
    case 'submit':
      // Deliberately preserves `breaches`: when the user is resubmitting to
      // acknowledge a breach, the banner must stay on screen rather than
      // flickering away and reappearing.
      return { ...state, phase: 'submitting', message: null }

    case 'breach':
      return {
        phase: 'needs_acknowledgement',
        breaches: event.risk_check.breaches,
        message: null,
      }

    case 'rejected':
      // NOT acknowledgeable. This is the other 409 (and 400/403/500): the write
      // is refused outright, so there is nothing for the user to override.
      return { phase: 'error', breaches: [], message: event.message }

    case 'succeeded':
      return { phase: 'done', breaches: [], message: null }

    case 'edited':
      // Any change to the form invalidates a verdict computed from the old
      // values. Falling back to idle forces a fresh check.
      return initialState()
  }
}

export function canSubmit(reason: string, quantity: string): boolean {
  if (reason.trim().length === 0) return false
  if (quantity.trim().length === 0) return false
  // Number('') is 0, which is why the empty check comes first.
  return Number.isFinite(Number(quantity))
}

export type DiffLine = { field: string; from: string; to: string }

export function buildDiff(
  before: { quantity: number; average_price: number | null } | null,
  after: { quantity: number; average_price: number | null },
): DiffLine[] {
  const lines: DiffLine[] = []

  const beforeQty = before ? String(before.quantity) : '-'
  const afterQty = after.quantity === 0 ? '0 (closing)' : String(after.quantity)
  if (!before || before.quantity !== after.quantity) {
    lines.push({ field: 'Quantity', from: beforeQty, to: afterQty })
  }

  const bp = before?.average_price ?? null
  if (after.average_price !== null && bp !== after.average_price) {
    lines.push({
      field: 'Average price',
      from: bp === null ? '-' : String(bp),
      to: String(after.average_price),
    })
  }

  return lines
}
