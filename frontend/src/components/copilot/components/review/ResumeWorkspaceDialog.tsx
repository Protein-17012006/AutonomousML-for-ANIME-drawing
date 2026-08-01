"use client";

// Shown on sign-in when the server still holds an unfinished run.
//
// It has two faces because there are two ways to arrive here, and telling them
// apart matters to the artist. A run that stopped mid-way is offered back
// ("Resume"); a run that FINISHED but whose save to history failed is a
// different message ("Finish saving") — their frames already exist and the only
// thing outstanding is filing them.

import { AlertTriangle, Loader2, RotateCcw, Save, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ActiveWorkspace } from "@/lib/activeWorkspaceApi";

interface Props {
  workspace: ActiveWorkspace | null;
  busy: boolean;
  error: string | null;
  onResume: () => void;
  onRetryPublish: () => void;
  onDiscard: () => void;
}

export function ResumeWorkspaceDialog({
  workspace,
  busy,
  error,
  onResume,
  onRetryPublish,
  onDiscard,
}: Props) {
  if (!workspace) return null;

  const pendingSave = workspace.state === "publish_pending";
  const pairs = workspace.snapshot?.pairs.length ?? 0;

  return (
    <Dialog open>
      <DialogContent showCloseButton={false} className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {pendingSave ? "Finish saving your session" : "Resume your workspace"}
          </DialogTitle>
          <DialogDescription>
            {error ??
              (pendingSave
                ? "Your generated frames are safe — saving them to your history did not finish."
                : pairs > 0
                  ? `A run with ${pairs} ${pairs === 1 ? "pair" : "pairs"} is still open. Pick it up where you left off, or throw it away.`
                  : "A run is still open on the server. Pick it up where you left off, or throw it away.")}
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <p className="flex items-start gap-2 font-body text-sm text-destructive">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>{error}</span>
          </p>
        ) : null}

        <DialogFooter className="gap-2 sm:justify-between">
          {/* Discard is destructive and deliberately the quiet one. */}
          <Button
            variant="ghost"
            onClick={onDiscard}
            disabled={busy}
            className="text-muted-foreground hover:text-destructive"
          >
            <Trash2 className="size-4" aria-hidden />
            Discard
          </Button>
          <Button onClick={pendingSave ? onRetryPublish : onResume} disabled={busy}>
            {busy ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : pendingSave ? (
              <Save className="size-4" aria-hidden />
            ) : (
              <RotateCcw className="size-4" aria-hidden />
            )}
            {pendingSave ? "Finish saving" : "Resume"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
