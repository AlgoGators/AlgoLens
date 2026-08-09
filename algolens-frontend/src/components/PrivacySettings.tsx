import React, { useState } from 'react';
import { ArrowLeft, ChevronRight, Shield, Lock, Eye, Fingerprint, Smartphone, Key } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';

interface PrivacySettingsProps {
  onBack: () => void;
}

export function PrivacySettings({ onBack }: PrivacySettingsProps) {
  const { theme } = useTheme();
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(true);
  const [biometricEnabled, setBiometricEnabled] = useState(false);
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [pushNotifications, setPushNotifications] = useState(true);

  const Toggle = ({ enabled, onChange }: { enabled: boolean; onChange: () => void }) => (
    <button
      onClick={onChange}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
        enabled ? 'bg-orange-500' : theme === 'dark' ? 'bg-gray-700' : 'bg-gray-300'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
          enabled ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  );

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
        <h2 className="text-xl">Privacy & Security</h2>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {/* Security */}
        <div className="mb-8">
          <h3 className={`text-sm uppercase tracking-wider mb-4 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            Security
          </h3>
          <div className={`border rounded-lg overflow-hidden ${
            theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
          }`}>
            <div
              className={`w-full flex items-center justify-between p-4 border-b ${
                theme === 'dark' 
                  ? 'border-gray-800' 
                  : 'border-gray-200'
              }`}
            >
              <div className="flex items-center gap-3 flex-1">
                <Shield className={`w-5 h-5 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`} />
                <div>
                  <div>Two-Factor Authentication</div>
                  <div className={`text-sm mt-1 ${
                    theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                  }`}>
                    Extra security for your account
                  </div>
                </div>
              </div>
              <Toggle enabled={twoFactorEnabled} onChange={() => setTwoFactorEnabled(!twoFactorEnabled)} />
            </div>

            <div
              className={`w-full flex items-center justify-between p-4 border-b ${
                theme === 'dark' 
                  ? 'border-gray-800' 
                  : 'border-gray-200'
              }`}
            >
              <div className="flex items-center gap-3 flex-1">
                <Fingerprint className={`w-5 h-5 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`} />
                <div>
                  <div>Biometric Login</div>
                  <div className={`text-sm mt-1 ${
                    theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                  }`}>
                    Use fingerprint or Face ID
                  </div>
                </div>
              </div>
              <Toggle enabled={biometricEnabled} onChange={() => setBiometricEnabled(!biometricEnabled)} />
            </div>

            <button
              className={`w-full flex items-center justify-between p-4 border-b transition-colors ${
                theme === 'dark' 
                  ? 'border-gray-800 hover:bg-gray-900' 
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <div className="flex items-center gap-3 flex-1 text-left">
                <Smartphone className={`w-5 h-5 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`} />
                <div>
                  <div>Trusted Devices</div>
                  <div className={`text-sm mt-1 ${
                    theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                  }`}>
                    Manage devices with access
                  </div>
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
              <div className="flex items-center gap-3 flex-1 text-left">
                <Key className={`w-5 h-5 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`} />
                <div>
                  <div>Active Sessions</div>
                  <div className={`text-sm mt-1 ${
                    theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                  }`}>
                    View and end active sessions
                  </div>
                </div>
              </div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>
          </div>
        </div>

        {/* Privacy */}
        <div className="mb-8">
          <h3 className={`text-sm uppercase tracking-wider mb-4 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            Privacy
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
              <div className="flex items-center gap-3 flex-1 text-left">
                <Eye className={`w-5 h-5 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`} />
                <div>
                  <div>Data Sharing</div>
                  <div className={`text-sm mt-1 ${
                    theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                  }`}>
                    Control how your data is used
                  </div>
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
              <div className="flex items-center gap-3 flex-1 text-left">
                <Lock className={`w-5 h-5 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`} />
                <div>
                  <div>Download Your Data</div>
                  <div className={`text-sm mt-1 ${
                    theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                  }`}>
                    Get a copy of your information
                  </div>
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
                <div>Privacy Policy</div>
                <div className={`text-sm mt-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Read our privacy policy
                </div>
              </div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>
          </div>
        </div>

        {/* Notifications */}
        <div>
          <h3 className={`text-sm uppercase tracking-wider mb-4 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            Notifications
          </h3>
          <div className={`border rounded-lg overflow-hidden ${
            theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
          }`}>
            <div
              className={`w-full flex items-center justify-between p-4 border-b ${
                theme === 'dark' 
                  ? 'border-gray-800' 
                  : 'border-gray-200'
              }`}
            >
              <div className="flex-1">
                <div>Email Notifications</div>
                <div className={`text-sm mt-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Receive updates via email
                </div>
              </div>
              <Toggle enabled={emailNotifications} onChange={() => setEmailNotifications(!emailNotifications)} />
            </div>

            <div
              className={`w-full flex items-center justify-between p-4 border-b ${
                theme === 'dark' 
                  ? 'border-gray-800' 
                  : 'border-gray-200'
              }`}
            >
              <div className="flex-1">
                <div>Push Notifications</div>
                <div className={`text-sm mt-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Receive alerts on your device
                </div>
              </div>
              <Toggle enabled={pushNotifications} onChange={() => setPushNotifications(!pushNotifications)} />
            </div>

            <button
              className={`w-full flex items-center justify-between p-4 transition-colors ${
                theme === 'dark' 
                  ? 'hover:bg-gray-900' 
                  : 'hover:bg-gray-50'
              }`}
            >
              <div className="text-left">
                <div>Notification Preferences</div>
                <div className={`text-sm mt-1 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Customize what you receive
                </div>
              </div>
              <ChevronRight className={`w-5 h-5 ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
