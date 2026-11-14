import {
  AlertTriangleIcon,
  BanknoteIcon,
  CheckCircle2Icon,
  FileTextIcon,
  MessageSquareQuoteIcon,
  PhoneOffIcon,
  ShieldCheckIcon,
  StoreIcon,
  TruckIcon,
  UserRoundIcon,
  WrenchIcon,
  XCircleIcon,
} from "lucide-react";

import { ApprovalActions } from "@/components/approval-actions";
import { RelTime } from "@/components/rel-time";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { CaseDetail } from "@/lib/data";
import {
  absoluteTime,
  clockTime,
  dateOnly,
  duration,
  issueLabel,
  languageName,
  money,
  stateClasses,
  stateLabel,
  toolLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------- small bits */

function Fact({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  tone?: "warn";
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.7rem] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-0.5 truncate text-sm",
          mono && "font-mono tabular-nums",
          tone === "warn" && "font-semibold text-amber-700 dark:text-amber-300",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function SectionTitle({
  icon: Icon,
  children,
  count,
}: {
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <CardTitle className="flex items-center gap-2 text-sm font-semibold">
      <Icon className="size-4 text-muted-foreground" />
      {children}
      {count !== undefined && (
        <span className="text-xs font-normal text-muted-foreground tabular-nums">({count})</span>
      )}
    </CardTitle>
  );
}

/* ------------------------------------------------------------------- panes */

export function CaseDetailPane({
  detail,
  now,
  operator,
}: {
  detail: CaseDetail;
  now: number;
  operator: string;
}) {
  const {
    feed,
    merchant,
    devices,
    plan,
    settlement,
    calls,
    events,
    proofs,
    pendingRefunds,
    decidedRefunds,
    creditNotes,
    tickets,
    handovers,
  } = detail;

  const shopName = merchant?.shop_name ?? feed.shop_name ?? "Unidentified caller";
  const spokenEvents = events.filter((e) => e.say);

  return (
    <div className="space-y-4 p-4 pb-16 lg:p-5">
      {/* 1 ------------------------------------------------- merchant header */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <StoreIcon className="size-4 text-muted-foreground" />
            <CardTitle className="text-lg leading-tight">{shopName}</CardTitle>
            <Badge variant="ghost" className={stateClasses(feed.state)}>
              {stateLabel(feed.state)}
            </Badge>
            {merchant?.shop_status === "closed" && (
              <Badge variant="destructive">
                Shop closed {merchant.shop_closed_on ? dateOnly(merchant.shop_closed_on) : ""}
              </Badge>
            )}
          </div>
          <CardDescription className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-mono text-xs tabular-nums text-foreground">{feed.case_ref}</span>
            <span aria-hidden>·</span>
            <span>{issueLabel(feed.issue_type)}</span>
            <span aria-hidden>·</span>
            <span>
              opened <RelTime iso={feed.opened_at} now={now} />
            </span>
            <span aria-hidden>·</span>
            <span>
              updated <RelTime iso={feed.updated_at} now={now} />
            </span>
          </CardDescription>
          <CardAction>
            <div className="text-right">
              <div className="text-2xl font-semibold tabular-nums leading-none">{feed.calls}</div>
              <div className="text-[0.7rem] uppercase tracking-wide text-muted-foreground">
                {feed.calls === 1 ? "call" : "calls"}
              </div>
            </div>
          </CardAction>
        </CardHeader>

        <CardContent className="space-y-4">
          {feed.issue_summary && (
            <p className="text-sm text-muted-foreground">{feed.issue_summary}</p>
          )}

          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 xl:grid-cols-4">
            <Fact
              label="Merchant"
              value={`${merchant?.merchant_code ?? feed.merchant_code ?? "—"}`}
              mono
            />
            <Fact
              label="Owner"
              value={
                <span className="inline-flex items-center gap-1.5">
                  <UserRoundIcon className="size-3.5 text-muted-foreground" />
                  {merchant?.owner_name ?? feed.owner_name ?? "—"}
                </span>
              }
            />
            <Fact label="City" value={merchant?.city ?? feed.city ?? "—"} />
            <Fact
              label="Phone"
              value={merchant?.phone ?? feed.caller_phone ?? "—"}
              mono
            />
            <Fact
              label="Language"
              value={languageName(merchant?.language_code ?? feed.language_code)}
            />
            <Fact
              label="Shop status"
              value={
                merchant?.shop_status === "closed"
                  ? `Closed ${dateOnly(merchant.shop_closed_on)}`
                  : (merchant?.shop_status ?? "—")
              }
              tone={merchant?.shop_status === "closed" ? "warn" : undefined}
            />
            {merchant?.address && <Fact label="Address" value={merchant.address} />}
            {merchant && <Fact label="Onboarded" value={dateOnly(merchant.onboarded_on)} />}
          </dl>

          {devices.length > 0 && (
            <>
              <Separator />
              <div className="space-y-3">
                {devices.map((d) => (
                  <dl
                    key={d.serial}
                    className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 xl:grid-cols-4"
                  >
                    <Fact label={d.device_type} value={d.serial} mono />
                    <Fact
                      label="Device status"
                      value={
                        <Badge
                          variant="ghost"
                          className={
                            d.status === "active"
                              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200"
                              : "bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200"
                          }
                        >
                          {d.status.replace(/_/g, " ")}
                        </Badge>
                      }
                    />
                    <Fact
                      label="Last heartbeat"
                      value={<RelTime iso={d.last_heartbeat_at} now={now} />}
                    />
                    <Fact
                      label="Billing stopped"
                      value={d.billing_stopped_from ? dateOnly(d.billing_stopped_from) : "still billing"}
                      tone={d.billing_stopped_from ? undefined : "warn"}
                    />
                  </dl>
                ))}
              </div>
            </>
          )}

          {(plan || settlement?.status === "on_hold") && <Separator />}

          {plan && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 xl:grid-cols-4">
              <Fact
                label="Promised plan"
                value={
                  plan.promised_plan_name
                    ? `${plan.promised_plan_name} · ${money(plan.promised_monthly_amount)}/mo`
                    : "none on record"
                }
              />
              <Fact
                label="Billed plan"
                value={`${plan.billed_plan_name} · ${money(plan.billed_monthly_amount)}/mo`}
              />
              <Fact label="Billing since" value={dateOnly(plan.billing_started_on)} />
              {plan.promised_by && <Fact label="Promised by" value={plan.promised_by} />}
            </dl>
          )}

          {settlement && settlement.status === "on_hold" && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 xl:grid-cols-4">
              <Fact
                label="Settlement on hold"
                value={money(settlement.amount_on_hold)}
                tone="warn"
                mono
              />
              <Fact label="Held since" value={dateOnly(settlement.held_since)} />
              <Fact
                label="Missing documents"
                value={
                  settlement.missing_documents?.length
                    ? settlement.missing_documents.join(", ")
                    : "—"
                }
              />
              <Fact
                label="Expected release"
                value={dateOnly(settlement.expected_release_date)}
              />
            </dl>
          )}
        </CardContent>
      </Card>

      {/* 5 (hoisted) ------------------------------------- refund approval */}
      <RefundApproval
        pending={pendingRefunds}
        decided={decidedRefunds}
        shopName={shopName}
        operator={operator}
        now={now}
      />

      {/* 2 ---------------------------------------------------- call sessions */}
      <Card>
        <CardHeader>
          <SectionTitle icon={PhoneOffIcon} count={calls.length}>
            Call sessions
          </SectionTitle>
          <CardDescription>
            One case, many calls. A dropped call plus a callback is the same case — the agent
            resumes instead of restarting.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {calls.length === 0 ? (
            <p className="text-sm text-muted-foreground">No call sessions recorded yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">#</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Turns</TableHead>
                  <TableHead>Ended</TableHead>
                  <TableHead className="text-right">Flags</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {calls.map((c) => (
                  <TableRow
                    key={c.id}
                    className={cn(
                      c.end_reason === "disconnected" && "bg-destructive/5",
                      c.ended_mid_action && "bg-amber-50 dark:bg-amber-500/10",
                    )}
                  >
                    <TableCell className="font-mono tabular-nums">{c.sequence_no}</TableCell>
                    <TableCell title={absoluteTime(c.started_at)}>
                      <span className="font-mono text-xs tabular-nums">
                        {clockTime(c.started_at)}
                      </span>{" "}
                      <span className="text-muted-foreground">
                        <RelTime iso={c.started_at} now={now} />
                      </span>
                    </TableCell>
                    <TableCell className="tabular-nums">{duration(c.duration_s)}</TableCell>
                    <TableCell className="tabular-nums">{c.turn_count}</TableCell>
                    <TableCell>
                      {c.end_reason === "disconnected" ? (
                        <Badge variant="destructive" className="gap-1">
                          <PhoneOffIcon className="size-3" />
                          disconnected
                        </Badge>
                      ) : c.end_reason ? (
                        <Badge variant="outline">{c.end_reason}</Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">in progress</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {c.ended_mid_action ? (
                        <Badge
                          variant="ghost"
                          className="gap-1 bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200"
                        >
                          <AlertTriangleIcon className="size-3" />
                          ended mid-action
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 3 --------------------------------------------------- action timeline */}
      <Card>
        <CardHeader>
          <SectionTitle icon={MessageSquareQuoteIcon} count={events.length}>
            Action timeline
          </SectionTitle>
          <CardDescription>
            Append-only audit log. The quoted line is the exact sentence the agent spoke —
            computed by the backend, never composed by the model.
          </CardDescription>
          <CardAction>
            <span className="text-xs text-muted-foreground tabular-nums">
              {spokenEvents.length} spoken
            </span>
          </CardAction>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing has happened on this case yet.</p>
          ) : (
            <ol className="relative space-y-3 border-l pl-5">
              {events.map((e) => (
                <li key={e.id} className="relative">
                  <span
                    className={cn(
                      "absolute -left-[1.4rem] top-1.5 size-2 rounded-full ring-3 ring-card",
                      e.ok === false ? "bg-destructive" : "bg-brand",
                    )}
                  />
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="text-sm font-medium">{toolLabel(e.tool_name)}</span>
                    {e.ok === false && (
                      <Badge variant="destructive" className="gap-1">
                        <XCircleIcon className="size-3" />
                        failed
                      </Badge>
                    )}
                    {e.actor !== "agent" && (
                      <Badge variant="outline" className="text-[0.65rem]">
                        {e.actor}
                      </Badge>
                    )}
                    {e.tool_name === "identity_verified" && e.args?.factor && (
                      <Badge
                        variant="ghost"
                        className="gap-1 bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200"
                        title="Which factor proved the caller is the merchant"
                      >
                        <ShieldCheckIcon className="size-3" />
                        {e.args.factor}
                      </Badge>
                    )}
                    <span
                      className="text-xs text-muted-foreground tabular-nums"
                      title={absoluteTime(e.at)}
                    >
                      {clockTime(e.at)}
                    </span>
                    {e.latency_ms !== null && (
                      <span
                        className={cn(
                          "text-xs tabular-nums",
                          e.latency_ms > 2000 ? "text-amber-600" : "text-muted-foreground",
                        )}
                        title="Tool budget is 2000 ms"
                      >
                        {e.latency_ms} ms
                      </span>
                    )}
                  </div>
                  {e.say && (
                    <blockquote className="mt-1.5 border-l-2 border-brand/50 bg-brand/[0.05] py-1.5 pl-3 pr-2 text-[0.9rem] leading-relaxed">
                      <span className="text-muted-foreground">&ldquo;</span>
                      {e.say}
                      <span className="text-muted-foreground">&rdquo;</span>
                    </blockquote>
                  )}
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      {/* 4 ------------------------------------------------- the written proof */}
      <Card>
        <CardHeader>
          <SectionTitle icon={FileTextIcon} count={proofs.length}>
            Written proof sent to the merchant
          </SectionTitle>
          <CardDescription>
            Nothing is only spoken. Every action is confirmed in writing on the merchant&rsquo;s
            registered number.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {proofs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No written confirmation has been sent for this case yet.
            </p>
          ) : (
            proofs.map((p) => (
              <div key={p.proof_ref} className="space-y-2">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="font-mono tabular-nums text-foreground">{p.proof_ref}</span>
                  <Badge variant="outline">{p.channel}</Badge>
                  <Badge
                    variant="ghost"
                    className={
                      p.status === "sent"
                        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200"
                        : "bg-destructive/10 text-destructive"
                    }
                  >
                    {p.status}
                  </Badge>
                  {p.sent_to && <span className="font-mono tabular-nums">{p.sent_to}</span>}
                  <span>
                    sent <RelTime iso={p.sent_at} now={now} />
                  </span>
                </div>
                {p.subject && <div className="text-sm font-semibold">{p.subject}</div>}
                {p.body_html ? (
                  <Tabs defaultValue="rendered">
                    <TabsList>
                      <TabsTrigger value="rendered">As the merchant sees it</TabsTrigger>
                      <TabsTrigger value="text">Plain text</TabsTrigger>
                    </TabsList>
                    <TabsContent value="rendered">
                      <div
                        className="proof-html rounded-lg border bg-background p-4"
                        /* Trusted: generated by our own backend, never merchant input. */
                        dangerouslySetInnerHTML={{ __html: p.body_html }}
                      />
                    </TabsContent>
                    <TabsContent value="text">
                      <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-4 text-xs leading-relaxed whitespace-pre-wrap">
                        {p.body_text ?? "—"}
                      </pre>
                    </TabsContent>
                  </Tabs>
                ) : (
                  <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-4 text-xs leading-relaxed whitespace-pre-wrap">
                    {p.body_text ?? "—"}
                  </pre>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {/* 6 ----------------------------------------- credits, tickets, handover */}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <SectionTitle icon={BanknoteIcon} count={creditNotes.length}>
              Credit notes
            </SectionTitle>
          </CardHeader>
          <CardContent>
            {creditNotes.length === 0 ? (
              <p className="text-sm text-muted-foreground">No credit note on this case.</p>
            ) : (
              <ul className="space-y-3">
                {creditNotes.map((n) => (
                  <li key={n.note_ref} className="space-y-1">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="font-mono text-xs tabular-nums">{n.note_ref}</span>
                      <span className="text-sm font-semibold tabular-nums">
                        {money(n.amount)}
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {dateOnly(n.period_start)} – {dateOnly(n.period_end)}
                      {n.reason ? ` · ${n.reason}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <SectionTitle icon={TruckIcon} count={tickets.length}>
              Field visits
            </SectionTitle>
          </CardHeader>
          <CardContent>
            {tickets.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No pickup or technician visit on this case.
              </p>
            ) : (
              <ul className="space-y-3">
                {tickets.map((t) => (
                  <li key={t.ticket_ref} className="space-y-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="inline-flex items-center gap-1.5">
                        {t.kind === "pickup" ? (
                          <TruckIcon className="size-3.5 text-muted-foreground" />
                        ) : (
                          <WrenchIcon className="size-3.5 text-muted-foreground" />
                        )}
                        <span className="font-mono text-xs tabular-nums">{t.ticket_ref}</span>
                        <Badge variant="outline">{t.kind}</Badge>
                      </span>
                      <Badge
                        variant="ghost"
                        className={
                          t.status === "scheduled"
                            ? "bg-brand/12 text-brand dark:bg-brand/20"
                            : t.status === "completed"
                              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200"
                              : "bg-muted text-muted-foreground"
                        }
                      >
                        {t.status}
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {dateOnly(t.scheduled_date)}
                      {t.address ? ` · ${t.address}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      {handovers.length > 0 && (
        <Card>
          <CardHeader>
            <SectionTitle icon={UserRoundIcon} count={handovers.length}>
              Handed to a person
            </SectionTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {handovers.map((h) => (
              <div key={h.summary_ref} className="space-y-2">
                <div className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                  <span className="font-mono tabular-nums text-foreground">{h.summary_ref}</span>
                  <span>{h.reason}</span>
                  <RelTime iso={h.created_at} now={now} />
                </div>
                <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-3 text-xs leading-relaxed whitespace-pre-wrap">
                  {h.summary_md}
                </pre>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ----------------------------------------------------- the safety claim */

function RefundApproval({
  pending,
  decided,
  shopName,
  operator,
  now,
}: {
  pending: CaseDetail["pendingRefunds"];
  decided: CaseDetail["decidedRefunds"];
  shopName: string;
  operator: string;
  now: number;
}) {
  const hasPending = pending.length > 0;

  return (
    <Card
      className={cn(
        hasPending &&
          "border-amber-400 bg-amber-50/60 shadow-sm ring-1 ring-amber-300/60 dark:border-amber-500/50 dark:bg-amber-500/8 dark:ring-amber-500/20",
      )}
    >
      <CardHeader>
        <SectionTitle icon={ShieldCheckIcon}>Refund approval</SectionTitle>
        <CardDescription>
          The agent can raise a refund. Only a person can pay one.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {hasPending ? (
          pending.map((r) => (
            <div key={r.request_ref} className="space-y-3">
              <Alert className="border-amber-300 bg-transparent dark:border-amber-500/40">
                <AlertTriangleIcon className="text-amber-600 dark:text-amber-400" />
                <AlertTitle>Waiting on a human decision</AlertTitle>
                <AlertDescription>
                  No money moves until someone clicks a button below.
                </AlertDescription>
              </Alert>

              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <div className="text-3xl font-semibold tabular-nums leading-none">
                    {money(r.amount)}
                  </div>
                  <div className="mt-1.5 text-xs text-muted-foreground">
                    <span className="font-mono tabular-nums text-foreground">
                      {r.request_ref}
                    </span>{" "}
                    · requested <RelTime iso={r.requested_at} now={now} />
                  </div>
                </div>
                <p className="max-w-md text-sm text-muted-foreground">{r.reason}</p>
              </div>

              <ApprovalActions
                requestRef={r.request_ref}
                amountText={money(r.amount)}
                shopName={shopName}
                operator={operator}
              />
            </div>
          ))
        ) : decided.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No refund has been requested on this case.
          </p>
        ) : null}

        {decided.length > 0 && (
          <>
            {hasPending && <Separator />}
            <ul className="space-y-2">
              {decided.map((r) => (
                <li
                  key={r.request_ref}
                  className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm"
                >
                  <span className="inline-flex items-center gap-2">
                    {r.status === "approved" ? (
                      <CheckCircle2Icon className="size-4 text-emerald-600" />
                    ) : (
                      <XCircleIcon className="size-4 text-destructive" />
                    )}
                    <span className="font-mono text-xs tabular-nums">{r.request_ref}</span>
                    <span className="font-semibold tabular-nums">{money(r.amount)}</span>
                    <Badge
                      variant="ghost"
                      className={
                        r.status === "approved"
                          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200"
                          : "bg-destructive/10 text-destructive"
                      }
                    >
                      {r.status}
                    </Badge>
                  </span>
                  <span className="text-xs text-muted-foreground">
                    by {r.decided_by ?? "—"} · <RelTime iso={r.decided_at} now={now} />
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
