import { Button } from "@/components/ui/button";
import { GoogleIcon } from "@/components/common/icons/GoogleIcon";
import { GitHubIcon } from "@/components/common/icons/GitHubIcon";
import { AppleIcon } from "@/components/common/icons/AppleIcon";

// Third-party sign-in options. TEMPLATE ONLY — buttons are non-functional (type="button",
// no handler); Stage 3 wires these to Firebase Auth. Logos are inline brand SVGs (see
// components/common/icons/*): Google stays 4-color; GitHub + Apple inherit currentColor.
const PROVIDERS = [
  { name: "Google", Icon: GoogleIcon },
  { name: "GitHub", Icon: GitHubIcon },
  { name: "Apple", Icon: AppleIcon },
] as const;

export function SocialAuthButtons() {
  return (
    <div className="flex flex-col gap-2">
      {PROVIDERS.map(({ name, Icon }) => (
        <Button
          key={name}
          type="button"
          variant="outline"
          className="h-10 w-full justify-center gap-2"
        >
          <Icon className="size-4" />
          Continue with {name}
        </Button>
      ))}
    </div>
  );
}
