"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Pencil } from "lucide-react";
import { useAuthContext } from "@/hooks/useAuthContext";
import { useUpdateUser } from "@/hooks/useUpdateUser";
import Link from "next/link";
import { useChangePassword } from "@/hooks/useChangePassword";
import { useRouter } from "next/navigation";

export default function ProfilePage() {
  const { user, dispatch } = useAuthContext();
  const [isEditing, setIsEditing] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const {
    status: pwdStatus,
    error: pwdError,
    changePassword,
  } = useChangePassword();
  const { status, error, updateUser } = useUpdateUser();
  const router = useRouter();

  useEffect(() => {
    setFirstName(user?.first_name || "");
    setLastName(user?.last_name || "");
    if (user?.force_password_change) {
      setIsEditing(true);
    }
  }, [user]);

  if (!user) {
    return (
      <p className="text-center mt-10">
        Access denied. Please{" "}
        <Link href="/" className="text-blue-600 underline">
          login
        </Link>
      </p>
    );
  }

  const handleSave = async () => {
    if (!user) return;

    let hasChanges = false;
    let hasErrors = false;

    // Only attempt password change if both fields are filled
    if (oldPassword && newPassword) {
      const success = await changePassword(user.id, oldPassword, newPassword);
      if (!success) {
        hasErrors = true;
      } else {
        hasChanges = true;
        // Clear password fields after successful change
        setOldPassword("");
        setNewPassword("");
      }
    }

    // Only update names if they've actually changed
    const nameChanges = {
      first_name: firstName !== user.first_name ? firstName : undefined,
      last_name: lastName !== user.last_name ? lastName : undefined,
    };

    // Only make the API call if there are actual changes
    if (nameChanges.first_name || nameChanges.last_name) {
      const success = await updateUser(
        user.id,
        undefined, // no password here
        undefined, // no role update allowed here
        nameChanges.first_name,
        nameChanges.last_name
      );

      if (success) {
        dispatch({
          type: "UPDATE_USER",
          payload: {
            ...user,
            first_name: nameChanges.first_name || user.first_name,
            last_name: nameChanges.last_name || user.last_name,
          },
        });
        hasChanges = true;
      } else {
        hasErrors = true;
      }
    }

    // Only close the edit mode if we had changes AND no errors
    if (hasChanges && !hasErrors) {
      setIsEditing(false);
      setOldPassword("");
      setNewPassword("");
      // If this was a forced password change, we can now navigate away
      if (user.force_password_change) {
        router.push("/dashboard");
      }
    } else if (!hasChanges) {
      // If nothing changed, just close the edit mode
      setIsEditing(false);
      setOldPassword("");
      setNewPassword("");
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

      {user?.force_password_change && (
        <Alert className="mb-4 bg-yellow-50 border-yellow-200">
          <AlertTitle>Password Change Required</AlertTitle>
          <AlertDescription>
            You must change your password before continuing to use the
            application.
          </AlertDescription>
        </Alert>
      )}

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
          placeholder="Old Password"
          value={oldPassword}
          onChange={(e) => setOldPassword(e.target.value)}
          disabled={!isEditing}
        />
        <Input
          type="password"
          placeholder="New Password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
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
              onClick={handleSave}
              disabled={status === "loading" || pwdStatus === "loading"}
            >
              {status === "loading" || pwdStatus === "loading"
                ? "Saving..."
                : "Save"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setFirstName(user?.first_name || "");
                setLastName(user?.last_name || "");
                setOldPassword("");
                setNewPassword("");
                setIsEditing(false);
              }}
              disabled={status === "loading"}
            >
              Cancel
            </Button>
          </div>
        )}
        {pwdStatus === "error" && (
          <Alert
            variant="destructive"
            className="bg-red-100 text-red-800 border-red-400"
          >
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{pwdError}</AlertDescription>
          </Alert>
        )}
        {status === "error" && (
          <Alert
            variant="destructive"
            className="bg-red-100 text-red-800 border-red-400"
          >
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </form>
    </div>
  );
}
