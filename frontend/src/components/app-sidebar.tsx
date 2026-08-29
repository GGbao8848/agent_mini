"use client"

import * as React from "react"

import { NavMain } from "@/components/nav-main"
import { StatusDot } from "@/components/runs/status-dot"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { Skeleton } from "@/components/ui/skeleton"
import { useRuns } from "@/hooks/use-console"
import { fmtTimeShort } from "@/lib/format"
import { excerpt } from "@/lib/runs"
import { BotIcon, LayoutDashboardIcon, WrenchIcon } from "lucide-react"

const data = {
  brand: {
    name: "Agent Console",
    plan: "Agent Core",
  },
  navMain: [
    {
      title: "任务台",
      url: "#",
      icon: <LayoutDashboardIcon />,
    },
    {
      title: "工具箱",
      url: "#",
      icon: <WrenchIcon />,
    },
  ],
}

function SidebarRuns({
  selectedRunId,
  onSelectRun,
}: {
  selectedRunId: string | null
  onSelectRun: (runId: string) => void
}) {
  const runs = useRuns()
  const list = runs.data ?? []
  const sorted = [...list]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 40)

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>任务</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {runs.isLoading &&
            Array.from({ length: 3 }).map((_, i) => (
              <SidebarMenuItem key={i}>
                <Skeleton className="h-8 w-full" />
              </SidebarMenuItem>
            ))}
          {!runs.isLoading && sorted.length === 0 && (
            <p className="px-2 py-1 text-xs text-muted-foreground">还没有任务，派一个吧</p>
          )}
          {sorted.map((run) => (
            <SidebarMenuItem key={run.id}>
              <SidebarMenuButton
                isActive={run.id === selectedRunId}
                onClick={() => onSelectRun(run.id)}
                className="gap-2 py-1.5"
                title={excerpt(run)}
              >
                <StatusDot status={run.status} />
                <span className="flex-1 truncate text-xs">{excerpt(run, 60)}</span>
                <span className="shrink-0 text-[0.65rem] tabular-nums text-muted-foreground">
                  {fmtTimeShort(run.created_at)}
                </span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

export function AppSidebar({
  view,
  onViewChange,
  selectedRunId,
  onSelectRun,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  view: string
  onViewChange: (view: string) => void
  selectedRunId: string | null
  onSelectRun: (runId: string) => void
}) {
  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" className="pointer-events-none" tabIndex={-1}>
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <BotIcon />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{data.brand.name}</span>
                <span className="truncate text-xs">{data.brand.plan}</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain
          items={data.navMain.map((item) => ({
            ...item,
            isActive: item.title === view,
            onSelect: () => onViewChange(item.title),
          }))}
        />
        <SidebarRuns selectedRunId={selectedRunId} onSelectRun={onSelectRun} />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
