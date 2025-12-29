import React from 'react';
import { Search, Bell, User, Users } from 'lucide-react';
import logo from '../assets/logo.png';
import { useTheme } from '../contexts/ThemeContext';

interface HeaderProps {
  onProfileClick: () => void;
  onBuilderClick?: () => void;
}

export function Header({ onProfileClick, onBuilderClick }: HeaderProps) {
  const { theme } = useTheme();
  
  return (
    <header className={`sticky top-0 z-10 border-b ${
      theme === 'dark' 
        ? 'bg-black border-gray-800' 
        : 'bg-white border-gray-200'
    }`}>
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-3 md:py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-3">
              <img src={logo} alt="ALGO" className="h-6 md:h-8" />
              <div className="hidden md:block">
                <div className={`text-xs ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Student Investment Fund
                </div>
              </div>
            </div>
            
            <nav className="hidden md:flex items-center gap-6">
              <button className={`transition-colors ${
                theme === 'dark' 
                  ? 'text-white hover:text-orange-500' 
                  : 'text-black hover:text-orange-500'
              }`}>
                Portfolio
              </button>
              <button 
                onClick={onBuilderClick}
                className={`transition-colors ${
                  theme === 'dark' 
                    ? 'text-gray-400 hover:text-orange-500' 
                    : 'text-gray-500 hover:text-orange-500'
                }`}
              >
                Strategy Builder
              </button>
            </nav>
          </div>
          
          <div className="flex items-center gap-3 md:gap-4">
            <button className={`p-2 rounded-full transition-colors ${
              theme === 'dark' 
                ? 'hover:bg-gray-900' 
                : 'hover:bg-gray-100'
            }`}>
              <Search className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
              }`} />
            </button>
            <button className={`p-2 rounded-full transition-colors relative ${
              theme === 'dark' 
                ? 'hover:bg-gray-900' 
                : 'hover:bg-gray-100'
            }`}>
              <Bell className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
              }`} />
              <span className="absolute top-1 right-1 w-2 h-2 bg-orange-500 rounded-full"></span>
            </button>
            <button 
              onClick={onProfileClick}
              className={`p-2 rounded-full transition-colors ${
                theme === 'dark' 
                  ? 'hover:bg-gray-900' 
                  : 'hover:bg-gray-100'
              }`}
            >
              <User className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
              }`} />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}