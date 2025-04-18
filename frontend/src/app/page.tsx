"use client";

import { Menubar, MenubarMenu, MenubarTrigger } from "@/components/ui/menubar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import Link from "next/link";
import Image from "next/image";
import { useLogout } from "@/hooks/useLogout";
import { useAuthContext } from "@/hooks/useAuthContext";

export default function MenuPage() {
  const { logout } = useLogout();
  const { user, isAuthReady } = useAuthContext();
  return (
    <>
      <Menubar className="fixed top-0 left-0 w-full h-20 px-4 bg-background shadow-sm flex items-center justify-between">
        {/* Left: Logo + Title */}
        <div className="flex items-center space-x-4">
          <Link href="/">
            <Image
              src="/images/AlgoLogo.png"
              alt="AlgoLogo"
              width={60}
              height={60}
              loading="eager"
            />
          </Link>
          <span className="text-3xl font-bold">AlgoLens</span>
        </div>

        {/* Right: Profile Dropdown */}
        <div>
          {!isAuthReady ? null : user ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="w-10 h-10 rounded-full bg-orange-500 text-white font-bold">
                  {user.first_name?.charAt(0).toUpperCase() || "U"}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="mt-2 bg-white">
                <DropdownMenuItem
                  asChild
                  className="hover:border hover:border-black"
                >
                  <Link
                    href="/profile"
                    className="cursor-pointer hover:border hover:border-black"
                  >
                    Profile
                  </Link>
                </DropdownMenuItem>
                {user.role === "exec_board" && (
                  <DropdownMenuItem
                    asChild
                    className="hover:border hover:border-black"
                  >
                    <Link href="/users" className="cursor-pointer">
                      Users
                    </Link>
                  </DropdownMenuItem>
                )}
                {user.role === "exec_board" && (
                  <DropdownMenuItem
                    asChild
                    className="hover:border hover:border-black"
                  >
                    <Link href="/signup" className="cursor-pointer">
                      Create a user
                    </Link>
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem
                  asChild
                  className="hover:border hover:border-black"
                >
                  <button onClick={logout} className="cursor-pointer">
                    Logout
                  </button>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Link
              href="/login"
              className="px-4 py-2 rounded-md bg-orange-500 text-white font-semibold"
            >
              Login
            </Link>
          )}
        </div>
      </Menubar>

      {/* Main content with padding to avoid overlap */}
      <div className="flex flex-col items-center justify-center min-h-screen pt-20 space-y-8">
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
    </>
  );
}
