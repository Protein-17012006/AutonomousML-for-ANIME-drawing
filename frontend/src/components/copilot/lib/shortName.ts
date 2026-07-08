// Truncate a filename to display on button — keeping the full name in the button's `title`

export function shortName(name: string, head = 14): string {
  if (name.length <= head + 8) return name;
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 ? name.slice(dot) : "";
  return name.slice(0, head) + "…" + ext;
}