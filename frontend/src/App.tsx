import * as React from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { PreviewProvider } from "@/components/preview/preview-panel"
import { SiteHeader } from "@/components/site-header"
import { TokenDialog } from "@/components/token-dialog"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { useApprovals, useGlobalEvents } from "@/hooks/use-console"
import { McpView } from "@/views/mcp-view"
import { ModelView } from "@/views/model-view"
import { SchedulesView } from "@/views/schedules-view"
import { SkillsView } from "@/views/skills-view"
import { TasksView } from "@/views/tasks-view"
import { ToolsView } from "@/views/tools-view"

const OTHER_VIEWS: Record<
  string,
  (props: { onOpenTask?: (taskId: string) => void }) => React.ReactNode
> = {
  "日程": ({ onOpenTask }) => <SchedulesView onOpenTask={onOpenTask} />,
  "技能": () => <SkillsView />,
  "MCP": () => <McpView />,
  "工具": () => <ToolsView />,
  "模型配置": () => <ModelView />,
}

export default function App() {
  const [view, setView] = React.useState("新建任务")
  const [selectedTaskId, setSelectedTaskId] = React.useState<string | null>(null)
  // The project a brand-new conversation should bind to (set by the sidebar's
  // project-row "+"); cleared once consumed by a submitted task.
  const [presetProjectId, setPresetProjectId] = React.useState<string | null>(null)
  const [tokenOpen, setTokenOpen] = React.useState(false)
  const conn = useGlobalEvents()
  const approvals = useApprovals()

  const openTask = React.useCallback((taskId: string) => {
    setSelectedTaskId(taskId)
    setView("新建任务")
  }, [])

  // Clicking the "新建任务" nav entry (or switching to any other view) clears
  // the open conversation so the main area shows the composer.
  const changeView = React.useCallback((next: string) => {
    if (next === "新建任务") setSelectedTaskId(null)
    setView(next)
  }, [])

  // ZCode-style: the sidebar project row's "+" jumps to the composer with the
  // folder pre-selected.
  const newTaskInProject = React.useCallback((projectId: string) => {
    setSelectedTaskId(null)
    setPresetProjectId(projectId)
    setView("新建任务")
  }, [])

  // The API layer dispatches this on any 401 — pop the token dialog.
  React.useEffect(() => {
    const show = () => setTokenOpen(true)
    window.addEventListener("console:unauthorized", show)
    return () => window.removeEventListener("console:unauthorized", show)
  }, [])

  const renderView = (() => {
    if (view === "新建任务") {
      return (
        <TasksView
          selectedId={selectedTaskId}
          onSelect={setSelectedTaskId}
          presetProjectId={presetProjectId}
          onConsumePreset={() => setPresetProjectId(null)}
        />
      )
    }
    const factory = OTHER_VIEWS[view]
    return factory ? factory({ onOpenTask: openTask }) : <TasksView selectedId={selectedTaskId} onSelect={setSelectedTaskId} />
  })()

  return (
    <PreviewProvider>
      <SidebarProvider className="h-svh overflow-hidden">
        <AppSidebar
          view={view}
          onViewChange={changeView}
          selectedTaskId={selectedTaskId}
          onSelectTask={openTask}
          onNewTaskInProject={newTaskInProject}
        />
        <SidebarInset>
          <SiteHeader
            title={view}
            conn={conn}
            pendingApprovals={approvals.data?.length ?? 0}
            onOpenTokenDialog={() => setTokenOpen(true)}
            taskId={view === "新建任务" ? selectedTaskId : null}
          />
          <div className="flex min-h-0 flex-1">{renderView}</div>
        </SidebarInset>
        <TokenDialog open={tokenOpen} onOpenChange={setTokenOpen} />
        <Toaster richColors position="bottom-right" />
      </SidebarProvider>
    </PreviewProvider>
  )
}
