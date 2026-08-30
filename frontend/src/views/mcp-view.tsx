import { McpPanel } from "@/components/toolbox/mcp-panel"

export function McpView() {
  return (
    <div className="grid items-start gap-4 p-4 lg:grid-cols-2 xl:grid-cols-3">
      <div className="lg:col-span-2 xl:col-span-1">
        <McpPanel />
      </div>
    </div>
  )
}
