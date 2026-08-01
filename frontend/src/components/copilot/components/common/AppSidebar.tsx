"use client";

import { useState, type FormEvent } from "react";

import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BrandIcon } from "@/components/common/BrandIcon";
import { Input } from "@/components/ui/input";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import type { PublishedSessionSummary } from "@/lib/sessionApi";
import {
  Check,
  LayoutGrid,
  LoaderCircle,
  LogOut,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";

export interface SidebarAccount {
  name?: string | null;
  username?: string | null;
}

interface AppSidebarProps {
  account: SidebarAccount | null;
  onSignOut: () => void;
  sessions: PublishedSessionSummary[];
  selectedPid: string | null;
  historyLoading: boolean;
  historyLoadingMore: boolean;
  historyError: string | null;
  hasMoreSessions: boolean;
  onSelectSession: (session: PublishedSessionSummary) => void;
  onCreateSession: (title: string) => Promise<void>;
  onRenameSession: (pid: string, title: string) => Promise<void>;
  onDeleteSession: (pid: string) => Promise<void>;
  onRetryHistory: () => void;
  onLoadMore: () => void;
  view: "chat" | "board";
  onViewChange: (view: "chat" | "board") => void;
  previewAvailable: boolean;
}

function accountName(account: SidebarAccount | null) {
  return account?.name?.trim() || account?.username?.trim() || "Animator";
}

function initials(account: SidebarAccount | null) {
  const source = accountName(account);
  return source
    .split(/\s|@/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function AppSidebar({
  account,
  onSignOut,
  sessions,
  selectedPid,
  historyLoading,
  historyLoadingMore,
  historyError,
  hasMoreSessions,
  onSelectSession,
  onCreateSession,
  onRenameSession,
  onDeleteSession,
  onRetryHistory,
  onLoadMore,
  view,
  onViewChange,
  previewAvailable,
}: AppSidebarProps) {
  const { state, isMobile, toggleSidebar } = useSidebar();
  const collapsedRail = state === "collapsed" && !isMobile;
  const [creating, setCreating] = useState(false);
  const [createTitle, setCreateTitle] = useState("");
  const [editingPid, setEditingPid] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [deletingPid, setDeletingPid] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const submitCreate = async (event: FormEvent) => {
    event.preventDefault();
    const title = createTitle.trim();
    if (!title || title.length > 80) {
      setFormError("Use 1–80 characters.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await onCreateSession(title);
      setCreateTitle("");
      setCreating(false);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not create session.");
    } finally {
      setSaving(false);
    }
  };

  const submitRename = async (event: FormEvent, pid: string) => {
    event.preventDefault();
    const title = editTitle.trim();
    if (!title || title.length > 80) {
      setFormError("Use 1–80 characters.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await onRenameSession(pid, title);
      setEditingPid(null);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not rename session.");
    } finally {
      setSaving(false);
    }
  };

  const submitDelete = async (pid: string) => {
    setDeleting(true);
    setFormError(null);
    try {
      await onDeleteSession(pid);
      setDeletingPid(null);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not delete session.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size={collapsedRail ? "icon" : "default"}
              type="button"
              onClick={collapsedRail ? toggleSidebar : undefined}
              aria-label={collapsedRail ? "Expand sidebar" : undefined}
              title={collapsedRail ? "Expand sidebar" : undefined}
              tabIndex={collapsedRail ? 0 : -1}
              className={collapsedRail ? "group/brand" : "px-0 hover:bg-transparent"}
            >
              {collapsedRail ? (
                <>
                  <span className="flex group-hover/brand:hidden">
                    <BrandIcon />
                  </span>
                  <PanelLeftOpen className="hidden h-5 w-5 text-washi group-hover/brand:block" />
                </>
              ) : (
                <BrandIcon />
              )}
            </Button>
            <span className="font-display text-sm whitespace-nowrap text-washi group-data-[collapsible=icon]:hidden">
              In-Between Co-pilot
            </span>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            type="button"
            onClick={toggleSidebar}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
            className="text-ash transition-colors hover:text-washi group-data-[collapsible=icon]:hidden"
          >
            <PanelLeftClose />
          </Button>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                type="button"
                isActive={view === "chat"}
                onClick={() => onViewChange("chat")}
                tooltip="Chat"
              >
                <MessageSquare />
                <span>Chat</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton
                type="button"
                isActive={view === "board"}
                disabled={!previewAvailable}
                onClick={() => onViewChange("board")}
                tooltip={
                  previewAvailable
                    ? "Preview board"
                    : "Run a session first to open the preview board."
                }
              >
                <LayoutGrid />
                <span>Preview board</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>

        <SidebarGroup className="min-h-0 group-data-[collapsible=icon]:hidden">
          <div className="flex items-center justify-between gap-2 px-2">
            <SidebarGroupLabel className="px-0">History</SidebarGroupLabel>
            <Button
              variant="ghost"
              size="icon-xs"
              type="button"
              onClick={() => {
                setCreating(true);
                setEditingPid(null);
                setFormError(null);
              }}
              aria-label="Create session"
              title="Create session"
            >
              <Plus />
            </Button>
          </div>
          <SidebarMenu>
            {creating && (
              <SidebarMenuItem>
                <form onSubmit={submitCreate} className="flex items-center gap-1 px-2 py-1">
                  <Input
                    autoFocus
                    value={createTitle}
                    maxLength={80}
                    placeholder="Session title"
                    aria-label="New session title"
                    disabled={saving}
                    onChange={(event) => setCreateTitle(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") {
                        setCreating(false);
                        setCreateTitle("");
                        setFormError(null);
                      }
                    }}
                    className="h-8 min-w-0"
                  />
                  <Button type="submit" variant="ghost" size="icon-xs" disabled={saving} aria-label="Create">
                    {saving ? <LoaderCircle className="animate-spin" /> : <Check />}
                  </Button>
                  <Button type="button" variant="ghost" size="icon-xs" disabled={saving} aria-label="Cancel" onClick={() => setCreating(false)}>
                    <X />
                  </Button>
                </form>
              </SidebarMenuItem>
            )}
            {historyLoading && sessions.length === 0 && (
              <SidebarMenuItem className="flex items-center gap-2 px-2 py-2 text-xs text-ash">
                <LoaderCircle className="size-3.5 animate-spin" /> Loading sessions…
              </SidebarMenuItem>
            )}
            {!historyLoading && !historyError && sessions.length === 0 && (
              <SidebarMenuItem className="px-2 py-2 text-xs text-ash">No sessions yet.</SidebarMenuItem>
            )}
            {sessions.map((session) => (
              <SidebarMenuItem key={session.pid} className="flex items-center gap-1">
                {editingPid === session.pid ? (
                  <form onSubmit={(event) => submitRename(event, session.pid)} className="flex min-w-0 flex-1 items-center gap-1 px-2 py-1">
                    <Input
                      autoFocus
                      value={editTitle}
                      maxLength={80}
                      aria-label={`Rename ${session.title}`}
                      disabled={saving}
                      onChange={(event) => setEditTitle(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") {
                          setEditingPid(null);
                          setFormError(null);
                        }
                      }}
                      className="h-8 min-w-0"
                    />
                    <Button type="submit" variant="ghost" size="icon-xs" disabled={saving} aria-label="Save title">
                      {saving ? <LoaderCircle className="animate-spin" /> : <Check />}
                    </Button>
                    <Button type="button" variant="ghost" size="icon-xs" disabled={saving} aria-label="Cancel rename" onClick={() => setEditingPid(null)}>
                      <X />
                    </Button>
                  </form>
                ) : (
                  <>
                    <SidebarMenuButton
                      type="button"
                      isActive={selectedPid === session.pid}
                      onClick={() => onSelectSession(session)}
                      tooltip={session.title}
                      className="min-w-0 flex-1"
                    >
                      <span className={`size-1.5 shrink-0 rounded-full ${session.status === "draft" ? "bg-ash" : "bg-pass"}`} aria-hidden="true" />
                      <span className="truncate">{session.title}</span>
                    </SidebarMenuButton>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      aria-label={`Rename ${session.title}`}
                      title="Rename session"
                      onClick={() => {
                        setEditingPid(session.pid);
                        setEditTitle(session.title);
                        setCreating(false);
                        setFormError(null);
                      }}
                    >
                      <Pencil />
                    </Button>
                    {session.status === "complete" && (
                      <AlertDialog
                        open={deletingPid === session.pid}
                        onOpenChange={(open) => {
                          if (!deleting) setDeletingPid(open ? session.pid : null);
                        }}
                      >
                        <AlertDialogTrigger asChild>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-xs"
                            disabled={saving || deleting}
                            aria-label={`Delete ${session.title}`}
                            title="Delete session"
                            onClick={() => {
                              setEditingPid(null);
                              setCreating(false);
                              setFormError(null);
                            }}
                          >
                            <Trash2 />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent className="items-center text-center">
                          <AlertDialogHeader className="items-center text-center">
                            <AlertDialogTitle>Delete this session?</AlertDialogTitle>
                            <AlertDialogDescription>
                              <span className="font-medium text-washi">{session.title}</span> and all of its generated media, review results, and Q&amp;A history will be permanently deleted.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter className="justify-center">
                            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
                            <AlertDialogAction
                              variant="destructive"
                              disabled={deleting}
                              onClick={(event) => {
                                event.preventDefault();
                                void submitDelete(session.pid);
                              }}
                            >
                              {deleting ? <LoaderCircle className="animate-spin" /> : <Trash2 />}
                              Delete session
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}
                  </>
                )}
              </SidebarMenuItem>
            ))}
            {historyError && (
              <SidebarMenuItem className="flex items-center justify-between gap-2 px-2 py-1 text-xs text-destructive">
                <span className="truncate">{historyError}</span>
                <Button type="button" variant="ghost" size="icon-xs" onClick={onRetryHistory} aria-label="Retry session history">
                  <RotateCcw />
                </Button>
              </SidebarMenuItem>
            )}
            {formError && <SidebarMenuItem className="px-2 py-1 text-xs text-destructive">{formError}</SidebarMenuItem>}
            {hasMoreSessions && !historyError && (
              <SidebarMenuItem>
                <SidebarMenuButton type="button" onClick={onLoadMore} disabled={historyLoadingMore} className="text-ash">
                  {historyLoadingMore ? <LoaderCircle className="animate-spin" /> : <Plus />}
                  <span>Load more</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size="lg">
                  <Avatar size="default">
                    <AvatarFallback>{initials(account)}</AvatarFallback>
                  </Avatar>
                  <div className="flex flex-col gap-0.5 group-data-[collapsible=icon]:hidden">
                    <span className="truncate text-sm text-washi">
                      {accountName(account)}
                    </span>
                    <Badge variant="outline" className="border-line text-ash">
                      Free
                    </Badge>
                  </div>
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent side="top" align="start">
                <DropdownMenuItem onClick={onSignOut}>
                  <LogOut />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
