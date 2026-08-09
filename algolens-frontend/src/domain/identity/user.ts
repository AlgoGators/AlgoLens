export interface User {
  id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  role?: string;
}

export interface AuthResponse {
  user: User;
}

const INTERNAL_ROLES = new Set(['admin', 'general_member']);

export function isInternalRole(role?: string | null): boolean {
  return role ? INTERNAL_ROLES.has(role) : false;
}
