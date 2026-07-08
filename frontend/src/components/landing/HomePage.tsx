import { LandingNav } from "./components/LandingNav";
import { Hero } from "./components/Hero";
import { Milestones } from "./components/Milestones";
import { About } from "./components/About";
import { FeatureShowcase } from "./components/FeatureShowcase";
import { Newsletter } from "./components/Newsletter";
import { Footer } from "./components/Footer";

// Full landing composition. The section components live in ./components/*; the route
// (src/app/page.tsx) imports only <HomePage /> and keeps ownership of page metadata.
// Server component (statically prerendered); interactivity lives in the "use client" children
// (LandingNav drawer, FeatureShowcase selector, Newsletter form).
export function HomePage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <LandingNav />
      <main className="flex flex-col">
        <Hero />
        <Milestones />
        <About />
        <FeatureShowcase />
        <Newsletter />
      </main>
      <Footer />
    </div>
  );
}
