# Design System and Landing Page Review

Use `$ui-ux-pro-max`, `$frontend-design-direction`, and `$tailwind-design-system` skills to review and improve the application's visual system and synchronize it across all pages.

## Phase 1 — Font System Review

- Inspect the current font families, weights, sizes, line heights, letter spacing, and typography hierarchy used throughout the application. (refer to `frontend\src\app\layout.tsx` and `frontend\src\app\globals.css` for current fonts used)
- Evaluate whether the current fonts suit the application's anime-production, creative-tool, and technical Co-pilot identity.
- Identify inconsistent, unnecessary, or conflicting font usage.
- Prefer fonts that work well across headings, body text, labels, controls, and technical information.
- If another font would provide a clear improvement in readability, visual identity, or consistency, provide a small set of suitable alternatives and explain why they would fit better and verify with the user. Otherwise, keep the existing fonts
- Avoid replacing fonts only for novelty.


## Phase 2 — Co-pilot Design Token Review

- Inspect the current Co-pilot design tokens defined in `globals.css`, and styles in `copilot.css`, and the Tailwind theme configuration.
- Review the visual quality and consistency of backgrounds, surfaces, text hierarchy, borders, dividers, accent colors, semantic states, shadows, radii, spacing, and interaction states.
- Determine whether the current tokens provide sufficient contrast, hierarchy, readability, and visual cohesion. If not, suggest improvements and verify with user
- Prefer semantic and reusable tokens over page-specific or arbitrary values.
- Avoid creating an unrelated design system or generic AI/SaaS appearance.
- Use existing working Co-pilot components as the visual reference.

## Phase 3 — Application Theme Synchronization

- Synchronize the visual theme across the Landing page, and related authentication pages, and the main Co-pilot Chat page.
- The Co-pilot Chat page currently follows the shared Co-pilot design tokens, while the Landing and authentication pages use a different visual theme.
- Use the reviewed Co-pilot design system as the primary reference and update the Landing and authentication pages to follow the same shared theme.
- Synchronize theme colors, typography, surfaces, borders, accents, and semantic states.
- Replace hardcoded or page-specific visual values with shared design tokens where appropriate.
- Preserve appropriate differences in presentation: the Landing page may remain more expressive and marketing-oriented, authentication pages should remain focused and minimal, and the Co-pilot Chat page should remain functional and application-oriented.
- Ensure all pages clearly feel like parts of the same application.

## Phase 4 — Landing Page Structure

Reorganize the Landing page sections into the following order:

1. Hero
2. Affiliate Display (new)
3. About
4. Feature Showcase

- Move the existing `FeatureShowcase` section directly below the `About` section.
- Add a new Affiliate Display section between the Hero and About sections.
- Implement the Affiliate Display as an automatically scrolling brand-logo carousel (use pre-built carousel, not create custom carousel, consider using carousel component from `shadcn` if suitable, verify me this)
- Make the carousel responsive, visually subtle, and consistent with the shared Co-pilot design system.
- Respect appropriate accessibility requirements.
- The following affiliate brands should be displayed: Nextjs, React, Tailwind CSS, shadcn/ui, Lucide, FastAPI, PyTorch, AWS, Netflix, Redbull
- Brand images/icons should be in monochrome, cite the sources as you import, ask me if some brand images/icons are unfound


## Constraints

- Inspect `globals.css`, `copilot.css`, the Tailwind theme configuration, font configuration, existing working components, and all affected pages before editing.
- Preserve existing functionality, component APIs, responsive behavior, and accessibility.
- Avoid arbitrary colors, spacing, typography, shadows, gradients, and animations.
- Avoid modifying unrelated files or adding unnecessary dependencies.
- Run lint and TypeScript checks after implementation.
- Report font recommendations, design-token changes, theme synchronization changes, files changed, validation results, and any remaining issues.
