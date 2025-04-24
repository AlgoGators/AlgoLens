"use client";

import dynamic from "next/dynamic";
import { useAuthContext } from "@/hooks/useAuthContext";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

const Backtesting = dynamic(() => import("@/components/pages/Backtesting"), {
  ssr: false,
});

export default function BacktestingPage() {
  const { user } = useAuthContext();
  const router = useRouter();

  useEffect(() => {
    if (!user) {
      router.replace("/"); // redirect to login
    }
  }, [user, router]);
  return <Backtesting />;
}
