import { parseConfigurationInspection, UnsupportedNumericRepresentationError, type InspectionResponse } from '../../domain/portfolio/configurationInspection';
import { API_BASE_URL, getWithAuth } from './httpClient';

const MAX_RESPONSE_BYTES = 3 * 1024 * 1024;

export class InspectionReadError extends Error {
  constructor(readonly status?: number) {
    super(status === 403 ? 'Published configuration access is unavailable.'
      : status === 404 ? 'Published configuration registry is unavailable.'
        : 'Published configuration could not be loaded.');
  }
}

async function readBounded(response: Response): Promise<string> {
  const contentLength = response.headers.get('content-length');
  if (contentLength !== null && /^\d+$/.test(contentLength) && Number(contentLength) > MAX_RESPONSE_BYTES) {
    throw new InspectionReadError();
  }
  const reader = response.body?.getReader();
  if (!reader) throw new InspectionReadError();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > MAX_RESPONSE_BYTES) throw new InspectionReadError();
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
  catch { throw new InspectionReadError(); }
}

export async function getConfigurationInspection(
  registryId: string, portfolioId: string, signal?: AbortSignal,
): Promise<InspectionResponse> {
  if (!registryId || !portfolioId) throw new InspectionReadError();
  const url = `${API_BASE_URL}/portfolio/strategies/${encodeURIComponent(registryId)}/configuration?portfolio_id=${encodeURIComponent(portfolioId)}`;
  const response = await getWithAuth(url, signal);
  if (!response.ok) throw new InspectionReadError(response.status);
  if (!/^application\/json(?:\s*;|\s*$)/i.test(response.headers.get('content-type') ?? '')) {
    throw new InspectionReadError();
  }
  try {
    const raw = await readBounded(response);
    return parseConfigurationInspection(raw, registryId, portfolioId);
  } catch (error) {
    if (error instanceof UnsupportedNumericRepresentationError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new InspectionReadError();
  }
}
