import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useState, useEffect } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import Image from "next/image";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";

type User = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  role: string;
  team: string;
};

type EditUserModalProps = {
  user: User | null;
  isOpen: boolean;
  onClose: () => void;
  onSave: (updatedUser: Partial<User>) => Promise<void>;
};

export function EditUserModal({
  user,
  isOpen,
  onClose,
  onSave,
}: EditUserModalProps) {
  const [firstName, setFirstName] = useState(user?.first_name || "");
  const [lastName, setLastName] = useState(user?.last_name || "");
  const [role, setRole] = useState(user?.role || "");
  const [team, setTeam] = useState(user?.team || "");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form when modal opens with new user
  useEffect(() => {
    if (user) {
      setFirstName(user.first_name);
      setLastName(user.last_name);
      setRole(user.role);
      setTeam(user.team);
      setError(null);
    }
  }, [user]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      await onSave({
        first_name: firstName,
        last_name: lastName,
        role,
        team,
      });
      onClose();
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Failed to update user"
      );
    } finally {
      setIsLoading(false);
    }
  };

  const roleMapping: { [key: string]: string } = {
    exec_board: "Executive Board",
    general_member: "General Member",
    team_lead: "Team Lead",
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="bg-gray-50 shadow-2xl rounded-xl px-10 py-12 w-full max-w-sm font-sans sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle className="sr-only">Edit User</DialogTitle>
        </DialogHeader>
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
          Edit User
        </h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <Alert
              variant="destructive"
              className="bg-red-100 text-red-800 border-red-400"
            >
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-4">
            <Input
              placeholder="First Name"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              required
            />
            <Input
              placeholder="Last Name"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              required
            />

            <Select value={role} onValueChange={setRole}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="general_member">General Member</SelectItem>
                <SelectItem value="team_lead">Team Lead</SelectItem>
                <SelectItem value="exec_board">Executive Board</SelectItem>
              </SelectContent>
            </Select>

            <Input
              placeholder="Team"
              value={team}
              onChange={(e) => setTeam(e.target.value)}
              required
            />
          </div>

          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              className="flex-1"
              disabled={isLoading}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              className="flex-1 bg-[#ff5c02] hover:bg-[#e55302] text-white font-medium"
              disabled={isLoading}
            >
              {isLoading ? "Saving..." : "Save Changes"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
