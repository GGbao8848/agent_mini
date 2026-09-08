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
  const sourceLabel = tool.source === "internal" ? "内部" : "内置"
  const description = tool.description || "无描述"
  return (
    <div className="flex h-full flex-col gap-1.5 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium" title={tool.name}>
          {tool.name}
        </span>
        <Badge variant="secondary" className="shrink-0">
          {sourceLabel}
        </Badge>
        <Badge variant="outline" className={`shrink-0 ${RISK_STYLES[tool.risk_level] ?? ""}`}>
          {tool.risk_level}
        </Badge>
        <span className="ml-auto flex shrink-0 items-center gap-1 text-xs">
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
      <p className="line-clamp-2 min-h-8 text-xs text-muted-foreground" title={description}>
        {description}
      </p>
      {!tool.available && tool.availability_reason && (
        <p className="truncate text-xs text-destructive" title={tool.availability_reason}>
          {tool.availability_reason}
        </p>
      )}
    </div>
  )
}

export function ToolsPanel() {
  const tools = useTools()
  const reload = useToolReload()
  // 只展示内置工具；MCP 工具在 MCP 页的服务器卡片详情里看
  const list = (tools.data ?? []).filter((tool) => tool.source !== "mcp")

  // Empty state: built-in tools come from the runtime registry.
  if (!tools.isLoading && list.length === 0) {
    return (
      <div className="flex min-h-full flex-1 flex-col items-center justify-center gap-4 p-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
            <WrenchIcon className="size-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-medium">还没有内置工具</h2>
          <p className="text-sm text-muted-foreground">内置工具由运行时注册，可点击下方按钮重新加载</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => reload.mutate(undefined)} disabled={reload.isPending}>
          <RefreshCwIcon data-icon="inline-start" />
          重新加载
        </Button>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">内置工具（{list.length} 个）</h2>
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
