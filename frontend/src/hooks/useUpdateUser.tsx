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
    last_name?: string
  ) => {
    setStatus("loading");
    setError(null);
    const userData: any = {};
    if (password !== undefined) {
      userData.password = password;
    }
    if (role !== undefined) {
      userData.role = role;
    }
    if (first_name !== undefined) {
      userData.password = first_name;
    }
    if (last_name !== undefined) {
      userData.password = last_name;
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
        console.log(response);
        throw new Error("Failed to update user");
      }
      const user = await response.json();
      const updated_user = user;
      console.log(updated_user);
      localStorage.setItem("user", updated_user);
      setStatus("success");
    } catch (err) {
      setStatus("error");
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("An unknown error occurred");
      }
    }
  };

  return { status, error, updateUser };
};
