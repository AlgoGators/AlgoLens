import React, { useState } from 'react';
import { ArrowLeft, ChevronRight, User, Mail, Phone, MapPin, Briefcase, Calendar } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';
import { useAuth } from '../adapters/react/AuthContext';

interface AccountSettingsProps {
  onBack: () => void;
}

export function AccountSettings({ onBack }: AccountSettingsProps) {
  const { theme } = useTheme();
  const { user } = useAuth();

  const fullName = user?.first_name && user?.last_name
    ? `${user.first_name} ${user.last_name}`
    : 'Not set';

  const accountInfo = [
    { icon: User, label: 'Full Name', value: fullName, action: 'Edit' },
    { icon: Mail, label: 'Email', value: user?.email || 'Not set', action: 'Change' },
    { icon: Phone, label: 'Phone Number', value: 'Not set', action: 'Update' },
    { icon: MapPin, label: 'Address', value: 'Not set', action: 'Update' },
    { icon: Calendar, label: 'Date of Birth', value: 'Not set', action: 'Edit' },
    { icon: Briefcase, label: 'Role', value: user?.role || 'Not set', action: 'View' },
  ];

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className={`flex items-center gap-4 p-4 border-b ${
        theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
      }`}>
        <button
          onClick={onBack}
          className={`p-2 rounded-full transition-colors ${
            theme === 'dark' ? 'hover:bg-gray-900' : 'hover:bg-gray-100'
          }`}
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <h2 className="text-xl">Account Settings</h2>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {/* Personal Information */}
        <div className="mb-8">
          <h3 className={`text-sm uppercase tracking-wider mb-4 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            Personal Information
          </h3>
          <div className={`border rounded-lg overflow-hidden ${
            theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
          }`}>
            {accountInfo.map((item, index) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.label}
                  className={`w-full flex items-center justify-between p-4 transition-colors ${
                    theme === 'dark' 
                      ? 'hover:bg-gray-900' 
                      : 'hover:bg-gray-50'
                  } ${
                    index !== accountInfo.length - 1 
                      ? theme === 'dark' 
                        ? 'border-b border-gray-800' 
                        : 'border-b border-gray-200' 
                      : ''
                  }`}
                >
                  <div className="flex items-center gap-3 flex-1 text-left">
                    <Icon className={`w-5 h-5 ${
                      theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                    }`} />
                    <div>
                      <div className={`text-sm ${
                        theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                      }`}>
                        {item.label}
                      </div>
                      <div className="mt-1">{item.value}</div>
                    </div>
                  </div>
                  <span className="text-orange-500 text-sm">{item.action}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Account Actions */}
        <div className="mb-8">
          <h3 className={`text-sm uppercase tracking-wider mb-4 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            Account Actions
          </h3>
          <div className={`border rounded-lg overflow-hidden ${
            theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
          }`}>
            <button
              className={`w-full flex items-center justify-between p-4 border-b transition-colors ${
                theme === 'dark' 
                  ? 'border-gray-800 hover:bg-gray-900' 
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <div className="text-left">
                <div>Change Password</div>
                <div className={`text-sm mt-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Update your account password
                </div>
              </div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>

            <button
              className={`w-full flex items-center justify-between p-4 border-b transition-colors ${
                theme === 'dark' 
                  ? 'border-gray-800 hover:bg-gray-900' 
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <div className="text-left">
                <div>Tax Documents</div>
                <div className={`text-sm mt-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  View and download tax forms
                </div>
              </div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>

            <button
              className={`w-full flex items-center justify-between p-4 border-b transition-colors ${
                theme === 'dark' 
                  ? 'border-gray-800 hover:bg-gray-900' 
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <div className="text-left">
                <div>Bank Accounts</div>
                <div className={`text-sm mt-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Manage linked bank accounts
                </div>
              </div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>

            <button
              className={`w-full flex items-center justify-between p-4 transition-colors ${
                theme === 'dark' 
                  ? 'hover:bg-gray-900' 
                  : 'hover:bg-gray-50'
              }`}
            >
              <div className="text-left">
                <div>Deactivate Account</div>
                <div className={`text-sm mt-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Temporarily disable your account
                </div>
              </div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>
          </div>
        </div>

        {/* Danger Zone */}
        <div>
          <h3 className={`text-sm uppercase tracking-wider mb-4 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            Danger Zone
          </h3>
          <div className={`border border-red-500 rounded-lg overflow-hidden`}>
            <button
              className={`w-full flex items-center justify-between p-4 transition-colors ${
                theme === 'dark' 
                  ? 'hover:bg-red-950' 
                  : 'hover:bg-red-50'
              }`}
            >
              <div className="text-left">
                <div className="text-red-500">Close Account</div>
                <div className={`text-sm mt-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Permanently close your account
                </div>
              </div>
              <ChevronRight className="w-5 h-5 text-red-500" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
