import React, { useState, useEffect } from 'react';
import { Bell, FlaskConical, Library, User, X } from 'lucide-react';
import logo from '../assets/logo.png';
import { isInternalRole } from '../domain/identity/user';
import { useAuth } from '../adapters/react/useAuth';
import { useTheme } from '../adapters/react/ThemeContext';

interface HeaderProps {
  onProfileClick: () => void;
  onBuilderClick?: () => void;
  onHomeClick?: () => void;
  onIncubationClick?: () => void;
  onBooksClick?: () => void;
  activeTab?: 'portfolio' | 'incubation' | 'builder' | 'books' | 'news' | 'profile';
}

export function Header({
  onProfileClick,
  onBuilderClick,
  onHomeClick,
  onIncubationClick,
  onBooksClick,
  activeTab = 'portfolio',
}: HeaderProps) {
  const { theme } = useTheme();
  const { user } = useAuth();
  const [showNotification, setShowNotification] = useState(false);
  const isInternalMember = isInternalRole(user?.role);


  // There was a clock here, not a data source. Any weekday after 09:30 EST it
  // asserted "Daily Trading Report Available" -- weekends, holidays, and days
  // no report was produced included -- with an unread dot indistinguishable
  // from a real alert. Nothing checked that a report existed.
  //
  // There is no endpoint that reports whether one was generated. Until there
  // is, the bell shows what is actually known: nothing.

  const handleDismissNotification = () => {
    setShowNotification(false);
  };

  return (
    <header className={`sticky top-0 z-10 border-b ${theme === 'dark'
      ? 'bg-black border-gray-800'
      : 'bg-white border-gray-200'
      }`}>
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-3 md:py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-8">
            <button
              onClick={onHomeClick}
              className="flex items-center gap-3 cursor-pointer"
            >
              <img src={logo} alt="ALGO" className="h-6 md:h-8" style={theme === 'dark' ? { filter: 'invert(1) hue-rotate(180deg)' } : undefined} />
              <div className="hidden md:block">
                <div className={`text-xs ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                  }`}>
                  Student Investment Fund
                </div>
              </div>
            </button>

            <nav className="hidden md:flex items-center gap-6">
              <button
                onClick={onHomeClick}
                className={`transition-colors ${activeTab === 'portfolio'
                  ? theme === 'dark'
                    ? 'text-white font-semibold'
                    : 'text-black font-semibold'
                  : theme === 'dark'
                    ? 'text-gray-400 hover:text-orange-500'
                    : 'text-gray-500 hover:text-orange-500'
                  }`}>
                Portfolio
              </button>
              <button
                onClick={onBuilderClick}
                className={`transition-colors ${activeTab === 'builder'
                  ? theme === 'dark'
                    ? 'text-white font-semibold'
                    : 'text-black font-semibold'
                  : theme === 'dark'
                    ? 'text-gray-400 hover:text-orange-500'
                    : 'text-gray-500 hover:text-orange-500'
                  }`}
              >
                Strategy Builder
              </button>
              {isInternalMember && (
                <button
                  onClick={onBooksClick}
                  className={`transition-colors flex items-center gap-2 ${activeTab === 'books'
                    ? theme === 'dark'
                      ? 'text-white font-semibold'
                      : 'text-black font-semibold'
                    : theme === 'dark'
                      ? 'text-gray-400 hover:text-orange-500'
                      : 'text-gray-500 hover:text-orange-500'
                    }`}
                >
                  <Library className="w-4 h-4" />
                  Books
                </button>
              )}
              {isInternalMember && (
                <button
                  onClick={onIncubationClick}
                  className={`transition-colors flex items-center gap-2 ${activeTab === 'incubation'
                    ? theme === 'dark'
                      ? 'text-white font-semibold'
                      : 'text-black font-semibold'
                    : theme === 'dark'
                      ? 'text-gray-400 hover:text-orange-500'
                      : 'text-gray-500 hover:text-orange-500'
                    }`}
                >
                  <FlaskConical className="w-4 h-4" />
                  Incubation
                </button>
              )}
            </nav>
          </div>

          <div className="flex items-center gap-3 md:gap-4">
            <div className="relative">
              <button
                onClick={() => setShowNotification(!showNotification)}
                className={`p-2 rounded-full transition-colors relative ${theme === 'dark'
                  ? 'hover:bg-gray-900'
                  : 'hover:bg-gray-100'
                  }`}
              >
                <Bell className={`w-5 h-5 ${theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
                  }`} />
                {/* No unread dot: nothing here knows whether anything is
                    unread. It used to appear on a timer. */}
              </button>

              {/* Notification Dropdown */}
              {showNotification && (
                <div className={`absolute right-0 top-12 w-80 rounded-lg shadow-xl border z-50 ${theme === 'dark'
                  ? 'bg-gray-900 border-gray-700'
                  : 'bg-white border-gray-200'
                  }`}>
                  <div className={`flex items-center justify-between p-3 border-b ${theme === 'dark' ? 'border-gray-700' : 'border-gray-200'
                    }`}>
                    <h3 className="font-semibold">Notifications</h3>
                    <button
                      onClick={() => setShowNotification(false)}
                      className={`p-1 rounded hover:bg-gray-800 ${theme === 'dark' ? 'hover:bg-gray-800' : 'hover:bg-gray-100'}`}
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>

                  <div className="p-3">
                    {(

                      <p className={`text-sm text-center py-4 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                        No new notifications
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
            <button
              onClick={onProfileClick}
              className={`p-2 rounded-full transition-colors ${theme === 'dark'
                ? 'hover:bg-gray-900'
                : 'hover:bg-gray-100'
                }`}
            >
              <User className={`w-5 h-5 ${theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
                }`} />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
