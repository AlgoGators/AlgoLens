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

// exec_board is exec, and exec equals admin (HD ruling 2026-09-25); keep in step with the API.
const INTERNAL_ROLES = new Set(['admin', 'exec_board', 'general_member']);

export function isInternalRole(role?: string | null): boolean {
  return role ? INTERNAL_ROLES.has(role) : false;
}
