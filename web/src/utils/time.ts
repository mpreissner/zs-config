function toUtcDate(value: string): Date {
  // If the string has no timezone indicator, treat it as UTC
  const s = value.trimEnd();
  if (/[Zz]$/.test(s) || /[+-]\d{2}:?\d{2}$/.test(s)) {
    return new Date(s);
  }
  // Append Z so the browser parses as UTC rather than local time
  return new Date(s.replace(" UTC", "") + "Z");
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const d = toUtcDate(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const d = toUtcDate(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { dateStyle: "medium" });
}
