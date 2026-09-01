import * as React from "react"
import { ApprovalCard } from "@/components/runs/approval-card"
import { RunStatsLine } from "@/components/runs/task-stats"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  useApprovals,
  useSendFollowup,
  useSubmitTask,
  useTask,
  useTasks,
  useUploadAttachments,
} from "@/hooks/use-console"
import type { Task } from "@/lib/types"
import {
  ArrowUpIcon,
  PaperclipIcon,
  XIcon,
} from "lucide-react"

function Bubble({ role, text }: { role: "user" | "avatar"; text: string }) {
  return (
    <div className={role === "user" ? "flex justify-end" : "flex justify-start"}>
      <div
        data-role={role}
        className="max-w-[85%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap break-words bg-muted text-foreground data-[role=user]:bg-primary data-[role=user]:text-primary-foreground"
      >
        <div className="mb-0.5 text-[0.7rem] opacity-70">{role === "user" ? "你" : "分身"}</div>
        {text}
      </div>
    </div>
  )
}

type PendingFile = { file: File; preview?: string }

function isImage(file: File): boolean {
  return file.type.startsWith("image/")
}

function AttachmentChips({
  files,
  onRemove,
}: {
  files: PendingFile[]
  onRemove: (index: number) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {files.map((item, index) => (
        <div
          key={`${item.file.name}-${index}`}
          className="flex items-center gap-1.5 rounded-lg border bg-muted/40 py-1 pr-1 pl-1.5 text-xs"
        >
          {item.preview ? (
            <img
              src={item.preview}
              alt={item.file.name}
              className="size-6 rounded object-cover"
            />
          ) : (
            <PaperclipIcon className="size-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="max-w-40 truncate text-foreground/80">{item.file.name}</span>
          <button
            type="button"
            aria-label={`移除 ${item.file.name}`}
            onClick={() => onRemove(index)}
            className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <XIcon className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  )
}

function Composer({
  placeholder,
  pending,
  onSubmit,
  children,
}: {
  placeholder: string
  pending: boolean
  onSubmit: (text: string, attachmentPaths: string[]) => void
  children?: React.ReactNode
}) {
  const [text, setText] = React.useState("")
  const [files, setFiles] = React.useState<PendingFile[]>([])
  const [dragging, setDragging] = React.useState(false)
  const inputRef = React.useRef<HTMLInputElement>(null)
  const upload = useUploadAttachments()

  // Revoke object URLs we created for image previews.
  React.useEffect(() => {
    const urls = files.map((f) => f.preview).filter(Boolean) as string[]
    return () => urls.forEach((url) => URL.revokeObjectURL(url))
  }, [files])

  const addFiles = (incoming: File[]) => {
    const next = incoming
      .filter((file) => !files.some((f) => f.file.name === file.name))
      .map((file) => ({
        file,
        preview: isImage(file) ? URL.createObjectURL(file) : undefined,
      }))
    if (next.length) setFiles((prev) => [...prev, ...next])
  }

  const removeFile = (index: number) => {
    setFiles((prev) => {
      const target = prev[index]
      if (target?.preview) URL.revokeObjectURL(target.preview)
      return prev.filter((_, i) => i !== index)
    })
  }

  const submit = async () => {
    const trimmed = text.trim()
    if ((!trimmed && files.length === 0) || pending) return
    setText("")
    const paths = files.length
      ? (await upload.mutateAsync({ files: files.map((f) => f.file) })).map(
          (item) => item.path,
        )
      : []
    // Clean up file state after a successful upload (or a text-only message).
    files.forEach((f) => f.preview && URL.revokeObjectURL(f.preview))
    setFiles([])
    onSubmit(trimmed || "（附件）", paths)
  }

  const hasContent = text.trim().length > 0 || files.length > 0

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        addFiles(Array.from(e.dataTransfer.files ?? []))
      }}
      onPaste={(e) => {
        const pasted = Array.from(e.clipboardData?.files ?? [])
        if (pasted.length) {
          e.preventDefault()
          addFiles(pasted)
        }
      }}
      className={
        "flex flex-col gap-1.5 rounded-xl border bg-card p-2 shadow-sm transition-colors " +
        (dragging ? "border-primary ring-1 ring-primary" : "")
      }
    >
      {children}
      {files.length > 0 && <AttachmentChips files={files} onRemove={removeFile} />}
      <Textarea
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            void submit()
          }
        }}
        placeholder={placeholder}
        className="resize-none border-0 shadow-none focus-visible:ring-0"
      />
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <span className="text-xs text-muted-foreground">
            Enter 发送 · Shift+Enter 换行 · 拖拽/粘贴上传文件
          </span>
          {upload.isPending && <span className="text-xs text-muted-foreground">上传中…</span>}
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={upload.isPending}
            aria-label="添加附件"
            onClick={() => inputRef.current?.click()}
          >
            <PaperclipIcon />
            <span className="sr-only">添加附件</span>
          </Button>
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []))
              e.target.value = ""
            }}
          />
          <Button size="icon-sm" disabled={pending || !hasContent} onClick={() => void submit()}>
            <ArrowUpIcon />
            <span className="sr-only">发送</span>
          </Button>
        </div>
      </div>
    </div>
  )
}

