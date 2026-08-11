export const INTERNAL_ROLES: ReadonlySet<string> = new Set([
  'admin',
  'general_member',
]);

export function isInternalRole(role?: string | null): boolean {
  return role ? INTERNAL_ROLES.has(role) : false;
}
