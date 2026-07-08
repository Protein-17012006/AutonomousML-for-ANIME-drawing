import Link from "next/link";
import { ArrowRight, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

// Hero — headline + subcopy + two CTAs. Fills the viewport height and centers content with flex
// (no margin/absolute). `min-h-svh` uses the SMALL viewport height so it matches the visible area
// on mobile (plain 100vh/min-h-screen counts the space behind the address bar → too tall on small
// screens); `min-h-` (not fixed height) lets it grow if the content is ever taller than the screen.
export function Hero() {
  return (
    <section
      id="home"
      className="flex min-h-svh items-center justify-center px-6 pt-8 pb-16"
    >
      <div className="flex w-full max-w-3xl flex-col items-center gap-6 text-center">
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-muted/50 px-3 py-1 font-mono text-xs text-muted-foreground">
          <Sparkles className="size-3.5 text-purple-500" />
          Calibrated self-QA for anime in-betweens
        </span>

        <h1 className="font-display text-4xl leading-tight font-bold text-foreground sm:text-5xl lg:text-6xl">
          Draw the keys. We fill — and{" "}
          <span className="bg-linear-to-r from-purple-500 to-pink-500 bg-clip-text text-transparent">
            verify
          </span>{" "}
          the in-betweens.
        </h1>

        <p className="max-w-2xl font-body text-lg text-muted-foreground">
          The In-Between Co-pilot generates the frames between your key drawings
          and runs calibrated self-QA on every one — so nothing off-model,
          flickering, or morphed ever ships.
        </p>

        <div className="flex flex-col gap-3 sm:flex-row">
          <Button
            asChild
            className="h-11 border-0 bg-linear-to-r from-purple-500 to-pink-500 px-6 text-sm text-white hover:opacity-90 sm:text-base"
          >
            <Link href="/copilot">
              Create now
              <ArrowRight />
            </Link>
          </Button>
          <Button
            asChild
            variant="outline"
            className="h-11 px-6 text-sm sm:text-base"
          >
            <a href="#milestones">Explore now</a>
          </Button>
        </div>
      </div>
    </section>
  );
}
