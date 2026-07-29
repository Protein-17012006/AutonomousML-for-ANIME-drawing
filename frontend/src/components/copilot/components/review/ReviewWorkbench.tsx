// review workbench: two scroll-synced columns (the "board" view).
// Extracted from CopilotApp.tsx.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { PairEvent, ResultEvent } from "../../types";
import { downloadBundle, downloadReview } from "../../lib/exportSession";
import { QAPanel } from "./QAPanel";
import { RunLoader } from "./RunLoader";
import { ReconPlayer } from "./ReconPlayer";
import { FrameCard } from "./FrameCard";
import { ReviewPairRow } from "./ReviewPairRow";
import { ChatWelcome } from "../chat/ChatWelcome";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Download,
  Keyboard,
  Play,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

type Filter = "offmodel" | "unsure" | "pass" | "all" | "needs_key";
const filterDesc: Record<Filter, string> = {
  offmodel:
    "In-betweens the co-pilot thinks are off-model — review / redraw these first.",
  unsure: "In-betweens the co-pilot won't vouch for — worth a second look.",
  pass: "In-betweens the co-pilot is confident are on-model — skim, then accept.",
  all: "Every in-between the co-pilot filled (on-model + unsure + off-model).",
  needs_key:
    "Pairs whose two keys are too far apart to fill — draw a breakdown key between them.",
};

