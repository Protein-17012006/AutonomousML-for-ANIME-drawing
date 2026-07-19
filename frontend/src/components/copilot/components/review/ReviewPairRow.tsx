import type { CsqBand, Explanation, PairEvent } from "../../types";
import { statusClass, whyText } from "../../lib/pairView";
import { actionLabel, errTypeLabel, qaLabel, regionLabel } from "../../labels";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ConfidenceMeter } from "./ConfidenceMeter";
import { FlipPlayer, type Frame } from "./FlipPlayer";
import { StatusGlyph } from "./StatusGlyph";
import { Check, Pencil, X } from "lucide-react";

interface ReviewPairRowProps {
  pair: PairEvent;
  index: number;
  focused: boolean;
  verdict?: "accept" | "reject";
  keyUrls: string[];
  pairMids?: Record<string, string>;
  explanation?: Explanation;
  csq?: CsqBand | null;
  onFocus: () => void;
  onVerdict: (index: number, verdict: "accept" | "reject") => void;
  onRefill: (index: number, file: File) => void;
}

export function ReviewPairRow({
  pair,
  index,
  focused,
  verdict,
  keyUrls,
  pairMids,
  explanation,
  csq,
  onFocus,
  onVerdict,
  onRefill,
}: ReviewPairRowProps) {
  const a = keyUrls[pair.index];
  const b = keyUrls[pair.index + 1];
  const mid = pair.mid_url ?? pairMids?.[String(pair.index)];
  const frames: Frame[] | null =
    a && b
      ? [
          { url: a, label: "key A" },
          ...(mid ? [{ url: mid, label: "in-between" }] : []),
          { url: b, label: "key B" },
        ]
      : null;

  return (
    <li
      id={`row-${pair.index}`}
      data-pair={pair.index}
      style={{ "--i": Math.min(index, 12) } as React.CSSProperties}
      className={cn(
        statusClass(pair),
        focused && "focused",
        verdict && `v-${verdict}`,
      )}
      role="button"
      tabIndex={0}
      onClick={onFocus}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onFocus();
        }
      }}
    >
      <div className="log-head">
        <span
          className={cn("sglyph", `sglyph-${statusClass(pair)}`)}
          aria-hidden="true"
        >
          <StatusGlyph pair={pair} />
        </span>
        pair {pair.index} · {actionLabel(pair.action)}
        {pair.qa ? ` · ${qaLabel(pair.qa)}` : ""}
        {verdict && (
          <span className={`verdict-badge ${verdict}`}>
            {verdict === "accept" ? "kept" : "redraw"}
          </span>
        )}
      </div>
      <div className="log-why">{whyText(pair)}</div>
      {pair.qa !== "pass" && <ConfidenceMeter p={pair} band={csq} />}
      {explanation && (
        <div className="log-explain">
          <Pencil className="mr-1 inline size-3" aria-hidden="true" />
          {errTypeLabel(explanation.err_type)}
          {regionLabel(explanation.region)
            ? `, ${regionLabel(explanation.region)}`
            : ""} — {explanation.explanation}
        </div>
      )}
      {frames && <FlipPlayer frames={frames} />}
      {pair.action !== "needs_key" ? (
        <div className="verdict">
          <span className="verdict-label">Your call</span>
          <Button
            variant="ghost"
            type="button"
            className={cn(
              "vbtn",
              "accept",
              verdict === "accept" && "on",
              "hover:bg-transparent",
            )}
            onClick={(event) => {
              event.stopPropagation();
              onVerdict(pair.index, "accept");
            }}
          >
            <Check data-icon="inline-start" aria-hidden="true" />
            Keep
          </Button>
          <Button
            variant="ghost"
            type="button"
            className={cn(
              "vbtn",
              "reject",
              verdict === "reject" && "on",
              "hover:bg-transparent",
            )}
            onClick={(event) => {
              event.stopPropagation();
              onVerdict(pair.index, "reject");
            }}
          >
            <X data-icon="inline-start" aria-hidden="true" />
            Redraw
          </Button>
        </div>
      ) : (
        <label className="group mt-[11px] inline-block cursor-pointer" onClick={(event) => event.stopPropagation()}>
          <input
            type="file"
            accept="image/png"
            className="sr-only"
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (file) onRefill(pair.index, file);
            }}
          />
          <span className="inline-block rounded-md border border-akaire bg-akaire/10 px-3.5 py-1.5 font-mono text-xs tracking-[0.02em] text-akaire-ink transition-all group-hover:bg-akaire group-hover:text-white group-active:translate-y-px">
            <Pencil className="mr-1 inline size-3.5" aria-hidden="true" />
            Add my key
          </span>
        </label>
      )}
    </li>
  );
}
