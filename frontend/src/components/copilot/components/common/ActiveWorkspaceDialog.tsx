"use client";

import { LoaderCircle, RotateCcw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import type { ActiveWorkspace } from "@/lib/activeWorkspace";

export function ActiveWorkspaceDialog({ workspace, busy, error, onResume, onRetry, onDiscard, intent = "recovery" }: {
  workspace: ActiveWorkspace | null;
  busy: boolean;
  error: string | null;
  onResume: () => void;
  onRetry: () => void;
  onDiscard: () => void;
  intent?: "recovery" | "run-preflight";
}) {
  if (!workspace) return null;
  const publishing = workspace.state === "publish_pending";
  const startingNewRun = intent === "run-preflight";
  return (
    <Dialog open onOpenChange={() => undefined}>
      <DialogContent showCloseButton={false} className="copilot-recovery-dialog" onEscapeKeyDown={(event) => event.preventDefault()} onPointerDownOutside={(event) => event.preventDefault()}>
        <DialogHeader>
          <DialogTitle>{startingNewRun ? "An active workspace is available" : publishing ? "Finish saving your session" : "Resume your workspace"}</DialogTitle>
          <DialogDescription>
            {error ?? (startingNewRun
              ? "Resume the existing workspace, or discard it and start the newly prepared session."
              : publishing
              ? "Your generated frames are safe on this workstation. Retry publishing them to your session history."
              : workspace.state === "generating"
                ? "Your co-pilot is still processing. Resume to review saved progress and reconnect."
                : "A recoverable co-pilot workspace is available on this workstation.")}
          </DialogDescription>
        </DialogHeader>
        <p className="copilot-recovery-readout">STATUS · {workspace.state.replaceAll("_", " ")} · EXPIRES {new Date(workspace.expires_at * 1000).toLocaleString()}</p>
        <DialogFooter>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" type="button" disabled={busy}><Trash2 data-icon="inline-start" />Discard</Button>
            </AlertDialogTrigger>
            <AlertDialogContent className="copilot-recovery-dialog">
              <AlertDialogHeader>
                <AlertDialogTitle>{startingNewRun ? "Discard the active workspace and start over?" : "Discard this workspace?"}</AlertDialogTitle>
                <AlertDialogDescription>{startingNewRun
                  ? "This removes the existing temporary source files and generated output. Your newly staged input will be used for the new run; completed history is not affected."
                  : "This removes the temporary source files and generated output from this workstation. Completed session history is not affected."}</AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={busy}>Keep workspace</AlertDialogCancel>
                <AlertDialogAction variant="destructive" disabled={busy} onClick={onDiscard}>{startingNewRun ? "Discard and run" : "Discard workspace"}</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <Button type="button" onClick={error ? onRetry : onResume} disabled={busy}>
            {busy ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : error ? <RotateCcw data-icon="inline-start" /> : null}
            {error ? "Retry" : startingNewRun ? "Resume workspace" : publishing ? "Resume and publish" : "Resume"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
