import { absoluteTime, relativeTime } from "@/lib/format";

/**
 * "3 min ago", with the absolute IST timestamp on hover.
 *
 * `now` is passed in from the server render so the string is stable between
 * server and client (no hydration mismatch). The page revalidates every 3s,
 * so it stays honest without client-side ticking.
 */
export function RelTime({
  iso,
  now,
  className,
}: {
  iso: string | null | undefined;
  now: number;
  className?: string;
}) {
  if (!iso) return <span className={className}>—</span>;
  return (
    <time dateTime={iso} title={absoluteTime(iso)} className={className}>
      {relativeTime(iso, now)}
    </time>
  );
}
