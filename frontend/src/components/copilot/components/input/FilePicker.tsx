export function FilePicker({ id, label, onAdd }: { id: string; label: string; onAdd: (files: File[]) => void }) {
  return (
    <>
      <input
        type="file"
        id={id}
        accept="image/png"
        multiple
        className="visually-hidden"
        onChange={(e) => {
          // Snapshot the files NOW: in Chromium, resetting input.value="" empties the
          // live FileList, so handing it to a deferred setState updater loses everything
          // (the load→clear→load bug). A plain array is independent of the input.
          const picked = Array.from(e.currentTarget.files ?? []);
          e.currentTarget.value = ""; // allow re-picking the same files (re-fires change)
          onAdd(picked);
        }}
      />
      <label htmlFor={id} className="btn btn-ghost">{label}</label>
    </>
  );
}