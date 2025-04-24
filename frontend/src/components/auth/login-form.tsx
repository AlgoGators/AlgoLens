"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLogin } from "@/hooks/useLogin";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { useAuthContext } from "@/hooks/useAuthContext";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const { login, isLoading, error } = useLogin();
  const { user } = useAuthContext();
  const router = useRouter();

  useEffect(() => {
    if (user) {
      router.push("/dashboard");
    }
  }, [user, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await login(email, password);
  };

  return (
    <div className="bg-gray-50 shadow-2xl rounded-xl px-10 py-12 w-full max-w-sm font-sans">
      <div className="flex justify-center mb-6">
        <Image
          src="/images/AlgoLogo.png"
          alt="Algo Logo"
          width={60}
          height={60}
          priority
        />
      </div>

      <h2 className="text-2xl font-bold text-center mb-6 text-[#000000] tracking-tight">
        Sign in to AlgoLens
      </h2>

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <Alert
            variant="destructive"
            className="bg-red-100 text-red-800 border-red-400"
          >
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <Input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <div className="space-y-1">
          <Input
            type={showPassword ? "text" : "password"}
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <div className="flex items-center justify-between text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={showPassword}
                onChange={(e) => setShowPassword(e.target.checked)}
              />
              Show Password
            </label>
            <Link
              href="/reset-password-email"
              className="text-[#ff5c02] hover:underline"
            >
              Forgot password?
            </Link>
          </div>
        </div>

        <Button
          type="submit"
          className="w-full bg-[#ff5c02] hover:bg-[#e55302] text-white font-medium"
          disabled={isLoading}
        >
          {isLoading ? "Signing in..." : "Sign In"}
        </Button>
      </form>
    </div>
  );
}
