import type { PairEvent } from "../../types";
import { statusClass } from "../../lib/pairView";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { FlipPlayer, type Frame } from "./FlipPlayer";
import { KeyframeUploadButton } from "./KeyframeUploadButton";
import { StatusGlyph } from "./StatusGlyph";
import { Check, X } from "lucide-react";

interface ReviewPairRowProps {
  pair: PairEvent;
  index: number;
  focused: boolean;
  verdict?: "accept" | "reject";
  keyUrls: string[];
  pairMids?: Record<string, string>;
  onFocus: () => void;
  onVerdict: (index: number, verdict: "accept" | "reject") => void;
  onRefill: (index: number, file: File) => void;
  verdictEnabled?: boolean;
  refillEnabled?: boolean;
}

export function ReviewPairRow({
  pair,
  index,
  focused,
  verdict,
  keyUrls,
  pairMids,
  onFocus,
  onVerdict,
  onRefill,
  verdictEnabled = true,
  refillEnabled = true,
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
        pair {pair.index}

        {verdict && (
          <span className={`verdict-badge ${verdict}`}>
            {verdict === "accept" ? "kept" : "redraw"}
          </span>
        )}
      </div>

      {frames && <FlipPlayer frames={frames} />}

      {pair.action !== "needs_key" && verdictEnabled ? (
        <div className="verdict">
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
      ) : pair.action === "needs_key" ? (
        <KeyframeUploadButton
          disabled={!refillEnabled}
          onFileSelect={(file) => onRefill(pair.index, file)}
        />
      ) : null}
    </li>
  );
}
