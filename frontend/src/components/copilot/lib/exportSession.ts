// Session export helpers — the usable deliverable + the artist-κ review labels.
// Extracted from CopilotApp.tsx.
import type { PairEvent, ResultEvent } from "../types";

/** Export the usable result: the box already built the reconstructed video + in-between
 *  frames + montage into the session dir; /bundle.zip zips them for one-click download. */
export function downloadBundle(result: ResultEvent | null) {
  const art = result?.artifacts;
  if (!art) return;
  const ref = art.video || art.montage;           // any artifact shares /session/{sid}/…
  const bundleUrl = ref.replace(/\/[^/]+$/, "/bundle.zip");
  const a = document.createElement("a");
  a.href = bundleUrl;
  a.download = "copilot_session.zip";
  a.click();
}

/** The artist-κ deliverable: the model's self-QA verdict × the artist's accept/reject per filled pair.
 *  This is the independent κ ground-truth the project lacks — written client-side to review.json so the
 *  artist's review work isn't thrown away (the bundle zip carries pixels; this carries the labels). */
export function downloadReview(log: PairEvent[], verdicts: Record<number, "accept" | "reject">) {
  const pairs = log.filter((p) => p.action !== "needs_key").map((p) => ({
    pair: p.index,
    model_qa: p.qa ?? null,
    model_reason: p.reason ?? null,
    verdict_prob: p.verdict_prob ?? null,
    artist: verdicts[p.index] ?? null,
  }));
  const doc = { reviewed: pairs.filter((r) => r.artist).length, total: pairs.length, pairs };
  const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "review.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}
