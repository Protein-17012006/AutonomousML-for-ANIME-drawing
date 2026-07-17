import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { BrandIcon } from "@/components/common/BrandIcon";
import { ModeToggle } from "@/components/ModeToggle";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// Shared shell for the /login and /signup pages: a slim top bar (back-to-home + theme toggle)
// and a centered auth card. Centering is done with flex (items-center/justify-center), not margin.
interface AuthShellProps {
  title: string;
  description: string;
  children: ReactNode;
}

export function AuthShell({ title, description, children }: AuthShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-sumi">
      <header className="flex justify-center px-6 py-4">
        <div className="flex w-full max-w-6xl items-center justify-between">
          <Link
            href="/"
            className="flex items-center gap-2 font-body text-sm text-ash transition-colors hover:text-washi"
          >
            <ArrowLeft className="size-4" />
            Back to home
          </Link>
          <ModeToggle />
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-6 py-8">
        <Card className="w-full max-w-md">
          <CardHeader className="flex flex-col items-center gap-2 text-center">
            <BrandIcon />
            <CardTitle className="font-display text-2xl text-washi">
              {title}
            </CardTitle>
            <CardDescription>{description}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">{children}</CardContent>
        </Card>
      </main>
    </div>
  );
}
