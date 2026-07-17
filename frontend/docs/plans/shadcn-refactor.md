# Shadcn UI Review and Improvement

Use the `$shadcn` skill to **add, review, diagnose, and improve** the UI components in this project.

## Tasks

1. **Review shadcn/ui components**

   * Diagnose incorrect usage, composition, accessibility, variants, states, and integration issues.

2. **Adopt shadcn/ui where appropriate**

   * Identify plain HTML elements that should use existing shadcn/ui components.
   * Migrate them when it improves consistency, accessibility, or maintainability.
   * Do not replace plain HTML unnecessarily.

3. **Use Tailwind CSS for styling**

   * Style components with Tailwind CSS.
   * Pay close attention to the Co-pilot design tokens defined in `globals.css`.
   * Reuse existing design tokens instead of introducing arbitrary values.

4. **Preserve existing styles during migration**

   * When converting traditional HTML/CSS components to Tailwind, inspect their existing styles in `copilot.css` and `globals.css`.
   * Use current working components as the source of truth.
   * Preserve the original visual appearance and behavior.

5. **Maintain compatibility**

   * Preserve existing component APIs, functionality, responsive behavior, and the Co-pilot visual language.

6. **Keep changes focused**

   * Avoid modifying unrelated files.
   * Avoid adding unnecessary dependencies.

7. **Validate changes**

   * Run lint and TypeScript checks after making changes.
   * Report any remaining issues.

## Before Editing

Inspect the relevant components, `copilot.css`, `globals.css`, and existing working shadcn/Tailwind components to understand and follow the project's established patterns.
