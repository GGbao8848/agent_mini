/* Two-level model picker for the composer: provider (endpoint) → model.
   Selection persists in localStorage; "default" clears the override. */
import * as React from "react"

import { Button } from "@/components/ui/button"
import { useModelConfig } from "@/hooks/use-console"
import { cn } from "@/lib/utils"
import { CheckIcon, ChevronLeftIcon, ChevronRightIcon, CpuIcon } from "lucide-react"

const MODEL_KEY = "composer_model"

export function getSelectedModel(): string | null {
  return localStorage.getItem(MODEL_KEY) || null
}

export function ModelPicker() {
  const config = useModelConfig()
  const [open, setOpen] = React.useState(false)
  const [pickedProvider, setPickedProvider] = React.useState<string | null>(null)
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

  const endpoints = config.data?.custom_models ?? []
  const provider = endpoints.find((e) => e.name === pickedProvider)
  const label = selected ?? "默认模型"

  const choose = (spec: string | null) => {
    setSelected(spec)
    if (spec) localStorage.setItem(MODEL_KEY, spec)
    else localStorage.removeItem(MODEL_KEY)
    setOpen(false)
    setPickedProvider(null)
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
        <div className="absolute bottom-full left-0 z-50 mb-2 w-72 overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-md">
          {!pickedProvider ? (
            <div className="flex flex-col">
              <button
                type="button"
                onClick={() => choose(null)}
                className="flex items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent"
              >
                <CheckIcon className={cn("size-4", selected ? "invisible" : "text-primary")} />
                默认模型
                <span className="ml-auto truncate text-xs text-muted-foreground">
                  {config.data?.effective_model}
                </span>
              </button>
              <div className="border-t" />
              {endpoints.map((e) => (
                <button
                  key={e.name}
                  type="button"
                  onClick={() => (e.models.length ? setPickedProvider(e.name) : undefined)}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent",
                    !e.models.length && "opacity-50",
                  )}
                  title={e.base_url}
                >
                  {selected?.startsWith(`${e.name}:`) ? (
                    <CheckIcon className="size-4 text-primary" />
                  ) : (
                    <span className="size-4" />
                  )}
                  <span className="font-mono text-xs">{e.name}</span>
                  <span className="ml-auto flex items-center gap-0.5 text-xs text-muted-foreground">
                    {e.models.length ? `${e.models.length}` : "无模型"}
                    {e.models.length > 0 && <ChevronRightIcon className="size-3.5" />}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="flex flex-col">
              <button
                type="button"
                onClick={() => setPickedProvider(null)}
                className="flex items-center gap-1.5 border-b px-3 py-2 text-left text-xs text-muted-foreground hover:bg-accent"
              >
                <ChevronLeftIcon className="size-3.5" />
                {pickedProvider}
              </button>
              {provider?.models.map((m) => {
                const spec = `${pickedProvider}:${m}`
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => choose(spec)}
                    className="flex items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent"
                    title={spec}
                  >
                    <CheckIcon className={cn("size-4", selected === spec ? "text-primary" : "invisible")} />
                    <span className="min-w-0 truncate font-mono text-xs">{m}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
