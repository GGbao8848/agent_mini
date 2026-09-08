import * as React from "react"

import { AddModelDialog } from "@/components/settings/add-model-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCustomModelManage, useModelConfig, useUpdateModelConfig, useVerifyModel } from "@/hooks/use-console"
import type { CustomModel } from "@/lib/types"
import { CircleCheckIcon, CircleXIcon, Loader2Icon, PencilIcon, PlusIcon, RotateCcwIcon, Trash2Icon } from "lucide-react"

/** One uniform endpoint card: built-in providers and user-added endpoints
 *  render exactly the same way — name, base URL, model count, edit/reset. */
function EndpointCard({
  endpoint,
  onEdit,
  onRemove,
  removing,
}: {
  endpoint: CustomModel
  onEdit: () => void
  onRemove: () => void
  removing: boolean
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border p-2.5">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span className="truncate font-mono text-sm font-medium">{endpoint.name}</span>
          {endpoint.builtin && (
            <Badge variant="secondary" className="shrink-0">
              内置
            </Badge>
          )}
          <Badge variant="outline" className="shrink-0">
            {endpoint.api_format}
          </Badge>
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
            {endpoint.models.length > 0 ? `${endpoint.models.length} 个模型` : "未选模型"}
          </span>
        </div>
        <span className="truncate font-mono text-xs text-muted-foreground" title={endpoint.base_url}>
          {endpoint.base_url || "（未配置端点地址）"}
        </span>
        <div className="flex items-center gap-2">
          {endpoint.key_hint ? (
            <span className="shrink-0 text-xs text-muted-foreground" title="API Key 已配置（末几位提示）">
              Key ····{endpoint.key_hint}
            </span>
          ) : (
            <span className="shrink-0 text-xs text-muted-foreground/60">无 Key</span>
          )}
          {endpoint.models.length > 0 && (
            <span className="min-w-0 truncate text-xs text-muted-foreground" title={endpoint.models.join(", ")}>
              {endpoint.models.slice(0, 4).join(", ")}
              {endpoint.models.length > 4 ? ` 等` : ""}
            </span>
          )}
        </div>
      </div>
      <Button size="xs" variant="ghost" title="编辑" onClick={onEdit}>
        <PencilIcon />
      </Button>
      <Button
        size="xs"
        variant="ghost"
        className="text-destructive"
        title={endpoint.builtin ? "重置为默认（清除页面覆盖）" : "删除该端点"}
        disabled={removing}
        onClick={onRemove}
      >
        {endpoint.builtin ? <RotateCcwIcon /> : <Trash2Icon />}
      </Button>
    </div>
  )
}

export function ModelPanel() {
  const config = useModelConfig()
  const update = useUpdateModelConfig()
  const verify = useVerifyModel()
  const customManage = useCustomModelManage()

  const [modelSpec, setModelSpec] = React.useState("")
  const [addOpen, setAddOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<CustomModel | null>(null)

  // Sync the form from the server state whenever a (re)fetch lands.
  React.useEffect(() => {
    if (!config.data) return
    setModelSpec(config.data.model ?? "")
  }, [config.data])

  const save = () => {
    update.mutate({ model: modelSpec.trim() })
  }

  const data = config.data
  const endpoints = data?.custom_models ?? []

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-sm font-medium text-muted-foreground">模型配置</h2>
        <p className="text-xs text-muted-foreground">
          所有模型都以「模型端点」形式统一管理：内置 provider 与自行添加的服务同一张卡片格式。
          页面配置优先于环境变量，持久保存，改完即生效。
        </p>
      </div>

      {config.isLoading || !data ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <>
          <div className="flex flex-col gap-3 rounded-lg border p-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  <Label htmlFor="model-spec" className="text-sm font-medium">
                    默认模型
                  </Label>
                  <span className="truncate font-mono text-xs text-muted-foreground">
                    当前生效：{data.effective_model}
                  </span>
                </div>
                <Input
                  id="model-spec"
                  value={modelSpec}
                  onChange={(e) => setModelSpec(e.target.value)}
                  placeholder={data.effective_model}
                  className="font-mono"
                />
                <p className="text-xs text-muted-foreground">
                  格式 <code className="font-mono">名称:模型id</code>，如 openai:gpt-4o-mini、
                  my-vllm:qwen3.8-27b；留空沿用环境变量。
                </p>
              </div>
              <div className="flex items-center gap-2 self-end">
                <Button onClick={save} disabled={update.isPending}>
                  {update.isPending && <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />}
                  保存
                </Button>
                <Button
                  variant="outline"
                  disabled={verify.isPending}
                  onClick={() => verify.mutate({ model: modelSpec.trim() || undefined })}
                >
                  {verify.isPending && <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />}
                  测试连接
                </Button>
              </div>
            </div>
            {verify.data && !verify.isPending && (
              <span className="flex items-center gap-1.5 text-xs">
                {verify.data.ok ? (
                  <>
                    <CircleCheckIcon className="size-4 text-emerald-600" />
                    连接成功（{verify.data.latency_ms}ms）
                    {verify.data.reply && <span className="text-muted-foreground">回复：{verify.data.reply}</span>}
                  </>
                ) : (
                  <>
                    <CircleXIcon className="size-4 text-destructive" />
                    失败：{verify.data.error}
                  </>
                )}
              </span>
            )}
          </div>

          <div className="flex flex-col gap-3 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium">
                模型端点
                <span className="text-xs font-normal text-muted-foreground">
                  内置与自添加统一管理；点「探测模型列表」勾选可用的模型
                </span>
              </div>
              <Button
                size="sm"
                onClick={() => {
                  setEditing(null)
                  setAddOpen(true)
                }}
              >
                <PlusIcon data-icon="inline-start" />
                添加模型
              </Button>
            </div>
            <div className="flex flex-col gap-2">
              {endpoints.map((m) => (
                <EndpointCard
                  key={m.name}
                  endpoint={m}
                  removing={customManage.remove.isPending}
                  onEdit={() => {
                    setEditing(m)
                    setAddOpen(true)
                  }}
                  onRemove={() => customManage.remove.mutate(m.name)}
                />
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              内置端点不可删除，「重置」只清除页面覆盖、回到 .env / 默认值；Key 留空表示沿用环境变量。
            </p>
          </div>
        </>
      )}

      <AddModelDialog open={addOpen} onOpenChange={setAddOpen} editing={editing} />
    </div>
  )
}
