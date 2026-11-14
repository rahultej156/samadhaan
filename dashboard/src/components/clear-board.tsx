"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2Icon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";

import { resetDemo } from "@/app/actions";
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
 * Empties the board for a clean demo take. Asks first: this deletes every
 * case in the shared database, not just what this screen shows.
 */
export function ClearBoard({ caseCount }: { caseCount: number }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();

  function clear() {
    setOpen(false);
    startTransition(async () => {
      const result = await resetDemo();
      if (result.ok) {
        toast.success(result.message);
        router.push("/");
      } else {
        toast.error(result.message);
      }
      router.refresh();
    });
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        disabled={pending}
        onClick={() => setOpen(true)}
        title="Delete every case and reset the four demo merchants"
      >
        {pending ? <Loader2Icon className="animate-spin" /> : <Trash2Icon />}
        Clear
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Clear the board?</DialogTitle>
            <DialogDescription>
              All {caseCount} case{caseCount === 1 ? "" : "s"} will be deleted, with their calls,
              transcripts, refunds, credit notes and tickets. The four demo merchants go back to
              their starting state, ready for a fresh demo. Phone links made with bind-phone are
              kept. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="lg">
                Cancel
              </Button>
            </DialogClose>
            <Button size="lg" variant="destructive" onClick={clear}>
              Yes, clear everything
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
