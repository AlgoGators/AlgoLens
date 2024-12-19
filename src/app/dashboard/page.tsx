"use client";

import { StrategyProvider } from "@/components/StrategyContext";
import DashboardContent from "@/components/DashboardContent";

export default function DashboardPage() {
  return (
    <StrategyProvider>
      <DashboardContent />
    </StrategyProvider>
  );
}
