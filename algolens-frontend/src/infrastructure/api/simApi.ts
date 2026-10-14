import type { SimState } from '../../domain/sim/simClock';
import { API_BASE_URL } from './httpClient';

/** GET /api/sim: the sim clock, or null when this is not the simulator (404) or it fails. */
export async function fetchSimState(): Promise<SimState | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/sim`, { credentials: 'include' });
    if (!response.ok) return null;
    const data = (await response.json()) as SimState;
    return data && data.sim === true && typeof data.serverTime === 'string' ? data : null;
  } catch {
    return null;
  }
}
