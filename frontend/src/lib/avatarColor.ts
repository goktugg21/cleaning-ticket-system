/**
 * RF-1 — deterministic avatar background colour from a seed string
 * (name or email), so the initials fallback is stable and visually
 * distinct per person, WhatsApp-style. Same input always yields the
 * same hue; readable white text sits on the returned colour.
 */
export function avatarColor(seed: string | null | undefined): string {
  const s = (seed || "").trim() || "?";
  let hash = 0;
  for (let i = 0; i < s.length; i += 1) {
    hash = (hash * 31 + s.charCodeAt(i)) | 0;
  }
  const hue = Math.abs(hash) % 360;
  // Fixed saturation/lightness keeps contrast with white text consistent.
  return `hsl(${hue}deg 45% 42%)`;
}
