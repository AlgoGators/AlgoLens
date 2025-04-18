"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Pencil } from "lucide-react";
import { useAuthContext } from "@/hooks/useAuthContext";
import { useUpdateUser } from "@/hooks/useUpdateUser";

export default function ProfilePage() {
  const { user, dispatch } = useAuthContext();
  const [isEditing, setIsEditing] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");
  const { status, error, updateUser } = useUpdateUser();

  useEffect(() => {
    setFirstName(user?.first_name || "");
    setLastName(user?.last_name || "");
  }, [user]);

  const handleSave = async () => {
    if (!user) return;

    await updateUser(user.id, password, user.role, firstName, lastName);

    if (status === "success") {
      dispatch({
        type: "UPDATE_USER",
        payload: { ...user, first_name: firstName, last_name: lastName },
      });
      setIsEditing(false);
    }
  };

  return (
    <div className="bg-gray-50 shadow-2xl rounded-xl px-10 py-12 w-full max-w-xl font-sans mx-auto mt-10">
      <div className="flex items-center mb-6">
        <Image
          src="/images/AlgoLogo.png"
          alt="Algo Logo"
          width={60}
          height={60}
          priority
        />
        <h2 className="text-2xl font-bold ml-4 text-[#000000] tracking-tight">
          My Profile
        </h2>
      </div>

      <form className="space-y-4">
        <div className="flex gap-2 items-center">
          <Input
            type="text"
            placeholder="First Name"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            disabled={!isEditing}
          />
          <Input
            type="text"
            placeholder="Last Name"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            disabled={!isEditing}
          />
          {!isEditing && (
            <button type="button" onClick={() => setIsEditing(true)}>
              <Pencil size={20} />
            </button>
          )}
        </div>
        <Input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={!isEditing}
        />
        <Input type="email" value={user?.email || ""} disabled />
        <Input type="text" value={user?.role || ""} disabled />
        <Input type="text" value={user?.team || ""} disabled />

        {isEditing && (
          <div className="flex gap-2">
            <Button
              type="button"
              className="bg-[#ff5c02] text-white"
              //onClick={}
              disabled={status === "loading"}
            >
              {status === "loading" ? "Saving..." : "Save"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setFirstName(user?.first_name || "");
                setLastName(user?.last_name || "");
                setIsEditing(false);
              }}
              disabled={status === "loading"}
            >
              Cancel
            </Button>
          </div>
        )}
        {status === "error" && <p className="text-red-500">{error}</p>}
      </form>
    </div>
  );
}
