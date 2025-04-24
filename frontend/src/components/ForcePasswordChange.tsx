"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuthContext } from "@/hooks/useAuthContext";

const ALLOWED_PATHS = ["/profile", "/", "/login", "/register"];

export function ForcePasswordChange() {
  const { user } = useAuthContext();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Skip if not logged in or on allowed paths
    if (!user || ALLOWED_PATHS.includes(pathname)) return;

    // If force_password_change is true, redirect to profile
    if (user.force_password_change) {
      console.log("Forcing password change, redirecting to profile");
      router.push("/profile");
    }
  }, [user, router, pathname]);

  return null; // This component doesn't render anything
}
