"use client";

import dynamic from "next/dynamic";

const Backtesting = dynamic(() => import("@/components/pages/Backtesting"), {
  ssr: false,
});

export default function BacktestingPage() {
  return <Backtesting />;
}
