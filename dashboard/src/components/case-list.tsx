import Link from "next/link";
import { PhoneOffIcon, PhoneIcon, IndianRupeeIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { RelTime } from "@/components/rel-time";
import type { CaseFeedRow } from "@/lib/data";
import { cn } from "@/lib/utils";
import { issueLabel, stateClasses, stateLabel } from "@/lib/format";

export function CaseList({
  cases,
  selectedRef,
  now,
}: {
  cases: CaseFeedRow[];
  selectedRef: string | null;
  now: number;
}) {
  return (
    <ScrollArea className="h-full">
      <ul className="divide-y">
        {cases.map((c) => {
          const selected = c.case_ref === selectedRef;
          const urgent = c.pending_approvals > 0;

          return (
            <li key={c.id}>
              <Link
                href={`/?case=${encodeURIComponent(c.case_ref)}`}
                scroll={false}
                aria-current={selected ? "true" : undefined}
                className={cn(
                  "block border-l-[3px] px-3.5 py-3 transition-colors",
                  selected
                    ? "border-l-brand bg-brand/[0.07]"
                    : "border-l-transparent hover:bg-muted/60",
                  urgent && !selected && "border-l-amber-500 bg-amber-50/70 dark:bg-amber-500/8",
                  urgent && selected && "border-l-amber-500",
                )}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono text-xs font-medium tracking-tight text-muted-foreground tabular-nums">
                    {c.case_ref}
                  </span>
                  <Badge variant="ghost" className={cn("shrink-0", stateClasses(c.state))}>
                    {stateLabel(c.state)}
                  </Badge>
                </div>

                <div className="mt-1 truncate text-sm font-semibold">
                  {c.shop_name ?? "Unidentified caller"}
                </div>

                <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="font-mono tabular-nums">{c.merchant_code ?? "—"}</span>
                  <span aria-hidden>·</span>
                  <span className="truncate">{issueLabel(c.issue_type)}</span>
                </div>

                {urgent && (
                  <div className="mt-2 flex items-center gap-1.5 rounded-md bg-amber-500/15 px-2 py-1 text-xs font-semibold text-amber-900 dark:text-amber-200">
                    <span className="relative flex size-1.5">
                      <span className="absolute inline-flex size-1.5 animate-ping rounded-full bg-amber-600" />
                      <span className="relative inline-flex size-1.5 rounded-full bg-amber-600" />
                    </span>
                    <IndianRupeeIcon className="size-3" />
                    {c.pending_approvals} refund{c.pending_approvals > 1 ? "s" : ""} awaiting your
                    approval
                  </div>
                )}

                <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span className="flex items-center gap-2.5 tabular-nums">
                    <span className="inline-flex items-center gap-1" title="Calls on this case">
                      <PhoneIcon className="size-3" />
                      {c.calls}
                    </span>
                    {c.dropped_calls > 0 && (
                      <span
                        className="inline-flex items-center gap-1 text-destructive"
                        title="Calls that dropped"
                      >
                        <PhoneOffIcon className="size-3" />
                        {c.dropped_calls}
                      </span>
                    )}
                    <span title="Actions in the audit log">{c.action_count} actions</span>
                  </span>
                  <RelTime iso={c.updated_at} now={now} className="shrink-0" />
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </ScrollArea>
  );
}
