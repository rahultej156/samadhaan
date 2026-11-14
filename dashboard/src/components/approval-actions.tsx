"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckIcon, Loader2Icon, XIcon } from "lucide-react";
import { toast } from "sonner";

import { decideRefund } from "@/app/actions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * The human in the loop. Nothing is paid until one of these is clicked.
 *
 * The click calls a server action, which calls the backend with the shared
 * secret. No key and no Supabase call happens in the browser.
 */
export function ApprovalActions({
  requestRef,
  amountText,
  shopName,
  operator,
}: {
  requestRef: string;
  amountText: string;
  shopName: string;
  operator: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(null);

  function submit(decision: "approve" | "reject") {
    setConfirming(null);
    startTransition(async () => {
      const result = await decideRefund(requestRef, decision);
      if (result.ok) {
        toast.success(result.message);
      } else {
        toast.error(result.message);
      }
      router.refresh();
    });
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="lg"
          disabled={pending}
          onClick={() => setConfirming("approve")}
          className="bg-emerald-600 text-white hover:bg-emerald-600/85"
        >
          {pending ? <Loader2Icon className="animate-spin" /> : <CheckIcon />}
          Approve {amountText}
        </Button>
        <Button
          size="lg"
          variant="destructive"
          disabled={pending}
          onClick={() => setConfirming("reject")}
        >
          <XIcon />
          Reject
        </Button>
        <span className="text-xs text-muted-foreground">
          Recorded as <span className="font-medium text-foreground">{operator}</span> in the audit
          log
        </span>
      </div>

      <Dialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {confirming === "approve" ? "Approve this refund?" : "Reject this refund?"}
            </DialogTitle>
            <DialogDescription>
              {confirming === "approve" ? (
                <>
                  {amountText} will be approved for payout to {shopName}, against request{" "}
                  {requestRef}. This is the step the voice agent cannot take.
                </>
              ) : (
                <>
                  {requestRef} for {amountText} will be rejected and the case handed to a
                  person for follow-up with {shopName}.
                </>
              )}{" "}
              Recorded against {operator}.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="lg">
                Cancel
              </Button>
            </DialogClose>
            <Button
              size="lg"
              variant={confirming === "reject" ? "destructive" : "default"}
              className={
                confirming === "approve"
                  ? "bg-emerald-600 text-white hover:bg-emerald-600/85"
                  : undefined
              }
              onClick={() => confirming && submit(confirming)}
            >
              {confirming === "approve" ? `Yes, approve ${amountText}` : "Yes, reject"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
