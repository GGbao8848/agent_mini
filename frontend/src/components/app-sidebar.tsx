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
import { useTasks } from "@/hooks/use-console"
import { fmtTimeShort } from "@/lib/format"
import { excerpt } from "@/lib/tasks"
import {
  BotIcon,
  CalendarDaysIcon,
  LayoutDashboardIcon,
  PlugIcon,
  PuzzleIcon,
  WrenchIcon,
} from "lucide-react"

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
      title: "日程",
      url: "#",
      icon: <CalendarDaysIcon />,
    },
    {
      title: "技能",
      url: "#",
      icon: <PuzzleIcon />,
    },
    {
      title: "MCP",
      url: "#",
      icon: <PlugIcon />,
    },
    {
      title: "工具",
      url: "#",
      icon: <WrenchIcon />,
    },
  ],
}

function SidebarTasks({
  selectedTaskId,
  onSelectTask,
}: {
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
}) {
  const tasks = useTasks()
  const list = tasks.data ?? []
  const sorted = [...list]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 40)

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>任务</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {tasks.isLoading &&
            Array.from({ length: 3 }).map((_, i) => (
              <SidebarMenuItem key={i}>
                <Skeleton className="h-8 w-full" />
              </SidebarMenuItem>
            ))}
          {!tasks.isLoading && sorted.length === 0 && (
            <p className="px-2 py-1 text-xs text-muted-foreground">还没有任务，派一个吧</p>
          )}
          {sorted.map((task) => (
            <SidebarMenuItem key={task.id}>
              <SidebarMenuButton
                isActive={task.id === selectedTaskId}
                onClick={() => onSelectTask(task.id)}
                className="gap-2 py-1.5"
                title={excerpt(task, 160)}
              >
                <StatusDot status={task.status} />
                <span className="flex-1 truncate text-xs">{excerpt(task, 60)}</span>
                <span className="shrink-0 text-[0.65rem] tabular-nums text-muted-foreground">
                  {fmtTimeShort(task.created_at)}
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
  selectedTaskId,
  onSelectTask,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  view: string
  onViewChange: (view: string) => void
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
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
        <SidebarTasks selectedTaskId={selectedTaskId} onSelectTask={onSelectTask} />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
