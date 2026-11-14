import {
  InboxIcon,
  PhoneIncomingIcon,
  ShieldAlertIcon,
  TriangleAlertIcon,
  UserRoundIcon,
} from "lucide-react";

import { operatorName } from "@/app/actions";
import { AutoRefresh } from "@/components/auto-refresh";
import { CaseList } from "@/components/case-list";
import { CaseDetailPane } from "@/components/case-detail";
import { ThemeToggle } from "@/components/theme-toggle";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getCaseDetail, listCases, type CaseDetail, type CaseFeedRow } from "@/lib/data";
import { serverNow } from "@/lib/now";

/**
 * No browser-side Supabase key exists by design, so there is no Realtime
 * subscription. The server re-reads every 3 seconds instead; <AutoRefresh />
 * nudges the client to pick the new render up.
 */
export const revalidate = 3;

export default async function OperationsPage({ searchParams }: PageProps<"/">) {
  const params = await searchParams;
  const requested = typeof params.case === "string" ? params.case : undefined;

  let cases: CaseFeedRow[] = [];
  let loadError: string | null = null;
  try {
    cases = await listCases();
  } catch (error) {
    loadError = error instanceof Error ? error.message : String(error);
  }

  const selectedRef = requested ?? cases[0]?.case_ref ?? null;

  let detail: CaseDetail | null = null;
  if (!loadError && selectedRef) {
    try {
      detail = await getCaseDetail(selectedRef);
    } catch (error) {
      loadError = error instanceof Error ? error.message : String(error);
    }
  }

  const now = await serverNow();
  const operator = await operatorName();
  const awaiting = cases.reduce((n, c) => n + Number(c.pending_approvals), 0);
  const liveCalls = cases.filter((c) => c.state === "open" || c.state === "acting").length;

  return (
    <div className="flex h-dvh flex-col">
      {/* ------------------------------------------------------------- header */}
      <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3 lg:px-5">
        <div className="flex items-baseline gap-2.5">
          <span className="text-base font-semibold tracking-tight">Samadhan</span>
          <span className="hidden text-sm text-muted-foreground sm:inline">
            Merchant support operations
          </span>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <InboxIcon className="size-3.5" />
            <span className="font-semibold tabular-nums text-foreground">{cases.length}</span>
            cases
          </span>
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <PhoneIncomingIcon className="size-3.5" />
            <span className="font-semibold tabular-nums text-foreground">{liveCalls}</span>
            in progress
          </span>
          {awaiting > 0 ? (
            <Badge
              variant="ghost"
              className="h-6 gap-1.5 bg-amber-100 px-2.5 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200"
            >
              <ShieldAlertIcon className="size-3" />
              <span className="font-semibold tabular-nums">{awaiting}</span>
              awaiting approval
            </Badge>
          ) : (
            <span className="text-xs text-muted-foreground">0 awaiting approval</span>
          )}
          <AutoRefresh intervalMs={3000} />
          <span
            className="flex items-center gap-1.5 border-l pl-4 text-xs text-muted-foreground"
            title="Decisions are recorded against this name in the audit log"
          >
            <UserRoundIcon className="size-3.5" />
            <span className="font-medium text-foreground">{operator}</span>
          </span>
          <ThemeToggle />
        </div>
      </header>

      {/* --------------------------------------------------------------- body */}
      {loadError ? (
        <main className="p-4 lg:p-5">
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertTitle>Could not read the database</AlertTitle>
            <AlertDescription>
              {loadError}
              <br />
              Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in dashboard/.env.local. RLS is on
              with no policies, so only the service-role key can read these tables.
            </AlertDescription>
          </Alert>
        </main>
      ) : cases.length === 0 ? (
        <main className="flex flex-1 items-start justify-center p-4 lg:p-5">
          <Card className="w-full max-w-xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <InboxIcon className="size-4 text-muted-foreground" />
                No cases yet
              </CardTitle>
              <CardDescription>
                A case appears the moment a merchant calls. Nothing has come in.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>
                Cases only exist once a call has happened — the agent opens one on{" "}
                <code className="font-mono text-xs">call_started</code> and every tool call after
                that is appended to it.
              </p>
              <p>
                This view polls every 3 seconds, so a live call will show up here on its own.
              </p>
            </CardContent>
          </Card>
        </main>
      ) : (
        <main className="grid min-h-0 flex-1 grid-rows-[auto_1fr] lg:grid-cols-[22rem_1fr] lg:grid-rows-1 xl:grid-cols-[25rem_1fr]">
          <section
            aria-label="Cases"
            className="flex min-h-0 flex-col border-b lg:border-b-0 lg:border-r"
          >
            <div className="flex shrink-0 items-center justify-between gap-2 px-3.5 py-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Live cases
              </h2>
              <span className="text-xs text-muted-foreground tabular-nums">
                newest first
              </span>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden max-lg:max-h-72">
              <CaseList cases={cases} selectedRef={selectedRef} now={now} />
            </div>
          </section>

          <section aria-label="Case detail" className="min-h-0 overflow-hidden">
            {detail ? (
              <ScrollArea className="h-full">
                <CaseDetailPane detail={detail} now={now} operator={operator} />
              </ScrollArea>
            ) : (
              <div className="p-4 lg:p-5">
                <Alert>
                  <TriangleAlertIcon />
                  <AlertTitle>Case {selectedRef} not found</AlertTitle>
                  <AlertDescription>
                    Pick a case from the list on the left.
                  </AlertDescription>
                </Alert>
              </div>
            )}
          </section>
        </main>
      )}
    </div>
  );
}
