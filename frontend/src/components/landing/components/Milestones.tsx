import { Gauge, ShieldCheck, Sparkles, Users } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// Milestones — 4 stat cards in a responsive grid. Figures are illustrative placeholders.
const MILESTONES = [
  {
    icon: Gauge,
    stat: "40% faster",
    body: "Artists ship sequences in a fraction of the time — the tedious middles are handled for them.",
  },
  {
    icon: ShieldCheck,
    stat: "99.2% on-model",
    body: "Calibrated QA catches off-model drift, flicker and morph before they ever reach the timeline.",
  },
  {
    icon: Sparkles,
    stat: "1M+ frames vouched",
    body: "Every generated frame passes a three-state pass / abstain / flag review — never a silent guess.",
  },
  {
    icon: Users,
    stat: "12k+ artists",
    body: "Studios and solo animators alike trust the co-pilot as a first-class step in their pipeline.",
  },
] as const;

export function Milestones() {
  return (
    <section id="milestones" className="flex justify-center px-6 py-16">
      <div className="flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col items-center gap-3 text-center">
          <h2 className="font-display text-3xl font-bold text-foreground sm:text-4xl">
            Milestones that matter
          </h2>
          <p className="max-w-2xl font-body text-muted-foreground">
            Numbers our artists feel in the studio — speed, trust, and frames
            that hold up under a fan&apos;s eye.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {MILESTONES.map(({ icon: Icon, stat, body }) => (
            <Card key={stat} className="gap-3">
              <CardHeader className="gap-3">
                <div className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                  <Icon className="size-5" />
                </div>
                <CardTitle className="font-display text-2xl text-foreground">
                  {stat}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="font-body text-sm text-muted-foreground">
                  {body}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
