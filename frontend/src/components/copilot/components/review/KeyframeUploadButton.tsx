import { useRef } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Pencil } from "lucide-react";

export function KeyframeUploadButton({
  onFileSelect,
  className,
  buttonClassName,
  label = "Add my key",
  disabled = false,
}: {
  onFileSelect: (file: File) => void;
  className?: string;
  buttonClassName?: string;
  label?: string;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div
      className={cn("inline-flex pt-[11px]", className)}
      onClick={(event) => event.stopPropagation()}
    >
      <input
        ref={inputRef}
        type="file"
        disabled={disabled}
        accept="image/png"
        className="sr-only"
        onChange={(event) => {
          event.stopPropagation();
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (file) onFileSelect(file);
        }}
      />
      <Button
        variant="outline"
        type="button"
        disabled={disabled}
        className={cn(
          "border-akaire bg-akaire/10 font-mono text-xs tracking-[0.02em] text-akaire-ink hover:bg-akaire hover:text-white active:translate-y-px",
          buttonClassName,
        )}
        onClick={() => inputRef.current?.click()}
      >
        <Pencil data-icon="inline-start" aria-hidden="true" />
        {label}
      </Button>
    </div>
  );
}
