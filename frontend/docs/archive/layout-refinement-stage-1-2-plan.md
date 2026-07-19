# Layout Refinement — Stage 1 & 2 Implementation Plan

> Status: **proposed** · created 2026-07-08
> Parent: `frontend/docs/plans/layout-refinement-initial-plan.md`
> Scope of this doc: **Stage 1 (landing page)** + **Stage 2 (login/signup templates)**. Stage 3
> (Firebase auth + chat persistence, see `frontend/docs/plans/firebase-chat-persistence-plan.md`) is
> out of scope and to be discussed separately.

## 1. Context

Today `/copilot` is **anonymous**: anyone visiting it gets a session, and nothing is persisted. The
goal (from `layout-refinement-initial-plan.md`) is to gate the co-pilot behind auth and give each user
their own persisted history. This plan covers the **first two, UI-only stages**:

- **Stage 1** — a real landing page at `/`, replacing today's `window.location.replace("/copilot")`
  redirect stub in `frontend/src/app/page.tsx`.
- **Stage 2** — `/login` + `/signup` **templates + styles only** (email/password **plus** Google /
  GitHub / Apple social buttons). **No functionality** — no Firebase calls, no form submission.

Firebase (`auth`, `db`) is already initialized in `frontend/src/lib/firebase.ts` but **completely
dormant** — nothing imports it, and there is zero auth anywhere today. So Stages 1–2 touch no backend.

### Confirmed decisions
- **Scope:** Stages 1 + 2 together (both are template + styles only).
- **Auth methods shown in UI:** email/password **plus** Google / GitHub / Apple social buttons.
- **Social logos:** inline **official brand SVGs** (sources listed in §6, pending final sign-off).

## 2. Conventions this must follow (from `frontend/CLAUDE.md`)

- **Tailwind 4 + shadcn/ui only.** Components live under `frontend/src/components/ui/`.
- **Flex/grid for all layout & alignment. Padding only for internal spacing. NO `margin` and NO
  `absolute` positioning for alignment.** This bans `mx-auto` for centering — center with a flex
  parent instead: `<section class="flex justify-center …"><div class="w-full max-w-6xl">…</div></section>`.
  (`position: sticky` for the nav is acceptable — it is not `absolute`.)
- **Reuse theme-reactive shadcn framework tokens** — `bg-background`, `text-foreground`, `bg-primary` /
  `text-primary-foreground`, `bg-card`, `text-muted-foreground`, `border-border`, `rounded-lg/xl`. These
  flip light/dark automatically via next-themes (`class` attribute); defined in
  `frontend/src/app/globals.css` (`@theme inline`). **Do NOT import
  `frontend/src/app/copilot/copilot.css`** (it forces `overflow:hidden` + full-viewport heights) and do
  NOT reuse the `/copilot`-scoped ink tokens (`bg-sumi`, `text-washi`, …).
- **Brand accent = purple→pink gradient**, matching `frontend/src/components/common/BrandIcon.tsx`
  (`bg-linear-to-r from-purple-500 to-pink-500`). Use sparingly for hero/CTA emphasis.
- **Fonts (already wired as utilities):** `font-display` (Space Grotesk) for headings, `font-body`
  (IBM Plex Sans) for copy, `font-mono` for accents. Inherited from `frontend/src/app/layout.tsx`.
- **Reuse:** `BrandIcon`, `ModeToggle` (`frontend/src/components/ModeToggle.tsx`), `cn()`
  (`frontend/src/lib/utils.ts`); mirror the flex nav pattern of
  `frontend/src/components/copilot/components/chat/ChatHeader.tsx` and the Card/CTA pattern of
  `frontend/src/components/copilot/components/chat/ChatWelcome.tsx` — but **do not import `ChatHeader`
  directly** (it depends on `useSidebar()`).
- **Static-export safe** (`BUILD_EXPORT=1` → `output: "export"`, see `frontend/next.config.ts`): no
  server actions, no route handlers, no server `redirect()`. Client nav via `next/link` `<Link>`;
  in-page nav via `#anchor` links.
- **Pattern: pages are server components** (so they can `export const metadata`) that render
  `"use client"` child components for any interactivity. Static export prerenders them at build (SSG).

