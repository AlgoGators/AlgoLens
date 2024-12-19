"use client";

import "./globals.css";

import { StrategyProvider } from "@/components/StrategyContext";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <StrategyProvider>{children}</StrategyProvider>
      </body>
    </html>
  );
}
