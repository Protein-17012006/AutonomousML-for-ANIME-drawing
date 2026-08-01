// original-vs-RIFE side-by-side: one server-rendered video (left ORIGINAL /
// right RECON, frame-synced at cadence*2 fps). The continuous loop IS the
// presentation — same as the box compare video — so no transport controls.
export function ComparePlayer({
  src,
  onError,
}: {
  src: string;
  // same contract as ReconPlayer: the workbench swaps in a message on failure
  onError?: () => void;
}) {
  return (
    <video
      className="compare-video block w-full"
      src={src}
      autoPlay
      loop
      muted
      playsInline
      onError={onError}
      onLoadedMetadata={(event) => {
        const video = event.currentTarget;
        if (
          video.videoWidth < 1 ||
          video.videoHeight < 1 ||
          !Number.isFinite(video.duration) ||
          video.duration <= 0
        ) {
          onError?.();
        }
      }}
      aria-label="original versus RIFE reconstruction, looping"
    />
  );
}
