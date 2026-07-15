"use client";

import type { ConversationMeta } from "@/models/conversation";
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
import { BrandIcon } from "@/components/common/BrandIcon";
import {
  History,
  LayoutGrid,
  LogOut,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
} from "lucide-react";

export interface SidebarAccount {
  name: string;
  email?: string;
}

interface AppSidebarProps {
  conversations: ConversationMeta[];
  activeCid: string | null;
  saving: boolean;
  account: SidebarAccount | null;
  onSelect: (conversation: ConversationMeta) => void;
  onNewChat: () => void;
  onSignOut: () => void;
}

function initials(account: SidebarAccount | null) {
  const source = account?.name || account?.email || "Animator";
  return source
    .split(/\s|@/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function AppSidebar({
  conversations,
  activeCid,
  saving,
  account,
  onSelect,
  onNewChat,
  onSignOut,
}: AppSidebarProps) {
  const { state, isMobile, toggleSidebar } = useSidebar();
  const collapsedRail = state === "collapsed" && !isMobile;

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={collapsedRail ? toggleSidebar : undefined}
              aria-label={collapsedRail ? "Expand sidebar" : undefined}
              title={collapsedRail ? "Expand sidebar" : undefined}
              tabIndex={collapsedRail ? 0 : -1}
              className={
                collapsedRail
                  ? "group/brand flex h-8 w-8 items-center justify-center"
                  : "flex items-center"
              }
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
            </button>
            <span className="font-display text-sm whitespace-nowrap text-washi group-data-[collapsible=icon]:hidden">
              In-Between Co-pilot
            </span>
          </div>
          <button
            type="button"
            onClick={toggleSidebar}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
            className="flex items-center text-ash transition-colors hover:text-washi group-data-[collapsible=icon]:hidden"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton isActive tooltip="Chat">
                <MessageSquare />
                <span>Chat</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton tooltip="Preview board">
                <LayoutGrid />
                <span>Preview board</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>

        <SidebarGroup className="group-data-[collapsible=icon]:hidden">
          <div className="flex items-center justify-between gap-2">
            <SidebarGroupLabel>History</SidebarGroupLabel>
            {saving && <span className="text-xs text-ash">Saving...</span>}
          </div>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton onClick={onNewChat} className="text-washi">
                <Plus />
                <span>New chat</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            {conversations.map((conversation) => (
              <SidebarMenuItem key={conversation.cid}>
                <SidebarMenuButton
                  isActive={conversation.cid === activeCid}
                  onClick={() => onSelect(conversation)}
                  className="text-ash"
                >
                  <History />
                  <span className="truncate">{conversation.title}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size="lg">
                  <Avatar className="h-8 w-8">
                    <AvatarFallback>{initials(account)}</AvatarFallback>
                  </Avatar>
                  <div className="flex flex-col gap-0.5 group-data-[collapsible=icon]:hidden">
                    <span className="truncate text-sm text-washi">
                      {account?.name || "Animator"}
                    </span>
                    <Badge variant="outline" className="border-line text-ash">
                      {account?.email || "Signed in"}
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
