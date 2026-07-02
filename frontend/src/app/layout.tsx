import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ThemeProvider } from "@/components/ThemeProvider";
import "./globals.css";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

const metadata: Metadata = {
  title: "Anime Frame Interface",
  description: "Interactive workspace for managing generated outputs.",
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: Readonly<RootLayoutProps>) {
  return (
    <html
      lang="en"
      className={cn("font-sans", geist.variable)}
      suppressHydrationWarning
    >
      <head></head>
      <body>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}

export { metadata };