## 3. Route organization (advice requested in parent plan)

Flat routes — **no route groups** — so URLs and `out/` paths stay obvious (`/`, `/login`, `/signup` →
`out/index.html`, `out/login/index.html`, `out/signup/index.html`).

```
frontend/src/app/
  page.tsx                 # Stage 1 landing — REPLACE redirect stub (server; exports metadata)
  login/page.tsx           # Stage 2 (server; exports metadata) -> renders <LoginForm/>
  signup/page.tsx          # Stage 2 (server; exports metadata) -> renders <SignupForm/>
  layout.tsx               # MODIFY: add `scroll-smooth` to <html> for anchor nav
frontend/src/components/
  landing/
    LandingNav.tsx         # "use client" — anchor links + mobile drawer (shadcn Sheet)
    Hero.tsx               # server
    Milestones.tsx         # server — 4 cards
    About.tsx              # server — background/mission + team avatars
    FeatureShowcase.tsx    # "use client" — left feature nav <-> right overview (useState)
    Newsletter.tsx         # "use client" — email form (preventDefault stub)
    Footer.tsx             # server
  auth/
    AuthShell.tsx          # shared centered card shell (brand + ModeToggle + slot)
    SocialAuthButtons.tsx  # Google / GitHub / Apple row (inline brand SVGs)
    LoginForm.tsx          # "use client"
    SignupForm.tsx         # "use client"
  common/icons/
    GoogleIcon.tsx  GitHubIcon.tsx  AppleIcon.tsx   # inline official brand SVGs (sources in §6)
```

## 4. Stage 1 — Landing page (`/`)

Replace `frontend/src/app/page.tsx` with a **server component** composing the sections below; add
`scroll-smooth` to `<html>` in `frontend/src/app/layout.tsx`. Each section wrapper:
`<section id="…" class="flex justify-center px-6 py-16/24"><div class="w-full max-w-6xl flex flex-col gap-…">`.

1. **LandingNav** (`sticky top-0 z-40`, `flex items-center justify-between gap-4`): `BrandIcon` +
   wordmark left; links **Home / About us / Highlight features** as `#home #about #features` anchors;
   `ModeToggle`; **"Visit space"** `Button` → `/copilot`. Mobile (`md:hidden`): shadcn `Sheet` drawer
   holding the same links + CTA.
2. **Hero** (`#home`): headline (`font-display`, `text-4xl sm:text-5xl lg:text-6xl`), subcopy
   (`text-muted-foreground`), two CTAs in `flex flex-col sm:flex-row gap-3` — **"Create now"** (primary,
   gradient) → `/copilot`; **"Explore now"** (outline) → `#milestones`.
3. **Milestones** (`#milestones`): 4 shadcn `Card`s in `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4
   gap-6`; each = lucide icon in a tinted/gradient rounded box + `CardTitle` + `CardDescription`
   (imaginary achievements per plan).
4. **About us** (`#about`): `grid gap-8 lg:grid-cols-2` — left: title + background + mission; right:
   **team placeholders** as shadcn `Avatar` with fallback initials (no external image URLs) in a
   `flex flex-wrap gap-4`.
5. **FeatureShowcase** (`#features`, `"use client"`): `flex flex-col lg:flex-row gap-8` — **left** a
   vertical nav of the 3 real features (Frames → Video, Video → Frames, In-Between Fills) as buttons
   (`flex flex-col gap-2`); **right** (`flex-1`) an overview panel that swaps on the active index
   (`useState`), each with title, description, and a placeholder visual (`bg-muted aspect-video` +
   centered lucide icon).
6. **Newsletter** (`"use client"`): title + description + email form (`Input` + `Button`,
   `onSubmit={e=>e.preventDefault()}` stub) + placeholder image block (`bg-muted aspect-*`).
7. **Footer**: `BrandIcon` + brief quote + copyright + columns of links (`grid grid-cols-2
   sm:grid-cols-4 gap-8`). Links are placeholder `#`/`/copilot` for now.

