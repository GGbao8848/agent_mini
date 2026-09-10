/* 探测添加 dialog: probe a SAVED provider for the models its endpoint offers,
   check the ones to add, and register them in one go.

   The probe runs server-side (the browser never holds the plaintext key), so
   this only needs the provider name. Models already registered are shown for
   context but cannot be re-added. */
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
import { useAddProviderModels, useDiscoverProviderModels } from "@/hooks/use-console"
import type { CustomModel } from "@/lib/types"
import { CircleCheckIcon, CircleXIcon, Loader2Icon, SearchIcon } from "lucide-react"

export function ProbeModelsDialog({
  open,
  onOpenChange,
  provider,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  provider: CustomModel
}) {
  const probe = useDiscoverProviderModels()
  const addModels = useAddProviderModels()

  const [found, setFound] = React.useState<string[]>([])
  const [selected, setSelected] = React.useState<Set<string>>(new Set())
  const [contextWindow, setContextWindow] = React.useState("")

  const already = new Set(provider.catalog.map((e) => e.id))

  const run = React.useCallback(() => {
    probe.mutate(provider.name, {
      onSuccess: (data) => {
        if (!data.ok) {
          setFound([])
          return
        }
        setFound(data.models)
        // Pre-select everything not already registered.
        setSelected(new Set(data.models.filter((id) => !already.has(id))))
      },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.name])

  // Probe as soon as the dialog opens — that is the whole point of the action.
  React.useEffect(() => {
    if (!open) return
    setFound([])
    setSelected(new Set())
    setContextWindow("")
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const chosen = [...selected]
  const newCount = chosen.filter((id) => !already.has(id)).length

  const save = () => {
    if (newCount === 0) return
    addModels.mutate(
      {
        provider: provider.name,
        models: chosen.filter((id) => !already.has(id)),
        context_window: contextWindow.trim() ? Number(contextWindow.trim()) : null,
      },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-4 overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>探测添加模型</DialogTitle>
          <DialogDescription>
            探测供应商 <span className="font-mono">{provider.name}</span> 的模型列表
            （<span className="font-mono">{provider.base_url}</span>），勾选要添加的模型。
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={probe.isPending} onClick={run}>
            {probe.isPending ? (
              <Loader2Icon className="size-3.5 animate-spin" data-icon="inline-start" />
            ) : (
              <SearchIcon data-icon="inline-start" />
            )}
            重新探测
          </Button>
          {probe.data && !probe.isPending && (
            <span className="flex items-center gap-1.5 text-xs">
              {probe.data.ok ? (
                <>
                  <CircleCheckIcon className="size-3.5 text-emerald-600" />
                  发现 {probe.data.models.length} 个模型
                </>
              ) : (
                <>
                  <CircleXIcon className="size-3.5 text-destructive" />
                  {probe.data.error || "探测失败"}
                </>
              )}
            </span>
          )}
        </div>

        {found.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <div className="flex max-h-64 flex-col gap-1 overflow-y-auto rounded-md border p-2">
              {found.map((id) => {
                const registered = already.has(id)
                return (
                  <label
                    key={id}
                    className={`flex items-center gap-2 rounded px-1.5 py-1 text-sm transition-colors ${
                      registered ? "opacity-60" : "cursor-pointer hover:bg-accent"
                    }`}
                  >
                    <input
                      type="checkbox"
                      disabled={registered}
                      checked={selected.has(id)}
                      onChange={() => toggle(id)}
                      className="size-4 accent-[var(--primary)]"
                    />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs" title={id}>
                      {id}
                    </span>
                    {registered && <span className="shrink-0 text-xs text-muted-foreground">已添加</span>}
                  </label>
                )
              })}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="pm-ctx">新模型的上下文窗口（可空，统一应用）</Label>
              <Input
                id="pm-ctx"
                type="number"
                min={0}
                value={contextWindow}
                onChange={(e) => setContextWindow(e.target.value)}
                placeholder="如 128000；留空则不设置"
              />
            </div>
            <p className="text-xs text-muted-foreground">已选 {newCount} 个待添加。</p>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={save} disabled={newCount === 0 || addModels.isPending}>
            {addModels.isPending && (
              <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />
            )}
            添加所选模型
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
