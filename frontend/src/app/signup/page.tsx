"use client";

import { RegistrationForm } from "@/components/auth/registration-form";
import { useAuthContext } from "@/hooks/useAuthContext";
import Link from "next/link";

export default function RegisterPage() {
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
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <RegistrationForm />
    </div>
  );
}
