import React from 'react';
import { Home, TrendingUp, FileText, FlaskConical, Library, User } from 'lucide-react';
import { can } from '../domain/identity/user';
import { useAuth } from '../adapters/react/useAuth';
import { useTheme } from '../adapters/react/ThemeContext';

interface BottomNavProps {
  activeTab?: string;
  onTabChange?: (tab: string) => void;
}

export function BottomNav({ activeTab = 'portfolio', onTabChange }: BottomNavProps) {
  const { theme } = useTheme();
  const { user } = useAuth();
  const canManageBooks = can(user, 'manage_books');
  const canManageIncubation = can(user, 'manage_incubation');
  
  const tabs = [
    { id: 'portfolio', label: 'Portfolio', icon: Home },
    ...(canManageBooks ? [{ id: 'books', label: 'Books', icon: Library }] : []),
    ...(canManageIncubation ? [{ id: 'incubation', label: 'Incubation', icon: FlaskConical }] : []),
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
      <div
        style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}
        className="grid"
      >
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
