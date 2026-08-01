import { Gauge, ShieldCheck, Sparkles, Users } from "lucide-react";

// Four product principles, designed for text-first scanning rather than numeric stats.
//
// These were four statistics — "40% faster", "99.2% on-model", "1M+ frames
// vouched", "12k+ artists" — presented as measurement. Nothing in the project
// supports any of them, and there is no external user base for the last one to
// describe. Keep these as claims an artist can check by using the product; an
// invented number is the easiest thing on a page to be taken apart on.
const MILESTONES = [
  {
    icon: Gauge,
    title: "In-betweens, drawn for you",
    body: "Hand it consecutive keys and it generates the drawings between them, at the cadence and depth you set.",
  },
  {
    icon: ShieldCheck,
    title: "Pass, abstain, or flag",
    body: "Every generated pair gets a calibrated verdict — never a silent guess presented as a finished drawing.",
  },
  {
    icon: Sparkles,
    title: "It says when it cannot",
    body: "When the gap is too wide to fill honestly, it asks you for a key instead of inventing motion it cannot see.",
  },
  {
    icon: Users,
    title: "Your call, every time",
    body: "Nothing is applied without you accepting it, and every frame stays yours to reject and re-run.",
  },
] as const;

export function Milestones() {
  return (
    <section id="milestones" className="flex justify-center px-6 py-20">
      <div className="flex w-full max-w-6xl flex-col gap-12">
        <div className="flex max-w-3xl self-center flex-col items-center gap-3 text-center">
          <h2 className="font-display text-3xl font-bold text-foreground sm:text-4xl">
            Milestones that matter
          </h2>
          <p className="max-w-2xl font-body text-muted-foreground">
            What artists should feel in the studio: faster iteration, honest
            feedback, and control over every drawing.
          </p>
        </div>

        <div className="grid grid-cols-1 overflow-hidden rounded-2xl border border-border md:grid-cols-2 md:[&>article:nth-child(n+3)]:border-b-0 md:[&>article:nth-child(odd)]:border-r">
          {MILESTONES.map(({ icon: Icon, title, body }, index) => (
            <article
              key={title}
              className="grid grid-cols-[auto_minmax(0,1fr)] gap-4 border-b border-border bg-card p-6 last:border-b-0 md:p-8"
            >
              <div className="flex flex-col items-center gap-3">
                <span className="font-mono text-xs font-medium tracking-[0.16em] text-muted-foreground">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                  <Icon className="size-5" />
                </div>
              </div>
              <div className="flex flex-col gap-3">
                <h3 className="font-display text-xl font-semibold leading-tight text-foreground sm:text-2xl">
                  {title}
                </h3>
                <p className="font-body leading-relaxed text-muted-foreground">
                  {body}
                </p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