Content is **placeholder / imaginary** per the plan (milestones = imaginary achievements, team =
placeholder avatars; feature copy drawn from the app's real capabilities).

## 5. Stage 2 — Auth templates (`/login`, `/signup`) — non-functional

`login/page.tsx` and `signup/page.tsx` are server components (export `metadata`) rendering
`<LoginForm/>` / `<SignupForm/>`. Shared **`AuthShell`**: `flex min-h-screen items-center justify-center
px-6` wrapping a shadcn `Card` (~`max-w-md w-full`) with `BrandIcon` + title; a small top row holds
`ModeToggle` via flex (not absolute).

- **`SocialAuthButtons`** — 3 `Button variant="outline"` in `flex flex-col gap-2`, each = inline brand
  SVG + label ("Continue with Google/GitHub/Apple"). Separated from the email form by a shadcn
  `Separator` with an "or continue with" caption.
- **`LoginForm`** (`/login`): email + password fields (plain styled `<label htmlFor>` + shadcn `Input`),
  **"Sign in"** primary button (`type="button"`, no action / `preventDefault`), a `Link` to `/signup`,
  and `SocialAuthButtons`.
- **`SignupForm`** (`/signup`): email + password + confirm-password fields, **"Create account"** button,
  a `Link` to `/login`, and `SocialAuthButtons`.
- **Labels:** plain `<label htmlFor>` styled with Tailwind — **no new shadcn install needed**. (If the
  shadcn `Label` primitive is preferred, it can be added with owner OK — respecting the ask-before-install rule.)

## 6. Social brand SVGs — sources for sign-off (per CLAUDE.md "verify me the sources")

`lucide-react@1.21.0` ships **no** usable mark for any of these (GitHub/Google absent; its `Apple` is
the *fruit*). So each is a small inline-SVG component under `common/icons/`:

- **GitHub** — Primer **Octicons `mark-github`** (MIT-licensed), monochrome via `currentColor` (adapts
  to light/dark). Source: `github.com/primer/octicons`.
- **Apple** — Apple logo from **"Sign in with Apple" Human Interface Guidelines**, monochrome
  `currentColor`. Source: `developer.apple.com/design/human-interface-guidelines/sign-in-with-apple`.
- **Google** — official **4-color "G"** per **Google Identity branding guidelines** (guidelines require
  the colored mark). Source: `developers.google.com/identity/branding-guidelines`.

## 7. Files

- **Modify:** `frontend/src/app/page.tsx` (replace stub), `frontend/src/app/layout.tsx`
  (`scroll-smooth`; optionally update the app `<title>`).
- **Create:** the `landing/`, `auth/`, and `common/icons/` components listed in §3, plus
  `frontend/src/app/login/page.tsx` and `frontend/src/app/signup/page.tsx`.
- **No** new npm deps, **no** new shadcn components (existing `card`, `input`, `button`, `separator`,
  `sheet`, `avatar` cover it), **no** changes to `/copilot` or `copilot.css`.

## 8. Verification

- `cd frontend; npm run dev` → open `/`, `/login`, `/signup`:
  - Nav anchors scroll to sections; mobile `Sheet` drawer opens; "Visit space" / "Create now" →
    `/copilot`; "Explore now" → `#milestones`.
  - `ModeToggle` flips light/dark — every section + auth card stays legible (theme tokens only).
  - Responsive sweep: mobile (single column + drawer), tablet, desktop.
  - FeatureShowcase left nav swaps the right panel; newsletter/auth submits do nothing (`preventDefault`).
- `npm run lint`.
- Static-export sanity: `$env:BUILD_EXPORT="1"; npm run build` → confirm `/`, `/login`, `/signup`
  prerender into `out/` with no server-only errors.
- **Post-change (CLAUDE.md):** add a timestamped plan/status doc under `Vault/05 - Plans and Roadmap/`,
  update memory, and ask the owner to push the remote vault.

## 9. Open items to confirm during implementation

1. Sign off on the three logo sources in §6.
2. "Visit space" / "Create now" target **for now**: default → `/copilot` (keeps the app reachable
   pre-auth). Stage 3 will make it conditional (signed-in → `/copilot`, else → `/login`). Say if it
   should point at `/login` now.
