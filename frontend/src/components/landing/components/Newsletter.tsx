"use client";

import { useState } from "react";
import { Check, Mail, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function Newsletter() {
  const [email, setEmail] = useState("");
  const [subscribedEmail, setSubscribedEmail] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedEmail = email.trim();
    if (!EMAIL_PATTERN.test(normalizedEmail)) {
      setError("Enter a valid email address.");
      return;
    }

    setError(null);
    setSubscribedEmail(normalizedEmail);
    setEmail("");
    setDialogOpen(true);
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

          <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row">
            <label htmlFor="newsletter-email" className="sr-only">
              Email address
            </label>
            <Input
              id="newsletter-email"
              type="email"
              required
              name="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@studio.com"
              aria-describedby={error ? "newsletter-email-error" : undefined}
              aria-invalid={!!error}
              className="h-11 flex-1"
            />
            <Button type="submit" className="h-11 px-5">
              Subscribe
              <Send />
            </Button>
          </form>
          {error && (
            <p id="newsletter-email-error" role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>

        <div
          aria-hidden="true"
          className="flex aspect-video items-center justify-center rounded-xl border border-line bg-screen p-5 sm:p-6"
        >
          <div className="flex size-24 items-center justify-center rounded-2xl border border-ao/50 bg-sumi-2 text-ao shadow-sm sm:size-28">
            <Mail className="size-12 stroke-[1.5] sm:size-14" />
          </div>
        </div>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="border border-line bg-sumi-2 text-washi sm:max-w-md">
          <DialogHeader className="items-center text-center">
            <div className="flex size-14 items-center justify-center rounded-full border border-pass/50 bg-sumi-3 text-pass">
              <Check className="size-7 stroke-[2.5]" />
            </div>
            <DialogTitle className="font-display text-xl text-washi">
              You&apos;re subscribed
            </DialogTitle>
            <DialogDescription className="font-body text-ash">
              {subscribedEmail} is on the local newsletter preview list.
            </DialogDescription>
          </DialogHeader>
          <Button type="button" onClick={() => setDialogOpen(false)}>
            Done
          </Button>
        </DialogContent>
      </Dialog>
    </section>
  );
}
