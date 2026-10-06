import { describe, expect, it } from 'vitest';

import { can, decodeUser } from './user';

describe('identity capabilities', () => {
  it('accepts explicitly provisioned config capabilities without granting positions', () => {
    const user = decodeUser({ id: '1', email: 'a@example.com', capabilities: ['edit_config', 'approve_config'] });
    expect(can(user, 'edit_config')).toBe(true);
    expect(can(user, 'approve_config')).toBe(true);
    expect(can(user, 'edit_qt_book')).toBe(false);
    expect(can(user, 'approve_qt_override')).toBe(false);
  });
  it('uses only server-returned capabilities for UI authority', () => {
    const user = decodeUser({
      id: '7', email: 'john@example.com', first_name: 'John', last_name: 'Riley',
      role: 'general_member', capabilities: ['view_internal', 'edit_qt_book'],
    });
    expect(can(user, 'view_internal')).toBe(true);
    expect(can(user, 'edit_qt_book')).toBe(true);
    expect(can(user, 'approve_qt_override')).toBe(false);
    expect(can({ ...user, role: 'admin', capabilities: [] }, 'view_internal')).toBe(false);
  });

  it('rejects missing, duplicate, or unknown capability payloads', () => {
    expect(() => decodeUser({ id: '1', email: 'a@example.com', role: 'admin' })).toThrow();
    expect(() => decodeUser({ id: '1', email: 'a@example.com', role: 'admin', capabilities: ['view_internal', 'view_internal'] })).toThrow();
    expect(() => decodeUser({ id: '1', email: 'a@example.com', role: 'admin', capabilities: ['invented'] })).toThrow();
  });
});
