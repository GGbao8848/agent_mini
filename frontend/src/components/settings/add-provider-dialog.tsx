/* 添加模型供应商 dialog: name + base URL + API key + API format, and an inline
   model list you can grow with 添加模型. Mirrors the reference flow: the primary
   action stays disabled until at least one model exists. */
import * as React from "react"

import { Button } from "@/components/ui/button"
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
import { useCustomModelManage, useDiscoverModels } from "@/hooks/use-console"
import { CircleCheckIcon, CircleXIcon, Loader2Icon, PlusIcon, SearchIcon, Trash2Icon } from "lucide-react"

const API_FORMATS = [
  { value: "openai", label: "OpenAI 兼容 (chat/completions)" },
  { value: "responses", label: "Responses (/responses)" },
  { value: "anthropic", label: "Anthropic Messages (/v1/messages)" },
]

type DraftModel = { id: string; context_window: number | null }

export function AddProviderDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved?: (name: string) => void
}) {
  const discover = useDiscoverModels()
  const manage = useCustomModelManage()

  const [name, setName] = React.useState("")
  const [baseUrl, setBaseUrl] = React.useState("")
  const [apiKey, setApiKey] = React.useState("")
  const [apiFormat, setApiFormat] = React.useState("openai")
  const [models, setModels] = React.useState<DraftModel[]>([])

  React.useEffect(() => {
    if (!open) return
    setName("")
    setBaseUrl("")
    setApiKey("")
    setApiFormat("openai")
    setModels([])
    discover.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const addModel = () => setModels((prev) => [...prev, { id: "", context_window: null }])
  const setModelAt = (index: number, patch: Partial<DraftModel>) =>
    setModels((prev) => prev.map((m, i) => (i === index ? { ...m, ...patch } : m)))

  const probe = () => {
    if (!baseUrl.trim()) return
    discover.mutate(
      { base_url: baseUrl.trim(), api_format: apiFormat, api_key: apiKey.trim() || undefined },
      {
        onSuccess: (data) => {
          if (!data.ok) return
          // Fill empty rows first, then append the rest.
          setModels((prev) => {
            const next = [...prev]
            const empty = next.findIndex((m) => !m.id.trim())
            if (empty >= 0) next[empty] = { ...next[empty], id: data.models[0] ?? "" }
            for (const id of data.models.slice(empty >= 0 ? 1 : 0)) {
              if (!next.some((m) => m.id === id)) next.push({ id, context_window: null })
            }
            return next
          })
        },
      },
    )
  }

  const named = models.filter((m) => m.id.trim())
  const canSave = name.trim().length > 0 && baseUrl.trim().length > 0 && named.length > 0

  const save = () => {
    if (!canSave) return
    manage.upsert.mutate(
      {
        name: name.trim(),
        base_url: baseUrl.trim(),
        api_format: apiFormat,
        api_key: apiKey.trim() || undefined,
        models: named.map((m) => m.id.trim()),
        catalog: named.map((m) => ({
          id: m.id.trim(),
          context_window: m.context_window,
          enabled: true,
        })),
      },
      {
        onSuccess: () => {
          onOpenChange(false)
          onSaved?.(name.trim())
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-4 overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>添加模型供应商</DialogTitle>
          <DialogDescription>配置一个完全自定义的 API 端点和初始模型。</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="pv-name">名称</Label>
            <Input
              id="pv-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如: 智谱 GLM"
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="pv-base">Base URL</Label>
            <Input
              id="pv-base"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="pv-key">API Key</Label>
            <Input
              id="pv-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="输入 API Key"
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label>API 格式</Label>
            <Select value={apiFormat} onValueChange={(v) => setApiFormat(v ?? "openai")}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {API_FORMATS.map((f) => (
                  <SelectItem key={f.value} value={f.value}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <Label>模型列表</Label>
              <Button
                type="button"
                variant="outline"
                size="xs"
                disabled={!baseUrl.trim() || discover.isPending}
                onClick={probe}
              >
                {discover.isPending ? (
                  <Loader2Icon className="size-3.5 animate-spin" data-icon="inline-start" />
                ) : (
                  <SearchIcon data-icon="inline-start" />
                )}
                探测模型
              </Button>
            </div>

            {discover.data && !discover.isPending && (
              <span className="flex items-center gap-1.5 text-xs">
                {discover.data.ok ? (
                  <>
                    <CircleCheckIcon className="size-3.5 text-emerald-600" />
                    发现 {discover.data.models.length} 个模型
                  </>
                ) : (
                  <>
                    <CircleXIcon className="size-3.5 text-destructive" />
                    {discover.data.error || "探测失败"}
                  </>
                )}
              </span>
            )}

            {models.length === 0 ? (
              <div className="rounded-lg border border-dashed px-3 py-3 text-xs text-muted-foreground">
                当前没有配置模型，添加模型后可在聊天中使用。
              </div>
            ) : (
              <div className="flex flex-col gap-2 rounded-lg border p-2">
                {models.map((m, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input
                      value={m.id}
                      onChange={(e) => setModelAt(i, { id: e.target.value })}
                      placeholder="模型 id，如 glm-4-plus"
                      className="h-8 min-w-0 flex-1 font-mono text-xs"
                    />
                    <Input
                      type="number"
                      min={0}
                      value={m.context_window ?? ""}
                      onChange={(e) =>
                        setModelAt(i, {
                          context_window: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                      placeholder="窗口"
                      className="h-8 w-24 text-xs"
                    />
                    <Button
                      type="button"
                      size="icon-xs"
                      variant="ghost"
                      className="text-destructive"
                      onClick={() => setModels((prev) => prev.filter((_, j) => j !== i))}
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                ))}
              </div>
            )}
            <Button type="button" variant="outline" size="sm" className="self-start" onClick={addModel}>
              <PlusIcon data-icon="inline-start" />
              添加模型
            </Button>
          </div>

          {!canSave && (
            <p className="text-xs text-muted-foreground">
              添加供应商前，请至少添加一个模型。
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={save} disabled={!canSave || manage.upsert.isPending}>
            {manage.upsert.isPending && (
              <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />
            )}
            添加供应商
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
