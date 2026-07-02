"use client";

import { useState } from "react";
import { Clapperboard, LogIn, LogOut, Plus, Sparkles, User } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
} from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";

interface BarAccountProps {
  authMode: string;
}

function BarHeader() {
  const handleNewChat = () => {};

  return (
    <div className="flex flex-col items-start justify-start gap-2 ">
      <Link href={"/"} className="flex items-center justify-start gap-2">
        <Sparkles className="p-1 h-8 w-8 text-white rounded-lg bg-linear-to-r from-purple-500 to-pink-500" />
        <p className="font-bold">AI Animee</p>
      </Link>
      <Button
        onClick={handleNewChat}
        className="w-full"
        variant={"outline"}
        size={"default"}
      >
        <Plus />
        New Chat
      </Button>
      <Button asChild className="w-full" variant={"default"} size={"default"}>
        <Link href={"/copilot"}>
          <Clapperboard />
          In-Between Co-pilot
        </Link>
      </Button>
    </div>
  );
}

function BarAnonymousWarning() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm text-destructive">
          You&apos;re chatting anonymously
        </CardTitle>
        <CardDescription className="text-sm">
          Sign in to save your chat history.
        </CardDescription>
      </CardHeader>

      <CardFooter>
        <Button className="w-full" variant={"outline"} size={"sm"}>
          <LogIn />
          Sign In
        </Button>
      </CardFooter>
    </Card>
  );
}

function BarChatHistory() {
  return (
    <div className="flex flex-1 flex-col items-start justify-start gap-2">
      <h3 className="text-foreground text-sm font-semibold">Chat History</h3>
    </div>
  );
}

function BarAccount({ authMode = "signout" }: BarAccountProps) {
  const handleSignin = () => {};
  const handleSignout = () => {};
  return (
    <div className="flex items-center justify-start gap-2">
      <Avatar className="w-8 h-8">
        <AvatarFallback
          className={authMode === "signin" ? "bg-green-500" : "bg-blue-500"}
        >
          <User className="text-white" />
        </AvatarFallback>
      </Avatar>
      <div className="flex flex-col items-start justify-start flex-1">
        <p className="text-sm">
          {authMode === "signin" ? "Luu Dat Phong" : "Anonymous User"}
        </p>
        <Badge variant={authMode === "signin" ? "default" : "secondary"}>
          {authMode === "signin" ? "Signed In" : "Anonymous"}
        </Badge>
      </div>
      {authMode === "signin" ? (
        <Button onClick={handleSignin} className="ml-auto" size={"icon"}>
          <LogIn className="w-8 h-8" />
        </Button>
      ) : (
        <Button
          onClick={handleSignout}
          className="ml-auto"
          variant={"ghost"}
          size={"icon"}
        >
          <LogOut className="w-8 h-8" />
        </Button>
      )}
    </div>
  );
}

function ChatSideBar() {
  const [showAuthModal, setAuthModal] = useState(false);
  const [authMode, setAuthMode] = useState<"signin" | "signout">("signout");

  return (
    <div className="h-screen flex flex-col gap-3 w-50 border-r p-2">
      <BarHeader />
      <Separator />
      <BarAnonymousWarning />
      <Separator />
      <BarChatHistory />
      <Separator />
      <BarAccount authMode={authMode} />
    </div>
  );
}

export default ChatSideBar;
