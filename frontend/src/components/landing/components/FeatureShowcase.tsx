"use client";

import { useState } from "react";
import { Clapperboard, Film, Layers, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// Highlight features — left column selects, right column previews. Two-up on desktop
// (flex row), stacked on mobile. Selection is local useState; alignment is flex/grid only.
interface Feature {
  icon: LucideIcon;
  title: string;
  short: string;
  body: string;
}

const FEATURES: Feature[] = [
  {
    icon: Film,
    title: "Frames to video",
    short: "Assemble keys + in-betweens into motion",
    body: "Drop in your key drawings and generated in-betweens and the co-pilot assembles them into a smooth, playable clip — with cadence and timing you can scrub, compare, and export.",
  },
  {
    icon: Clapperboard,
    title: "Video to frames",
    short: "Pull clean keys from a reference clip",
    body: "Point the co-pilot at a reference video and it extracts clean, evenly-spaced frames you can use as keys — the fastest way to turn existing motion into a new in-betweening session.",
  },
  {
    icon: Layers,
    title: "In-between fills",
    short: "Generate the middles, verified",
    body: "Between any two keys, the co-pilot generates the middle frames and runs calibrated self-QA on each — passing what holds up, abstaining when unsure, and flagging what needs your eye.",
  },
];

export function FeatureShowcase() {
  const [active, setActive] = useState(0);
  const current = FEATURES[active];
  const CurrentIcon = current.icon;

  return (
    <section id="features" className="flex justify-center px-6 py-16">
      <div className="flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col items-center gap-3 text-center">
          <h2 className="font-display text-3xl font-bold text-foreground sm:text-4xl">
            Highlight features
          </h2>
          <p className="max-w-2xl font-body text-muted-foreground">
            Three ways the co-pilot moves your work forward — pick one to see
            what it does.
          </p>
        </div>

        <div className="flex flex-col gap-8 lg:flex-row">
          {/* Selector */}
          <div className="flex flex-col gap-2 lg:w-80 lg:shrink-0">
            {FEATURES.map((feature, index) => {
              const Icon = feature.icon;
              const isActive = index === active;
              return (
                <button
                  key={feature.title}
                  type="button"
                  onClick={() => setActive(index)}
                  aria-pressed={isActive}
                  className={cn(
                    "flex items-start gap-3 rounded-xl border p-4 text-left transition-colors",
                    isActive
                      ? "border-transparent bg-linear-to-r from-purple-500/10 to-pink-500/10 ring-1 ring-purple-500/30"
                      : "border-border hover:bg-muted/50",
                  )}
                >
                  <div
                    className={cn(
                      "flex size-9 shrink-0 items-center justify-center rounded-lg",
                      isActive
                        ? "bg-linear-to-br from-purple-500 to-pink-500 text-white"
                        : "bg-muted text-muted-foreground",
                    )}
                  >
                    <Icon className="size-5" />
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <span className="font-body text-sm font-medium text-foreground">
                      {feature.title}
                    </span>
                    <span className="font-body text-xs text-muted-foreground">
                      {feature.short}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Preview */}
          <div className="flex flex-1 flex-col gap-4 rounded-2xl border border-border bg-card p-6">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl bg-linear-to-br from-purple-500 to-pink-500 text-white">
                <CurrentIcon className="size-5" />
              </div>
              <h3 className="font-display text-xl font-semibold text-foreground">
                {current.title}
              </h3>
            </div>
            <p className="font-body text-muted-foreground">{current.body}</p>
            <div className="flex aspect-video items-center justify-center gap-2 rounded-xl bg-muted text-muted-foreground">
              <CurrentIcon className="size-6" />
              <span className="font-mono text-sm">Preview coming soon</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
