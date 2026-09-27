// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AccountSettings } from './AccountSettings';
import { BottomNav } from './BottomNav';
import { Header } from './Header';
import { LoginView } from './LoginView';
import { PrivacySettings } from './PrivacySettings';
import { ProfileScreen } from './ProfileScreen';

let role = 'admin';
vi.mock('../adapters/react/useAuth', () => ({
  useAuth: () => ({ user: { role, email: 'member@example.test', first_name: 'Ada', last_name: 'Lovelace' }, login: vi.fn() }),
}));
vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light', toggleTheme: vi.fn() }),
}));

beforeEach(() => { role = 'admin'; });

it('keeps Books reachable in internal mobile navigation only', () => {
  const { rerender } = render(<BottomNav />);
  expect(screen.getByRole('button', { name: /Books/i })).toBeTruthy();
  role = 'subscriber';
  rerender(<BottomNav />);
  expect(screen.queryByRole('button', { name: /Books/i })).toBeNull();
});

it('labels icon controls and exposes no fake password-reset action', () => {
  render(<Header onProfileClick={() => {}} />);
  expect(screen.getByRole('button', { name: 'Notifications' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Open account' })).toBeTruthy();
  render(<LoginView />);
  expect(screen.getByLabelText('Email')).toBeTruthy();
  expect(screen.getByLabelText('Password')).toBeTruthy();
  expect((screen.getByRole('button', { name: /Forgot your password/i }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/Password reset is not available/i)).toBeTruthy();
});

it('marks account and privacy rows with no implementation as unavailable', () => {
  const { unmount } = render(<AccountSettings onBack={() => {}} />);
  expect(screen.getByRole('button', { name: 'Back to account' })).toBeTruthy();
  expect((screen.getByRole('button', { name: /Full Name/i }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getAllByText('Not available yet').length).toBeGreaterThan(5);
  unmount();
  render(<PrivacySettings onBack={() => {}} />);
  expect(screen.getByRole('button', { name: 'Back to account' })).toBeTruthy();
  for (const name of ['Trusted Devices', 'Active Sessions', 'Data Sharing', 'Download Your Data', 'Privacy Policy', 'Notification Preferences']) {
    expect((screen.getByRole('button', { name: new RegExp(name, 'i') }) as HTMLButtonElement).disabled).toBe(true);
  }
});

describe('profile modal lifecycle', () => {
  it('is labelled, takes focus and closes on Escape', () => {
    const onClose = vi.fn();
    render(<ProfileScreen onClose={onClose} onLogout={() => {}} onNavigate={() => {}} />);
    const dialog = screen.getByRole('dialog', { name: 'Account' });
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
