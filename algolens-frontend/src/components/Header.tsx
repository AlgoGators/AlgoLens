import React, { useState, useEffect } from 'react';
import { Bell, User, X } from 'lucide-react';
import logo from '../assets/logo.png';
import { useTheme } from '../adapters/react/ThemeContext';

interface HeaderProps {
  onProfileClick: () => void;
  onBuilderClick?: () => void;
  onHomeClick?: () => void;
  activeTab?: 'portfolio' | 'builder' | 'news' | 'profile';
}

export function Header({ onProfileClick, onBuilderClick, onHomeClick, activeTab = 'portfolio' }: HeaderProps) {
  const { theme } = useTheme();
  const [showNotification, setShowNotification] = useState(false);
  const [hasNewNotification, setHasNewNotification] = useState(false);

  const OUTLOOK_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=9199bf20-a13f-4107-85dc-02114787ef48&scope=https%3A%2F%2Foutlook.office.com%2F.default%20openid%20profile%20offline_access&redirect_uri=https%3A%2F%2Foutlook.live.com%2Fmail%2F&client-request-id=db1c7baa-e08c-3071-7a19-53c59751400e&response_mode=fragment&client_info=1&prompt=select_account&nonce=019b9607-602c-78ec-971e-ab36297d8aed&state=eyJpZCI6IjAxOWI5NjA3LTYwMmMtNzY4MS05NGI3LTkzZDZlZDI4ZjdiZiIsIm1ldGEiOnsiaW50ZXJhY3Rpb25UeXBlIjoicmVkaXJlY3QifX0%3D%7CaHR0cHM6Ly9vdXRsb29rLmxpdmUuY29tL21haWwvMC8_ZGVlcGxpbms9bWFpbCUyRjAlMkY&claims=%7B%22access_token%22%3A%7B%22xms_cc%22%3A%7B%22values%22%3A%5B%22CP1%22%5D%7D%7D%7D&x-client-SKU=msal.js.browser&x-client-VER=4.26.0&response_type=code&code_challenge=edvy3GffheuAG3xMagQGunjdE7B2ST-J3LKoL2izw9Q&code_challenge_method=S256&cobrandid=ab0455a0-8d03-46b9-b18b-df2f57b9e44c&fl=dob,flname,wld';

  // Check if it's 9:30 AM EST or later today
  useEffect(() => {
    const checkNotificationTime = () => {
      const now = new Date();
      // Convert to EST (UTC-5)
      const estOffset = -5 * 60; // EST offset in minutes
      const localOffset = now.getTimezoneOffset();
      const estTime = new Date(now.getTime() + (localOffset + estOffset) * 60000);

      const hours = estTime.getHours();
      const minutes = estTime.getMinutes();

      // Check if it's 9:30 AM EST or later (until end of day)
      if (hours > 9 || (hours === 9 && minutes >= 30)) {
        // Check if notification was already dismissed today
        const lastDismissed = localStorage.getItem('notificationDismissed');
        const today = estTime.toDateString();

        if (lastDismissed !== today) {
          setHasNewNotification(true);
        }
      }
    };

    checkNotificationTime();
    // Check every minute
    const interval = setInterval(checkNotificationTime, 60000);
    return () => clearInterval(interval);
  }, []);

  const handleDismissNotification = () => {
    const now = new Date();
    const estOffset = -5 * 60;
    const localOffset = now.getTimezoneOffset();
    const estTime = new Date(now.getTime() + (localOffset + estOffset) * 60000);

    localStorage.setItem('notificationDismissed', estTime.toDateString());
    setHasNewNotification(false);
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
                {hasNewNotification && (
                  <span className="absolute top-1 right-1 w-2 h-2 bg-orange-500 rounded-full"></span>
                )}
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
                    {hasNewNotification ? (
                      <div className={`p-3 rounded-lg ${theme === 'dark' ? 'bg-gray-800' : 'bg-orange-50'}`}>
                        <div className="flex items-start gap-3">
                          <div className="w-2 h-2 bg-orange-500 rounded-full mt-2 flex-shrink-0"></div>
                          <div className="flex-1">
                            <p className={`text-sm font-medium ${theme === 'dark' ? 'text-white' : 'text-gray-900'}`}>
                              Daily Trading Report Available
                            </p>
                            <p className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}`}>
                              Check your email for today's trading performance report.
                            </p>
                            <div className="flex items-center gap-2 mt-3">
                              <a
                                href={OUTLOOK_URL}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs bg-orange-500 text-white px-3 py-1.5 rounded hover:bg-orange-600 transition-colors"
                              >
                                Open Email
                              </a>
                              <button
                                onClick={handleDismissNotification}
                                className={`text-xs px-3 py-1.5 rounded transition-colors ${theme === 'dark'
                                  ? 'text-gray-400 hover:text-white hover:bg-gray-700'
                                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
                                  }`}
                              >
                                Dismiss
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    ) : (
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