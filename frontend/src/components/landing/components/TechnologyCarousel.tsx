"use client";

import { useEffect, useMemo, useState } from "react";
import { Cloud } from "lucide-react";
import AutoScroll from "embla-carousel-auto-scroll";
import {
  siFastapi,
  siLucide,
  siNextdotjs,
  siPytorch,
  siReact,
  siShadcnui,
  siTailwindcss,
} from "simple-icons";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  type CarouselApi,
} from "@/components/ui/carousel";

// Mark sources: Simple Icons (https://simpleicons.org/) and AWS Architecture Icons
// (https://aws.amazon.com/architecture/icons/). Each mark links to its source below.

type Technology = {
  name: string;
  path?: string;
  source: string;
  aws?: boolean;
};

const TECHNOLOGIES: Technology[] = [
  { name: "Next.js", path: siNextdotjs.path, source: siNextdotjs.source },
  { name: "React", path: siReact.path, source: siReact.source },
  { name: "Tailwind CSS", path: siTailwindcss.path, source: siTailwindcss.source },
  { name: "shadcn/ui", path: siShadcnui.path, source: siShadcnui.source },
  { name: "Lucide", path: siLucide.path, source: siLucide.source },
  { name: "FastAPI", path: siFastapi.path, source: siFastapi.source },
  { name: "PyTorch", path: siPytorch.path, source: siPytorch.source },
  {
    name: "AWS",
    source: "https://aws.amazon.com/architecture/icons/",
    aws: true,
  },
];

function TechnologyMark({ technology }: { technology: Technology }) {
  if (technology.aws) {
    return <Cloud aria-hidden="true" className="size-7" />;
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-7 fill-current">
      <path d={technology.path} />
    </svg>
  );
}

export function TechnologyCarousel() {
  const [api, setApi] = useState<CarouselApi>();
  const [reducedMotion, setReducedMotion] = useState(true);
  const autoScroll = useMemo(
    () => AutoScroll({
      speed: 0.7,
      playOnInit: false,
      stopOnInteraction: false,
      stopOnMouseEnter: true,
      stopOnFocusIn: true,
    }),
    [],
  );

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    const plugin = api?.plugins().autoScroll;
    if (!plugin) return;
    if (reducedMotion) plugin.stop();
    else plugin.play();
  }, [api, reducedMotion]);

  return (
    <section aria-label="Built with technologies" className="flex justify-center px-6 py-16">
      <div className="flex w-full max-w-6xl flex-col gap-6 rounded-xl border border-border bg-card p-6 sm:p-8">
        <div className="flex justify-center text-center">
          <p className="font-mono text-xs tracking-[0.12em] text-ao uppercase">Built with</p>
        </div>

        <div className="min-w-0">
          <Carousel setApi={setApi} plugins={[autoScroll]} opts={{ align: "start", loop: true }} aria-label="Technologies used by In-Between Co-pilot">
            <CarouselContent>
              {TECHNOLOGIES.map((technology) => (
                <CarouselItem key={technology.name} className="basis-1/2 sm:basis-1/3 lg:basis-1/4">
                  <a
                    href={technology.source}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`${technology.name} source`}
                    className="flex h-24 flex-col items-center justify-center gap-2 rounded-lg border border-transparent text-muted-foreground transition-colors hover:border-border hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                  >
                    <TechnologyMark technology={technology} />
                    <span className="font-mono text-xs">{technology.name}</span>
                  </a>
                </CarouselItem>
              ))}
            </CarouselContent>
          </Carousel>
        </div>
      </div>
    </section>
  );
}
