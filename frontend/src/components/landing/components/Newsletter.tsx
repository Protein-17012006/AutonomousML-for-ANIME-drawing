import { Mail } from "lucide-react";

// This section used to collect an email address, validate it, and open a dialog
// titled "You're subscribed" — while sending it precisely nowhere. No subscribe
// endpoint exists in this app or in the backend's route table, and the copy
// promised "unsubscribe anytime" for a list that does not exist.
//
// Collecting a real person's address under a false confirmation is worse than
// having no signup at all, so the form is gone rather than mocked. It comes back
// when there is something behind it.
export function Newsletter() {
  return (
    <section className="flex justify-center px-6 py-16">
      <div className="grid w-full max-w-6xl items-center gap-8 rounded-2xl border border-border bg-card p-8 lg:grid-cols-2 lg:p-12">
        <div className="flex flex-col gap-4">
          <h2 className="font-display text-3xl font-bold text-foreground sm:text-4xl">
            Still being built
          </h2>
          <p className="font-body text-muted-foreground">
            The In-Between Co-pilot is in active development with a small group
            of artists. There is no mailing list yet — when there is something
            worth sending, there will be somewhere to sign up.
          </p>
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
    </section>
  );
}
