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

// Empty-state greeting on the chat surface. Styled to the co-pilot ink theme
// (sumi desk / washi paper / ash graphite / ao pencil); `.btn .btn-*` come from copilot.css
// so they override the Button variant colors (same idiom as ChatComposer).
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
    <Card className="flex-1 w-full flex flex-col gap-4 rounded-xl bg-sumi-2 ring-line text-washi">
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
          className="visually-hidden"
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
          className="visually-hidden"
          onChange={(e) => {
            const f = e.currentTarget.files?.[0] ?? null;
            e.currentTarget.value = "";
            if (f && isVideoFile(f)) onImportVideo?.(f);
          }}
        />

        <Button
          className="btn btn-primary flex-1"
          onClick={() => framesInputRef.current?.click()}
        >
          Import Keyframes
        </Button>

        <Button
          className="btn btn-ghost flex-1"
          onClick={() => videoInputRef.current?.click()}
        >
          Import Video
        </Button>
      </CardContent>
    </Card>
  );
}