function NewTaskComposer({
  pending,
  onSubmit,
}: {
  pending: boolean
  onSubmit: (text: string, attachmentPaths: string[]) => void
}) {
  return (
    <Composer
      placeholder="给分身派个任务，例如：把画册的冬天板块加两张图…"
      pending={pending}
      onSubmit={onSubmit}
    />
  )
}

function EmptyState({
  onSubmitted,
}: {
  onSubmitted: (task: Task) => void
}) {
  const submit = useSubmitTask()
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <div className="flex size-12 items-center justify-center overflow-hidden rounded-xl bg-muted">
          <img src="/app-icon.png" alt="Agent Console" className="size-full object-cover" />
        </div>
        <h2 className="text-lg font-medium">给分身派个任务</h2>
        <p className="text-sm text-muted-foreground">
          在左侧选择历史任务，可以继续那条对话
        </p>
      </div>
      <div className="w-full max-w-2xl">
        <NewTaskComposer
          pending={submit.isPending}
          onSubmit={(text, attachments) =>
            submit.mutate({ input: text, attachments }, { onSuccess: onSubmitted })
          }
        />
      </div>
    </div>
  )
}

/** One conversation: the active run's header, every turn, and a follow-up box. */
function ChatThread({ task }: { task: Task }) {
  const { data: fresh } = useTask(task.id)
  const current = fresh ?? task
  const approvals = useApprovals()
  const followup = useSendFollowup()

  // Run ids referenced by this conversation (approvals may sit on any of them).
  const runIds = React.useMemo(() => {
    const ids = new Set<string>()
    for (const turn of current.turns) {
      const runId = turn.metadata?.run_id
      if (typeof runId === "string") ids.add(runId)
    }
    if (current.active_run_id) ids.add(current.active_run_id)
    return ids
  }, [current])
  const pendingHere = (approvals.data ?? []).filter((a) => runIds.has(a.run_id))

  const scrollRef = React.useRef<HTMLDivElement>(null)
  const prevTurnsRef = React.useRef(current.turns.length)

  // On conversation switch the thread remounts with scrollTop=0 (top). Pin to
  // the latest message instantly — an animated scrollIntoView here is what
  // caused the old "从头滚到底一次" yank; a silent scrollTop assignment paints
  // once, already at the bottom.
  React.useLayoutEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  // A new turn arriving sticks the view to the bottom so the fresh answer is
  // visible; while reading history (no new turns) the scroll stays put.
  React.useEffect(() => {
    const el = scrollRef.current
    const prev = prevTurnsRef.current
    prevTurnsRef.current = current.turns.length
    if (!el) return
    if (current.turns.length <= prev) return
    el.scrollTop = el.scrollHeight
  }, [current.turns.length])

  return (
    <>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col-reverse gap-3 p-4">
          {/* flex-col-reverse renders DOM order bottom-up: the visual top-down
              order is user → avatar, oldest first. Scroll anchoring is manual
              (see above) so replays during switch don't trigger a full scroll. */}
          {[...current.turns].reverse().map((turn) => (
            <React.Fragment key={turn.id}>
              {turn.role === "assistant" && (
                <div className="flex flex-col gap-0.5">
                  <Bubble role="avatar" text={turn.content} />
                  {typeof turn.metadata?.run_id === "string" && (
                    <RunStatsLine runId={turn.metadata.run_id} />
                  )}
                </div>
              )}
              {turn.role === "user" && <Bubble role="user" text={turn.content} />}
            </React.Fragment>
          ))}
          {!current.turns.length && (
            <p className="text-center text-sm text-muted-foreground">这条对话还没有内容</p>
          )}
        </div>
      </div>
      {pendingHere.length > 0 && (
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-4 pb-2">
          {pendingHere.map((approval) => (
            <ApprovalCard key={approval.id} approval={approval} />
          ))}
        </div>
      )}
      <div className="border-t p-3">
        <div className="mx-auto w-full max-w-3xl">
          <Composer
            placeholder="继续这条对话…（分身带着全部上下文）"
            pending={followup.isPending}
            onSubmit={(text, attachments) =>
              followup.mutate({ taskId: current.id, input: text, attachments })
            }
          />
        </div>
      </div>
    </>
  )
}

export function TasksView({
  selectedId,
  onSelect,
}: {
  selectedId: string | null
  onSelect: (taskId: string | null) => void
}) {
  const tasks = useTasks()
  const taskList = tasks.data ?? []
  const listTask = taskList.find((t) => t.id === selectedId) ?? null

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {listTask ? (
        <ChatThread key={listTask.id} task={listTask} />
      ) : (
        <EmptyState onSubmitted={(task) => onSelect(task.id)} />
      )}
    </div>
  )
}
