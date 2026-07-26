/**
 * The acknowledge-once rule is the whole safety mechanism, so it is tested here
 * rather than only being clickable in a browser.
 *
 * The backend answers a risk-breaching write with 409 and the list of breaches.
 * The user must then take a SECOND, deliberate action to proceed. If the UI ever
 * resubmits automatically on 409, the risk gate silently becomes a no-op and
 * nobody finds out until an audit.
 */
import { describe, it, expect } from 'vitest'
import {
  initialState, reduce, canSubmit, buildDiff,
  type RiskCheck,
} from './positionEdit'

const BREACHED: RiskCheck = {
  evaluated: true,
  passed: false,
  breaches: [{
    limit: 'max_symbol_notional', limit_value: 300000, actual: 500000,
    message: 'ES notional 500,000 exceeds its cap of 300,000',
  }],
}

describe('submission state machine', () => {
  it('starts idle with nothing to report', () => {
    expect(initialState()).toEqual({ phase: 'idle', breaches: [], message: null })
  })

  it('moves to submitting when the user submits', () => {
    expect(reduce(initialState(), { type: 'submit' }).phase).toBe('submitting')
  })

  it('parks on needs_acknowledgement when the backend reports a breach', () => {
    const s = reduce(reduce(initialState(), { type: 'submit' }),
                     { type: 'breach', risk_check: BREACHED })
    expect(s.phase).toBe('needs_acknowledgement')
    expect(s.breaches).toHaveLength(1)
  })

  it('does NOT treat a breach as submittable on its own', () => {
    // The guard against auto-retry: reaching needs_acknowledgement must not
    // itself produce a submitting state.
    const s = reduce(reduce(initialState(), { type: 'submit' }),
                     { type: 'breach', risk_check: BREACHED })
    expect(s.phase).not.toBe('submitting')
    expect(s.phase).not.toBe('done')
    expect(s.phase).toBe('needs_acknowledgement')
  })

  it('requires a fresh submit event to move on from an acknowledged breach', () => {
    const acked = reduce(reduce(reduce(initialState(), { type: 'submit' }),
                                { type: 'breach', risk_check: BREACHED }),
                         { type: 'submit' })
    expect(acked.phase).toBe('submitting')
    expect(acked.breaches).toHaveLength(1)  // breaches stay visible while resubmitting
  })

  it('clears the breach list when the user edits the form again', () => {
    const s = reduce(reduce(reduce(initialState(), { type: 'submit' }),
                            { type: 'breach', risk_check: BREACHED }),
                     { type: 'edited' })
    expect(s.phase).toBe('idle')
    expect(s.breaches).toEqual([])
  })

  it('a flat rejection is an error, not something to acknowledge', () => {
    // The other 409: no engine rows exist for this book, so there is nothing to
    // override. Offering an "acknowledge" button here would be a lie.
    const s = reduce(reduce(initialState(), { type: 'submit' }),
                     { type: 'rejected', message: 'No existing positions' })
    expect(s.phase).toBe('error')
    expect(s.breaches).toEqual([])
    expect(s.message).toBe('No existing positions')
  })

  it('reaches done on success', () => {
    const s = reduce(reduce(initialState(), { type: 'submit' }), { type: 'succeeded' })
    expect(s.phase).toBe('done')
  })

  it('ignores a success that did not come from an in-flight submit', () => {
    // Guards the acknowledge-once rule at the machine level rather than trusting
    // the caller to dispatch in the right order.
    const breached = reduce(reduce(initialState(), { type: 'submit' }),
                            { type: 'breach', risk_check: BREACHED })
    const s = reduce(breached, { type: 'succeeded' })
    expect(s.phase).toBe('needs_acknowledgement')
  })
})

describe('canSubmit', () => {
  it('rejects an empty reason', () => {
    expect(canSubmit('', '12')).toBe(false)
  })
  it('rejects a whitespace-only reason', () => {
    expect(canSubmit('   ', '12')).toBe(false)
  })
  it('rejects a non-numeric quantity', () => {
    expect(canSubmit('trimming', 'twelve')).toBe(false)
  })
  it('rejects an empty quantity', () => {
    expect(canSubmit('trimming', '')).toBe(false)
  })
  it('rejects a whitespace-only quantity', () => {
    expect(canSubmit('trimming', '   ')).toBe(false)
  })
  it('accepts zero because it means close the position', () => {
    expect(canSubmit('flattening', '0')).toBe(true)
  })
  it('accepts a negative quantity because short is a position', () => {
    expect(canSubmit('going short', '-4')).toBe(true)
  })
  it('accepts a well-formed edit', () => {
    expect(canSubmit('Trimming ahead of CPI', '12')).toBe(true)
  })
})

describe('buildDiff', () => {
  it('describes a new position as coming from nothing', () => {
    const d = buildDiff(null, { quantity: 12, average_price: 5200 })
    expect(d).toContainEqual({ field: 'Quantity', from: '-', to: '12' })
  })
  it('shows both sides of a quantity change', () => {
    const d = buildDiff({ quantity: 10, average_price: 5000 },
                        { quantity: 12, average_price: 5000 })
    expect(d).toContainEqual({ field: 'Quantity', from: '10', to: '12' })
  })
  it('omits fields that did not change', () => {
    const d = buildDiff({ quantity: 10, average_price: 5000 },
                        { quantity: 12, average_price: 5000 })
    expect(d.find(l => l.field === 'Average price')).toBeUndefined()
  })
  it('calls out a close-to-zero explicitly', () => {
    const d = buildDiff({ quantity: 10, average_price: 5000 },
                        { quantity: 0, average_price: 5000 })
    expect(d).toContainEqual({ field: 'Quantity', from: '10', to: '0 (closing)' })
  })
  it('omits the price line when no new price was supplied', () => {
    // A blank price field means "leave it alone", not "set it to nothing" --
    // the backend only overwrites average_price when a value is present.
    const d = buildDiff({ quantity: 10, average_price: 5000 },
                        { quantity: 12, average_price: null })
    expect(d.find(l => l.field === 'Average price')).toBeUndefined()
  })
})
