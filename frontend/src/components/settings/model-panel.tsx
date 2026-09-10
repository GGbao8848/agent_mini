/* 模型设置页: a two-pane provider manager.

   Left: the provider list, grouped into 内置供应商 / 自定义供应商, each with a
   status dot; a 添加供应商 button at the bottom.

   Right: the selected provider's detail — name (rename), an 已启用/已禁用 pill
   with an enable/disable toggle, Base URL, API 格式, API Key, and the model
   list where every model row carries its own context-window badge and
   edit/delete actions.

   Everything is driven by the single /v1/model-config payload, which also
   produces `available_models` — the exact list the chat picker offers — so the
   page and the picker can never disagree. */
import * as React from "react"

import { AddProviderDialog } from "@/components/settings/add-provider-dialog"
import { ModelRowDialog } from "@/components/settings/model-row-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useCustomModelManage, useModelConfig } from "@/hooks/use-console"
import type { CustomModel } from "@/lib/types"
import {
  BoxesIcon,
  Loader2Icon,
  PencilIcon,
  PlusIcon,
  SparklesIcon,
  Trash2Icon,
} from "lucide-react"

const API_FORMAT_LABELS: Record<string, string> = {
  openai: "OpenAI 兼容 (chat/completions)",
  responses: "Responses (/responses)",
  anthropic: "Anthropic Messages (/v1/messages)",
}

function fmtWindow(tokens: number | null | undefined): string | null {
  if (!tokens) return null
  if (tokens >= 1_000_000) return `${Math.round(tokens / 100_000) / 10}M`
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}K`
  return String(tokens)
}

/** Provider list row (left pane). */
function ProviderRow({
  provider,
  active,
  onClick,
}: {
  provider: CustomModel
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
        active ? "bg-accent font-medium" : "hover:bg-accent/50"
      }`}
    >
      {provider.builtin ? (
        <SparklesIcon className="size-3.5 shrink-0 text-muted-foreground" />
      ) : (
        <BoxesIcon className="size-3.5 shrink-0 text-muted-foreground" />
      )}
      <span className="min-w-0 flex-1 truncate">{provider.name}</span>
      <span
        className={`size-2 shrink-0 rounded-full ${provider.enabled ? "bg-emerald-500" : "bg-muted-foreground/40"}`}
        title={provider.enabled ? "已启用" : "已禁用"}
      />
    </button>
  )
}

export function ModelPanel() {
  const config = useModelConfig()
  const manage = useCustomModelManage()

  const [selected, setSelected] = React.useState<string | null>(null)
  const [addOpen, setAddOpen] = React.useState(false)
  const [rowDialog, setRowDialog] = React.useState<{ modelId?: string } | null>(null)

  const providers = config.data?.custom_models ?? []

  // Select the first provider once the list arrives (and keep a valid choice).
  React.useEffect(() => {
    if (!providers.length) return
    if (!selected || !providers.some((p) => p.name === selected)) {
      setSelected(providers[0].name)
    }
  }, [providers, selected])

  const current = providers.find((p) => p.name === selected) ?? null
  const builtins = providers.filter((p) => p.builtin)
  const customs = providers.filter((p) => !p.builtin)

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">模型设置</h2>
        <p className="text-xs text-muted-foreground">
          管理自定义模型供应商，配置后可在聊天时选择使用。
        </p>
      </div>

      {config.isLoading || !config.data ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <div className="flex min-h-0 flex-1 gap-0 overflow-hidden rounded-xl border">
          {/* ------------------------------------------------ left: providers */}
          <div className="flex w-60 shrink-0 flex-col border-r bg-muted/20">
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-2">
              {builtins.length > 0 && (
                <div className="flex flex-col gap-0.5">
                  <span className="px-2 py-1 text-xs font-medium text-muted-foreground">内置供应商</span>
                  {builtins.map((p) => (
                    <ProviderRow
                      key={p.name}
                      provider={p}
                      active={p.name === selected}
                      onClick={() => setSelected(p.name)}
                    />
                  ))}
                </div>
              )}
              <div className="flex flex-col gap-0.5">
                <span className="px-2 py-1 text-xs font-medium text-muted-foreground">自定义供应商</span>
                {customs.length === 0 && (
                  <span className="px-2 py-1 text-xs text-muted-foreground/60">暂无</span>
                )}
                {customs.map((p) => (
                  <ProviderRow
                    key={p.name}
                    provider={p}
                    active={p.name === selected}
                    onClick={() => setSelected(p.name)}
                  />
                ))}
              </div>
            </div>
            <div className="border-t p-2">
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-start"
                onClick={() => setAddOpen(true)}
              >
                <PlusIcon data-icon="inline-start" />
                添加供应商
              </Button>
            </div>
          </div>

          {/* ------------------------------------------------ right: detail */}
          <div className="min-w-0 flex-1 overflow-y-auto p-4">
            {current ? (
              <ProviderDetail
                key={current.name}
                provider={current}
                onModelRow={(modelId) => setRowDialog({ modelId })}
              />
            ) : (
              <p className="text-sm text-muted-foreground">从左侧选择一个供应商。</p>
            )}
          </div>
        </div>
      )}

      <AddProviderDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onSaved={(name) => setSelected(name)}
      />
      {current && rowDialog && (
        <ModelRowDialog
          open
          onOpenChange={(open) => !open && setRowDialog(null)}
          provider={current}
          modelId={rowDialog.modelId}
        />
      )}
      {manage.upsert.isPending && (
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Loader2Icon className="size-3 animate-spin" /> 保存中…
        </span>
      )}
    </div>
  )
}

