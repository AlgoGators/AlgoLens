import { describe, it, expect } from 'vitest';
import { describeServedBook } from './bookLabel';

describe('describeServedBook', () => {
  it('returns null when the response does not carry a book', () => {
    expect(describeServedBook({})).toBeNull();
  });

  it('names each known book', () => {
    expect(describeServedBook({ book: 'qt' })).toBe('QT book');
    expect(describeServedBook({ book: 'system' })).toBe('System book');
    expect(describeServedBook({ book: 'qt_proposal' })).toBe('QT proposal');
  });

  it('says when the default QT book fell back to system', () => {
    expect(describeServedBook({ book: 'system', fellBack: true })).toBe(
      'System book (no QT book yet)',
    );
  });

  it('shows an unknown book verbatim rather than hiding it', () => {
    expect(describeServedBook({ book: 'other' })).toBe('other');
  });
});
