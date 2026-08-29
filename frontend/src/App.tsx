import * as React from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { TokenDialog } from "@/components/token-dialog"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { useApprovals, useGlobalEvents } from "@/hooks/use-console"
import { RunsView } from "@/views/runs-view"
import { ToolboxView } from "@/views/toolbox-view"

export default function App() {
  const [view, setView] = React.useState("任务台")
  const [selectedRunId, setSelectedRunId] = React.useState<string | null>(null)
  const [tokenOpen, setTokenOpen] = React.useState(false)
  const conn = useGlobalEvents()
  const approvals = useApprovals()

  const openRun = React.useCallback((runId: string) => {
    setSelectedRunId(runId)
    setView("任务台")
  }, [])

  // The API layer dispatches this on any 401 — pop the token dialog.
  React.useEffect(() => {
    const show = () => setTokenOpen(true)
    window.addEventListener("console:unauthorized", show)
    return () => window.removeEventListener("console:unauthorized", show)
  }, [])

  return (
    <SidebarProvider className="h-svh overflow-hidden">
      <AppSidebar
        view={view}
        onViewChange={setView}
        selectedRunId={selectedRunId}
        onSelectRun={openRun}
      />
      <SidebarInset>
        <SiteHeader
          title={view}
          conn={conn}
          pendingApprovals={approvals.data?.length ?? 0}
          onOpenTokenDialog={() => setTokenOpen(true)}
        />
        <div className="flex min-h-0 flex-1 flex-col">
          {view === "任务台" ? (
            <RunsView selectedId={selectedRunId} onSelect={setSelectedRunId} />
          ) : (
            <ToolboxView />
          )}
        </div>
      </SidebarInset>
      <TokenDialog open={tokenOpen} onOpenChange={setTokenOpen} />
      <Toaster richColors position="bottom-right" />
    </SidebarProvider>
  )
}
