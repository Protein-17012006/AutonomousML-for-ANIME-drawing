import { Gauge, ShieldCheck, Sparkles, Users } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// Four cards describing what the co-pilot DOES.
//
// These were four statistics — "40% faster", "99.2% on-model", "1M+ frames
// vouched", "12k+ artists" — carrying a comment that called them illustrative
// placeholders while the page presented them as measurement. Nothing in the
// project supports any of them, parts are contradicted by it, and there is no
// external user base for the last one to describe. They are replaced with
// claims that are true and checkable by using the product, because an invented
// number is the easiest thing on a page to be taken apart on.
const MILESTONES = [
  {
    icon: Gauge,
    stat: "In-betweens, drawn for you",
    body: "Hand it consecutive keys and it generates the drawings between them, at the cadence and depth you set.",
  },
  {
    icon: ShieldCheck,
    stat: "Pass, abstain, or flag",
    body: "Every generated pair gets a calibrated verdict — never a silent guess presented as a finished drawing.",
  },
  {
    icon: Sparkles,
    stat: "It says when it cannot",
    body: "When the gap is too wide to fill honestly, it asks you for a key instead of inventing motion it cannot see.",
  },
  {
    icon: Users,
    stat: "Your call, every time",
    body: "Nothing is applied without you accepting it, and every frame stays yours to reject and re-run.",
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
