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
  DialogTrigger,
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useMcpServers, useMcpAction, useTools } from "@/hooks/use-console"
import { normalizeMcpConfig, validateServerPayload } from "@/lib/mcp-config"
import { PlugIcon, UnplugIcon, PlusIcon, Trash2Icon } from "lucide-react"

const JSON_TEMPLATE = `{
  "id": "demo",
  "name": "Demo MCP",
  "transport": "streamable_http",
  "endpoint": "http://127.0.0.1:8931/mcp",
  "description": "通过 JSON 粘贴注册的 MCP 服务器"
}`

function AddServerDialog() {
  const mcp = useMcpAction()
  const [open, setOpen] = React.useState(false)
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
    setOpen(isOpen)
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
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <PlusIcon data-icon="inline-start" />
        添加服务器
      </DialogTrigger>
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

export function McpPanel() {
  const servers = useMcpServers()
  const tools = useTools()
  const mcp = useMcpAction()
  const [removingId, setRemovingId] = React.useState<string | null>(null)

  const serverList = servers.data ?? []
  const toolList = tools.data ?? []

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-sm">MCP 服务器</CardTitle>
        <AddServerDialog />
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {servers.isLoading ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : serverList.length === 0 ? (
          <p className="text-sm text-muted-foreground">（尚未注册任何 MCP 服务器）</p>
        ) : (
          serverList.map((server) => {
            const toolCount = toolList.filter((t) => t.metadata?.mcp_server === server.id).length
            const healthy = server.status === "healthy"
            return (
              <div key={server.id} className="flex flex-col gap-1.5 rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{server.name}</span>
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
                  <span className="ml-auto text-xs text-muted-foreground">{server.transport}</span>
                </div>
                <p className="truncate text-xs text-muted-foreground">
                  {server.endpoint} · {toolCount} 个工具 · id: {server.id}
                </p>
                <div className="flex gap-2">
                  {healthy ? (
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={mcp.action.isPending}
                      onClick={() => mcp.action.mutate({ serverId: server.id, action: "disconnect" })}
                    >
                      <UnplugIcon data-icon="inline-start" />
                      断开
                    </Button>
                  ) : (
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={mcp.action.isPending}
                      onClick={() => mcp.action.mutate({ serverId: server.id, action: "connect" })}
                    >
                      <PlugIcon data-icon="inline-start" />
                      连接
                    </Button>
                  )}
                  <Button
                    size="xs"
                    variant="ghost"
                    className="text-destructive"
                    onClick={() => setRemovingId(server.id)}
                  >
                    <Trash2Icon data-icon="inline-start" />
                    删除
                  </Button>
                </div>
              </div>
            )
          })
        )}
      </CardContent>

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
    </Card>
  )
}
