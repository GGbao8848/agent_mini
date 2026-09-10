/* One flat model picker for the composer, grouped by provider. The list comes
   from the config's `available_models` — exactly the enabled models of the
   enabled providers — so it can never offer a model the page has switched off.
   Selection persists in localStorage; "默认模型" clears the override. */
import * as React from "react"

import { Button } from "@/components/ui/button"
import { useModelConfig } from "@/hooks/use-console"
import { cn } from "@/lib/utils"
import { CheckIcon, CpuIcon } from "lucide-react"

const MODEL_KEY = "composer_model"

export function getSelectedModel(): string | null {
  return localStorage.getItem(MODEL_KEY) || null
}

export function ModelPicker() {
  const config = useModelConfig()
  const [open, setOpen] = React.useState(false)
  const [selected, setSelected] = React.useState<string | null>(getSelectedModel)
  const rootRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener("mousedown", close)
    return () => window.removeEventListener("mousedown", close)
  }, [open])

  const options = config.data?.available_models ?? []
  const groups = React.useMemo(() => {
    const byProvider = new Map<string, typeof options>()
    for (const option of options) {
      const list = byProvider.get(option.provider) ?? []
      list.push(option)
      byProvider.set(option.provider, list)
    }
    return [...byProvider.entries()]
  }, [options])

  const label = selected ?? "默认模型"

  const choose = (spec: string | null) => {
    setSelected(spec)
    if (spec) localStorage.setItem(MODEL_KEY, spec)
    else localStorage.removeItem(MODEL_KEY)
    setOpen(false)
  }

  return (
    <div ref={rootRef} className="relative">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 gap-1.5 px-2 text-xs text-muted-foreground"
        onClick={() => setOpen((v) => !v)}
        title="选择本次对话使用的模型"
      >
        <CpuIcon className="size-3.5" />
        <span className="max-w-48 truncate">{label}</span>
      </Button>
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 max-h-80 w-80 overflow-y-auto rounded-lg border bg-popover text-popover-foreground shadow-md">
          <button
            type="button"
            onClick={() => choose(null)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent"
          >
            <CheckIcon className={cn("size-4", selected ? "invisible" : "text-primary")} />
            默认模型
            <span className="ml-auto truncate text-xs text-muted-foreground">
              {config.data?.effective_model}
            </span>
          </button>
          {groups.length === 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              还没有可用模型，去「模型设置」添加供应商和模型。
            </p>
          )}
          {groups.map(([provider, models]) => (
            <div key={provider} className="border-t">
              <div className="px-3 pt-2 pb-1 text-xs font-medium text-muted-foreground">
                {provider}
              </div>
              {models.map((option) => (
                <button
                  key={option.spec}
                  type="button"
                  onClick={() => choose(option.spec)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent"
                  title={option.spec}
                >
                  <CheckIcon
                    className={cn("size-4", selected === option.spec ? "text-primary" : "invisible")}
                  />
                  <span className="min-w-0 truncate font-mono text-xs">{option.model}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
