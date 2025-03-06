"use client";

import Link from "next/link";

export default function MenuPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen space-y-8">
      <Link
        href="/portfolio"
        className="px-8 py-4 bg-blue-500 text-white rounded-lg text-2xl font-bold"
      >
        Portfolio
      </Link>
      <Link
        href="/backtesting"
        className="px-8 py-4 bg-green-500 text-white rounded-lg text-2xl font-bold"
      >
        Backtesting
      </Link>
    </div>
  );
}
