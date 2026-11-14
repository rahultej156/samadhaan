"use server";

import { revalidatePath } from "next/cache";

export type DecisionResult = {
  ok: boolean;
  message: string;
};

/**
 * Who released the money. Stored by the backend as the audit record of the
 * decision, so it must be a real identity, not a hardcoded string.
 */
export async function operatorName(): Promise<string> {
  return process.env.OPERATOR_NAME?.trim() || "demo operator";
}

/**
 * Clear the board between demo takes. Calls the backend's /admin/reset, which
 * re-runs db/seed.sql: every case, call, transcript, refund, credit note and
 * ticket goes, the four demo merchants are restored to their starting state,
 * and phone bindings are kept.
 */
export async function resetDemo(): Promise<DecisionResult> {
  const base = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  const key = process.env.OPERATOR_API_KEY || process.env.SAMADHAN_API_KEY;
  if (!key) {
    return { ok: false, message: "Set OPERATOR_API_KEY in dashboard/.env.local" };
  }

  let response: Response;
  try {
    response = await fetch(`${base.replace(/\/$/, "")}/admin/reset`, {
      method: "POST",
      headers: { "X-Samadhan-Key": key },
      cache: "no-store",
    });
  } catch {
    return { ok: false, message: `Backend unreachable at ${base}. Is it running?` };
  }

  let body: Record<string, unknown> = {};
  try {
    body = (await response.json()) as Record<string, unknown>;
  } catch {
    /* non-JSON error page */
  }

  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    return { ok: false, message: `Not cleared — ${detail}` };
  }

  revalidatePath("/");
  const n = typeof body.cases_cleared === "number" ? body.cases_cleared : 0;
  const kept = typeof body.bindings_kept === "number" ? body.bindings_kept : 0;
  return {
    ok: true,
    message: `Cleared ${n} case${n === 1 ? "" : "s"}. Demo merchants reset${
      kept ? `, ${kept} phone link${kept === 1 ? "" : "s"} kept` : ""
    }.`,
  };
}

/**
 * The refund decision. It does not touch the database; it
 * calls the backend, which owns the audit log and the case state machine.
 *
 * Runs on the server, so no key reaches the browser. The key is the OPERATOR
 * key, deliberately not the voice platform's SAMADHAN_API_KEY — that one lives
 * in a third party's tool config and must not be able to approve money. The
 * backend still accepts it as a fallback while OPERATOR_API_KEY is unset.
 */
export async function decideRefund(
  requestRef: string,
  decision: "approve" | "reject",
): Promise<DecisionResult> {
  const base = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  const key = process.env.OPERATOR_API_KEY || process.env.SAMADHAN_API_KEY;
  const decidedBy = await operatorName();

  if (!key) {
    return {
      ok: false,
      message: "Set OPERATOR_API_KEY (or SAMADHAN_API_KEY) in dashboard/.env.local",
    };
  }

  let response: Response;
  try {
    response = await fetch(
      `${base.replace(/\/$/, "")}/ops/approvals/${encodeURIComponent(requestRef)}/${decision}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Samadhan-Key": key },
        body: JSON.stringify({ decided_by: decidedBy }),
        cache: "no-store",
      },
    );
  } catch {
    return { ok: false, message: `Backend unreachable at ${base}. Is it running on port 8000?` };
  }

  let body: Record<string, unknown> = {};
  try {
    body = (await response.json()) as Record<string, unknown>;
  } catch {
    /* non-JSON error page */
  }

  const past = decision === "approve" ? "approved" : "rejected";

  if (!response.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : typeof body.reason === "string"
          ? body.reason
          : `HTTP ${response.status}`;
    return { ok: false, message: `${requestRef} not ${past} — ${detail}` };
  }

  revalidatePath("/");

  const amount = typeof body.amount_text === "string" ? ` ${body.amount_text}` : "";
  const status = typeof body.status === "string" ? body.status : past;
  return { ok: true, message: `${requestRef}${amount} ${status} by ${decidedBy}` };
}
