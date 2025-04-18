import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthContext } from "@/hooks/useAuthContext";

export const useLogin = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { dispatch } = useAuthContext();
  const router = useRouter();

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    setError(null);

    try {
      // Step 1: Login to get token
      const res = await fetch("http://127.0.0.1:5000/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.msg || "Login failed");
      }

      const token = data.access_token;
      const decoded = JSON.parse(atob(token.split(".")[1]));
      const userId = decoded.sub;

      // Step 2: Get full user details using the ID
      const userRes = await fetch(`http://127.0.0.1:5000/users/${userId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      const userData = await userRes.json();

      if (!userRes.ok) {
        throw new Error(userData.msg || "Failed to fetch user details");
      }

      // Step 3: Save and dispatch full user info
      localStorage.setItem("user", JSON.stringify(userData.user));
      localStorage.setItem("access_token", token);
      dispatch({ type: "LOGIN", payload: userData.user });
      router.push("/");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return { login, isLoading, error };
};
