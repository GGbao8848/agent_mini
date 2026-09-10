/* 模型编辑 dialog: add or edit one model under a provider — its id, context
   window (used by the context gauge and the summarization trigger) and whether
   it is offered in the chat picker. */
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
import { Switch } from "@/components/ui/switch"
import { useCustomModelManage } from "@/hooks/use-console"
import { Loader2Icon } from "lucide-react"
import type { CustomModel } from "@/lib/types"

export function ModelRowDialog({
  open,
  onOpenChange,
  provider,
  modelId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  provider: CustomModel
  /** Editing this model id; undefined = add a new one. */
  modelId?: string
}) {
  const manage = useCustomModelManage()
  const existing = provider.catalog.find((e) => e.id === modelId)

  const [id, setId] = React.useState(modelId ?? "")
  const [window_, setWindow] = React.useState(
    existing?.context_window != null ? String(existing.context_window) : "",
  )
  const [enabled, setEnabled] = React.useState(existing?.enabled ?? true)

  const canSave = id.trim().length > 0
  const isEdit = Boolean(modelId)

  const save = () => {
    if (!canSave) return
    manage.upsertModel.mutate(
      {
        provider: provider.name,
        modelId: id.trim(),
        context_window: window_.trim() ? Number(window_.trim()) : null,
        enabled,
      },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? `编辑模型 ${modelId}` : "添加模型"}</DialogTitle>
          <DialogDescription>
            供应商 <span className="font-mono">{provider.name}</span> 下的一个模型。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="mr-id">模型 id</Label>
            <Input
              id="mr-id"
              value={id}
              onChange={(e) => setId(e.target.value)}
              placeholder="如 deepseek-v4-flash"
              className="font-mono"
              disabled={isEdit}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="mr-ctx">上下文窗口（tokens，可空）</Label>
            <Input
              id="mr-ctx"
              type="number"
              min={0}
              value={window_}
              onChange={(e) => setWindow(e.target.value)}
              placeholder="如 128000；用于上下文容量显示与摘要触发"
            />
          </div>
          <label className="flex items-center justify-between gap-2">
            <span className="text-sm">在聊天中启用</span>
            <Switch checked={enabled} onCheckedChange={setEnabled} />
          </label>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={save} disabled={!canSave || manage.upsertModel.isPending}>
            {manage.upsertModel.isPending && (
              <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />
            )}
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
