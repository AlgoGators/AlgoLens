// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import App from './App';

let user: object | null = null;
vi.mock('./adapters/react/useAuth', () => ({
  useAuth: () => ({ user, logout: vi.fn(), isLoading: false }),
}));
vi.mock('./adapters/react/AuthContext', () => ({ AuthProvider: ({ children }: any) => children }));
vi.mock('./adapters/react/ThemeContext', () => ({ ThemeProvider: ({ children }: any) => children }));
vi.mock('./components/LoginView', () => ({ LoginView: (p: any) => <div>Login screen<button onClick={p.onNavigateToRegister}>Join</button></div> }));
vi.mock('./components/RegisterView', () => ({ RegisterView: () => <div>Register screen</div> }));
vi.mock('./components/Dashboard', () => ({ Dashboard: () => <div>Dashboard screen</div> }));

it('resets the auth screen after authentication so logout returns to login', () => {
  user = null;
  const { rerender } = render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Join' }));
  expect(screen.getByText('Register screen')).toBeTruthy();

  user = { id: '1' };
  rerender(<App />);
  expect(screen.getByText('Dashboard screen')).toBeTruthy();

  user = null;
  rerender(<App />);
  expect(screen.getByText('Login screen')).toBeTruthy();
  expect(screen.queryByText('Register screen')).toBeNull();
});
