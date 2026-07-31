import { Avatar, AvatarFallback } from "@/components/ui/avatar";

// About / background + mission on the left, placeholder team on the right.
// Two-up on desktop via grid, stacked on mobile. Team photos are placeholder avatars.
const TEAM = [
  { initials: "LD", name: "Long D.", role: "Unassigned" },
  { initials: "HN", name: "Hoang N.", role: "Unassigned" },
  { initials: "HT", name: "Ha Tr.", role: "Unassigned" },
  { initials: "KB", name: "Khang B.", role: "Unassigned" },
  { initials: "PL", name: "Phong L.", role: "Unassigned" },
] as const;

export function About() {
  return (
    <section id="about" className="flex justify-center px-6 py-16">
      <div className="grid w-full max-w-6xl items-center gap-12 lg:grid-cols-2">
        <div className="flex flex-col gap-4">
          <h2 className="font-display text-3xl font-bold text-foreground sm:text-4xl">
            About us
          </h2>
          <p className="font-body text-muted-foreground">
            We started where every anime tool gets stuck: interpolation is a
            commodity, but keeping a character on-model between key drawings is
            not. The hard, defensible problem is knowing when an in-between is
            wrong — not merely drawing it.
          </p>
          <p className="font-body text-muted-foreground">
            Our mission is to give artists a co-pilot they can trust: one that
            fills the middles, abstains when it is unsure, and flags anything it
            cannot vouch for — so the artist stays in control and the studio
            keeps its style.
          </p>
        </div>

        <div className="flex flex-wrap justify-center gap-4">
          {TEAM.map((member) => (
            <div
              key={member.initials}
              className="flex w-32 flex-col items-center gap-2 rounded-xl border border-border bg-card p-4 text-center"
            >
              <Avatar size="lg">
                <AvatarFallback className="bg-muted font-display font-medium text-ao">
                  {member.initials}
                </AvatarFallback>
              </Avatar>
              <div className="flex flex-col">
                <span className="font-body text-sm font-medium text-foreground">
                  {member.name}
                </span>
                <span className="font-mono text-xs text-muted-foreground">
                  {member.role}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
