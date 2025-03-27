"use client";

import { Menubar, MenubarMenu, MenubarTrigger } from "@/components/ui/menubar";
import Link from "next/link";
import Image from "next/image";

export default function MenuPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen space-y-8">
      <div className="flex flex-col h-screen">
        {/* Header */}
        <Menubar className="h-20 px-4 bg-background shadow-sm">
          <MenubarMenu className="flex items-center space-x-4">
            <MenubarTrigger asChild>
              <Link href="/">
                <Image
                  src="/images/AlgoLogo.png"
                  alt="AlgoLogo"
                  width={60}
                  height={60}
                  loading="eager"
                />
              </Link>
            </MenubarTrigger>
            <span className="text-3xl font-bold">Glass Factory</span>
          </MenubarMenu>
        </Menubar>
        
      </div>
      
      <Link
        href="/portfolio"
        className="px-8 py-4 bg-orange-500 text-white rounded-lg text-2xl font-bold"
      >
        Portfolio
      </Link>
      <Link
        href="/backtesting"
        className="px-8 py-4 bg-orange-500 text-white rounded-lg text-2xl font-bold"
      >
        Backtesting
      </Link>
      <Link
        href="/metadata"
        className="px-8 py-4 bg-orange-500 text-white rounded-lg text-2xl font-bold"
      >
        Metadata
      </Link>
    </div>
  );
}
