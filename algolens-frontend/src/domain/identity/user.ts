export interface User {
  id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  role?: string;
  capabilities: Capability[];
}

export interface AuthResponse {
  user: User;
}

export const CAPABILITIES = [
  'edit_config', 'approve_config',
  'view_internal', 'view_qt_platform', 'edit_qt_book', 'approve_qt_override',
  'manage_incubation', 'manage_books', 'request_runtime_control',
  'approve_runtime_control', 'publish_qt_book', 'save_analysis', 'view_investor_book',
] as const;

export type Capability = typeof CAPABILITIES[number];
const knownCapabilities = new Set<string>(CAPABILITIES);

export function decodeUser(value: unknown): User {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid_user');
  const item = value as Record<string, unknown>;
  if ((typeof item.id !== 'string' && typeof item.id !== 'number') || typeof item.email !== 'string' ||
      (item.role !== undefined && typeof item.role !== 'string') || !Array.isArray(item.capabilities) ||
      item.capabilities.some(entry => typeof entry !== 'string' || !knownCapabilities.has(entry)) ||
      new Set(item.capabilities).size !== item.capabilities.length) throw new Error('invalid_user');
  return { ...item, id: String(item.id), capabilities: [...item.capabilities] as Capability[] } as User;
}

export function can(user: User | null | undefined, capability: Capability): boolean {
  return user?.capabilities?.includes(capability) === true;
}
