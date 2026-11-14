import "server-only";

/**
 * The clock, read once per server render and threaded down so every "3 min
 * ago" on the page agrees with every other one — and so the client renders the
 * same string the server did, instead of warning about a hydration mismatch.
 *
 * Async on purpose: the React Compiler's purity rule rightly refuses a bare
 * `Date.now()` in a component body.
 */
export async function serverNow(): Promise<number> {
  return Date.now();
}
