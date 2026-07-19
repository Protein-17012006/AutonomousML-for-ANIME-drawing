export function BrandIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-8 shrink-0"
      focusable="false"
      viewBox="0 0 32 32"
    >
      <rect
        x="2.75"
        y="2.75"
        width="26.5"
        height="26.5"
        rx="6"
        fill="var(--color-sumi-2)"
        stroke="var(--color-line)"
        strokeWidth="1.5"
      />
      <path
        d="M8 10.5h16M8 21.5h16"
        stroke="var(--color-line)"
        strokeLinecap="round"
        strokeWidth="1.5"
      />
      <circle cx="10" cy="16" r="3" fill="var(--color-ao)" />
      <circle cx="22" cy="16" r="3" fill="var(--color-akaire)" />
      <path
        d="M13.75 16h4.5"
        stroke="var(--color-washi)"
        strokeLinecap="round"
        strokeWidth="1.5"
      />
    </svg>
  );
}
