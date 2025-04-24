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
import { usePathname } from "next/navigation";

const Navbar = () => {
  const { logout } = useLogout();
  const { user, isAuthReady } = useAuthContext();
  const pathname = usePathname();
  let headerText = "AlgoLens";

  if (pathname === "/profile") {
    headerText = "Your Profile";
  } else if (pathname === "/users") {
    headerText = "Manage Users";
  } else if (pathname === "/backtesting") {
    headerText = "Backtesting";
  } else if (pathname === "/portfolio") {
    headerText = "Portfolio";
  } else if (pathname === "/metadata") {
    headerText = "Glass Factory";
  }
  return (
    <Menubar className="fixed top-0 left-0 w-full h-20 px-4 bg-background shadow-sm flex items-center">
      {/* Left: Logo + Title */}
      <div className="w-1/4 flex items-center space-x-4">
        <Link href="/">
          <Image
            src="/images/AlgoLogo.png"
            alt="AlgoLogo"
            width={60}
            height={60}
            loading="eager"
          />
        </Link>
        <span className="text-3xl font-bold">{headerText}</span>
      </div>

      {/* Middle section */}
      <div className="w-1/2 flex items-center justify-center space-x-6">
        <Link
          href="/portfolio"
          className="px-4 py-2 text-base font-bold text-gray-700 hover:text-orange-500 transition-colors"
        >
          Portfolio
        </Link>
        <Link
          href="/backtesting"
          className="px-8 py-2 text-base font-bold text-gray-700 hover:text-orange-500 transition-colors"
        >
          Backtesting
        </Link>
        <Link
          href="/metadata"
          className="px-8 py-2 text-base font-bold text-gray-700 hover:text-orange-500 transition-colors"
        >
          Metadata
        </Link>
      </div>

      {/* Right: Profile Dropdown */}
      <div className="w-1/4 flex justify-end">
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
            href="/"
            className="px-4 py-2 rounded-md bg-orange-500 text-white font-semibold"
          >
            Login
          </Link>
        )}
      </div>
    </Menubar>
  );
};

export default Navbar;
