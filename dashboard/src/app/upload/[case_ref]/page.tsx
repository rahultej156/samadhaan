import Link from "next/link";
import { LockIcon, ShieldCheckIcon } from "lucide-react";

import { UploadForm } from "@/app/upload/[case_ref]/upload-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export const metadata = {
  title: "Upload your documents — Samadhan",
};

/**
 * The link in the settlement-hold proof points here (backend: engine.upload_url).
 * A merchant whose settlement is held opens this from WhatsApp, so it has to
 * look like something a shopkeeper can use on a phone.
 */
export default async function UploadPage({ params }: PageProps<"/upload/[case_ref]">) {
  const { case_ref } = await params;
  const caseRef = decodeURIComponent(case_ref);

  return (
    <div className="mx-auto flex w-full max-w-xl flex-1 flex-col gap-4 px-4 py-8 sm:py-14">
      <div className="flex items-baseline gap-2.5">
        <span className="text-base font-semibold tracking-tight">Samadhan</span>
        <span className="text-sm text-muted-foreground">Paytm merchant support</span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Upload your documents</CardTitle>
          <CardDescription>
            Your settlement is on hold because two documents are missing. Send them here and the
            money is released once they are checked.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/40 px-3 py-2">
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Case reference
            </span>
            <span className="font-mono text-sm font-semibold tabular-nums">{caseRef}</span>
          </div>

          <UploadForm caseRef={caseRef} />

          <Separator />

          <ul className="space-y-2 text-xs text-muted-foreground">
            <li className="flex items-start gap-2">
              <LockIcon className="mt-0.5 size-3.5 shrink-0" />
              Photos are used only to clear this settlement hold.
            </li>
            <li className="flex items-start gap-2">
              <ShieldCheckIcon className="mt-0.5 size-3.5 shrink-0" />
              A person checks the documents. You get a message either way.
            </li>
          </ul>
        </CardContent>
      </Card>

      <p className="text-center text-xs text-muted-foreground">
        <Link href="/" className="underline underline-offset-2">
          Support operations
        </Link>
      </p>
    </div>
  );
}
