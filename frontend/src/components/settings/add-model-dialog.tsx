/* 添加模型 dialog: register an OpenAI-compatible endpoint, probe its model
   list, and pick which ids to expose as `<name>:<model>` specs. */
import * as React from "react"

import { Badge } from "@/components/ui/badge"
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
import type { CustomModel } from "@/lib/types"
import { CircleCheckIcon, CircleXIcon, Loader2Icon, SearchIcon } from "lucide-react"

const API_FORMATS = [
  { value: "openai", label: "OpenAI 兼容（vLLM / Ollama / OpenRouter…）" },
]

export function AddModelDialog({
  open,
  onOpenChange,
  editing,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** When set, the dialog edits this registration instead of creating one. */
  editing?: CustomModel | null
  onSaved?: (name: string) => void
}) {
  const discover = useDiscoverModels()
  const manage = useCustomModelManage()
  const [name, setName] = React.useState("")
  const [baseUrl, setBaseUrl] = React.useState("")
  const [apiFormat, setApiFormat] = React.useState("openai")
  const [apiKey, setApiKey] = React.useState("")
  const [models, setModels] = React.useState<string[]>([])
  const [selected, setSelected] = React.useState<Set<string>>(new Set())

  // Prefill when editing; reset when opening for a fresh entry.
  React.useEffect(() => {
    if (!open) return
    if (editing) {
      setName(editing.name)
      setBaseUrl(editing.base_url)
      setApiFormat(editing.api_format)
      setApiKey("")
      setModels(editing.models)
      setSelected(new Set(editing.models))
    } else {
      setName("")
      setBaseUrl("")
      setApiFormat("openai")
      setApiKey("")
      setModels([])
      setSelected(new Set())
    }
    discover.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing])

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const probe = () => {
    if (!baseUrl.trim()) return
    discover.mutate(
      { base_url: baseUrl.trim(), api_format: apiFormat, api_key: apiKey.trim() || undefined },
      {
        onSuccess: (data) => {
          if (data.ok) setModels(data.models)
        },
      },
    )
  }

  const save = () => {
    if (!name.trim() || !baseUrl.trim()) return
    manage.upsert.mutate(
      {
        name: name.trim(),
        base_url: baseUrl.trim(),
        api_format: apiFormat,
        api_key: apiKey.trim() || undefined,
        models: [...selected],
      },
      {
        onSuccess: () => {
          onOpenChange(false)
          onSaved?.(name.trim())
        },
      },
    )
  }

  const canSave = name.trim().length > 0 && baseUrl.trim().length > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-4 overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{editing ? `编辑模型 ${editing.name}` : "添加模型"}</DialogTitle>
          <DialogDescription>
            注册一个 OpenAI 兼容端点；填好后点「探测模型列表」，勾选要暴露给分身的模型。
            之后即可用 <code className="font-mono text-xs">名称:模型id</code> 作为模型（如 my-vllm:qwen3-32b）。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="am-name">名称（provider）</Label>
            <Input
              id="am-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如 my-vllm"
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="am-base">Base URL</Label>
            <Input
              id="am-base"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://10.10.10.146:8001/v1"
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
            <Label htmlFor="am-key">API Key（可空：本地端点常无鉴权）</Label>
            <Input
              id="am-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={editing?.key_hint ? `已配置（${editing.key_hint}），留空保持不变` : "sk-…"}
            />
          </div>

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!baseUrl.trim() || discover.isPending}
              onClick={probe}
            >
              {discover.isPending ? (
                <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />
              ) : (
                <SearchIcon data-icon="inline-start" />
              )}
              探测模型列表
            </Button>
            {discover.data && !discover.isPending && (
              <span className="flex items-center gap-1.5 text-xs">
                {discover.data.ok ? (
                  <>
                    <CircleCheckIcon className="size-4 text-emerald-600" />
                    发现 {discover.data.models.length} 个模型
                  </>
                ) : (
                  <>
                    <CircleXIcon className="size-4 text-destructive" />
                    {discover.data.error || "探测失败"}
                  </>
                )}
              </span>
            )}
          </div>

          {models.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <Label>模型列表（勾选要添加的）</Label>
              <div className="flex max-h-56 flex-col gap-1 overflow-y-auto rounded-md border p-2">
                {models.map((id) => (
                  <label
                    key={id}
                    className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm transition-colors hover:bg-accent"
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(id)}
                      onChange={() => toggle(id)}
                      className="size-4 accent-[var(--primary)]"
                    />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs" title={id}>
                      {id}
                    </span>
                    {selected.has(id) && (
                      <Badge variant="secondary" className="shrink-0">
                        名称: {name.trim() || "?"}:{id}
                      </Badge>
                    )}
                  </label>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                已选 {selected.size} / {models.length}
              </p>
            </div>
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
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
