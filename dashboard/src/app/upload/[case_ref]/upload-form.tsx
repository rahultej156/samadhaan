"use client";

import { useState } from "react";
import { CheckCircle2Icon, Loader2Icon, UploadIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Stub. Nothing is uploaded anywhere — it confirms to the merchant and stops.
 * Wiring real storage is a post-hackathon job.
 */
export function UploadForm({ caseRef }: { caseRef: string }) {
  const [pan, setPan] = useState<string | null>(null);
  const [gst, setGst] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pan && !gst) {
      toast.error("Add at least one document before sending.");
      return;
    }
    setSending(true);
    window.setTimeout(() => {
      setSending(false);
      setDone(true);
      toast.success(`Documents received for ${caseRef}. We will message you after the check.`);
    }, 700);
  }

  if (done) {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-3 dark:border-emerald-500/40 dark:bg-emerald-500/10">
        <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-emerald-600" />
        <div className="space-y-1 text-sm">
          <p className="font-semibold">Documents received</p>
          <p className="text-muted-foreground">
            {[pan, gst].filter(Boolean).join(" and ")} sent against {caseRef}. You will get a
            message on your registered mobile number once they are checked.
          </p>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="pan">PAN card photo</Label>
        <Input
          id="pan"
          name="pan"
          type="file"
          accept="image/*,application/pdf"
          onChange={(e) => setPan(e.target.files?.[0]?.name ?? null)}
        />
        <p className="text-xs text-muted-foreground">
          {pan ? `Selected: ${pan}` : "A clear photo of the PAN card is enough."}
        </p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="gst">GST certificate</Label>
        <Input
          id="gst"
          name="gst"
          type="file"
          accept="image/*,application/pdf"
          onChange={(e) => setGst(e.target.files?.[0]?.name ?? null)}
        />
        <p className="text-xs text-muted-foreground">
          {gst ? `Selected: ${gst}` : "Photo or PDF of the GST registration certificate."}
        </p>
      </div>

      <Button type="submit" size="lg" className="w-full" disabled={sending}>
        {sending ? <Loader2Icon className="animate-spin" /> : <UploadIcon />}
        {sending ? "Sending" : "Send documents"}
      </Button>
    </form>
  );
}
