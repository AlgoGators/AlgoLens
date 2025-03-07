"use client";

import dynamic from "next/dynamic";

const GlassFactory = dynamic(() => import("@/components/pages/GlassFactory"), {
  ssr: false,
});

export default function GlassFactoryPage() {
  return <GlassFactory />;
}
