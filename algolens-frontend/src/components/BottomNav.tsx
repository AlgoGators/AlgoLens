import React from 'react';
import { Home, TrendingUp, FileText, User } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';

interface BottomNavProps {
  activeTab?: string;
  onTabChange?: (tab: string) => void;
}

export function BottomNav({ activeTab = 'portfolio', onTabChange }: BottomNavProps) {
  const { theme } = useTheme();
  
  const tabs = [
    { id: 'portfolio', label: 'Portfolio', icon: Home },
    { id: 'builder', label: 'Builder', icon: TrendingUp },
    { id: 'news', label: 'News', icon: FileText },
    { id: 'profile', label: 'Profile', icon: User },
  ];

  return (
    <nav className={`md:hidden fixed bottom-0 left-0 right-0 border-t ${
      theme === 'dark' 
        ? 'bg-black border-gray-800' 
        : 'bg-white border-gray-200'
    }`}>
      <div className="grid grid-cols-4">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange?.(tab.id)}
              className={`flex flex-col items-center gap-1 py-3 transition-colors ${
                isActive
                  ? 'text-orange-500'
                  : theme === 'dark'
                    ? 'text-gray-400 hover:text-white'
                    : 'text-gray-500 hover:text-black'
              }`}
            >
              <Icon className="w-5 h-5" />
              <span className="text-xs">{tab.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}