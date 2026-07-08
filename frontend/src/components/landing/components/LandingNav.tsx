"use client";

import { useState } from "react";
import Link from "next/link";
import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { BrandIcon } from "@/components/common/BrandIcon";
import { ModeToggle } from "@/components/ModeToggle";

// Landing top nav — brand left, anchor links center, theme toggle + "Visit space" right.
// Layout is structural Tailwind only (flex + justify-between + gap — no margin/absolute).
// On < md the links collapse into a shadcn Sheet drawer. `position: sticky` keeps it pinned.
const NAV_LINKS = [
  { label: "Home", href: "#home" },
  { label: "About us", href: "#about" },
  { label: "Highlight features", href: "#features" },
] as const;

// Where the co-pilot lives today. Stage 3 will gate this (signed-in -> /copilot, else -> /login).
const SPACE_HREF = "/copilot";

export function LandingNav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 flex justify-center border-b border-border bg-background/80 backdrop-blur">
      <div className="flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-3">
        <Link href="/" className="flex items-center gap-2">
          <BrandIcon />
          <span className="font-display text-base font-semibold text-foreground">
            In-Between Co-pilot
          </span>
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {NAV_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="font-body text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <ModeToggle />
          <Button asChild className="hidden h-9 px-4 sm:inline-flex">
            <Link href={SPACE_HREF}>Visit space</Link>
          </Button>

          {/* Mobile drawer trigger */}
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                className="md:hidden"
                aria-label="Open menu"
              >
                <Menu />
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-72">
              <SheetHeader>
                <SheetTitle className="flex items-center gap-2">
                  <BrandIcon />
                  <span className="font-display">In-Between Co-pilot</span>
                </SheetTitle>
              </SheetHeader>
              <nav className="flex flex-col gap-1 px-4">
                {NAV_LINKS.map((link) => (
                  <SheetClose asChild key={link.href}>
                    <a
                      href={link.href}
                      className="rounded-lg px-3 py-2 font-body text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    >
                      {link.label}
                    </a>
                  </SheetClose>
                ))}
              </nav>
              <div className="flex flex-col gap-2 px-4">
                <SheetClose asChild>
                  <Button asChild className="h-9 w-full">
                    <Link href={SPACE_HREF}>Visit space</Link>
                  </Button>
                </SheetClose>
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  );
}
