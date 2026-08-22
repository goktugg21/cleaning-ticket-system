// Round-trip between an ISO instant and a `datetime-local` input value
// (local wall time, no timezone suffix).
//
// Lives here rather than inside a component file because two modules now
// need it (the ticket assignment dialog and the section that owns it), and
// exporting a non-component from a component file trips
// `react-refresh/only-export-components`.

export function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
    d.getDate(),
  )}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function localInputToIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}
