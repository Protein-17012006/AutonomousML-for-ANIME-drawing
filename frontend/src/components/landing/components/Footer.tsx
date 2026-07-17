import Link from "next/link";
import { BrandIcon } from "@/components/common/BrandIcon";

// Footer — brand + quote on the left, link columns on the right. Grid layout, no margin/absolute.
const LINK_COLUMNS = [
  {
    heading: "Product",
    links: [
      { label: "Co-pilot", href: "/copilot" },
      { label: "Frames to video", href: "#features" },
      { label: "In-between fills", href: "#features" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "About us", href: "#about" },
      { label: "Milestones", href: "#milestones" },
    ],
  },
  {
    heading: "Resources",
    links: [
      {
        label: "Documentation",
        href: "https://github.com/Protein-17012006/AutonomousML-for-ANIME-drawing#readme",
      },
      {
        label: "Contact",
        href: "https://github.com/Protein-17012006/AutonomousML-for-ANIME-drawing/issues",
      },
    ],
  },
] as const;

export function Footer() {
  return (
    <footer className="flex justify-center border-t border-border px-6 py-12">
      <div className="grid w-full max-w-6xl gap-8 md:grid-cols-[1.5fr_1fr_1fr_1fr]">
        <div className="flex flex-col gap-3">
          <Link href="/" className="flex items-center gap-2">
            <BrandIcon />
            <span className="font-display text-base font-semibold text-foreground">
              In-Between Co-pilot
            </span>
          </Link>
          <p className="max-w-xs font-body text-sm text-muted-foreground">
            Fill the middles. Verify every frame. Keep your style.
          </p>
          <span className="font-mono text-xs text-muted-foreground">
            © 2026 In-Between Co-pilot. All rights reserved.
          </span>
        </div>

        {LINK_COLUMNS.map((column) => (
          <div key={column.heading} className="flex flex-col gap-3">
            <span className="font-body text-sm font-medium text-foreground">
              {column.heading}
            </span>
            <ul className="flex flex-col gap-2">
              {column.links.map((link) => (
                <li key={link.label}>
                  <Link
                    href={link.href}
                    className="font-body text-sm text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </footer>
  );
}