export function ReviewWorkbench({
  log,
  result,
  running,
  keyUrls,
  verdicts,
  onVerdict,
  onRefill,
  compareSlot,
  fps,
  initialFocus,
}: {
  log: PairEvent[];
  result: ResultEvent | null;
  running: boolean;
  keyUrls: string[];
  verdicts: Record<number, "accept" | "reject">;
  onVerdict: (idx: number, v: "accept" | "reject") => void;
  onRefill: (index: number, file: File) => void;
  compareSlot: React.ReactNode;
  fps: number;
  initialFocus?: number | null; // chat "Review this pair" deep-link
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [focused, setFocused] = useState<number | null>(initialFocus ?? null);

  useEffect(() => {
    if (initialFocus == null) return;
    const frame = requestAnimationFrame(() => setFocused(initialFocus));
    return () => cancelAnimationFrame(frame);
  }, [initialFocus]);

  const [exported, setExported] = useState(false);
  const [glider, setGlider] = useState({ left: 0, width: 0 });
  const [reconOpen, setReconOpen] = useState(false);
  const pickedRef = useRef(false);
  const autoTriagedRef = useRef(false);
  const tabsRef = useRef<HTMLDivElement>(null);
  const explanations = result?.explanations;
  const mids = result?.pair_mids;
  const samp = result?.sampling;
  const video = result?.artifacts?.video;

  //!REDESIGN: TWO CATEGORIES INCLUDE FILLED AND UNFILLED FRAMES (NEEDS KEY). FILLED FRAMES CONTAIN TWO SUB-CATEGORIES ARE PASS AND UNSURE (DISPLAY THE PROBABILITY ON EACH PAIR). INSTEAD OF HAVING FIVE SEPARATE CATEGORIES OF FILLED, GAPS, OFFMODEL, UNSURE, PASSED
  const {
    filled,
    gaps,
    offmodel,
    unsure,
    passed,
    holds,
    snaps,
    interpd,
    shown,
  } = useMemo(() => {
    const filled = log.filter((p) => p.action !== "needs_key");
    const gaps = log.filter((p) => p.action === "needs_key");
    // Current design: pass, abstain, flag belongs to filled group based on probabilities
    // Expected design: Two categories - filled and unfilled (needs key), filled category includes pass and unsure (needs user feedback - verdict)
    // Flag means needs key, in-between not filled
    const offmodel = filled.filter((p) => p.qa === "flag"); // belong to needs key
    // Abstain requires user feedback, in-between filled
    const unsure = filled.filter((p) => p.qa === "abstain"); // belong to filled
    const passed = filled.filter((p) => p.qa === "pass"); // belong to filled
    const shown =
      filter === "offmodel"
        ? offmodel
        : filter === "unsure"
          ? unsure
          : filter === "pass"
            ? passed
            : filter === "needs_key"
              ? gaps
              : filled;
    return {
      filled,
      gaps,
      offmodel,
      unsure,
      passed,
      holds: filled.filter((p) => p.route === "hold").length,
      snaps: filled.filter((p) => p.route === "snap_preserve").length,
      interpd: filled.filter((p) => p.route === "rife").length,
      shown,
    };
  }, [filter, log]);

  const reviewedCount = filled.filter((p) => verdicts[p.index]).length;
  const pending = Math.max(0, keyUrls.length - 1 - log.length);

  const panelPair =
    (focused != null ? log.find((p) => p.index === focused) : null) ??
    shown[0] ??
    null;

  //! REMOVE: HEADLINE IS REDUNDANT
  const headline = result
    ? [
        `Filled ${filled.length} in-between${filled.length === 1 ? "" : "s"}`,
        offmodel.length + unsure.length === 0
          ? "all clean"
          : `${offmodel.length + unsure.length} to review`,
        ...(gaps.length > 0
          ? [`${gaps.length} key${gaps.length === 1 ? "" : "s"} to draw`]
          : []),
      ].join(" · ")
    : null;

  const playCut = () => {
    setReconOpen(true);
    requestAnimationFrame(() => {
      const v = document.getElementById(
        "recon-video",
      ) as HTMLVideoElement | null;
      v?.play().catch(() => {});
    });
  };

  //! REDESIGN: IF A PAIR IN EITHER COLUMN IS CLICKED, SCROLL THE CORRESPONDING PAIR IN THE OPPOSITE COLUMN, NO NEED SYNCHRONIZATION
  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const active = useRef<"L" | "R" | null>(null);
  const rafing = useRef(false);
  const timer = useRef<number | undefined>(undefined);

  const offCache = useRef<{
    L: { pair: number; top: number }[];
    R: { pair: number; top: number }[];
  }>({ L: [], R: [] });

  const offMap = useRef<{ L: Map<number, number>; R: Map<number, number> }>({
    L: new Map(),
    R: new Map(),
  });

  const rebuildOffsets = () => {
    (["L", "R"] as const).forEach((k) => {
      const el = k === "L" ? leftRef.current : rightRef.current;
      if (!el) return;
      const arr: { pair: number; top: number }[] = [];
      const m = new Map<number, number>();
      el.querySelectorAll<HTMLElement>("[data-pair]").forEach((r) => {
        const pair = Number(r.dataset.pair);
        const top = r.offsetTop;
        arr.push({ pair, top });
        m.set(pair, top);
      });
      offCache.current[k] = arr;
      offMap.current[k] = m;
    });
  };

  useLayoutEffect(() => {
    rebuildOffsets();
  }, [filter, shown.length, log.length, result]);

  useEffect(() => {
    const onResize = () => rebuildOffsets();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const sync = (from: "L" | "R") => {
    if (active.current && active.current !== from) return;
    active.current = from;
    if (!rafing.current) {
      rafing.current = true;
      requestAnimationFrame(() => {
        rafing.current = false;
        const src = from === "L" ? leftRef.current : rightRef.current;
        const dst = from === "L" ? rightRef.current : leftRef.current;
        if (!src || !dst) return;
        const arr = offCache.current[from];
        if (arr.length === 0) return;
        const st = src.scrollTop;
        let pair = arr[0].pair;
        let best = Infinity;
        for (const e of arr) {
          const d = Math.abs(e.top - st);
          if (d < best) {
            best = d;
            pair = e.pair;
          }
        }
        const dtop = offMap.current[from === "L" ? "R" : "L"].get(pair);
        if (dtop != null) dst.scrollTop = dtop;
      });
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      active.current = null;
    }, 140);
  };

  const shownRef = useRef(shown);
  const focusedRef = useRef(focused);
  const verdictRef = useRef(onVerdict);

  useEffect(() => {
    shownRef.current = shown;
    focusedRef.current = focused;
    verdictRef.current = onVerdict;
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;

      if (el?.isContentEditable || el?.closest?.('[role="slider"]')) return;

      const list = shownRef.current;
      if (list.length === 0) return;

      const cur = list.findIndex((p) => p.index === focusedRef.current);
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setFocused(
          list[Math.min(list.length - 1, (cur < 0 ? -1 : cur) + 1)].index,
        );
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setFocused(list[Math.max(0, (cur < 0 ? 1 : cur) - 1)].index);
      } else if (e.key === "a" || e.key === "x") {
        if (cur < 0) return;
        verdictRef.current(
          list[cur].index,
          e.key === "a" ? "accept" : "reject",
        );
        setFocused(list[Math.min(list.length - 1, cur + 1)].index);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (focused == null) return;
    if (shown.some((p) => p.index === focused)) return;
    /* eslint-disable react-hooks/set-state-in-effect */
    if (shown.length === 0) {
      setFocused(null);
      return;
    }
    const nearest = shown.reduce(
      (best, p) =>
        Math.abs(p.index - focused) < Math.abs(best.index - focused) ? p : best,
      shown[0],
    );
    setFocused(nearest.index);
    /* eslint-enable react-hooks/set-state-in-effect */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  useEffect(() => {
    if (!result) {
      pickedRef.current = false;
      autoTriagedRef.current = false;
      return;
    }
    if (autoTriagedRef.current) return;
    autoTriagedRef.current = true;
    /* eslint-disable react-hooks/set-state-in-effect */

    if (!pickedRef.current)
      setFilter(
        offmodel.length ? "offmodel" : unsure.length ? "unsure" : "all",
      );

    if (focused == null) {
      const first = offmodel[0] ?? unsure[0] ?? filled[0];
      if (first) setFocused(first.index);
    }
    /* eslint-enable react-hooks/set-state-in-effect */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  useEffect(() => {
    if (focused == null) return;
    leftRef.current
      ?.querySelector<HTMLElement>(`[data-pair="${focused}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [focused]);

  const pick = (f: Filter) => {
    pickedRef.current = true;
    setFilter(f);
  };

  const chip = (key: Filter, label: string, n: number, title: string) => (
    <Button
      variant="ghost"
      type="button"
      className={cn(
        "chip hover:bg-transparent",
        `chip-${key}`,
        filter === key && "on",
      )}
      title={title}
      aria-pressed={filter === key}
      onClick={() => pick(key)}
    >
      {label} <b>{n}</b>
    </Button>
  );

  useLayoutEffect(() => {
    const on = tabsRef.current?.querySelector<HTMLElement>(".chip.on");
    if (on) setGlider({ left: on.offsetLeft, width: on.offsetWidth });
  }, [
    filter,
    offmodel.length,
    unsure.length,
    passed.length,
    filled.length,
    gaps.length,
  ]);

  return (
    <>
      {log.length > 0 && (
        <div className="toolbar">
          {/* //!REMOVE */}
          {headline && (
            <div className="headline">
              <span className="headline-text">{headline}</span>
              {video && (
                <Button
                  variant="default"
                  type="button"
                  className="border-ao bg-ao px-3.5 py-1.5 font-mono text-xs font-semibold tracking-[0.02em] text-on-ao hover:bg-ao/85 active:translate-y-px"
                  onClick={playCut}
                >
                  <Play data-icon="inline-start" aria-hidden="true" /> Play your
                  cut
                </Button>
              )}
            </div>
          )}
          {result && filled.length > 0 && (
            <p
              className="cadence"
              title="Holds are copied and snaps keep their timing — the co-pilot only interpolates genuine small motion, so the original on-2s/on-3s cadence is preserved."
            >
              {/* //!UPDATE CADENCE MARK USING LUCIDE ICON */}
              <span className="cadence-mark" aria-hidden="true" />
              {holds + snaps > 0 ? (
                <>
                  cadence kept — <b>{holds}</b> held · <b>{snaps}</b> snapped ·{" "}
                  <b>{interpd}</b> interpolated
                </>
              ) : (
                <>
                  <b>{interpd}</b> in-between{interpd === 1 ? "" : "s"}{" "}
                  interpolated
                </>
              )}
              {/* //! CONSIDER REMOVE */}
              <span className="cadence-tag">45fps · not 60</span>
            </p>
          )}
          <div className="triage">
            <div
              className="triage-tabs"
              ref={tabsRef}
              data-tone={
                filter === "offmodel" || filter === "needs_key"
                  ? "akaire"
                  : filter === "unsure"
                    ? "abstain"
                    : "ao"
              }
            >
              {/* //! NOTE SURE */}
              <div
                className="triage-glider"
                aria-hidden="true"
                style={{
                  transform: `translateX(${glider.left}px)`,
                  width: glider.width,
                }}
              />
              {/* //! REDESIGN NOTE + USE MODEL AND DO LOOP */}
              {chip(
                "offmodel",
                "Off-model",
                offmodel.length,
                "In-betweens the co-pilot thinks are off-model — review / redraw",
              )}
              {chip(
                "unsure",
                "Unsure",
                unsure.length,
                "In-betweens the co-pilot won't vouch for — a second look",
              )}
              {chip(
                "pass",
                "On-model",
                passed.length,
                "In-betweens the co-pilot is confident are on-model",
              )}
              {chip(
                "all",
                "All filled",
                filled.length,
                "Everything the co-pilot interpolated",
              )}
              {gaps.length > 0 &&
                chip(
                  "needs_key",
                  "Needs key",
                  gaps.length,
                  "Gaps too large to fill — draw a breakdown key",
                )}
            </div>
            {/* //! REVIEWED COUNT NEEDS TO BE REVISED */}
            <span className="triage-progress">
              {reviewedCount}/{filled.length} reviewed
              {result && (
                <>
                  {" "}
                  · {result.n_autopass} on-model · {result.flagged.length}{" "}
                  off-model · {result.keys_requested_total} needs key
                </>
              )}
            </span>
            <Button
              variant="outline"
              type="button"
              className={cn(
                "font-mono text-[11px] tracking-[0.04em] uppercase hover:border-ao hover:bg-sumi-3 hover:text-ao active:translate-y-px",
                exported &&
                  "border-pass text-pass shadow-[inset_0_0_0_1px_color-mix(in_oklab,var(--color-pass)_32%,transparent)]",
              )}
              disabled={!result}
              title={
                result
                  ? "Download the reconstructed video, frames, and your accept/reject review"
                  : "Run the co-pilot first"
              }
              onClick={() => {
                downloadBundle(result);
                downloadReview(log, verdicts);
                setExported(true);
                window.setTimeout(() => setExported(false), 1600);
              }}
            >
              {exported ? (
                "Exported"
              ) : (
                <>
                  <Download data-icon="inline-start" aria-hidden="true" />{" "}
                  Export
                </>
              )}
            </Button>
          </div>
          {/* //! REMOVE FILTER DESC, KEYBOARD PROMPTS CONSIDER TO BE RELAYOUT WITH SUGGESTIONS */}
          <div className="toolbar-foot">
            <p className="filter-desc">{filterDesc[filter]}</p>
            <p className="kbd-hint">
              <Keyboard className="mr-1 inline size-3" aria-hidden="true" />
              J/K navigate · A keep · X redraw · columns stay synced
            </p>
          </div>
        </div>
      )}
      {/* //! REDESIGN: IF THERE IS NO RESULT, DISPLAY EMPTY PANELS */}
      {log.length === 0 && !running ? (
        <main className="landing">
          <ChatWelcome />
          {/* //! UNSURE */}
          {compareSlot}
        </main>
      ) : (
        //! CONSIDER LAYOUT: SHOULD DISPLAY IN CHAT VIEW
        <>
          {samp && samp.kept != null && (
            <div
              className={`sampling-note${(samp.stride ?? 0) > (samp.requested_stride ?? 0) ? " warn" : ""}`}
            >
              {(samp.stride ?? 0) > (samp.requested_stride ?? 0) ? (
                <>
                  <TriangleAlert
                    className="mr-1 inline size-3.5"
                    aria-hidden="true"
                  />
                  {`Long clip — sampled every ${samp.stride} frames (kept ${samp.kept} of ${samp.source_frames}). This samples the cut, not every frame; trim to a short cut for a faithful reconstruction.`}
                </>
              ) : (
                `Sampled ${samp.kept} keys from ${samp.source_frames} frames (every ${samp.stride}).`
              )}
            </div>
          )}
          {/* //! REDESIGN: A BUTTON TO TOGGLE (SIMILAR TO FILTER TAB) + REMOVE TEXT, KEEP VIDEO */}
          {video && (
            <div className={`recon-band${reconOpen ? "" : " is-collapsed"}`}>
              <Button
                variant="ghost"
                type="button"
                className="recon-band-head rounded-none font-normal hover:bg-transparent"
                aria-expanded={reconOpen}
                onClick={() => setReconOpen((o) => !o)}
              >
                <span className="recon-band-caret" aria-hidden="true">
                  {reconOpen ? (
                    <ChevronDown data-icon="inline-start" />
                  ) : (
                    <ChevronRight data-icon="inline-start" />
                  )}
                </span>
                <span className="eyebrow">Output</span>
                <span className="recon-band-title">Reconstructed cut</span>
                {!reconOpen && (
                  <span className="recon-band-hint">
                    <Play data-icon="inline-start" aria-hidden="true" /> play
                    the filled cut
                  </span>
                )}
              </Button>
              {reconOpen && (
                <div className="recon-band-body">
                  <ReconPlayer src={video} fps={fps} />
                </div>
              )}
            </div>
          )}

          <main className="dual">
            {/* LEFT: review controls */}
            <section
              className="pane col-left"
              ref={leftRef}
              onScroll={() => sync("L")}
            >
              {log.length > 0 && (
                <QAPanel
                  p={panelPair}
                  band={result?.csq}
                  ex={
                    panelPair
                      ? explanations?.[String(panelPair.index)]
                      : undefined
                  }
                />
              )}
              {/* //! REMOVE: THE PREVIEW BOARD WILL BE DIMMED WITH EMPTY CONTENT ON BOTH COLUMNS WHEN SESSION IN PROGRESS */}
              {running && shown.length === 0 ? (
                <RunLoader />
              ) : log.length === 0 ? (
                <p className="log-empty">
                  Load two or more keyframes, then Run. The co-pilot fills what
                  it can and flags the rest — review the suspect in-betweens
                  here (flip the key, in-between, then key), with the big frames
                  synced on the right.
                </p>
              ) : shown.length === 0 ? (
                //! ONLY SHOW ONE MESSAGE: VERIFY LATER
                <p className="log-empty">
                  {filter === "offmodel" || filter === "unsure" ? (
                    <>
                      <Sparkles
                        className="mr-1 inline size-3.5"
                        aria-hidden="true"
                      />
                      Nothing here — the co-pilot is confident about every
                      in-between.
                    </>
                  ) : (
                    "No in-betweens in this view."
                  )}
                </p>
              ) : (
                <ol className="log" key={filter}>
                  {shown.map((pair, index) => (
                    <ReviewPairRow
                      key={pair.index}
                      pair={pair}
                      index={index}
                      focused={focused === pair.index}
                      verdict={verdicts[pair.index]}
                      keyUrls={keyUrls}
                      pairMids={mids}
                      explanation={explanations?.[String(pair.index)]}
                      csq={result?.csq}
                      onFocus={() => setFocused(pair.index)}
                      onVerdict={onVerdict}
                      onRefill={onRefill}
                    />
                  ))}
                </ol>
              )}

              {/* //! REVIEW: LOADING SKELETON MIGHT BE USEFUL WHEN PROGRESS IS RUNNING AND PREVIEW BOARD IS OPENED, USED WITH TOGGLE MODE */}
              {running && pending > 0 && shown.length > 0 && (
                <ul className="skel-list" aria-hidden="true">
                  {Array.from({ length: Math.min(pending, 6) }).map((_, i) => (
                    <li
                      className="cel-skel"
                      key={i}
                      style={{ "--i": i } as React.CSSProperties}
                    >
                      <span className="skel-line skel-head" />
                      <span className="skel-line skel-why" />
                      <span className="skel-trip">
                        <i />
                        <i />
                        <i />
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {/* //! REMOVE: TOO COMPLICATED, FILTER TAB PROVIDES ENOUGH INFORMATION */}
              {gaps.length > 0 && filter !== "needs_key" && (
                <div className="gaps">
                  <Button
                    variant="ghost"
                    type="button"
                    className="gaps-head rounded-none font-normal hover:bg-[color-mix(in_oklab,var(--color-akaire)_7%,var(--color-sumi-2))]"
                    onClick={() => pick("needs_key")}
                  >
                    <span className="gaps-mark" aria-hidden="true" />
                    {gaps.length} gap{gaps.length > 1 ? "s" : ""} too large —
                    draw a key here
                    <span className="gaps-toggle">
                      view{" "}
                      <ArrowRight data-icon="inline-end" aria-hidden="true" />
                    </span>
                  </Button>
                </div>
              )}
            </section>

            {/* RIGHT: big per-pair frames (key A · in-between · key B), synced */}
            <section
              className="pane col-right"
              ref={rightRef}
              onScroll={() => sync("R")}
            >
              {/* //! REMOVE: TOO COMPLICATED */}
              <div className="frames-head">
                <span className="eyebrow">Output Frames</span>
                <h2>key · in-between · key</h2>
              </div>

              {running && log.length === 0 ? (
                <RunLoader />
              ) : shown.length === 0 ? (
                <p className="log-empty">No in-betweens in this view.</p>
              ) : (
                <div className="frames-list" key={filter}>
                  {shown.map((p, i) => {
                    const a = keyUrls[p.index];
                    const b = keyUrls[p.index + 1];
                    const mid = p.mid_url ?? mids?.[String(p.index)];
                    const ex = explanations?.[String(p.index)];
                    return (
                      <FrameCard
                        key={p.index}
                        p={p}
                        a={a}
                        b={b}
                        mid={mid}
                        ex={ex}
                        i={i}
                        focused={focused === p.index}
                        onFocus={() => setFocused(p.index)}
                      />
                    );
                  })}
                </div>
              )}
            </section>
          </main>
        </>
      )}
    </>
  );
}
