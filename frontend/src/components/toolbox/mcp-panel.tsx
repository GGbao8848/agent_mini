import * as React from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { useMcpServers, useMcpAction, useTools } from "@/hooks/use-console"
import { normalizeMcpConfig, validateServerPayload } from "@/lib/mcp-config"
import type { MCPServer, Tool } from "@/lib/types"
import {
  PlugIcon,
  UnplugIcon,
  PlusIcon,
  Trash2Icon,
  ServerIcon,
  ChevronRightIcon,
  CircleCheckIcon,
  CircleXIcon,
} from "lucide-react"

const JSON_TEMPLATE = `{
  "id": "demo",
  "name": "Demo MCP",
  "transport": "streamable_http",
  "endpoint": "http://127.0.0.1:8931/mcp",
  "description": "通过 JSON 粘贴注册的 MCP 服务器"
}`

const TOOL_RISK_STYLES: Record<string, string> = {
  low: "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  medium: "border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-400",
  high: "border-orange-500/30 bg-orange-500/15 text-orange-700 dark:text-orange-400",
  critical: "border-destructive/40 bg-destructive/15 text-destructive",
}

function AddServerDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const mcp = useMcpAction()
  const [mode, setMode] = React.useState("json")
  const [json, setJson] = React.useState("")
  const [form, setForm] = React.useState({
    id: "",
    name: "",
    transport: "streamable_http",
    endpoint: "",
    authRef: "",
    description: "",
  })
  const [error, setError] = React.useState("")

  const openDialog = (isOpen: boolean) => {
    onOpenChange(isOpen)
    if (isOpen && !json) setJson(JSON_TEMPLATE)
    if (!isOpen) setError("")
  }

  const submitJson = async () => {
    setError("")
    let payloads
    try {
      const normalized = normalizeMcpConfig(JSON.parse(json))
      if ("error" in normalized) {
        setError(normalized.error)
        return
      }
      payloads = normalized.servers
    } catch (e) {
      setError(`JSON 解析失败：${e instanceof Error ? e.message : String(e)}`)
      return
    }
    for (const payload of payloads) {
      const problem = validateServerPayload(payload)
      if (problem) {
        setError(problem)
        return
      }
    }
    for (const payload of payloads) {
      try {
        await mcp.create.mutateAsync(payload)
      } catch {
        return // toast already shown by the mutation
      }
    }
    openDialog(false)
  }

  const submitForm = () => {
    setError("")
    const payload = {
      id: form.id.trim(),
      name: form.name.trim(),
      transport: form.transport,
      endpoint: form.endpoint.trim(),
      auth_ref: form.authRef.trim() || null,
      description: form.description.trim(),
      metadata: {},
    }
    const problem = validateServerPayload(payload)
    if (problem) {
      setError(problem)
      return
    }
    mcp.create.mutate(payload, { onSuccess: () => openDialog(false) })
  }

  return (
    <Dialog open={open} onOpenChange={openDialog}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>添加 MCP 服务器</DialogTitle>
          <DialogDescription>
            支持标准 mcpServers 配置（Claude Desktop / Cherry Studio 同款），凭据可放 headers/env。
          </DialogDescription>
        </DialogHeader>
        <Tabs value={mode} onValueChange={setMode}>
          <TabsList className="w-full">
            <TabsTrigger value="json" className="flex-1">
              JSON（推荐）
            </TabsTrigger>
            <TabsTrigger value="form" className="flex-1">
              表单
            </TabsTrigger>
          </TabsList>
          <TabsContent value="json" className="flex flex-col gap-2">
            <Textarea
              rows={9}
              spellCheck={false}
              value={json}
              onChange={(e) => setJson(e.target.value)}
              className="font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">
              支持标准 mcpServers 配置或本系统定义 {`{id, name, transport, endpoint}`}
              ；type 可写 http/sse/stdio，支持 headers 与 env，或用 auth_ref 引用服务器环境变量。
            </p>
          </TabsContent>
          <TabsContent value="form" className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-2">
              <div className="grid gap-1.5">
                <Label htmlFor="mcp-id">id</Label>
                <Input id="mcp-id" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="mcp-name">名称</Label>
                <Input id="mcp-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
            </div>
            <div className="grid gap-1.5">
              <Label>transport</Label>
              <Select value={form.transport} onValueChange={(v) => setForm({ ...form, transport: v ?? "streamable_http" })}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="streamable_http">streamable_http</SelectItem>
                  <SelectItem value="stdio">stdio</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="mcp-endpoint">endpoint</Label>
              <Input
                id="mcp-endpoint"
                placeholder="http://host:port/mcp 或启动命令"
                value={form.endpoint}
                onChange={(e) => setForm({ ...form, endpoint: e.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="mcp-auth">auth_ref</Label>
              <Input
                id="mcp-auth"
                placeholder="可空：服务器环境变量里的凭据引用名"
                value={form.authRef}
                onChange={(e) => setForm({ ...form, authRef: e.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="mcp-desc">描述</Label>
              <Input
                id="mcp-desc"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
          </TabsContent>
        </Tabs>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button
            disabled={mcp.create.isPending}
            onClick={() => (mode === "json" ? submitJson() : submitForm())}
          >
            导入 / 注册
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ToolRow({ tool }: { tool: Tool }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs font-medium">{tool.name}</span>
        <Badge variant="outline" className={TOOL_RISK_STYLES[tool.risk_level] ?? ""}>
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
      {tool.description && <p className="mt-1 text-xs text-muted-foreground">{tool.description}</p>}
      {!tool.available && tool.availability_reason && (
        <p className="mt-1 text-xs text-destructive">{tool.availability_reason}</p>
      )}
    </div>
  )
}

/** Server detail dialog: the tool list of one MCP server, scrollable. */
function ServerToolsDialog({
  server,
  onClose,
}: {
  server: MCPServer | null
  onClose: () => void
}) {
  const tools = useTools()
  const mcp = useMcpAction()
  const serverTools = server
    ? (tools.data ?? []).filter((t) => t.metadata?.mcp_server === server.id)
    : []
  const healthy = server?.status === "healthy"

  return (
    <Dialog open={server !== null} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-4 sm:max-w-2xl">
        {server && (
          <>
            <DialogHeader>
              <DialogTitle className="flex flex-wrap items-center gap-2">
                <span className="flex items-center gap-1.5">
                  <ServerIcon className="size-4" />
                  {server.name}
                </span>
                <Badge
                  variant="outline"
                  className={
                    healthy
                      ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                      : ""
                  }
                >
                  {healthy ? "已连接" : "未连接"}
                </Badge>
              </DialogTitle>
              <DialogDescription className="flex flex-col gap-0.5">
                <span className="font-mono text-xs">{server.id} · {server.transport}</span>
                {server.endpoint && (
                  <span className="truncate font-mono text-xs" title={server.endpoint}>
                    {server.endpoint}
                  </span>
                )}
                {server.description && <span className="text-xs">{server.description}</span>}
              </DialogDescription>
            </DialogHeader>
            {!healthy ? (
              <div className="flex flex-col items-start gap-2 text-sm text-muted-foreground">
                <p>服务器未连接，连接后这里会列出它提供的工具。</p>
                <Button
                  size="xs"
                  variant="outline"
                  disabled={mcp.action.isPending}
                  onClick={() => mcp.action.mutate({ serverId: server.id, action: "connect" })}
                >
                  <PlugIcon data-icon="inline-start" />
                  连接
                </Button>
              </div>
            ) : serverTools.length === 0 ? (
              <p className="text-sm text-muted-foreground">该服务器没有注册任何工具。</p>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col gap-2">
                <h4 className="text-xs font-medium text-muted-foreground">
                  工具（{serverTools.length}）
                </h4>
                <div className="-mx-1 flex flex-col gap-2 overflow-y-auto px-1 pb-1">
                  {serverTools.map((tool) => (
                    <ToolRow key={tool.name} tool={tool} />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function McpPanel() {
  const servers = useMcpServers()
  const tools = useTools()
  const mcp = useMcpAction()
  const [addOpen, setAddOpen] = React.useState(false)
  const [removingId, setRemovingId] = React.useState<string | null>(null)
  const [detailServer, setDetailServer] = React.useState<MCPServer | null>(null)

  const serverList = servers.data ?? []
  const toolList = tools.data ?? []

  // Empty state: a centered add button is the whole page.
  if (!servers.isLoading && serverList.length === 0) {
    return (
      <div className="flex min-h-full flex-1 flex-col items-center justify-center gap-4 p-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
            <ServerIcon className="size-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-medium">还没有 MCP 服务器</h2>
          <p className="text-sm text-muted-foreground">
            添加服务器后，点击它的卡片即可查看该服务器提供的工具
          </p>
        </div>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <PlusIcon data-icon="inline-start" />
          添加服务器
        </Button>
        <AddServerDialog open={addOpen} onOpenChange={setAddOpen} />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">MCP 服务器（{serverList.length} 个）</h2>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <PlusIcon data-icon="inline-start" />
          添加服务器
        </Button>
      </div>

      {servers.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {serverList.map((server) => {
            const toolCount = toolList.filter((t) => t.metadata?.mcp_server === server.id).length
            const healthy = server.status === "healthy"
            return (
              <div
                key={server.id}
                role="button"
                tabIndex={0}
                onClick={() => setDetailServer(server)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault()
                    setDetailServer(server)
                  }
                }}
                className="group flex h-full cursor-pointer flex-col gap-1.5 rounded-lg border p-4 outline-none transition-colors hover:border-foreground/25 hover:bg-accent/40 focus-visible:ring-2"
              >
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium" title={server.name}>
                    {server.name}
                  </span>
                  <Badge
                    variant="outline"
                    className={
                      healthy
                        ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                        : ""
                    }
                  >
                    {healthy ? "已连接" : "未连接"}
                  </Badge>
                  <span className="ml-auto flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                    {server.transport}
                    <ChevronRightIcon className="size-3.5 opacity-40 transition-opacity group-hover:opacity-100" />
                  </span>
                </div>
                <p className="truncate text-xs text-muted-foreground" title={server.endpoint || server.id}>
                  {server.endpoint || server.id} · {toolCount} 个工具
                </p>
                {server.description && (
                  <p className="line-clamp-2 text-xs text-muted-foreground" title={server.description}>
                    {server.description}
                  </p>
                )}
                <div className="mt-auto flex gap-2 pt-1">
                  {healthy ? (
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={mcp.action.isPending}
                      onClick={(e) => {
                        e.stopPropagation()
                        mcp.action.mutate({ serverId: server.id, action: "disconnect" })
                      }}
                    >
                      <UnplugIcon data-icon="inline-start" />
                      断开
                    </Button>
                  ) : (
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={mcp.action.isPending}
                      onClick={(e) => {
                        e.stopPropagation()
                        mcp.action.mutate({ serverId: server.id, action: "connect" })
                      }}
                    >
                      <PlugIcon data-icon="inline-start" />
                      连接
                    </Button>
                  )}
                  <Button
                    size="xs"
                    variant="ghost"
                    className="ml-auto text-destructive"
                    onClick={(e) => {
                      e.stopPropagation()
                      setRemovingId(server.id)
                    }}
                  >
                    <Trash2Icon data-icon="inline-start" />
                    删除
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <AddServerDialog open={addOpen} onOpenChange={setAddOpen} />
      <ServerToolsDialog server={detailServer} onClose={() => setDetailServer(null)} />

      <AlertDialog open={removingId !== null} onOpenChange={(isOpen) => !isOpen && setRemovingId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除 MCP 服务器 {removingId}？</AlertDialogTitle>
            <AlertDialogDescription>
              已连接的服务器会先断开；工具注册随之移除，agent 绑定需要手动调整。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (removingId) mcp.remove.mutate(removingId)
                setRemovingId(null)
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
