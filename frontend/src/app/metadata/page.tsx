"use client";

import dynamic from "next/dynamic";

const Metadata = dynamic(() => import("@/components/pages/Metadata"), {
  ssr: false,
});

export default function MetadataPage() {
  return <Metadata />;
}
