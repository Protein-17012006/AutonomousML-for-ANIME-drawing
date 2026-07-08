"use client";

import { BrandIcon } from "@/components/common/BrandIcon";
import { ModeToggle } from "@/components/ModeToggle";
import { useSidebar } from "@/components/ui/sidebar";
import { PanelLeftClose } from "lucide-react";

// Chat-surface header — title on the left, theme toggle pinned right.
// The brand mark now lives in the app sidebar (AppSidebar); on mobile the sidebar is a drawer,
// so the header carries a mobile-only trigger: it shows the BrandIcon and flips to a collapse
// icon on HOVER (clicking toggles the drawer). On desktop the brand is in the rail → no trigger,
// no dup. Layout is structural Tailwind (flex row + justify-between, gap — no margin/absolute).
export function ChatHeader() {
  const { isMobile, toggleSidebar } = useSidebar();
  return (
    <header className="flex shrink-0 items-center justify-between gap-3 pt-3.5 px-1 pb-2">
      <div className="flex items-center gap-3">
        {isMobile && (
          <button
            type="button"
            onClick={toggleSidebar}
            aria-label="Toggle menu"
            className="group/menu flex h-8 w-8 items-center justify-center text-washi"
          >
            {/* BrandIcon by default; flips to the collapse icon on hover (same fixed box → no shift) */}
            <span className="flex group-hover/menu:hidden">
              <BrandIcon />
            </span>
            <PanelLeftClose className="hidden h-7 w-7 group-hover/menu:block" />
          </button>
        )}
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
