import { useState } from "react";
import { useAuthContext } from "@/hooks/useAuthContext";

export function useChangePassword() {
  const [status, setStatus] = useState<
    "idle" | "loading" | "success" | "error"
  >("idle");
  const [error, setError] = useState<string | null>(null);
  const { dispatch } = useAuthContext();

  const changePassword = async (
    id: number,
    old_password: string,
    new_password: string
  ) => {
    setStatus("loading");
    try {
      const token = localStorage.getItem("access_token");
      const res = await fetch(`http://127.0.0.1:5000/users/${id}/password`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ old_password, new_password }),
      });

      const data = await res.json();

      if (!res.ok) {
        if (data.msg === "Old password did not match") {
          throw new Error("Old password is incorrect");
        }
        throw new Error("Failed to change password");
      }

      // Get the current user from localStorage
      const userStr = localStorage.getItem("user");
      if (userStr) {
        const user = JSON.parse(userStr);
        // Update the force_password_change flag
        const updatedUser = {
          ...user,
          force_password_change: false,
        };
        // Update localStorage and context
        localStorage.setItem("user", JSON.stringify(updatedUser));
        dispatch({ type: "UPDATE_USER", payload: updatedUser });
      }

      setStatus("success");
      return true;
    } catch (e: any) {
      setStatus("error");
      setError(e.message);
      return false;
    }
  };

  return { status, error, changePassword };
}
