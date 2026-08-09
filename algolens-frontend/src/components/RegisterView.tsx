import React, { useState } from 'react';
import logo from '../assets/logo.png';
import { useAuth } from '../adapters/react/AuthContext';

interface RegisterViewProps {
  onBackToLogin: () => void;
}

// Get API URL from environment variable or default to localhost
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

export function RegisterView({ onBackToLogin }: RegisterViewProps) {
  const [step, setStep] = useState<'email' | 'details'>('email');
  const [email, setEmail] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { register } = useAuth();

  const handleEmailSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const response = await fetch(`${API_URL}/auth/check-email`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      if (response.ok && !data.registered) {
        setStep('details');
      } else if (data.registered) {
        setError('Account already registered. Please login instead.');
      } else {
        setError(data.message || 'Email not authorized. Contact an administrator.');
      }
    } catch (err) {
      setError('Failed to verify email. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    // Mirror the server-side policy (backend enforces >= 12; this is UX only).
    if (password.length < 12) {
      setError('Password must be at least 12 characters');
      return;
    }

    setIsLoading(true);

    try {
      await register(email, password, firstName, lastName);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-white text-black flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-12">
          <img src={logo} alt="ALGO" className="h-16 mx-auto mb-4" />
          <h1 className="text-2xl mb-2">Join the Fund</h1>
          <p className="text-gray-600">Create your account</p>
        </div>

        {step === 'email' ? (
          <form onSubmit={handleEmailSubmit} className="space-y-4">
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
                {error}
              </div>
            )}

            <div>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-white border-b-2 border-gray-300 px-0 py-3 text-black focus:outline-none focus:border-orange-500 transition-colors placeholder:text-gray-400"
                placeholder="Student email"
                required
                disabled={isLoading}
              />
            </div>

            <div className="text-sm text-gray-600">
              Only pre-authorized email addresses can register. Contact an administrator if you don't have access.
            </div>

            <button
              type="submit"
              className="w-full bg-orange-500 text-white rounded-full py-4 hover:bg-orange-600 transition-colors mt-8 disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={isLoading}
            >
              {isLoading ? 'Checking...' : 'Continue'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleRegisterSubmit} className="space-y-4">
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
                {error}
              </div>
            )}

            <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded">
              Email verified! Complete your registration below.
            </div>

            <div>
              <input
                id="firstName"
                type="text"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                className="w-full bg-white border-b-2 border-gray-300 px-0 py-3 text-black focus:outline-none focus:border-orange-500 transition-colors placeholder:text-gray-400"
                placeholder="First name"
                required
                disabled={isLoading}
              />
            </div>

            <div>
              <input
                id="lastName"
                type="text"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                className="w-full bg-white border-b-2 border-gray-300 px-0 py-3 text-black focus:outline-none focus:border-orange-500 transition-colors placeholder:text-gray-400"
                placeholder="Last name"
                required
                disabled={isLoading}
              />
            </div>

            <div>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-white border-b-2 border-gray-300 px-0 py-3 text-black focus:outline-none focus:border-orange-500 transition-colors placeholder:text-gray-400"
                placeholder="Password"
                required
                disabled={isLoading}
              />
            </div>

            <div>
              <input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full bg-white border-b-2 border-gray-300 px-0 py-3 text-black focus:outline-none focus:border-orange-500 transition-colors placeholder:text-gray-400"
                placeholder="Confirm password"
                required
                disabled={isLoading}
              />
            </div>

            <button
              type="submit"
              className="w-full bg-orange-500 text-white rounded-full py-4 hover:bg-orange-600 transition-colors mt-8 disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={isLoading}
            >
              {isLoading ? 'Creating Account...' : 'Create Account'}
            </button>

            <button
              type="button"
              onClick={() => setStep('email')}
              className="w-full text-gray-600 hover:text-gray-800 text-sm"
              disabled={isLoading}
            >
              Use a different email
            </button>
          </form>
        )}

        <div className="mt-8 pt-8 border-t border-gray-200 text-center">
          <p className="text-gray-500 text-sm">
            Already have an account?{' '}
            <button onClick={onBackToLogin} className="text-orange-500 hover:text-orange-600">
              Sign in
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
