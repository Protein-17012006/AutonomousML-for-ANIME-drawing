import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface ChatWelcomeProps {
  username?: string; // Implement User object in the future
  onImportFrames?: () => void;
  onImportVideo?: () => void;
}

export function ChatWelcome({
  username = "Animator",
  onImportFrames,
  onImportVideo,
}: ChatWelcomeProps) {
  return (
    <Card className="bg-screen flex-1 w-full flex flex-col gap-2">
      <CardHeader className="flex flex-col gap-2">
        <CardTitle className="w-full font-display text-2xl text-center text-white">
          Welcome, <span className="italic">{username}</span> !
        </CardTitle>

        <CardDescription className="self-center max-w-md font-body text-sm text-center leading-6 text-ash">
          Start a new in-between session by importing your keyframes or a
          reference video. The co-pilot will prepare the workspace and guide you
          through interpolation and quality verification.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col  sm:flex-row gap-4">
        <Button size="lg" className="flex-1" onClick={onImportFrames}>
          Import Keyframes
        </Button>

        <Button
          size="lg"
          variant="secondary"
          className="flex-1"
          onClick={onImportVideo}
        >
          Import Video
        </Button>
      </CardContent>
    </Card>
  );
}
