import { ToolsPanel } from "@/components/tools/tools-panel"

export function ToolsView() {
  return (
    <div className="grid items-start gap-4 p-4 lg:grid-cols-2 xl:grid-cols-3">
      <div className="lg:col-span-2 xl:col-span-1">
        <ToolsPanel />
      </div>
    </div>
  )
}
