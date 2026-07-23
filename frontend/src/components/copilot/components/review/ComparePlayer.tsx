// original-vs-RIFE side-by-side: one server-rendered video (left ORIGINAL /
// right RECON, frame-synced at cadence*2 fps). The continuous loop IS the
// presentation — same as the box compare video — so no transport controls.
export function ComparePlayer({ src }: { src: string }) {
  return (
    <video
      className="compare-video block w-full"
      src={src}
      autoPlay
      loop
      muted
      playsInline
      aria-label="original versus RIFE reconstruction, looping"
    />
  );
}
