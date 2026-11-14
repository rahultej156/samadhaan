import "server-only";

import { selectOne, selectRows } from "@/lib/rows";

/* ------------------------------------------------------------------ types */
/* Field names follow db/schema.sql exactly. numeric(12,2) columns come back
   as strings over PostgREST, so money is typed `string | number`.          */

export type Money = string | number | null;

/** One row of the `case_feed` view. */
export type CaseFeedRow = {
  id: string;
  case_ref: string;
  issue_type: string;
  state: string;
  language_code: string | null;
  caller_phone: string | null;
  call_count: number;
  last_call_at: string | null;
  issue_summary: string | null;
  opened_at: string;
  updated_at: string;
  resolved_at: string | null;
  merchant_code: string | null;
  shop_name: string | null;
  owner_name: string | null;
  city: string | null;
  action_count: number;
  calls: number;
  dropped_calls: number;
  pending_approvals: number;
  proofs_sent: number;
};

export type Merchant = {
  id: string;
  merchant_code: string;
  owner_name: string;
  shop_name: string;
  phone: string;
  language_code: string;
  city: string;
  address: string | null;
  shop_status: string;
  shop_closed_on: string | null;
  onboarded_on: string;
};

export type Device = {
  device_type: string;
  serial: string;
  status: string;
  activated_on: string;
  last_heartbeat_at: string | null;
  billing_stopped_from: string | null;
};

export type Plan = {
  promised_plan_name: string | null;
  promised_monthly_amount: Money;
  promised_by: string | null;
  promised_on: string | null;
  billed_plan_name: string;
  billed_monthly_amount: Money;
  billing_started_on: string;
};

export type Settlement = {
  amount_on_hold: Money;
  hold_reason_plain: string | null;
  missing_documents: string[] | null;
  held_since: string | null;
  expected_release_date: string | null;
  status: string;
};

export type CallSession = {
  id: string;
  interaction_id: string;
  sequence_no: number;
  caller_phone: string | null;
  language_code: string | null;
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  end_reason: string | null;
  ended_mid_action: boolean;
  turn_count: number;
};

export type CaseEvent = {
  id: number;
  call_session_id: string | null;
  actor: string;
  tool_name: string | null;
  /** Tool arguments. Only read for `identity_verified`, which carries
   *  `{"factor": "caller id" | "device serial"}` — how the caller was proven. */
  args: { factor?: string } | null;
  say: string | null;
  ok: boolean | null;
  latency_ms: number | null;
  at: string;
};

/** One spoken turn, as Sarvam's transcript recorded it at the end of the call. */
export type ConversationTurn = {
  id: number;
  call_session_id: string | null;
  role: "merchant" | "samadhan";
  text_original: string | null;
  text_english: string | null;
  language_code: string | null;
  at: string;
};

export type Proof = {
  proof_ref: string;
  channel: string;
  sent_to: string | null;
  subject: string | null;
  body_html: string | null;
  body_text: string | null;
  status: string;
  sent_at: string;
};

export type RefundRequest = {
  request_ref: string;
  amount: Money;
  reason: string;
  status: string;
  requested_at: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_note: string | null;
};

export type CreditNote = {
  note_ref: string;
  amount: Money;
  period_start: string;
  period_end: string;
  reason: string | null;
  created_at: string;
};

export type ServiceTicket = {
  ticket_ref: string;
  kind: string;
  scheduled_date: string;
  address: string | null;
  status: string;
  created_at: string;
};

export type Handover = {
  summary_ref: string;
  reason: string;
  summary_md: string;
  created_at: string;
};

export type CaseDetail = {
  feed: CaseFeedRow;
  merchant: Merchant | null;
  devices: Device[];
  plan: Plan | null;
  settlement: Settlement | null;
  calls: CallSession[];
  events: CaseEvent[];
  turns: ConversationTurn[];
  proofs: Proof[];
  pendingRefunds: RefundRequest[];
  decidedRefunds: RefundRequest[];
  creditNotes: CreditNote[];
  tickets: ServiceTicket[];
  handovers: Handover[];
};

