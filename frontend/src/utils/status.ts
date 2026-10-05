export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

const configuredSeconds = Number(import.meta.env.VITE_DATA_STALE_SECONDS ?? '30');
export const STALE_AFTER_MS = (Number.isFinite(configuredSeconds) && configuredSeconds >= 5
  ? configuredSeconds : 30) * 1_000;

export function isFresh(timestamp: string | null | undefined, now: number): boolean {
  if (!timestamp) return false;
  const age = now - Date.parse(timestamp);
  return Number.isFinite(age) && age >= -STALE_AFTER_MS && age <= STALE_AFTER_MS;
}
