import { describe, expect, it } from 'vitest';
import { isInternalRole } from './user';

describe('isInternalRole', () => {
  it.each(['admin', 'exec_board', 'general_member'])('admits %s', (role) => {
    expect(isInternalRole(role)).toBe(true);
  });

  it.each([undefined, null, '', 'investor'])('refuses %s', (role) => {
    expect(isInternalRole(role)).toBe(false);
  });
});
