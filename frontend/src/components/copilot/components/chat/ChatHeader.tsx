import { BrandIcon } from "@/components/common/BrandIcon";
import { ModeToggle } from "@/components/ModeToggle";

// Chat-surface header — brand mark + title on the left, theme toggle pinned right.
// Extracted from CopilotApp's inline <header className="chat-brand">; layout migrated to
// structural Tailwind (flex row + justify-between, gap for spacing — no margin/absolute)
// per the in-progress copilot.css → Tailwind pass.
export function ChatHeader() {
  return (
    <header className="flex items-center justify-between gap-3 pt-3.5 px-1 pb-2">
      <div className="flex items-center gap-3">
        <BrandIcon />
        <div>
          <h1 className="font-display text-[1.05rem] text-washi">
            In-Between Co-pilot
          </h1>
          <p className="font-mono text-xs text-ash">
            Genga to douga · smooth motion, preserved style
          </p>
        </div>
      </div>
      <ModeToggle />
    </header>
  );
}
