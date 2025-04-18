"use client";

import { useState } from "react";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { useSignup } from "@/hooks/useSignup";

export function RegistrationForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [team, setTeam] = useState("Systems");
  const [role, setRole] = useState("general_member");
  const [showPassword, setShowPassword] = useState(false);
  const { signup, isLoading, error, success } = useSignup();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await signup(email, password, firstName, lastName, team, role);
    if (success) {
      setEmail("");
      setPassword("");
      setFirstName("");
      setLastName("");
      setTeam("Systems");
    }
  };

  return (
    <div className="bg-white shadow-2xl rounded-xl px-10 py-12 w-full max-w-sm font-sans">
      <div className="flex justify-center mb-6">
        <Image
          src="/images/AlgoLogo.png"
          alt="Algo Logo"
          width={60}
          height={60}
          priority
        />
      </div>

      <h2 className="text-2xl font-bold text-center mb-6 text-[#000000] tracking-tight">
        Create an AlgoLens Account
      </h2>

      <form onSubmit={handleSubmit} className="space-y-4">
        {success && (
          <Alert
            variant="default"
            className="bg-green-100 text-green-800 border-green-400"
          >
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>
              {"Account created successfully!"}
            </AlertDescription>
          </Alert>
        )}
        {error && (
          <Alert
            variant="destructive"
            className="bg-red-100 text-red-800 border-red-400"
          >
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <Input
          type="text"
          placeholder="First Name"
          value={firstName}
          onChange={(e) => setFirstName(e.target.value)}
          required
        />
        <Input
          type="text"
          placeholder="Last Name"
          value={lastName}
          onChange={(e) => setLastName(e.target.value)}
          required
        />
        <Input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <div className="space-y-1">
          <Input
            type={showPassword ? "text" : "password"}
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <div className="flex items-center justify-between text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={showPassword}
                onChange={(e) => setShowPassword(e.target.checked)}
              />
              Show Password
            </label>
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-sm font-medium text-gray-700">Team</label>
          <Select value={team} onValueChange={setTeam}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select a team" />
            </SelectTrigger>
            <SelectContent className="bg-white shadow-md border rounded-md">
              <SelectItem
                value="Systems"
                className="bg-white hover:bg-gray-100"
              >
                Systems
              </SelectItem>
              <SelectItem value="Data" className="bg-white hover:bg-gray-100">
                Data
              </SelectItem>
              <SelectItem
                value="Investment Relations"
                className="bg-white hover:bg-gray-100"
              >
                Investment Relations
              </SelectItem>
              <SelectItem
                value="Executive"
                className="bg-white hover:bg-gray-100"
              >
                Executive Board
              </SelectItem>
              <SelectItem value="Macro" className="bg-white hover:bg-gray-100">
                Macro
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <label className="text-sm font-medium text-gray-700">Role</label>
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select a role" />
            </SelectTrigger>
            <SelectContent className="bg-white shadow-md border rounded-md">
              <SelectItem
                value="general_member"
                className="bg-white hover:bg-gray-100"
              >
                General Member
              </SelectItem>
              <SelectItem
                value="team_lead"
                className="bg-white hover:bg-gray-100"
              >
                Team Lead
              </SelectItem>
              <SelectItem
                value="exec_board"
                className="bg-white hover:bg-gray-100"
              >
                Executive
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <Button
          type="submit"
          className="w-full bg-[#ff5c02] hover:bg-[#e55302] text-white font-medium"
          disabled={isLoading}
        >
          {isLoading ? "Creating account..." : "Sign Up"}
        </Button>
      </form>
    </div>
  );
}
