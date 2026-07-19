"use client";

import { useRef } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BrandIcon } from "@/components/common/BrandIcon";
import { isPng, isVideoFile } from "../../lib/media";

interface ChatWelcomeProps {
  username?: string; // Implement User object in the future
  onImportFrames?: (files: File[]) => void;
  onImportVideo?: (file: File) => void;
}

// Empty-state greeting on the chat surface, styled with the co-pilot ink tokens.
// The two CTAs are quick-import entry points: they proxy-click hidden pickers and lift the
// filtered media up — the parent feeds it into the SAME keys/video state the KeyframeDropzone
// reads and flips the mode dropdown, so the dropzone preview + selector update in lockstep.
export function ChatWelcome({
  username = "Animator",
  onImportFrames,
  onImportVideo,
}: ChatWelcomeProps) {
  const framesInputRef = useRef<HTMLInputElement>(null);
  const videoInputRef = useRef<HTMLInputElement>(null);

  return (
    <Card className="flex-1 w-full flex flex-col justify-start gap-4 rounded-xl bg-transparent ring-0 text-washi">
      <CardHeader className="flex flex-col gap-2">
        {/* brand mark — full-width row so justify-center actually centers the icon
            (CardHeader is a flex col with items-start, which otherwise left-pins it) */}
        <div className="w-full flex justify-center">
          <BrandIcon />
        </div>
        <CardTitle className="w-full font-display text-2xl text-center text-washi">
          Welcome, <span className="italic text-ao">{username}</span> !
        </CardTitle>

        <CardDescription className="self-center max-w-md font-body text-sm text-center leading-6 text-ash">
          Start a new in-between session by importing your keyframes or a
          reference video. The co-pilot will prepare the workspace and guide you
          through interpolation and quality verification.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col sm:flex-row gap-4">
        {/* hidden pickers — the CTAs proxy-click these. `accept` is only a dialog hint, so we
            filter for real with the same predicates the dropzone uses (lib/media). */}
        <input
          ref={framesInputRef}
          type="file"
          accept="image/png"
          multiple
          className="sr-only"
          onChange={(e) => {
            // snapshot before resetting value (the load→clear→load bug; see FilePicker)
            const picked = Array.from(e.currentTarget.files ?? []).filter(isPng);
            e.currentTarget.value = "";
            if (picked.length) onImportFrames?.(picked);
          }}
        />
        <input
          ref={videoInputRef}
          type="file"
          accept="video/mp4,video/*"
          className="sr-only"
          onChange={(e) => {
            const f = e.currentTarget.files?.[0] ?? null;
            e.currentTarget.value = "";
            if (f && isVideoFile(f)) onImportVideo?.(f);
          }}
        />

        {onImportFrames && (
          <Button
            className="flex-1 border-ao bg-ao font-mono text-[12.5px] font-semibold tracking-[0.02em] text-on-ao hover:bg-ao/85"
            onClick={() => framesInputRef.current?.click()}
          >
            Import Keyframes
          </Button>
        )}

        {onImportVideo && (
          <Button
            variant="outline"
            className="flex-1 border-line bg-transparent font-mono text-[12.5px] tracking-[0.02em] text-washi hover:border-ao hover:bg-transparent hover:text-ao"
            onClick={() => videoInputRef.current?.click()}
          >
            Import Video
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
