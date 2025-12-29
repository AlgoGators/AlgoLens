import React, { useState } from 'react';
import logo from '../assets/logo.png';

interface LoginViewProps {
  onLogin: () => void;
}

export function LoginView({ onLogin }: LoginViewProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onLogin();
  };

  return (
    <div className="min-h-screen bg-white text-black flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-12">
          <img src={logo} alt="ALGO" className="h-16 mx-auto mb-4" />
          <h1 className="text-2xl mb-2">Student Investment Fund</h1>
          <p className="text-gray-600">Member Portal</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-white border-b-2 border-gray-300 px-0 py-3 text-black focus:outline-none focus:border-orange-500 transition-colors placeholder:text-gray-400"
              placeholder="Student email"
              required
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
            />
          </div>

          <button
            type="submit"
            className="w-full bg-orange-500 text-white rounded-full py-4 hover:bg-orange-600 transition-colors mt-8"
          >
            Access Fund Dashboard
          </button>
        </form>

        <div className="mt-6 text-center">
          <button className="text-orange-500 text-sm hover:text-orange-600">
            Forgot your password?
          </button>
        </div>

        <div className="mt-8 pt-8 border-t border-gray-200 text-center">
          <p className="text-gray-500 text-sm">
            Not a member yet?{' '}
            <button className="text-orange-500 hover:text-orange-600">
              Join the fund
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}