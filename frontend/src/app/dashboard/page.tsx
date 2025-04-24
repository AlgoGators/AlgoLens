"use client";
import { useAuthContext } from "@/hooks/useAuthContext";
import Link from "next/link";

export default function MenuPage() {
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
    <>
      <div className="pt-24 px-6 md:px-12 lg:px-24 max-w-7xl mx-auto">
        <div className="flex flex-col md:flex-row items-center justify-between mb-16">
          <div className="md:w-1/2 mb-8 md:mb-0">
            <h1 className="text-4xl md:text-5xl font-bold text-gray-800 mb-4">
              Welcome to <span className="text-orange-500">AlgoLens</span>
            </h1>
          </div>
        </div>
      </div>
    </>
  );
}
