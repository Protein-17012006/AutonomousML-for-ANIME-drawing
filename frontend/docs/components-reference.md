# Frontend Components Reference

A teammate-facing guide to everything under [`frontend/src/components/`](../src/components/). Read this to
understand what each component does, what it expects, and who renders it — before touching the co-pilot UI.

> **Scope:** [`src/components/ui/`](../src/components/ui/) is the unmodified **shadcn/ui** primitive library
> (Button, Dialog, Avatar, …). It is standard third-party scaffolding and is intentionally **not documented
> here** — see the [shadcn/ui docs](https://ui.shadcn.com/). Everything else is our code and is covered below.

---

## 1. The big picture

The whole feature is the **In-Between Co-pilot**: an artist uploads keyframes (or a video), the FastAPI box
draws the in-betweens and streams a per-pair decision log, and the UI presents that as (a) a **chat transcript**
and (b) a deep **review board**. There is exactly one stateful root — [`CopilotApp`](../src/components/copilot/CopilotApp.tsx) —
and everything else is either a presentational component or a pure helper.

### Two conventions to know

| Convention | Meaning |
|---|---|
| **`lib/` vs `components/`** | Inside `copilot/`, **logic** (hooks + pure helpers) lives in [`lib/`](../src/components/copilot/lib/); **templates** (one React component per file) live in [`components/`](../src/components/copilot/components/). Don't grow `CopilotApp.tsx` back into a god-file — new logic → `lib/`, new UI → `components/`. |
| **Ownership boundary** | The [`components/chat/`](../src/components/copilot/components/chat/) subtree is the **chatbox surface**; the rest of `components/*` (plus `ReviewWorkbench`) is the **co-pilot review interface**. |

### Render hierarchy

```
app/copilot/page.tsx
 └─ CopilotApp                      (dynamic import, ssr:false — owns ALL state)
     ├─ [view === "chat"]
     │    ├─ PegBar                 (from Inputs.tsx — brand glyph)
     │    ├─ MultiplaneHero         (landing only, before first run)
     │    ├─ ChatView               (renders the derived transcript)
     │    │    ├─ FlagBubble
     │    │    ├─ KeyAskBubble
     │    │    └─ ResultCard
     │    └─ ChatComposer           (uses KeyframeDropzone + shortName from Inputs)
     │
     ├─ [view === "board"]
     │    └─ ReviewWorkbench        (the two-column review board)
     │         ├─ QAPanel
     │         ├─ MultiplaneHero    (board landing only)
     │         ├─ RunLoader
     │         ├─ ReconPlayer
     │         ├─ ConfidenceMeter
     │         ├─ FlipPlayer
     │         ├─ FrameCard ─────── FlipPlayer
     │         └─ compareSlot = Compare
     │                          ├─ FilePicker (Inputs)
     │                          └─ CompareWipe
     │
     └─ Toast                        (rendered in any view when a banner is set)
```

**Data-flow in one sentence:** `CopilotApp` holds the source state → `deriveMessages()` rebuilds the chat list
every render → `ChatView` renders it; the same source state feeds `ReviewWorkbench` for the board view. Nothing
downstream owns state — it is all props down, callbacks up.

---

## 2. Top-level components (`src/components/`)

### ThemeProvider.tsx
- **Exports:** `ThemeProvider`
- **What it is:** A thin `"use client"` wrapper that re-exports **next-themes'** `ThemeProvider`, forwarding all
  props. It defines no context of its own; the theme hook is `useTheme` imported straight from `next-themes`.
- **Mounted in:** [`app/layout.tsx`](../src/app/layout.tsx) around `{children}` with
  `attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange`.

### ModeToggle.tsx
- **Exports:** `ModeToggle`
- **What it is:** A Light / Dark / System theme menu (Button trigger with crossfading `Sun`/`Moon` lucide icons +
  a `DropdownMenu`). Uses the `ui/button` and `ui/dropdown-menu` primitives.
- ⚠️ **Currently orphaned** — `ModeToggle` is exported but **never imported/rendered** anywhere. If you want a
  theme switch on the co-pilot page, this is the component to wire in.

---

## 3. The co-pilot shell + support modules (`copilot/`)

### CopilotApp.tsx — the App shell
- **Export:** `default function App()` (`"use client"`). Imported as `CopilotApp` by
  [`app/copilot/page.tsx`](../src/app/copilot/page.tsx) via `next/dynamic(..., { ssr: false })` (client-only, to
  avoid hydration mismatch). **Sole stateful root of the feature.**
- **Owns all state**, notably:
  - `keys = useFileSet()` / `demo = useFileSet()` — uploaded keyframes / Compare-panel frames.
  - `engines` (`"box"`), `fps` (`"24"`), `stride` (`"2"`), `videoFile` — run options.
  - `running`, `banner` — run status + error-toast text.
  - `log: PairEvent[]` — streamed per-pair decisions; `result: ResultEvent | null` — final summary.
  - `verdicts: Record<number, "accept"|"reject">` — artist accept/reject per pair.
  - `view: "chat"|"board"`, `boardFocus`, `upload: UserTurn|null`, `qaTurns: QaTurn[]` — chat-surface state.
  - `plantedCases`, `demoBuilding/demoBanner/demoResult` — planted-demo + Compare state.
- **Derived (`useMemo`):**
  - `keyUrls` = `keys.files.map(URL.createObjectURL)` (revoked on change).
  - `effKeyUrls` — prefers client `keyUrls`; falls back to `result.key_urls` (drop-a-video flow, keys decoded
    server-side) so triptych A/B cells never render black.
  - `msgs = deriveMessages({ upload, log, result, running, banner, qa: qaTurns })`.
- **Key handlers:** `run()`, `runVideo()`, `runPlanted(id)`, `buildDemo()`, `onAsk(q)`, `refillKey(index, file)`,
  `clearAll()`, `openBoard(focus)`.
- **Note:** the "add a key" call (`POST /session/{sid}/key`) is implemented **inline here**, not in `api.ts`. It
  derives the live `sid` by splitting `result.artifacts.montage` (`/session/{sid}/…`), the same trick `onAsk` uses.

### api.ts — FastAPI service layer
Talks to the FastAPI co-pilot box; requests are same-origin paths proxied by Next. SSE (server-sent events) stream
for the decision log.
- **Types:** `SessionHandlers { onPair, onResult, onError }`, `PlantedCase { id, title, planted_type }`.
- **Functions:**
  - `runSession(files, engines, fps, h)` — `POST /session` (multipart `keys[]`), streams the SSE log.
  - `runVideoSession(video, stride, fps, engines, h)` — `POST /session/video`; server decodes + stride-decimates.
    Special-cases HTTP 413 (body too large, ~200 MB) and 422 guard errors into human messages.
  - `runPlantedSession(caseId, engines, fps, h)` — `POST /session/planted` (labeled planted-error demo).
  - `fetchPlantedCases()` — `GET /session/planted/cases`.
  - `askQuestion(sid, question)` — `POST /session/{sid}/ask` → `{ answer, grounded }` (grounded session Q&A;
    `grounded:false` = offline fallback).
  - `runDemo(files, engines, fps)` — `POST /demo` → `DemoResult` (the Compare side-by-side).
  - `parseSSE(buffer)` — low-level SSE frame splitter.

### labels.ts — humanized copy
Pure token → artist-language getters: `regionLabel`, `errTypeLabel`, `actionLabel`, `qaLabel` (`pass`→"on-model",
`abstain`→"unsure", `flag`→"off-model"), `readableReason` (parses `"csq:flag p=0.82 u=0.31"` →
`"Error likelihood 82% · uncertainty 31%"`). Consumed by `ConfidenceMeter`, `QAPanel`, `ReviewWorkbench`, `FrameCard`.

### types.ts — core domain / wire types
Mirrors the FastAPI SSE schema. The load-bearing ones:
- **`PairEvent`** — one decision per gap: `index`, `action` (`"needs_key"|"filled"|…`), `qa` (`"pass"|"abstain"|"flag"`),
  `route` (cadence engine), `reason`, `verdict_prob` (calibrated P(error) → drives the dial), `uncertainty`,
  **`mid_url`** (in-between PNG, streamed live), `correction` (director correction-loop trace).
- **`ResultEvent`** — final summary: `n_autopass`, `n_corrected`, `flagged[]`, `abstained[]`,
  **`artifacts { montage, video, report? }`**, `explanations` (index→`Explanation`), **`pair_mids`** (index→in-between url),
  **`key_urls`** (index→key PNG url, video flow), `sampling`, `csq` (`CsqBand`, box engines only), `qa_degraded`.
- **`Explanation`** — `err_type`, `region`, `explanation`, `box` (fractional `[x,y,w,h]` for the CSS overlay),
  **`annotated_url`** (server-burned overlay PNG, preferred over the CSS box).
- **`CsqBand`** — calibrated abstain-band thresholds for the dial (`tau_pass[]`, `tau_flag[]`, `u_edges[]`, `u_max`).
- **`DemoResult`** — Compare result: `video`, `video_orig?`, `video_rife?`, `frames`, `src`, `gt`.

---

## 4. Logic layer (`copilot/lib/`)

| Module | Exports | What it does |
|---|---|---|
| **chatModel.ts** | `deriveMessages(...)`, `ChatMsg`, `UserTurn`, `QaTurn` | **The heart of the chat surface.** A *pure* derivation that rebuilds the entire conversation from App state every render (so replacing the whole `log` on a draw-key splice just works). `ChatMsg` is a discriminated union on `kind`: `user-upload`, `progress`, `flag`, `ask-key`, `warning`, `result`, `qa`, `error`. |
| **exportSession.ts** | `downloadBundle(result)`, `downloadReview(log, verdicts)` | `downloadBundle` → downloads the server-built `bundle.zip` (recon video + frames + montage). `downloadReview` → builds the artist-κ `review.json` deliverable client-side (per-pair model verdict + artist accept/reject). |
| **pairView.ts** | `whyText`, `statusClass`, `statusGlyph`, `clamp01`, `abstainZone`, `ARC` | Confidence/status helpers. `whyText` = the human decision line; `statusGlyph` = deuteranopia-safe shape (`✎✓~!·`); `abstainZone` resolves the calibrated abstain band on the dial's "clean" axis; `ARC` = the shared 180° gauge SVG path. |
| **useFileSet.ts** | `useFileSet()` | File-accumulation hook → `{ files, add, insertAt, remove, clear }`. Dedups by `name+size`, name-sorted. `insertAt` is a positional splice with **no re-sort** (keeps index alignment with the server's key insert during the draw-key loop). |
| **useTilt.ts** | `useTilt<T>()` | Multiplane cursor-tilt hook. Returns a ref; on pointer move writes normalized cursor offsets to CSS vars `--mx`/`--my` for parallax. No-ops under `prefers-reduced-motion` or without a fine pointer. |

---

## 5. Review / presentational components (`copilot/components/`)

The "board" side of the app. Unless noted, each is presentational (props down, callbacks up) and its **only**
consumer is `ReviewWorkbench` or `CopilotApp`.

### ReviewWorkbench.tsx — the board view
- **Props:** `log`, `result`, `running`, `keyUrls`, `verdicts`, `onVerdict`, `onRefill`, `compareSlot`, `fps`, `initialFocus?`.
- The full two-column review board: **left** = `QAPanel` + triage list (verdict controls, `ConfidenceMeter`,
  `FlipPlayer`); **right** = big per-pair `FrameCard`s. Plus the toolbar (headline, cadence read-out, triage chips,
  export via `downloadBundle`/`downloadReview`), the collapsible reconstructed-cut band (`ReconPlayer`), and a
  landing state (`MultiplaneHero` + `compareSlot`). Handles the keyboard review loop (J/K/A/X), worst-first
  auto-triage, and scroll-synced columns. **Largest file in the tree.** Rendered by `CopilotApp` (board view).

### QAPanel.tsx
- **Props:** `p: PairEvent | null`, `band?`, `ex?`. The focused-pair verdict centerpiece — large 180° dial, abstain
  band drawn to scale, "% clean" readout, and the akaire explanation. Empty-state when `p` is null; dedicated
  "needs a key" state for `action === "needs_key"`. **Rendered by:** `ReviewWorkbench`.

### ConfidenceMeter.tsx
- **Props:** `p: PairEvent`, `band?`. Small 180° "% clean" dial (= 1 − P(error)) as a self-drawing SVG arc, with the
  calibrated abstain band to scale. Returns `null` when there's no verdict prob or the action is `needs_key`.
  **Rendered by:** `ReviewWorkbench` (per non-pass row).

### FrameCard.tsx
- **Props:** `p, a?, b?, mid?, ex?, i, focused, onFocus`. Wraps one reviewed pair as a hover-parallax "mini
  multiplane rig" figure for the right column. Private co-located `FrameTrip` draws the static key·in-between·key
  strip (or a `FlipPlayer` line-test on play) plus the akaire correction-box overlay. **Rendered by:** `ReviewWorkbench`.

### FlipPlayer.tsx
- **Props:** `frames: Frame[]` (also exports the `Frame = { url, label }` type). Per-pair line-test player: flips
  key A → in-between → key B on a shoot-on-2s cadence (240 ms) with play/pause + stepping. **Rendered by:**
  `FrameCard` and `ReviewWorkbench`.

### ReconPlayer.tsx
- **Props:** `src: string`, `fps: number`. Reconstructed-cut video transport with an X-sheet scrub rail and
  frame-accurate stepping (`requestVideoFrameCallback`, falls back to `timeupdate`). **Rendered by:** `ReviewWorkbench`.

### MultiplaneHero.tsx
- **Props:** none. The signature landing hero — a 3D multiplane cel-stack (KEY A / in-between / KEY B on glass
  planes) that cranes to the cursor via `useTilt`, plus the thesis copy. Private co-located `CelArt` draws each cel.
- ⚠️ **Rendered in TWO places** — `CopilotApp` (chat landing) *and* `ReviewWorkbench` (board landing). A change
  here affects both surfaces.

### RunLoader.tsx
- **Props:** none. Self-drawing "co-pilot is drawing the in-betweens…" indicator (`role="status"`). **Rendered by:**
  `ReviewWorkbench` (twice during a run, one per column).

### Compare.tsx
- **Props:** `files, onAdd, onClear, onBuild, building, banner, result: DemoResult | null`. Collapsible
  "See it on a real cut" demo panel — upload a full cut, build, and show original-vs-RIFE reconstruction (via
  `CompareWipe` when both videos exist, else a plain `<video>`). Renders `FilePicker` + `CompareWipe`.
  **Rendered by:** `CopilotApp`, passed as `ReviewWorkbench`'s `compareSlot`.

### CompareWipe.tsx
- **Props:** `orig: string`, `rife: string`. Before/after draggable wipe slider revealing SOURCE vs RIFE through the
  same frame (clip-path inset), keeping both videos time-synced, with keyboard arrow/Home/End control.
  **Rendered by:** `Compare` only.

### Toast.tsx
- **Props:** `message: string`, `onClose`. Slide-in "correction-stamp" error toast with a draining 5.2 s auto-dismiss
  + manual dismiss. Parent keys it by `message` so the timer resets on a new error. **Rendered by:** `CopilotApp`.

### Inputs.tsx — shared input primitives
Factored out so the composer and legacy panels share one definition. Exports:
- `FilePicker({ id, label, onAdd })` — hidden PNG `<input>` + styled label; snapshots the FileList before resetting
  `value` (dodges the Chromium load→clear→load bug). Used by `Compare`.
- `KeyframeDropzone({ files, urls, onAdd, onRemove, onClear, compact? })` — drag-drop light-table + collapsible cel
  contact-sheet (PNG only). Used by `ChatComposer`.
- `PegBar()` — the peg-bar brand glyph SVG. Used by `CopilotApp` and internally by `KeyframeDropzone`.
- `shortName(name, head=14)` — utility that truncates long video filenames, preserving the extension. Used by `ChatComposer`.

---

## 6. Chat surface (`copilot/components/chat/`)

The chatbox surface. `ChatView` is a **pure transcript renderer** over the `ChatMsg[]` list produced by
`deriveMessages()`; it owns no state.

### ChatView.tsx
- **Props:** `msgs: ChatMsg[]`, `keyUrls: string[]`, `onOpenBoard: (focus) => void`, `onRefill: (index, file) => Promise<void>`,
  `onExport: (result) => void`. Scrollable transcript that maps each `ChatMsg` to a bubble via a `switch` on
  `m.kind` and auto-scrolls to the newest. **Rendered by:** `CopilotApp`. Renders the three bubbles below.

### ChatComposer.tsx
- **Props:** one `p` object — the file set (`files`, `fileUrls`, `onAdd/onRemove/onClear`), run args
  (`engines/setEngines`, `fps/setFps`, `videoFile/onVideo`, `stride/setStride`), actions (`onRun`, `onRunVideo`,
  `onAsk`, `plantedCases`/`onRunPlanted`), and state (`running`, `compact`, `askEnabled`). Bottom-docked composer:
  drop keys/video, tweak args behind a ⚙ gear, type grounded follow-ups. Swaps its primary button between
  Run / Run video / Ask. **Rendered by:** `CopilotApp`. Uses `KeyframeDropzone` + `shortName`. (Uses native
  `<input>`/`<select>`, not `ui/input`.)

### FlagBubble.tsx
- **Props:** `pair: PairEvent`, `ex?`, `keyUrls: string[]`, `onReview: () => void`. Renders a flagged pair as a
  triptych; prefers the server `annotated_url`, else the raw mid + CSS region-box overlay, then explanation,
  P(error)/uncertainty, and the correction-round trace. **Rendered by:** `ChatView` (`kind: "flag"`).

### KeyAskBubble.tsx
- **Props:** `pair: PairEvent`, `resolved: boolean`, `onRefill: (index, file) => Promise<void>`. The agent asking the
  user to draw a key (the collaborative loop made conversational) — `needs_key`/abstain rendered as a question with
  an inline PNG reply dropzone; marks resolved once a key is supplied. **Rendered by:** `ChatView` (`kind: "ask-key"`).

### ResultCard.tsx
- **Props:** `result: ResultEvent`, `keyUrls: string[]`, `onOpenBoard: () => void`, `onExport: (result) => void`.
  Final session-summary bubble — pass/corrected/flagged/unsure/keys stats, artifact links (montage / recon cut /
  report), "Open review board" + "Export bundle", and per-flagged-pair key downloads. **Rendered by:** `ChatView`
  (`kind: "result"`).

---

## 7. Notes & gotchas for teammates

- **State lives in exactly one place** — `CopilotApp`. Everything else is props-down/callbacks-up. If you need new
  state, add it there and thread it down (or lift a `lib/` hook), rather than introducing local state in a leaf.
- **The chat transcript is derived, not stored.** `deriveMessages()` rebuilds it from `{ upload, log, result,
  running, banner, qa }` every render — so a new run wiping `log` naturally wipes the transcript. (Persisting this
  across reload is the subject of the separate Firebase persistence plan under `docs/`.)
- **`effKeyUrls`, not `keyUrls`, is what the UI should render** — it falls back to `result.key_urls` for the
  drop-a-video flow where keys are decoded server-side; using raw `keyUrls` there renders black A/B cells.
- **`MultiplaneHero` is shared by both landings** (chat + board) — test both when editing it.
- **`ModeToggle` is currently unmounted** — wire it in if you want a theme switch.
- **`src/components/ui/`** is stock shadcn/ui; in the live app the co-pilot renders its own hand-rolled markup
  (native `<button>`/`<input>` + `.btn`/`.ask-input` CSS), so most `ui/` primitives aren't reached yet — they're
  there for future surfaces (e.g. the planned conversation sidebar).

---

_Generated as a static reference — re-verify against source when in doubt. Last synced: 2026-07-06._