/* ---------------------------------------------------------------- queries */

/**
 * The case list. A case with a refund waiting on a human sorts to the top:
 * it is the most urgent thing on this screen.
 */
export async function listCases(): Promise<CaseFeedRow[]> {
  const rows = await selectRows<CaseFeedRow>({
    table: "case_feed",
    order: { column: "updated_at", ascending: false },
    limit: 80,
  });

  return [...rows].sort((a, b) => {
    const urgency = Number(b.pending_approvals > 0) - Number(a.pending_approvals > 0);
    if (urgency !== 0) return urgency;
    return b.updated_at.localeCompare(a.updated_at);
  });
}

export async function getCaseDetail(caseRef: string): Promise<CaseDetail | null> {
  const feed = await selectOne<CaseFeedRow>({
    table: "case_feed",
    eq: ["case_ref", caseRef],
  });
  if (!feed) return null;

  const caseId = feed.id;

  // `cases.merchant_id` is nullable — a caller we could not identify still gets
  // a case — so every merchant-side read has to tolerate null.
  const caseRow = await selectOne<{ merchant_id: string | null }>({
    table: "cases",
    columns: "merchant_id",
    eq: ["id", caseId],
  });
  const merchantId = caseRow?.merchant_id ?? null;

  const [calls, events, turns, proofs, refunds, creditNotes, tickets, handovers] = await Promise.all([
    selectRows<CallSession>({
      table: "call_sessions",
      eq: ["case_id", caseId],
      order: { column: "sequence_no" },
    }),
    selectRows<CaseEvent>({
      table: "case_events",
      columns: "id,call_session_id,actor,tool_name,args,say,ok,latency_ms,at",
      eq: ["case_id", caseId],
      order: { column: "id" },
    }),
    selectRows<ConversationTurn>({
      table: "conversation_turns",
      columns: "id,call_session_id,role,text_original,text_english,language_code,at",
      eq: ["case_id", caseId],
      order: { column: "id" },
    }),
    selectRows<Proof>({
      table: "proofs",
      eq: ["case_id", caseId],
      order: { column: "sent_at", ascending: false },
    }),
    selectRows<RefundRequest>({
      table: "refund_requests",
      eq: ["case_id", caseId],
      order: { column: "requested_at", ascending: false },
    }),
    selectRows<CreditNote>({
      table: "credit_notes",
      eq: ["case_id", caseId],
      order: { column: "created_at", ascending: false },
    }),
    selectRows<ServiceTicket>({
      table: "service_tickets",
      eq: ["case_id", caseId],
      order: { column: "created_at", ascending: false },
    }),
    selectRows<Handover>({
      table: "handovers",
      columns: "summary_ref,reason,summary_md,created_at",
      eq: ["case_id", caseId],
      order: { column: "created_at", ascending: false },
    }),
  ]);

  const [merchant, devices, plan, settlement] = merchantId
    ? await Promise.all([
        selectOne<Merchant>({ table: "merchants", eq: ["id", merchantId] }),
        selectRows<Device>({
          table: "devices",
          eq: ["merchant_id", merchantId],
          order: { column: "activated_on" },
        }),
        selectOne<Plan>({ table: "plans", eq: ["merchant_id", merchantId] }),
        selectOne<Settlement>({ table: "settlements", eq: ["merchant_id", merchantId] }),
      ])
    : [null, [] as Device[], null, null];

  return {
    feed,
    merchant,
    devices,
    plan,
    settlement,
    calls,
    events,
    turns,
    proofs,
    pendingRefunds: refunds.filter((r) => r.status === "awaiting_approval"),
    decidedRefunds: refunds.filter((r) => r.status !== "awaiting_approval"),
    creditNotes,
    tickets,
    handovers,
  };
}
