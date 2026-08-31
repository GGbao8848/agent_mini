import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useToolReload, useTools } from "@/hooks/use-console"
import type { Tool } from "@/lib/types"
import { CircleCheckIcon, CircleXIcon, RefreshCwIcon, WrenchIcon } from "lucide-react"

const RISK_STYLES: Record<string, string> = {
  low: "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  medium: "border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-400",
  high: "border-orange-500/30 bg-orange-500/15 text-orange-700 dark:text-orange-400",
  critical: "border-destructive/40 bg-destructive/15 text-destructive",
}

function ToolCard({ tool }: { tool: Tool }) {
  const sourceLabel =
    tool.source === "mcp"
      ? `MCP · ${(tool.metadata?.mcp_server as string) ?? ""}`
      : "内置"
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{tool.name}</span>
        <Badge variant="secondary">{sourceLabel}</Badge>
        <Badge
          variant="outline"
          className={RISK_STYLES[tool.risk_level] ?? ""}
        >
          {tool.risk_level}
        </Badge>
        <span className="ml-auto flex items-center gap-1 text-xs">
          {tool.available ? (
            <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
              <CircleCheckIcon className="size-3.5" />
              可用
            </span>
          ) : (
            <span className="flex items-center gap-1 text-destructive">
              <CircleXIcon className="size-3.5" />
              不可用
            </span>
          )}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{tool.description || "无描述"}</p>
      {!tool.available && tool.availability_reason && (
        <p className="text-xs text-destructive">{tool.availability_reason}</p>
      )}
    </div>
  )
}

export function ToolsPanel() {
  const tools = useTools()
  const reload = useToolReload()
  const list = tools.data ?? []

  // Empty state: tools come from MCP servers + built-ins; point to the MCP page.
  if (!tools.isLoading && list.length === 0) {
    return (
      <div className="flex min-h-full flex-1 flex-col items-center justify-center gap-4 p-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
            <WrenchIcon className="size-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-medium">还没有工具</h2>
          <p className="text-sm text-muted-foreground">工具由 MCP 服务器提供，去 MCP 页添加服务器后工具会出现在这里</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => reload.mutate(undefined)} disabled={reload.isPending}>
          <RefreshCwIcon data-icon="inline-start" />
          重新加载
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">工具（{list.length} 个）</h2>
        <Button
          size="sm"
          variant="outline"
          disabled={reload.isPending}
          onClick={() => reload.mutate(undefined)}
        >
          <RefreshCwIcon data-icon="inline-start" />
          重新加载
        </Button>
      </div>
      {tools.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((tool) => (
            <ToolCard key={tool.name} tool={tool} />
          ))}
        </div>
      )}
    </div>
  )
}
