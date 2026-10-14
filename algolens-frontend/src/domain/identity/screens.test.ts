import { describe, expect, it } from 'vitest';
import {
  availableScreens,
  landingScreen,
  NO_ACCESS,
  parseScreenAccess,
  screensChanged,
  toggleScreen,
  type ScreenAccess,
  isAdminRole,
} from './screens';

describe('parseScreenAccess', () => {
  it('drops unknown screens and orders them for landing', () => {
    expect(parseScreenAccess({ screens: ['investor', 'admin', 'member', 'qt'], is_admin: true })).toEqual({
      screens: ['qt', 'member', 'investor'],
      isAdmin: true,
    });
  });

  it.each([null, undefined, {}, { screens: 'qt' }, { is_admin: 'yes' }])('treats %j as no access', (data) => {
    expect(parseScreenAccess(data)).toEqual(NO_ACCESS);
  });
});

describe('landingScreen', () => {
  it('is null with no screen and no admin role (access pending)', () => {
    expect(landingScreen(NO_ACCESS)).toBeNull();
    expect(landingScreen(NO_ACCESS, 'member')).toBeNull();
  });

  it('opens on qt, then member, then investor', () => {
    expect(landingScreen({ screens: ['qt', 'member'], isAdmin: false })).toBe('qt');
    expect(landingScreen({ screens: ['member', 'investor'], isAdmin: false })).toBe('member');
    expect(landingScreen({ screens: ['investor'], isAdmin: false })).toBe('investor');
  });

  it('keeps the remembered screen while it is still held', () => {
    const access: ScreenAccess = { screens: ['qt', 'member'], isAdmin: true };
    expect(landingScreen(access, 'member')).toBe('member');
    expect(landingScreen(access, 'admin')).toBe('admin');
    expect(landingScreen({ screens: ['member'], isAdmin: false }, 'qt')).toBe('member');
    expect(landingScreen({ screens: ['member'], isAdmin: false }, 'bogus')).toBe('member');
  });

  it('sends an admin with no screen to Admin', () => {
    expect(landingScreen({ screens: [], isAdmin: true })).toBe('admin');
  });
});

describe('availableScreens', () => {
  it('lists held screens and Admin last for admins', () => {
    expect(availableScreens({ screens: ['qt', 'investor'], isAdmin: true })).toEqual(['qt', 'investor', 'admin']);
    expect(availableScreens({ screens: ['member'], isAdmin: false })).toEqual(['member']);
  });
});

describe('admin form state', () => {
  it('toggles a screen on and off in landing order', () => {
    expect(toggleScreen(['member'], 'qt', true)).toEqual(['qt', 'member']);
    expect(toggleScreen(['qt', 'member'], 'qt', false)).toEqual(['member']);
    expect(toggleScreen(['member'], 'member', true)).toEqual(['member']);
  });

  it('notices a changed draft regardless of order', () => {
    expect(screensChanged(['qt', 'member'], ['member', 'qt'])).toBe(false);
    expect(screensChanged(['member'], ['member', 'investor'])).toBe(true);
    expect(screensChanged(['member'], [])).toBe(true);
  });
});

describe('isAdminRole', () => {
  it('is exec_board or admin', () => {
    expect(isAdminRole('exec_board')).toBe(true);
    expect(isAdminRole('admin')).toBe(true);
    expect(isAdminRole('team_lead')).toBe(false);
    expect(isAdminRole(null)).toBe(false);
  });
});

