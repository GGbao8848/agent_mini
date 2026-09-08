import * as React from "react"

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

/* The pane keeps a fixed width while a preview is open. The user can drag its
 * left border to resize; that width is remembered for next time. */
const WIDTH_KEY = "console:preview-width"
const DEFAULT_WIDTH = 352 // the old w-[22rem]
const MIN_WIDTH = 300
const MAX_WIDTH_RATIO = 0.7

function loadWidth(): number {
  const raw = Number(localStorage.getItem(WIDTH_KEY))
  return Number.isFinite(raw) && raw >= MIN_WIDTH ? raw : DEFAULT_WIDTH
}

/* Open File Viewer ships its own scoped .ofv-* styles; the chat panel behind
 * the divider uses shadcn tokens, so the two don't collide. The styles are
 * imported inside the lazy factory below (with the JS) so the ~130 kB rule
 * sheet isn't part of the first paint. */

/* Rendering everything through Open File Viewer's local parsers means a large
 * file is fully fetched and parsed in the browser — cap that so a stray
 * multi-GB artifact can't freeze the tab; oversized files get the download
 * card instead. */
const MAX_PREVIEW_BYTES = 30 * 1024 * 1024

function downloadHref(target: PreviewTarget): string {
  return artifactUrl(target.runId, target.path)
}

function fileBaseName(path: string): string {
  return path.split("/").slice(-1)[0] || path
}

/* --------------------------------------------------- open-file-viewer */

/* Open File Viewer handles images, text/code/markdown, pdf and Office files
 * (docx/xlsx/pptx) — the whole old preview surface plus what used to be a
 * dead download card. It pulls a large eagerly-parsed bundle, so the whole
 * thing is code-split and only downloads once a preview is actually opened,
 * then stays cached for the session. */
function LazyFileViewer({ target }: { target: PreviewTarget }) {
  const [failed, setFailed] = React.useState(false)
  return (
    <React.Suspense
      fallback={
        <div className="flex flex-col gap-2 p-3">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-40 w-full" />
        </div>
      }
    >
      {failed ? (
        <DownloadCard target={target} />
      ) : (
        <div className="h-full">
          <FileViewerLoaded
            url={downloadHref(target)}
            name={fileBaseName(target.path)}
            onError={() => setFailed(true)}
          />
        </div>
      )}
    </React.Suspense>
  )
}

/** Shown when Open File Viewer reports a format it can't render (or errors
 *  out), and for files over the size cap: the old download card, never a
 *  dead pane. */
function DownloadCard({ target, reason }: { target: PreviewTarget; reason?: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-sm text-muted-foreground">
      <FileIcon className="size-8" />
      <p>{reason ?? "该文件无法在浏览器中预览"}</p>
      <a
        href={downloadHref(target)}
        download
        className={buttonVariants({ variant: "outline", size: "sm" })}
      >
        <DownloadIcon data-icon="inline-start" />
        下载文件
      </a>
    </div>
  )
}

/* React.lazy needs a default-exported component; the factory loads the viewer
 * packages and resolves to one. pdf.worker is emitted as a static asset by
 * Vite's ?url import and referenced from the pdf plugin. */
const FileViewerLoaded = React.lazy(async () => {
  await import("@open-file-viewer/core/style.css")
  const [{ FileViewer }, { imagePlugin, textPlugin, pdfPlugin, officePlugin }, worker] =
    await Promise.all([
      import("@open-file-viewer/react"),
      import("@open-file-viewer/core"),
      import("pdfjs-dist/build/pdf.worker.mjs?url"),
    ])
  const pdfWorkerSrc = worker.default
  const plugins = [
    imagePlugin(),
    textPlugin(),
    pdfPlugin({ workerSrc: pdfWorkerSrc }),
    officePlugin(),
  ]
  return {
    default: function FileViewerLoaded({ url, name, onError }: { url: string; name: string; onError?: () => void }) {
      return (
        <FileViewer
          file={url}
          fileName={name}
          width="100%"
          height="100%"
          fit="contain"
          toolbar
          theme="light"
          plugins={plugins}
          onError={onError}
          onUnsupported={onError}
        />
      )
    },
  }
})

/* ------------------------------------------------------------- preview body */

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

  if (payload.size > MAX_PREVIEW_BYTES) {
    return <DownloadCard target={target} reason={`文件过大（${fmtSize(payload.size)}），请下载后查看`} />
  }

  return <LazyFileViewer target={target} />
}

/* --------------------------------------------------------------- the pane */

function Panel({ target, onClose }: { target: PreviewTarget; onClose: () => void }) {
  const [width, setWidth] = React.useState<number>(loadWidth)
  const widthRef = React.useRef(width)
  const rootRef = React.useRef<HTMLElement>(null)
  const dragRef = React.useRef<{
    startX: number
    startWidth: number
    maxWidth: number
  } | null>(null)
  const name = fileBaseName(target.path)

  const applyWidth = (next: number) => {
    widthRef.current = next
    setWidth(next)
  }

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const root = rootRef.current
    if (!root?.parentElement) return
    const maxWidth = Math.max(MIN_WIDTH, root.parentElement.clientWidth * MAX_WIDTH_RATIO)
    dragRef.current = { startX: e.clientX, startWidth: widthRef.current, maxWidth }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = dragRef.current
    if (!d) return
    const next = Math.min(d.maxWidth, Math.max(MIN_WIDTH, d.startWidth + (d.startX - e.clientX)))
    applyWidth(next)
  }
  const onPointerEnd = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return
    dragRef.current = null
    e.currentTarget.releasePointerCapture(e.pointerId)
    localStorage.setItem(WIDTH_KEY, String(widthRef.current))
  }

  return (
    <aside
      ref={rootRef}
      style={{ width: `${width}px` }}
      className="relative flex shrink-0 flex-col border-l bg-card animate-fade-slide-up"
    >
      {/* Divider between the chat and the preview pane; drag to resize. */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="调整预览面板宽度"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        className="group absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize touch-none"
      >
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-colors group-hover:bg-foreground/40 group-active:bg-foreground/40" />
      </div>
      <div className="flex h-14 shrink-0 items-center gap-2 border-b pl-3 pr-1">
        <span className="min-w-0 flex-1 truncate text-sm font-medium" title={target.path}>
          {name}
        </span>
        <a
          href={downloadHref(target)}
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
      <div className="min-h-0 flex-1 overflow-hidden">
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
