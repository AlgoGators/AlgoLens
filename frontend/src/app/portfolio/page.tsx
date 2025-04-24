"use client";
import { useAuthContext } from "@/hooks/useAuthContext";
import Link from "next/link";

export default function PortfolioPage() {
  const { user } = useAuthContext();

  if (!user) {
    return (
      <p className="text-center mt-10">
        Access denied. Please{" "}
        <Link href="/" className="text-blue-600 underline">
          login
        </Link>
      </p>
    );
  }
  return (
    <div className="flex flex-col items-center justify-center min-h-screen space-y-4">
      <h1 className="text-4xl font-bold">Portfolio</h1>
      <p>This is a dummy portfolio page.</p>
    </div>
  );
}
