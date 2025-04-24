"use client";

import dynamic from "next/dynamic";
import { useAuthContext } from "@/hooks/useAuthContext";
import Link from "next/link";

const Metadata = dynamic(() => import("@/components/pages/Metadata"), {
  ssr: false,
});

export default function MetadataPage() {
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
  return <Metadata />;
}
