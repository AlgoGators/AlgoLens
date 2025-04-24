import { useState } from "react";

export const useUpdateUser = () => {
  const [status, setStatus] = useState<
    "idle" | "loading" | "success" | "error"
  >("idle");
  const [error, setError] = useState<string | null>(null);

  const updateUser = async (
    id: number,
    password?: string,
    role?: string,
    first_name?: string,
    last_name?: string,
    isSelfUpdate: boolean = false
  ): Promise<boolean> => {
    setStatus("loading");
    setError(null);
    const userData: any = {};
    if (role !== undefined) {
      userData.role = role;
    }
    if (first_name !== undefined) {
      userData.first_name = first_name;
    }
    if (last_name !== undefined) {
      userData.last_name = last_name;
    }
    const access_token = localStorage.getItem("access_token");
    try {
      const response = await fetch(`http://127.0.0.1:5000/users/${id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${access_token}`,
        },
        body: JSON.stringify(userData),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.msg || "Failed to update user");
      }
      const { user } = await response.json();

      if (isSelfUpdate) {
        localStorage.setItem("user", JSON.stringify(user));
      }

      setStatus("success");
      return true;
    } catch (err) {
      setStatus("error");
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("An unknown error occurred");
      }
      return false;
    }
  };

  return { status, error, updateUser };
};
