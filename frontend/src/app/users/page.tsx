"use client";

import { useState, useEffect } from "react";
import { Pencil, Lock, Spacer } from "lucide-react";
import { useAuthContext } from "@/hooks/useAuthContext";

export default function UsersPage() {
  const { user } = useAuthContext();
  const [users, setUsers] = useState<any[]>([]);

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
                <button className="mr-2">
                  <Pencil size={18} />
                </button>
                <button>
                  <Lock size={18} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
