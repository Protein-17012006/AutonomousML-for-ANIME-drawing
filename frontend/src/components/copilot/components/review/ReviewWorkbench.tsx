// Review workbench: focused pair review and frame preview.
import { useEffect, useMemo, useRef, useState } from "react";
import type { PairEvent, ResultEvent } from "../../types";
import { downloadBundle, downloadReview } from "../../lib/exportSession";
import { ChatHeader } from "../chat/ChatHeader";
import { QAPanel } from "./QAPanel";
import { RunLoader } from "./RunLoader";
import { ReconPlayer } from "./ReconPlayer";
import { ComparePlayer } from "./ComparePlayer";
import { FrameCard } from "./FrameCard";
import { ReviewPairRow } from "./ReviewPairRow";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Download, Film, PanelsTopLeft } from "lucide-react";

type MainFilter = "filled" | "needs_key";
type FilledFilter = "pass" | "abstain";
type SelectionSource = "left" | "right";
// OUTPUT view: the filled cut, or the box-style original-vs-RIFE loop.
type OutputTab = "recon" | "compare";

export function ReviewWorkbench({
  log,
  result,
  running,
  keyUrls,
  verdicts,
  onVerdict,
  onRefill,
  stagedRefills,
  canEdit,
  onSubmitVerdicts,
  onSubmitRefills,
  onDiscardStaged,
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
  stagedRefills: Record<number, { file: File; url: string }>;
  canEdit: boolean;
  onSubmitVerdicts: () => void;
  onSubmitRefills: () => void;
  onDiscardStaged: () => void;
  fps: number;
  initialFocus?: number | null;
}) {
  const [filter, setFilter] = useState<MainFilter>("filled");
  const [filledFilter, setFilledFilter] = useState<FilledFilter>("abstain");
  const [focused, setFocused] = useState<number | null>(initialFocus ?? null);
  const [exported, setExported] = useState(false);
  const [reconOpen, setReconOpen] = useState(false);
  const [outTab, setOutTab] = useState<OutputTab>("recon");
  const [failedReconUrl, setFailedReconUrl] = useState<string | null>(null);
  const [failedCompareUrl, setFailedCompareUrl] = useState<string | null>(null);
  const leftRef = useRef<HTMLElement>(null);
  const rightRef = useRef<HTMLElement>(null);

  const { filled, gaps, passed, abstained, shown } = useMemo(() => {
    const filled = log.filter((pair) => pair.action !== "needs_key");
    const gaps = log.filter((pair) => pair.action === "needs_key");
    const passed = filled.filter((pair) => pair.qa === "pass" || pair.artist_verdict === "accept");
    // Flagged in-betweens remain filled and share the abstain review queue.
    const abstained = filled.filter(
      (pair) => (pair.qa === "abstain" || pair.qa === "flag") && !pair.artist_verdict,
    );
    const shown =
      filter === "needs_key"
        ? gaps
        : filledFilter === "pass"
          ? passed
          : abstained;
    return { filled, gaps, passed, abstained, shown };
  }, [filledFilter, filter, log]);
  const hasAllVerdicts = abstained.length > 0 && abstained.every(
    (pair) => verdicts[pair.index] != null,
  );
  const missingVerdicts = abstained.filter(
    (pair) => verdicts[pair.index] == null,
  ).length;

  const video = result?.artifacts?.video;
  // absent on old sessions and on runs where every gap was refused
  const compareUrl = result?.artifacts?.compare;
  const explanations = result?.explanations;
  const mids = result?.pair_mids;
  const loadingPreview = running && !result;
  const reconFailed = video != null && failedReconUrl === video;
  const compareFailed = compareUrl != null && failedCompareUrl === compareUrl;
  const selectedIndex =
    focused != null && shown.some((pair) => pair.index === focused)
      ? focused
      : (shown[0]?.index ?? null);
  // Pair events arrive before the rendered result. Keep the QA panel aligned
  // with both review columns: before that result boundary there is no reviewable
  // pair, even though the progress log already contains entries.
  const panelPair = result
    ? ((selectedIndex != null
        ? log.find((pair) => pair.index === selectedIndex)
        : null) ??
      shown[0] ??
      null)
    : null;

  useEffect(() => {
    if (initialFocus == null) return;
    const frame = requestAnimationFrame(() => setFocused(initialFocus));
    return () => cancelAnimationFrame(frame);
  }, [initialFocus]);

  const scrollPair = (container: HTMLElement | null, index: number) => {
    container
      ?.querySelector<HTMLElement>(`[data-pair="${index}"]`)
      ?.scrollIntoView({ block: "nearest" });
  };

  // Click selection replaces scroll-driven synchronization: only the opposite pane moves.
  const selectPair = (index: number, source: SelectionSource) => {
    setFocused(index);
    requestAnimationFrame(() =>
      scrollPair(source === "left" ? rightRef.current : leftRef.current, index),
    );
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target?.isContentEditable ||
        ["INPUT", "SELECT", "TEXTAREA"].includes(target?.tagName ?? "") ||
        target?.closest?.('[role="slider"]')
      )
        return;
      if (shown.length === 0) return;

      const current = shown.findIndex((pair) => pair.index === selectedIndex);
      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        const next =
          shown[Math.min(shown.length - 1, Math.max(0, current + 1))];
        setFocused(next.index);
        requestAnimationFrame(() => scrollPair(leftRef.current, next.index));
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        const previous = shown[Math.max(0, current <= 0 ? 0 : current - 1)];
        setFocused(previous.index);
        requestAnimationFrame(() =>
          scrollPair(leftRef.current, previous.index),
        );
      } else if (canEdit && (event.key === "a" || event.key === "x") && current >= 0) {
        onVerdict(
          shown[current].index,
          event.key === "a" ? "accept" : "reject",
        );
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [canEdit, onVerdict, selectedIndex, shown]);

  const exportSession = () => {
    if (!result) return;
    downloadBundle(result);
    downloadReview(log, verdicts);
    setExported(true);
    window.setTimeout(() => setExported(false), 1600);
  };

  const showReviewPairs = () => setReconOpen(false);
  const toggleRecon = () => {
    setFailedReconUrl(null);
    setFailedCompareUrl(null);
    setReconOpen((open) => !open);
  };

  return (
    <div className="board-page">
      <div className="review-header">
        <ChatHeader />
        <div className="review-toolbar">
        <div className="review-filters" aria-label="Pair filter">
          <Button
            variant="ghost"
            type="button"
            className={cn("review-filter", filter === "filled" && "is-active")}
            aria-pressed={filter === "filled"}
            onClick={() => {
              showReviewPairs();
              setFilter("filled");
            }}
          >
            Filled <b>{filled.length}</b>
          </Button>
          <div className="review-subfilters" aria-label="Filled pair status">
            <Button
              variant="ghost"
              type="button"
              className={cn(filledFilter === "pass" && "is-active")}
              aria-pressed={filledFilter === "pass"}
              onClick={() => {
                showReviewPairs();
                setFilter("filled");
                setFilledFilter("pass");
              }}
            >
              Pass <b>{passed.length}</b>
            </Button>
            <Button
              variant="ghost"
              type="button"
              className={cn(filledFilter === "abstain" && "is-active")}
              aria-pressed={filledFilter === "abstain"}
              onClick={() => {
                showReviewPairs();
                setFilter("filled");
                setFilledFilter("abstain");
              }}
            >
              Abstain <b>{abstained.length}</b>
            </Button>
          </div>
          <Button
            variant="ghost"
            type="button"
            className={cn(
              "review-filter",
              filter === "needs_key" && "is-active",
            )}
            aria-pressed={filter === "needs_key"}
            onClick={() => {
              showReviewPairs();
              setFilter("needs_key");
            }}
          >
            Needs key <b>{gaps.length}</b>
          </Button>
        </div>
        <div className="review-actions">
          <Button
            variant="outline"
            type="button"
            disabled={!video}
            aria-pressed={reconOpen}
            onClick={toggleRecon}
          >
            {reconOpen ? <PanelsTopLeft /> : <Film />}
            {reconOpen ? "Review pairs" : "Recon"}
          </Button>
          <Button
            variant="outline"
            type="button"
            disabled={!result}
            onClick={exportSession}
            className={cn(exported && "border-pass text-pass")}
          >
            <Download /> {exported ? "Exported" : "Export"}
          </Button>
        </div>
      </div>
      </div>

      {reconOpen ? (
        <main className="recon-workspace">
          {loadingPreview ? (
            <RunLoader message="Preparing reconstructed cut…" />
          ) : !video ? (
            <RunLoader message="No reconstructed cut is available for this session." />
          ) : filled.length === 0 ? (
            <RunLoader message="No reconstructed cut is available yet — add a key to fill a gap first" />
          ) : (
            <div className={cn("recon-output", compareUrl && "is-tabbed")}>
              {/* the compare loop only exists once the server rendered one, so
                  the switch appears with it rather than sitting dead */}
              {compareUrl && (
                <div
                  className="recon-mode-tabs review-subfilters"
                  role="tablist"
                  aria-label="Output view"
                >
                  <Button
                    variant="ghost"
                    type="button"
                    role="tab"
                    aria-selected={outTab === "recon"}
                    className={cn(outTab === "recon" && "is-active")}
                    onClick={() => setOutTab("recon")}
                  >
                    Reconstructed
                  </Button>
                  <Button
                    variant="ghost"
                    type="button"
                    role="tab"
                    aria-selected={outTab === "compare"}
                    className={cn(outTab === "compare" && "is-active")}
                    onClick={() => setOutTab("compare")}
                  >
                    Original vs RIFE
                  </Button>
                </div>
              )}
              <div className="recon-media">
                {compareUrl && outTab === "compare" ? (
                  compareFailed ? (
                    <RunLoader message="The comparison could not be played. Try reopening the preview." />
                  ) : (
                    <ComparePlayer
                      src={compareUrl}
                      onError={() => setFailedCompareUrl(compareUrl)}
                    />
                  )
                ) : reconFailed ? (
                  <RunLoader message="The reconstructed cut could not be played. Try reopening the preview." />
                ) : (
                  <ReconPlayer
                    src={video}
                    fps={fps}
                    onError={() => setFailedReconUrl(video)}
                  />
                )}
              </div>
            </div>
          )}
        </main>
      ) : (
        <main className="dual">
          <section className="pane col-left" ref={leftRef}>
            <QAPanel
              p={panelPair}
              band={result?.csq}
              ex={
                panelPair
                  ? explanations?.[String(panelPair.index)]
                  : undefined
              }
            />
            {loadingPreview ? (
              <RunLoader message="Preparing preview frames…" />
            ) : shown.length === 0 ? (
              <p className="log-empty">No pairs in this view.</p>
            ) : (
              <ol className="log">
                {shown.map((pair, index) => (
                  <ReviewPairRow
                    key={pair.index}
                    pair={pair}
                    index={index}
                    focused={selectedIndex === pair.index}
                    verdict={verdicts[pair.index]}
                    verdictEnabled={(pair.qa === "abstain" || pair.qa === "flag") && !pair.artist_verdict && canEdit}
                    refillEnabled={canEdit}
                    keyUrls={keyUrls}
                    pairMids={mids}
                    onFocus={() => selectPair(pair.index, "left")}
                    onVerdict={(index, verdict) => { if (canEdit) onVerdict(index, verdict); }}
                    onRefill={(index, file) => { if (canEdit) onRefill(index, file); }}
                  />
                ))}
              </ol>
            )}
            {!running && (
              <div className="review-submit">
                {!canEdit ? <p className="review-readonly">This saved session is read-only.</p> : filter === "needs_key" ? (
                  <>
                    <Button type="button" onClick={onSubmitRefills} disabled={gaps.length === 0 || gaps.some((pair) => !stagedRefills[pair.index])}>
                      Submit replacement keys
                    </Button>
                    {Object.keys(stagedRefills).length > 0 && <Button type="button" variant="ghost" onClick={onDiscardStaged}>Discard staged keys</Button>}
                  </>
                ) : filledFilter === "abstain" ? (
                  <div className="review-verdict-submit">
                    <Button type="button" onClick={onSubmitVerdicts} disabled={!hasAllVerdicts}>
                      Submit verdicts
                    </Button>
                    {missingVerdicts > 0 && (
                      <span>{missingVerdicts} decision{missingVerdicts === 1 ? "" : "s"} remaining</span>
                    )}
                  </div>
                ) : null}
              </div>
            )}
          </section>
          <section className="pane col-right" ref={rightRef}>
            {loadingPreview ? (
              <RunLoader message="Preparing preview frames…" />
            ) : shown.length === 0 ? (
              <p className="log-empty">No frames in this view.</p>
            ) : (
              <div className="frames-list">
                {shown.map((pair, index) => (
                  <FrameCard
                    key={pair.index}
                    p={pair}
                    a={keyUrls[pair.index]}
                    b={keyUrls[pair.index + 1]}
                    mid={pair.mid_url ?? mids?.[String(pair.index)]}
                    ex={explanations?.[String(pair.index)]}
                    i={index}
                    focused={selectedIndex === pair.index}
                    onFocus={() => selectPair(pair.index, "right")}
                    onRefill={(index, file) => { if (canEdit) onRefill(index, file); }}
                    pendingKeyUrl={stagedRefills[pair.index]?.url}
                    refillEnabled={canEdit}
                  />
                ))}
              </div>
            )}
          </section>
        </main>
      )}
    </div>
  );
}
