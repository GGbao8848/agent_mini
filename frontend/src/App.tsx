import * as React from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { TokenDialog } from "@/components/token-dialog"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { useApprovals, useGlobalEvents } from "@/hooks/use-console"
import { McpView } from "@/views/mcp-view"
import { SchedulesView } from "@/views/schedules-view"
import { SkillsView } from "@/views/skills-view"
import { TasksView } from "@/views/tasks-view"
import { ToolsView } from "@/views/tools-view"

const VIEWS: Record<string, (props: { onOpenTask?: (taskId: string) => void }) => React.ReactNode> = {
  "任务台": () => null, // handled below (needs selectedId)
  "日程": ({ onOpenTask }) => <SchedulesView onOpenTask={onOpenTask} />,
  "技能": () => <SkillsView />,
  "MCP": () => <McpView />,
  "工具": () => <ToolsView />,
}

export default function App() {
  const [view, setView] = React.useState("任务台")
  const [selectedTaskId, setSelectedTaskId] = React.useState<string | null>(null)
  const [tokenOpen, setTokenOpen] = React.useState(false)
  const conn = useGlobalEvents()
  const approvals = useApprovals()

  const openTask = React.useCallback((taskId: string) => {
    setSelectedTaskId(taskId)
    setView("任务台")
  }, [])

  // The API layer dispatches this on any 401 — pop the token dialog.
  React.useEffect(() => {
    const show = () => setTokenOpen(true)
    window.addEventListener("console:unauthorized", show)
    return () => window.removeEventListener("console:unauthorized", show)
  }, [])

  const renderView = (() => {
    if (view === "任务台") {
      return <TasksView selectedId={selectedTaskId} onSelect={setSelectedTaskId} />
    }
    const factory = VIEWS[view]
    return factory ? factory({ onOpenTask: openTask }) : <TasksView selectedId={selectedTaskId} onSelect={setSelectedTaskId} />
  })()

  return (
    <SidebarProvider className="h-svh overflow-hidden">
      <AppSidebar
        view={view}
        onViewChange={setView}
        selectedTaskId={selectedTaskId}
        onSelectTask={openTask}
      />
      <SidebarInset>
        <SiteHeader
          title={view}
          conn={conn}
          pendingApprovals={approvals.data?.length ?? 0}
          onOpenTokenDialog={() => setTokenOpen(true)}
        />
        <div className="flex min-h-0 flex-1 flex-col">{renderView}</div>
      </SidebarInset>
      <TokenDialog open={tokenOpen} onOpenChange={setTokenOpen} />
      <Toaster richColors position="bottom-right" />
    </SidebarProvider>
  )
}
