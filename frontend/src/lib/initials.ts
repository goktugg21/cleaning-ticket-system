/**
 * Sprint 28 Batch 15.1 — shared initials helper.
 *
 * Extracted from AppShell so both the sidebar block and the topbar
 * UserMenu trigger render identical initials for the same input.
 *
 * Behaviour preserved verbatim from the previous in-file copy:
 *   - "" / undefined → "FM" (legacy default keeps existing tests stable)
 *   - "first.last@example.com" → "FL"
 *   - "first last" → "FL"
 *   - "alice" → "AL"
 */
export function getInitials(value: string | undefined | null): string {
  if (!value) return "FM";

  const clean = value.split("@")[0].replace(/[._-]+/g, " ");
  const parts = clean.split(" ").filter(Boolean);

  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  return clean.slice(0, 2).toUpperCase();
}

