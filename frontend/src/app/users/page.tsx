"use client";

import { useState, useEffect } from "react";
import { Pencil, Lock, User } from "lucide-react";
import Link from "next/link";
import { useAuthContext } from "@/hooks/useAuthContext";
import { EditUserModal } from "@/components/EditUserModal";
import { useUpdateUser } from "@/hooks/useUpdateUser";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

type User = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  role: string;
  team: string;
  force_password_change: boolean;
};

export default function UsersPage() {
  const { user } = useAuthContext();
  const [users, setUsers] = useState<User[]>([]);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isResetModalOpen, setIsResetModalOpen] = useState(false);
  const [resetPasswordResult, setResetPasswordResult] = useState<string | null>(
    null
  );
  const [resetError, setResetError] = useState<string | null>(null);
  const { updateUser, status, error } = useUpdateUser();

  useEffect(() => {
    const fetchUsers = async () => {
      const token = localStorage.getItem("access_token");
      const res = await fetch("http://127.0.0.1:5000/users/", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (res.ok) setUsers(data.users);
    };
    if (user?.role === "exec_board") {
      fetchUsers();
    }
  }, [user]);

  const handleEditClick = (userToEdit: User) => {
    setSelectedUser(userToEdit);
    setIsEditModalOpen(true);
  };

  const handleSaveUser = async (updatedUser: Partial<User>) => {
    if (!selectedUser) return;

    // Only include fields that have actually changed
    const changes: Partial<User> = {};
    if (updatedUser.first_name !== selectedUser.first_name) {
      changes.first_name = updatedUser.first_name;
    }
    if (updatedUser.last_name !== selectedUser.last_name) {
      changes.last_name = updatedUser.last_name;
    }
    if (updatedUser.role !== selectedUser.role) {
      changes.role = updatedUser.role;
    }
    if (updatedUser.team !== selectedUser.team) {
      changes.team = updatedUser.team;
    }

    // Only make API call if there are actual changes
    if (Object.keys(changes).length === 0) {
      setIsEditModalOpen(false);
      setSelectedUser(null);
      return;
    }

    // Call updateUser with the correct parameter order
    const success = await updateUser(
      selectedUser.id,
      undefined,
      changes.role,
      changes.first_name,
      changes.last_name,
      false
    );

    if (success) {
      // Update local state with all changes including team
      setUsers(
        users.map((u) => (u.id === selectedUser.id ? { ...u, ...changes } : u))
      );
      setIsEditModalOpen(false);
      setSelectedUser(null);
    }
  };

  const handleResetClick = (userToReset: User) => {
    setSelectedUser(userToReset);
    setIsResetModalOpen(true);
    setResetPasswordResult(null);
    setResetError(null);
  };

  const handleResetPassword = async () => {
    if (!selectedUser) return;

    try {
      const token = localStorage.getItem("access_token");
      const response = await fetch(
        `http://127.0.0.1:5000/users/${selectedUser.id}/admin-reset-password`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.msg || "Failed to reset password");
      }

      setResetPasswordResult(data.temp_password);
    } catch (err) {
      setResetError(
        err instanceof Error ? err.message : "Failed to reset password"
      );
    }
  };

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

  if (user?.role !== "exec_board") {
    return <p className="text-center mt-10">Access denied.</p>;
  }

  const roleMapping: { [key: string]: string } = {
    exec_board: "Executive Board",
    general_member: "General Member",
    team_lead: "Team Lead",
  };

  return (
    <div className="bg-gray-50 shadow-2xl rounded-xl px-10 py-12 w-full max-w-4xl font-sans mx-auto mt-10">
      <h2 className="text-2xl font-bold text-[#000000] tracking-tight mb-6">
        Users List
      </h2>
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-[#ff5c02] text-white">
            <th className="py-2 px-4 text-left">Name</th>
            <th className="py-2 px-4 text-left">Email</th>
            <th className="py-2 px-4 text-left">Role</th>
            <th className="py-2 px-4 text-left">Team</th>
            <th className="py-2 px-4 text-left">Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b hover:bg-gray-100">
              <td className="py-2 px-4">
                {u.first_name} {u.last_name}
              </td>
              <td className="py-2 px-4">{u.email}</td>
              <td className="py-2 px-4">{roleMapping[u.role] || u.role}</td>
              <td className="py-2 px-4">{u.team}</td>
              <td className="py-2 px-4">
                <button className="mr-2" onClick={() => handleEditClick(u)}>
                  <Pencil size={18} />
                </button>
                <button onClick={() => handleResetClick(u)}>
                  <Lock size={18} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <EditUserModal
        user={selectedUser}
        isOpen={isEditModalOpen}
        onClose={() => {
          setIsEditModalOpen(false);
          setSelectedUser(null);
        }}
        onSave={handleSaveUser}
        error={error}
        isLoading={status === "loading"}
      />

      <Dialog open={isResetModalOpen} onOpenChange={setIsResetModalOpen}>
        <DialogContent className="bg-gray-50 shadow-2xl rounded-xl px-10 py-12 w-full max-w-sm font-sans">
          <DialogHeader>
            <DialogTitle>Reset Password</DialogTitle>
            <DialogDescription>
              {selectedUser && (
                <>
                  Reset password for {selectedUser.first_name}{" "}
                  {selectedUser.last_name}? This will generate a temporary
                  password and force a password change on next login.
                </>
              )}
            </DialogDescription>
          </DialogHeader>

          {resetError && (
            <Alert
              variant="destructive"
              className="bg-red-100 text-red-800 border-red-400"
            >
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{resetError}</AlertDescription>
            </Alert>
          )}

          {resetPasswordResult && (
            <Alert className="bg-yellow-50 border-yellow-200">
              <AlertTitle>Temporary Password</AlertTitle>
              <AlertDescription>
                <div className="mt-2">
                  New password:{" "}
                  <code className="bg-gray-100 px-2 py-1 rounded">
                    {resetPasswordResult}
                  </code>
                </div>
                <div className="mt-2 text-sm text-gray-600">
                  Please provide this password to the user securely. They will
                  be required to change it on their next login.
                </div>
              </AlertDescription>
            </Alert>
          )}

          <div className="flex justify-end gap-2 mt-4">
            <button
              className="px-4 py-2 border rounded-md hover:bg-gray-100"
              onClick={() => {
                setIsResetModalOpen(false);
                setSelectedUser(null);
                setResetPasswordResult(null);
                setResetError(null);
              }}
            >
              Close
            </button>
            {!resetPasswordResult && (
              <button
                className="px-4 py-2 bg-[#ff5c02] text-white rounded-md hover:bg-[#e55302]"
                onClick={handleResetPassword}
              >
                Reset Password
              </button>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
