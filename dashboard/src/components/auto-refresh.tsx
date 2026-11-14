"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Poll instead of subscribe.
 *
 * There is no browser-side Supabase key by design (RLS with zero policies, so
 * the anon key reads nothing), which rules out Realtime. `router.refresh()`
 * re-runs the server components every 3 seconds instead — invisible next to
 * the length of a phone call.
 */
export function AutoRefresh({ intervalMs = 3000 }: { intervalMs?: number }) {
  const router = useRouter();
  const [age, setAge] = useState(0);

  useEffect(() => {
    const tick = setInterval(() => setAge((a) => a + 1), 1000);
    const poll = setInterval(() => {
      router.refresh();
      setAge(0);
    }, intervalMs);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [router, intervalMs]);

  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
      <span className="relative flex size-2">
        <span className="absolute inline-flex size-2 animate-ping rounded-full bg-emerald-500 opacity-75" />
        <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
      </span>
      Live · polling every {Math.round(intervalMs / 1000)}s
      <span className="tabular-nums opacity-60">({age}s)</span>
    </span>
  );
}
