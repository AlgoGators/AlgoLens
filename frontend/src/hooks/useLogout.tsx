import { useAuthContext } from "@/hooks/useAuthContext";
import { useRouter } from "next/navigation";

export const useLogout = () => {
  const { dispatch } = useAuthContext();
  const router = useRouter();

  const logout = () => {
    localStorage.removeItem("user");
    localStorage.removeItem("access_token");
    dispatch({ type: "LOGOUT" });
    router.push("/");
  };

  return { logout };
};
