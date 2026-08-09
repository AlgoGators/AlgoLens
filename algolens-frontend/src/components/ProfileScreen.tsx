import React from 'react';
import { X, Moon, Sun, LogOut, ChevronRight } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';
import { useAuth } from '../adapters/react/AuthContext';
import logo from '../assets/logo.png';

interface ProfileScreenProps {
  onClose: () => void;
  onLogout: () => void;
  onNavigate: (screen: 'account' | 'privacy') => void;
}

export function ProfileScreen({ onClose, onLogout, onNavigate }: ProfileScreenProps) {
  const { theme, toggleTheme } = useTheme();
  const { user } = useAuth();

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end md:items-center justify-center">
      <div className={`w-full md:w-[500px] md:max-h-[80vh] md:rounded-2xl overflow-hidden ${
        theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
      }`}>
        {/* Header */}
        <div className={`flex items-center justify-between p-4 border-b ${
          theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
          <h2 className="text-xl">Account</h2>
          <button
            onClick={onClose}
            className={`p-2 rounded-full transition-colors ${
              theme === 'dark' ? 'hover:bg-gray-900' : 'hover:bg-gray-100'
            }`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Profile Info */}
        <div className="p-6">
          <div className="flex items-center gap-4 mb-6">
            
            <div>
              <h3 className="text-xl mb-1">
                {user?.first_name && user?.last_name
                  ? `${user.first_name} ${user.last_name}`
                  : user?.email || 'User'}
              </h3>
              <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}>
                {user?.email || 'No email'}
              </p>
            </div>
          </div>

          {/* Menu Items */}
          <div className={`border rounded-lg overflow-hidden ${
            theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
          }`}>
            {/* Theme Toggle */}
            <button
              onClick={toggleTheme}
              className={`w-full flex items-center justify-between p-4 border-b transition-colors ${
                theme === 'dark' 
                  ? 'border-gray-800 hover:bg-gray-900' 
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <div className="flex items-center gap-3">
                {theme === 'dark' ? (
                  <Moon className="w-5 h-5 text-orange-500" />
                ) : (
                  <Sun className="w-5 h-5 text-orange-500" />
                )}
                <div className="text-left">
                  <div>Appearance</div>
                  <div className={`text-sm ${
                    theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                  }`}>
                    {theme === 'dark' ? 'Dark Mode' : 'Light Mode'}
                  </div>
                </div>
              </div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>

            {/* Account Settings */}
            <button
              onClick={() => onNavigate('account')}
              className={`w-full flex items-center justify-between p-4 border-b transition-colors ${
                theme === 'dark' 
                  ? 'border-gray-800 hover:bg-gray-900' 
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <div className="text-left">Account Settings</div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>

            {/* Privacy & Security */}
            <button
              onClick={() => onNavigate('privacy')}
              className={`w-full flex items-center justify-between p-4 transition-colors ${
                theme === 'dark' 
                  ? 'hover:bg-gray-900' 
                  : 'hover:bg-gray-50'
              }`}
            >
              <div className="text-left">Privacy & Security</div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>
          </div>

          {/* Sign Out Button */}
          <button
            onClick={onLogout}
            className="w-full mt-6 flex items-center justify-center gap-2 p-4 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors"
          >
            <LogOut className="w-5 h-5" />
            <span>Sign Out</span>
          </button>
        </div>
      </div>
    </div>
  );
}