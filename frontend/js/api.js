// Small fetch wrapper for the JSON API: throws an Error (with .status) carrying the server's message.
export async function api(path, opt) {
  const r = await fetch("/api/" + path, opt);
  if (!r.ok) {
    const e = new Error((await r.json().catch(() => ({}))).detail || r.status);
    e.status = r.status;
    throw e;
  }
  return r.json();
}

// "5 minutes ago", for epoch seconds
export function relTime(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  const steps = [[60, "second"], [3600, "minute"], [86400, "hour"], [2592000, "day"], [31536000, "month"], [Infinity, "year"]];
  if (s < 60) return "just now";
  const sizes = [1, 60, 3600, 86400, 2592000, 31536000];
  const i = steps.findIndex(([lim]) => s < lim);
  const n = Math.floor(s / sizes[i]);
  return `${n} ${steps[i][1]}${n === 1 ? "" : "s"} ago`;
}
