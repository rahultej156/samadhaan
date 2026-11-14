/**
 * Formatting helpers. No secrets, no data access — safe on both sides.
 */

const rupees = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** `1000` -> `₹1,000.00`. Money is numeric(12,2) in Postgres, so it may arrive
 *  as a string; never parse it as a float for arithmetic, only for display. */
export function money(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  return `₹${rupees.format(n)}`;
}

const absolute = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Kolkata",
});

export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${absolute.format(d)} IST`;
}

const clock = new Intl.DateTimeFormat("en-IN", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZone: "Asia/Kolkata",
});

export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return clock.format(d);
}

/** "3 min ago". Computed against a caller-supplied `now` so server and client
 *  renders agree and React does not warn about hydration. */
export function relativeTime(
  iso: string | null | undefined,
  now: number,
): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";

  const seconds = Math.round((now - then) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 45) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d ago`;
  const months = Math.round(days / 30);
  return `${months} mo ago`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

const DATE_ONLY = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" });

/** `date` columns arrive as `YYYY-MM-DD`; keep them timezone-free. */
export function dateOnly(value: string | null | undefined): string {
  if (!value) return "—";
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d) return value;
  return DATE_ONLY.format(new Date(Date.UTC(y, m - 1, d)));
}

const ISSUE_LABELS: Record<string, string> = {
  device_closure: "Shop closed, device still billing",
  plan_mismatch: "Plan promise mismatch",
  settlement_hold: "Settlement on hold",
  device_fault: "Device fault",
  unknown: "Not yet identified",
};

export function issueLabel(issueType: string | null | undefined): string {
  if (!issueType) return "Not yet identified";
  return ISSUE_LABELS[issueType] ?? issueType.replace(/_/g, " ");
}

const STATE_LABELS: Record<string, string> = {
  open: "Open",
  acting: "Acting",
  awaiting_approval: "Awaiting approval",
  resolved: "Resolved",
  handed_over: "Handed over",
};

export function stateLabel(state: string | null | undefined): string {
  if (!state) return "—";
  return STATE_LABELS[state] ?? state.replace(/_/g, " ");
}

/** One ring of colour per case state. Flat classes so Tailwind keeps them. */
export function stateClasses(state: string | null | undefined): string {
  switch (state) {
    case "open":
      return "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200";
    case "acting":
      return "bg-brand/12 text-brand dark:bg-brand/20";
    case "awaiting_approval":
      return "bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200";
    case "resolved":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200";
    case "handed_over":
      return "bg-violet-100 text-violet-800 dark:bg-violet-500/20 dark:text-violet-200";
    default:
      return "bg-muted text-muted-foreground";
  }
}

const LANGUAGES: Record<string, string> = {
  "te-IN": "Telugu",
  "hi-IN": "Hindi",
  "ta-IN": "Tamil",
  "kn-IN": "Kannada",
  "mr-IN": "Marathi",
  "bn-IN": "Bengali",
  "gu-IN": "Gujarati",
  "ml-IN": "Malayalam",
  "pa-IN": "Punjabi",
  "or-IN": "Odia",
  "en-IN": "English",
};

export function languageName(code: string | null | undefined): string {
  if (!code) return "—";
  return LANGUAGES[code] ? `${LANGUAGES[code]} (${code})` : code;
}

/** `get_merchant_context` -> `Get merchant context`. */
export function toolLabel(name: string | null | undefined): string {
  if (!name) return "event";
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
