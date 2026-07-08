"use client";

import { useState } from "react";
import { Check, Mail, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Newsletter sign-up. Template only — submit is a client-side stub (preventDefault), no backend.
export function Newsletter() {
  const [email, setEmail] = useState("");
  const [subscribed, setSubscribed] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (email.trim()) setSubscribed(true);
  }

  return (
    <section className="flex justify-center px-6 py-16">
      <div className="grid w-full max-w-6xl items-center gap-8 rounded-2xl border border-border bg-card p-8 lg:grid-cols-2 lg:p-12">
        <div className="flex flex-col gap-4">
          <h2 className="font-display text-3xl font-bold text-foreground sm:text-4xl">
            Stay in the loop
          </h2>
          <p className="font-body text-muted-foreground">
            Get occasional notes on new capabilities, studio case studies, and
            what the co-pilot learned this month. No spam — unsubscribe anytime.
          </p>

          {subscribed ? (
            <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 font-body text-sm text-foreground">
              <Check className="size-4 text-emerald-500" />
              Thanks — you&apos;re on the list.
            </div>
          ) : (
            <form
              onSubmit={handleSubmit}
              className="flex flex-col gap-3 sm:flex-row"
            >
              <Input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@studio.com"
                aria-label="Email address"
                className="h-11 flex-1"
              />
              <Button
                type="submit"
                className="h-11 border-0 bg-linear-to-r from-purple-500 to-pink-500 px-5 text-white hover:opacity-90"
              >
                Subscribe
                <Send />
              </Button>
            </form>
          )}
        </div>

        <div className="flex aspect-video items-center justify-center gap-2 rounded-xl bg-muted text-muted-foreground">
          <Mail className="size-6" />
          <span className="font-mono text-sm">Newsletter preview</span>
        </div>
      </div>
    </section>
  );
}