/** The selected provider's configuration form. */
function ProviderDetail({
  provider,
  onModelRow,
}: {
  provider: CustomModel
  onModelRow: (modelId?: string) => void
}) {
  const manage = useCustomModelManage()
  const [baseUrl, setBaseUrl] = React.useState(provider.base_url)
  const [apiFormat, setApiFormat] = React.useState(provider.api_format)
  const [apiKey, setApiKey] = React.useState("")
  const [showKey, setShowKey] = React.useState(false)
  const [renaming, setRenaming] = React.useState(false)
  const [nameDraft, setNameDraft] = React.useState(provider.name)

  const save = () => {
    manage.upsert.mutate({
      name: provider.name,
      base_url: baseUrl.trim(),
      api_format: apiFormat,
      api_key: apiKey.trim() || undefined,
      models: provider.models,
      catalog: provider.catalog.map((e) => ({
        id: e.id,
        context_window: e.context_window ?? null,
        enabled: e.enabled,
      })),
      context_window: provider.context_window ?? null,
      enabled: provider.enabled,
    })
  }

  const toggleEnabled = () =>
    manage.patch.mutate({ name: provider.name, enabled: !provider.enabled })

  const confirmRename = () => {
    const next = nameDraft.trim()
    setRenaming(false)
    if (!next || next === provider.name) return
    manage.patch.mutate({ name: provider.name, newName: next })
  }

  return (
    <div className="flex flex-col gap-4">
      {/* header */}
      <div className="flex items-center gap-2">
        {renaming ? (
          <Input
            autoFocus
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={confirmRename}
            onKeyDown={(e) => e.key === "Enter" && confirmRename()}
            className="h-8 max-w-56 font-mono"
          />
        ) : (
          <>
            <span className="font-mono text-base font-semibold">{provider.name}</span>
            {!provider.builtin && (
              <Button size="icon-xs" variant="ghost" title="重命名" onClick={() => setRenaming(true)}>
                <PencilIcon />
              </Button>
            )}
          </>
        )}
        <span
          className={`ml-1 rounded-full border px-2 py-0.5 text-xs ${
            provider.enabled
              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
              : "border-muted-foreground/30 bg-muted text-muted-foreground"
          }`}
        >
          {provider.enabled ? "已启用" : "已禁用"}
        </span>
        <Button size="xs" variant="outline" onClick={toggleEnabled}>
          {provider.enabled ? "禁用" : "启用"}
        </Button>
        {!provider.builtin && (
          <Button
            size="icon-xs"
            variant="ghost"
            className="ml-auto text-destructive"
            title="删除该供应商"
            onClick={() => manage.remove.mutate(provider.name)}
          >
            <Trash2Icon />
          </Button>
        )}
      </div>

      {/* fields */}
      <div className="grid gap-1.5">
        <Label>Base URL</Label>
        <Input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.example.com/v1"
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
            {Object.entries(API_FORMAT_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-1.5">
        <Label>API Key</Label>
        <div className="flex items-center gap-2">
          <Input
            type={showKey ? "text" : "password"}
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={provider.key_hint ? `已配置（${provider.key_hint}），留空保持不变` : "输入 API Key"}
            className="font-mono"
          />
          <Button size="xs" variant="outline" onClick={() => setShowKey((v) => !v)}>
            {showKey ? "隐藏" : "显示"}
          </Button>
        </div>
      </div>

      {/* model list */}
      <div className="flex flex-col gap-1.5">
        <Label>模型列表</Label>
        <div className="overflow-hidden rounded-lg border">
          {provider.catalog.length === 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">当前没有配置模型。</p>
          )}
          {provider.catalog.map((entry) => (
            <div
              key={entry.id}
              className="flex items-center gap-2 border-b px-3 py-2 last:border-b-0"
            >
              <span
                className={`min-w-0 flex-1 truncate font-mono text-xs ${entry.enabled ? "" : "text-muted-foreground line-through"}`}
                title={entry.id}
              >
                {entry.id}
              </span>
              {fmtWindow(entry.context_window ?? provider.context_window) && (
                <Badge variant="secondary" className="shrink-0">
                  {fmtWindow(entry.context_window ?? provider.context_window)}
                </Badge>
              )}
              <Button
                size="icon-xs"
                variant="ghost"
                title="编辑模型"
                onClick={() => onModelRow(entry.id)}
              >
                <PencilIcon />
              </Button>
              <Button
                size="icon-xs"
                variant="ghost"
                className="text-destructive"
                title="删除模型"
                onClick={() =>
                  manage.removeModel.mutate({ provider: provider.name, modelId: entry.id })
                }
              >
                <Trash2Icon />
              </Button>
            </div>
          ))}
        </div>
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => onModelRow(undefined)}
        >
          <PlusIcon data-icon="inline-start" />
          添加模型
        </Button>
      </div>

      <div className="flex justify-end">
        <Button onClick={save} disabled={manage.upsert.isPending}>
          {manage.upsert.isPending && (
            <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />
          )}
          保存
        </Button>
      </div>
    </div>
  )
}
