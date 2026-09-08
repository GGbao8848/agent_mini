import * as React from "react"

import { Markdown } from "@/components/chat/markdown"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api, artifactUrl } from "@/lib/api"
import { fmtSize } from "@/lib/format"
import { DownloadIcon, FileIcon, XIcon } from "lucide-react"

export interface PreviewTarget {
  runId: string
  path: string
}

interface PreviewPayload {
  kind: "text" | "image" | "binary"
  media_type: string
  size: number
  path: string
  content?: string
}

const PreviewContext = React.createContext<{
  open: (target: PreviewTarget) => void
  close: () => void
}>({ open: () => {}, close: () => {} })

/** Click-to-preview from anywhere in the chat (artifact rows, images). */
export function usePreview() {
  return React.useContext(PreviewContext)
}

function PreviewBody({ target }: { target: PreviewTarget }) {
  const [payload, setPayload] = React.useState<PreviewPayload | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let alive = true
    setPayload(null)
    setError(null)
    api
      .get<PreviewPayload>(
        `/v1/artifacts/${encodeURIComponent(target.runId)}/preview?path=${encodeURIComponent(target.path)}`,
      )
      .then((data) => alive && setPayload(data))
      .catch((err) => alive && setError(err instanceof Error ? err.message : String(err)))
    return () => {
      alive = false
    }
  }, [target])

  if (error) return <p className="p-3 text-sm text-destructive">{error}</p>
  if (!payload) {
    return (
      <div className="flex flex-col gap-2 p-3">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (payload.kind === "image") {
    return (
      <div className="flex justify-center p-3">
        <img
          src={artifactUrl(target.runId, payload.path)}
          alt={payload.path}
          className="max-h-full max-w-full rounded-lg border object-contain"
        />
      </div>
    )
  }
  if (payload.kind === "text") {
    const isMarkdown = /\.(md|markdown)$/i.test(payload.path)
    return isMarkdown ? (
      <div className="p-3">
        <Markdown text={payload.content ?? ""} />
      </div>
    ) : (
      <pre className="overflow-auto p-3 font-mono text-xs leading-snug whitespace-pre-wrap break-words">
        {payload.content}
      </pre>
    )
  }
  return (
    <div className="flex flex-col items-center gap-3 p-6 text-center text-sm text-muted-foreground">
      <FileIcon className="size-8" />
      <p>该文件类型不支持预览</p>
      <a
        href={artifactUrl(target.runId, payload.path)}
        download
        className={buttonVariants({ variant: "outline", size: "sm" })}
      >
        <DownloadIcon data-icon="inline-start" />
        下载文件（{fmtSize(payload.size)}）
      </a>
    </div>
  )
}

function Panel({ target, onClose }: { target: PreviewTarget; onClose: () => void }) {
  const name = target.path.split("/").slice(-1)[0] || target.path
  return (
    <aside className="flex w-[22rem] shrink-0 flex-col border-l bg-card xl:w-[26rem] animate-fade-slide-up">
      <div className="flex h-14 shrink-0 items-center gap-2 border-b px-3">
        <span className="min-w-0 flex-1 truncate text-sm font-medium" title={target.path}>
          {name}
        </span>
        <a
          href={artifactUrl(target.runId, target.path)}
          download
          title="下载"
          className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
        >
          <DownloadIcon />
        </a>
        <Button variant="ghost" size="icon-sm" onClick={onClose} title="关闭预览">
          <XIcon />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PreviewBody target={target} />
      </div>
    </aside>
  )
}

/** Right-hand preview pane. The pane must sit in the same horizontal flex
 *  row as the app (sidebar + main content): wrapping children in a flex
 *  container keeps the pane out of the document flow, so opening a preview
 *  never pushes the page below the fold. */
export function PreviewProvider({ children }: { children: React.ReactNode }) {
  const [target, setTarget] = React.useState<PreviewTarget | null>(null)
  const value = React.useMemo(
    () => ({
      open: (next: PreviewTarget) =>
        setTarget((prev) =>
          prev && prev.runId === next.runId && prev.path === next.path ? null : next,
        ),
      close: () => setTarget(null),
    }),
    [],
  )
  return (
    <PreviewContext.Provider value={value}>
      <div className="flex h-svh overflow-hidden">
        {children}
        {target && <Panel target={target} onClose={value.close} />}
      </div>
    </PreviewContext.Provider>
  )
}
