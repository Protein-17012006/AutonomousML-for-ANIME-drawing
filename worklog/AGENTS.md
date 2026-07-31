# Worklog Instructions

Maintain the worklog report as modular LaTeX.
This worklog will act as my contribution towards this project. Therefore, after any changes, must update the worklog

## Rules

### Integrity

- Do not invent features, results, metrics, citations, diagrams, or implementation details.
- Clearly distinguish:
  - Implemented
  - Partially implemented
  - Planned
  - Unverified

### Figures and Diagrams

- Store editable Mermaid sources under `worklog/diagrams/source/`.
- Use Mermaid Cli to render the diagram sources
- Store rendered diagrams and screenshots under the matching section directory in `worklog/figures/`.
- Use descriptive lowercase kebab-case filenames.
- Register every figure in `worklog/figures/figure-manifest.md`.
- Every figure must include:
  - A descriptive caption
  - A unique `fig:` label
  - An explicit reference in the surrounding text

### Preference 

- Must use Mermaid for diagrams, if other tools are better, verify the user first
