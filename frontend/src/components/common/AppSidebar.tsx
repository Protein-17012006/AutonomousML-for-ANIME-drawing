"use client";

// App-shell left rail for the co-pilot. TEMPLATE + STYLES ONLY — the tabs, history and account
// are static placeholders (no navigation/data/auth wiring yet). Built on the shadcn Sidebar
// (collapsible="icon" → icons-only on desktop, off-canvas Sheet drawer on mobile). Themed to the
// copilot ink palette via the --sidebar-* remap on .copilot-shell/body in copilot.css.
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
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { BrandIcon } from "@/components/common/BrandIcon";
import {
  MessageSquare,
  LayoutGrid,
  History,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";

// Static placeholder history — real sessions get wired in later.
const SESSIONS: { id: string; title: string }[] = [
  { id: "s1", title: "Genga pair 03 · walk cycle" },
  { id: "s2", title: "Hair overlap · 12 keys" },
  { id: "s3", title: "Clip: run_test_final.mp4" },
  { id: "s4", title: "Blink retime · stride 2" },
  { id: "s5", title: "Cape sim cleanup" },
];

export function AppSidebar() {
  const { state, isMobile, toggleSidebar } = useSidebar();
  // Only the DESKTOP icon-rail turns the brand into a hover-to-expand control. Inside the mobile
  // Sheet drawer (isMobile) the brand stays a plain, non-hovering logo.
  const collapsedRail = state === "collapsed" && !isMobile;

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        {/* Brand + desktop collapse toggle. When collapsed to icons the title and the collapse
            toggle fold away, so the brand mark itself becomes the click target to EXPAND
            (the thin rail / ⌘B still work too). When expanded it's a plain, non-focusable logo —
            the dedicated toggle on the right handles collapsing. */}
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
                  {/* collapsed rail: the brand IS the expand control. Show the BrandIcon by
                      default; on hover flip it to the collapsible icon to signal the click. */}
                  <span className="flex group-hover/brand:hidden">
                    <BrandIcon />
                  </span>
                  <PanelLeftOpen className="hidden h-5 w-5 text-washi group-hover/brand:block" />
                </>
              ) : (
                <BrandIcon />
              )}
            </button>
            {/* whitespace-nowrap: keep the title on one line so it doesn't wrap/jump while the
                rail animates its width open. */}
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
        {/* Working tabs — icons remain when collapsed; the tooltip labels them on hover. */}
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

        {/* Session history — hidden when collapsed (per-item titles are meaningless as icons). */}
        <SidebarGroup className="group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel>History</SidebarGroupLabel>
          <SidebarMenu>
            {SESSIONS.map((s) => (
              <SidebarMenuItem key={s.id}>
                <SidebarMenuButton className="text-ash">
                  <History />
                  <span className="truncate">{s.title}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        {/* Account — collapses to just the avatar. */}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg">
              <Avatar className="h-8 w-8">
                <AvatarFallback>AN</AvatarFallback>
              </Avatar>
              <div className="flex flex-col gap-0.5 group-data-[collapsible=icon]:hidden">
                <span className="truncate text-sm text-washi">Animator</span>
                <Badge variant="outline" className="border-line text-ash">
                  Free
                </Badge>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
