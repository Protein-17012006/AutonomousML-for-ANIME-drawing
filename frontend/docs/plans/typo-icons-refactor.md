# Typography and Iconography Review

Use `$ui-ux-pro-max` and `$frontend-design-direction` to review and improve typography and iconography across all components of the app, especially components under `frontend\src\components\copilot\components\chat`, `frontend\src\components\copilot\components\review`, `frontend\src\components\copilot\components\input`, `frontend\src\components\landing\components`

## Tasks

### Phase 1. Typography

- Inspect all user-facing text in the interface
- Review whether the current typography, wording, labels, capitalization, hierarchy, and microcopy are clear, consistent, and appropriate for the interface.
- Pay special attention to technical or compressed labels 
- Preserve domain-specific terminology when correct, and improve wording that is unclear, inconsistent, overly compressed, or difficult for users to understand.
- Keep typography and terminology consistent across both pages.

### Phase 2. Emojis and Lucide Icons

- Inspect all emojis used as UI icons or visual indicators.
- Replace emojis with semantically appropriate Lucide React icons wherever possible to create a consistent icon system.
- Review existing Lucide icons for semantic correctness, consistent sizing, alignment, spacing, and accessibility.
- Preserve emojis only when they are intentionally used as expressive content rather than as functional UI icons.
- Ensure icon-only interactive controls have appropriate accessible labels and tooltips where needed.

## Constraints

- Do not redesign the color theme, design tokens, fonts, or overall layout
- Preserve existing functionality, component APIs, responsive behavior, and accessibility.
- Keep changes focused specifically on typography, UI wording, emojis, and Lucide icon usage.
- Run lint and TypeScript checks after implementation and report any remaining issues.
