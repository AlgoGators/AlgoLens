import { useEffect } from "react";
import { useLogout } from "@/hooks/useLogout";
import { isTokenExpired } from "@/lib/checkTokenExpiration";

const useAutoLogout = () => {
  const { logout } = useLogout();

  useEffect(() => {
    const token = localStorage.getItem("access_token");

    if (token && isTokenExpired(token)) {
      logout();
    }

    const interval = setInterval(() => {
      const token = localStorage.getItem("access_token");
      if (token && isTokenExpired(token)) {
        logout();
      }
    }, 60000); // check every 60 seconds

    return () => clearInterval(interval);
  }, [logout]);
};

export default useAutoLogout;
