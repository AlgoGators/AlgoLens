import { useState } from "react";
import { useAuthContext } from "@/hooks/useAuthContext";

export const useSignup = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { dispatch } = useAuthContext();

  const signup = async (
    email: string,
    password: string,
    first_name: string,
    last_name: string,
    team: string,
    role?: string
  ) => {
    setIsLoading(true);
    setError(null);

    try {
      const token = localStorage.getItem("access_token");
      if (token === null) {
        throw new Error(
          "You must be logged in as an executive board member to register a new user."
        );
      } else if (JSON.parse(atob(token.split(".")[1])).role != "exec_board") {
        throw new Error(
          "You must be logged in as an executive board member to register a new user."
        );
      }
      const res = await fetch("http://127.0.0.1:5000/auth/register", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          email,
          password,
          role,
          first_name,
          last_name,
          team,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.msg || "Signup failed");
      }

      const user = {
        id: data.id,
        email: data.email,
        role: data.role,
        first_name: data.first_name,
        last_name: data.last_name,
        team: data.team,
      };

      localStorage.setItem("user", JSON.stringify(user));
      if (res.status == 201) {
        setSuccess(true);
      }
      dispatch({ type: "LOGIN", payload: user });
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "An unknown error occurred"
      );
    } finally {
      setIsLoading(false);
    }
  };

  return { signup, isLoading, error, success };
};
