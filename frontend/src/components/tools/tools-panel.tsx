import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useToolReload, useTools } from "@/hooks/use-console"
import type { Tool } from "@/lib/types"
import { CircleCheckIcon, CircleXIcon, RefreshCwIcon } from "lucide-react"

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
      : tool.source === "internal"
        ? "内置"
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

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-sm">
          工具{" "}
          <span className="text-xs font-normal text-muted-foreground">
            （{list.length} 个）
          </span>
        </CardTitle>
        <Button
          size="sm"
          variant="outline"
          disabled={reload.isPending}
          onClick={() => reload.mutate(undefined)}
        >
          <RefreshCwIcon data-icon="inline-start" />
          重新加载
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {tools.isLoading ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : list.length === 0 ? (
          <p className="text-sm text-muted-foreground">（还没有注册任何工具）</p>
        ) : (
          list.map((tool) => <ToolCard key={tool.name} tool={tool} />)
        )}
      </CardContent>
    </Card>
  )
}
