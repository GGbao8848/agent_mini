import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import {
  useModelConfig,
  useUpdateModelConfig,
  useVerifyModel,
} from "@/hooks/use-console"
import type { ProviderKey } from "@/lib/types"
import { CircleCheckIcon, CircleXIcon, KeyRoundIcon, Loader2Icon } from "lucide-react"

function SourceBadge({ source }: { source: "page" | "env" | null }) {
  if (source === "page") return <Badge variant="secondary">页面配置</Badge>
  if (source === "env") return <Badge variant="outline">环境变量</Badge>
  return <Badge variant="outline">未设置</Badge>
}

function KeyRow({
  provider,
  value,
  onChange,
  onClear,
}: {
  provider: ProviderKey
  value: string
  onChange: (value: string) => void
  onClear: () => void
}) {
  const placeholder =
    provider.set ? `已配置（${provider.hint}），留空则保持不变` : "未设置"
  return (
    <div className="grid gap-1.5">
      <div className="flex items-center gap-2">
        <Label htmlFor={`key-${provider.provider}`} className="text-sm font-medium">
          {provider.provider}
        </Label>
        <SourceBadge source={provider.set ? provider.source : null} />
        <span className="ml-auto text-xs text-muted-foreground">
          环境变量：{provider.env_var}
        </span>
      </div>
      <div className="flex gap-2">
        <Input
          id={`key-${provider.provider}`}
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
        />
        {provider.source === "page" && (
          <Button variant="outline" size="sm" onClick={onClear}>
            清除
          </Button>
        )}
      </div>
    </div>
  )
}

export function ModelPanel() {
  const config = useModelConfig()
  const update = useUpdateModelConfig()
  const verify = useVerifyModel()

  const [modelSpec, setModelSpec] = React.useState("")
  const [localBase, setLocalBase] = React.useState("")
  const [keys, setKeys] = React.useState<Record<string, string>>({})

  // Sync the form from the server state whenever a (re)fetch lands.
  React.useEffect(() => {
    if (!config.data) return
    setModelSpec(config.data.model ?? "")
    setLocalBase(config.data.local_base_url ?? "")
    setKeys({})
  }, [config.data])

  const save = () => {
    update.mutate(
      {
        model: modelSpec.trim(),
        local_base_url: localBase.trim(),
        ...(Object.keys(keys).length ? { api_keys: keys } : {}),
      },
      {
        onSuccess: () => {
          setKeys({})
        },
      },
    )
  }

  const clearKey = (provider: string) => {
    update.mutate({ api_keys: { [provider]: "" } })
  }

  const clearLocalBase = () => {
    setLocalBase("")
    update.mutate({ local_base_url: "" })
  }

  const data = config.data

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-sm font-medium text-muted-foreground">模型配置</h2>
        <p className="text-xs text-muted-foreground">
          在这里设置的值优先于 .env / 环境变量，并持久保存，重启后依然生效；
          留空的字段沿用环境变量配置。修改立即对之后的运行生效，无需重启。
        </p>
      </div>

      {config.isLoading || !data ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <>
          <div className="flex flex-col gap-3 rounded-lg border p-4">
            <div className="grid gap-1.5">
              <div className="flex items-center gap-2">
                <Label htmlFor="model-spec" className="text-sm font-medium">
                  默认模型
                </Label>
                <SourceBadge source={data.model ? data.model_source : null} />
              </div>
              <Input
                id="model-spec"
                value={modelSpec}
                onChange={(e) => setModelSpec(e.target.value)}
                placeholder={data.effective_model}
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground">
                格式 <code>provider:model</code>，如 openai:gpt-4o-mini、
                openrouter:deepseek/deepseek-chat、local:qwen3.8-27b。
                当前生效：{data.effective_model}
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-4 rounded-lg border p-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <KeyRoundIcon className="size-4" />
              API 密钥
            </div>
            {data.api_keys.map((provider) => (
              <KeyRow
                key={provider.provider}
                provider={provider}
                value={keys[provider.provider] ?? ""}
                onChange={(value) => setKeys((prev) => ({ ...prev, [provider.provider]: value }))}
                onClear={() => clearKey(provider.provider)}
              />
            ))}
            <p className="text-xs text-muted-foreground">
              密钥保存后不再回显，只显示末几位提示。
            </p>
          </div>

          <div className="flex flex-col gap-3 rounded-lg border p-4">
            <div className="flex items-center gap-2">
              <Label htmlFor="local-base" className="text-sm font-medium">
                本地模型端点（local provider）
              </Label>
              <SourceBadge source={data.local_base_url ? data.local_base_url_source : null} />
            </div>
            <div className="flex gap-2">
              <Input
                id="local-base"
                value={localBase}
                onChange={(e) => setLocalBase(e.target.value)}
                placeholder="http://10.0.0.5:8000/v1"
                className="font-mono"
              />
              {data.local_base_url_source === "page" && (
                <Button variant="outline" size="sm" onClick={clearLocalBase}>
                  清除
                </Button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              任意 OpenAI 兼容的自托管服务（vLLM、llama.cpp server、LMDeploy…）。
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={save} disabled={update.isPending}>
              {update.isPending && <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />}
              保存配置
            </Button>
            <Button
              variant="outline"
              disabled={verify.isPending}
              onClick={() => verify.mutate({ model: modelSpec.trim() || undefined })}
            >
              {verify.isPending
                ? <Loader2Icon className="size-4 animate-spin" data-icon="inline-start" />
                : null}
              测试连接
            </Button>
            {verify.data && !verify.isPending && (
              <span className="flex items-center gap-1.5 text-xs">
                {verify.data.ok ? (
                  <>
                    <CircleCheckIcon className="size-4 text-emerald-600" />
                    连接成功（{verify.data.latency_ms}ms）
                    {verify.data.reply && (
                      <span className="text-muted-foreground">回复：{verify.data.reply}</span>
                    )}
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
          <Separator />
          <p className="text-xs text-muted-foreground">
            优先级：页面配置 → 环境变量 / .env → 内置默认值。
          </p>
        </>
      )}
    </div>
  )
}
