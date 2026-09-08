import * as React from "react"
import { Markdown } from "@/components/chat/markdown"
import { ApprovalCard } from "@/components/runs/approval-card"
import { RunActivity, RunArtifacts } from "@/components/runs/run-activity"
import { RunStatsLine } from "@/components/runs/task-stats"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  useApprovals,
  useCancelTask,
  useMarkTaskRead,
  useProjects,
  useRun,
  useSendFollowup,
  useSubmitTask,
  useTask,
  useTaskArtifacts,
  useTaskEvents,
  useTasks,
  useUploadAttachments,
} from "@/hooks/use-console"
import { TERMINAL_RUN_STATUSES, type Artifact, type RunEvent, type Task } from "@/lib/types"
import { cn } from "@/lib/utils"
import {
  ArrowUpIcon,
  CircleStopIcon,
  FolderIcon,
  PaperclipIcon,
  XIcon,
} from "lucide-react"

function Bubble({ role, text }: { role: "user" | "avatar"; text: string }) {
  const isUser = role === "user"
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        data-role={role}
        className={cn(
          "max-w-[85%] rounded-xl px-3 py-2 text-sm break-words bg-muted text-foreground data-[role=user]:bg-primary data-[role=user]:text-primary-foreground",
          isUser && "whitespace-pre-wrap",
        )}
      >
        {isUser ? text : <Markdown text={text} />}
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
  running,
  onStop,
  children,
}: {
  placeholder: string
  pending: boolean
  onSubmit: (text: string, attachmentPaths: string[]) => void
  /** The agent is replying: the send slot turns into a stop button. */
  running?: boolean
  onStop?: () => void
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
          <Button
            size="icon-sm"
            variant={running ? "destructive" : "default"}
            disabled={!running && (pending || !hasContent)}
            onClick={() => {
              if (running) onStop?.()
              else void submit()
            }}
            title={running ? "停止运行" : "发送"}
          >
            {running ? <CircleStopIcon /> : <ArrowUpIcon />}
            <span className="sr-only">{running ? "停止" : "发送"}</span>
          </Button>
        </div>
      </div>
    </div>
  )
}

function NewTaskComposer({
  pending,
  onSubmit,
  initialProjectId,
}: {
  pending: boolean
  onSubmit: (text: string, attachmentPaths: string[], projectId: string | null) => void
  initialProjectId?: string | null
}) {
  const projects = useProjects()
  const [projectId, setProjectId] = React.useState<string | null>(initialProjectId ?? null)
  // The sidebar's project-row "+" updates the preset while the composer is
  // already mounted — follow it (the user can still change the select).
  React.useEffect(() => {
    setProjectId(initialProjectId ?? null)
  }, [initialProjectId])
  return (
    <Composer
      placeholder="给分身派个任务，例如：把画册的冬天板块加两张图…"
      pending={pending}
      onSubmit={(text, paths) => onSubmit(text, paths, projectId)}
    >
      {(projects.data?.length ?? 0) > 0 && (
        <div className="flex items-center gap-2 px-1 pt-1">
          <FolderIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <Select
            value={projectId ?? "none"}
            onValueChange={(value) => setProjectId(value === "none" ? null : value)}
          >
            <SelectTrigger className="h-7 w-auto gap-1 border-0 bg-muted px-2 text-xs shadow-none">
              <SelectValue>
                {(() => {
                  const selected = projects.data?.find((p) => p.id === projectId)
                  return selected ? selected.name : "无项目（产物放任务目录）"
                })()}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none" className="text-xs">
                无项目（产物放任务目录）
              </SelectItem>
              {projects.data!.map((project) => (
                <SelectItem key={project.id} value={project.id} className="text-xs">
                  {project.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
    </Composer>
  )
}

function EmptyState({
  onSubmitted,
  presetProjectId,
}: {
  onSubmitted: (task: Task) => void
  presetProjectId: string | null
}) {
  const submit = useSubmitTask()
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <div className="flex size-12 items-center justify-center overflow-hidden rounded-xl bg-muted">
          <img
            src="./app-icon.png?v=2"
            alt="Agent Console"
            className="size-full object-contain p-0.5"
            draggable={false}
          />
        </div>
        <h2 className="text-lg font-medium">给分身派个任务</h2>
        <p className="text-sm text-muted-foreground">
          在左侧选择历史任务，可以继续那条对话
        </p>
      </div>
      <div className="w-full max-w-2xl">
        <NewTaskComposer
          pending={submit.isPending}
          initialProjectId={presetProjectId}
          onSubmit={(text, attachments, projectId) =>
            submit.mutate(
              { input: text, attachments, project_id: projectId },
              { onSuccess: onSubmitted },
            )
          }
        />
      </div>
    </div>
  )
}

/** One conversation: every turn (bubble + live activity + artifacts) and a
 *  follow-up box. The old "运行详情" drawer is gone — the run's event stream,
 *  collapsible steps and deliverables all live here in the thread. */
function ChatThread({ task }: { task: Task }) {
  const { data: fresh } = useTask(task.id)
  const current = fresh ?? task
  const approvals = useApprovals()
  const followup = useSendFollowup()
  const cancel = useCancelTask()
  const events = useTaskEvents(task.id)
  const taskArtifacts = useTaskArtifacts(task.id)
  const [confirmStop, setConfirmStop] = React.useState(false)

  // Group the conversation-wide feeds by the run that produced them, so each
  // assistant turn shows exactly its own activity and deliverables.
  const eventsByRun = React.useMemo(() => {
    const map = new Map<string, RunEvent[]>()
    for (const event of events) {
      if (!event.run_id) continue
      if (!map.has(event.run_id)) map.set(event.run_id, [])
      map.get(event.run_id)!.push(event)
    }
    return map
  }, [events])
  const artifactsByRun = React.useMemo(() => {
    const map = new Map<string, Artifact[]>()
    for (const artifact of taskArtifacts.data ?? []) {
      const runId = artifact.run_id ?? ""
      if (!map.has(runId)) map.set(runId, [])
      map.get(runId)!.push(artifact)
    }
    return map
  }, [taskArtifacts.data])

  // Failed/cancelled runs have no assistant turn — surface their error inline
  // next to the user message that started them, instead of only in the header.
  const failedRunErrors = React.useMemo(() => {
    const map = new Map<string, string>()
    for (const event of events) {
      if (
        (event.event_type === "run_failed" || event.event_type === "run_cancelled") &&
        event.run_id &&
        event.error
      ) {
        map.set(event.run_id, event.error)
      }
    }
    return map
  }, [events])

  const activeRunId = current.active_run_id ?? null
  const running =
    activeRunId != null && !TERMINAL_RUN_STATUSES.has(current.status)
  const { data: activeRun } = useRun(activeRunId)

  // Run ids referenced by this conversation (approvals may sit on any of them).
  const runIds = React.useMemo(() => {
    const ids = new Set<string>()
    for (const turn of current.turns) {
      const runId = turn.metadata?.run_id
      if (typeof runId === "string") ids.add(runId)
    }
    if (activeRunId) ids.add(activeRunId)
    return ids
  }, [current, activeRunId])
  const pendingHere = (approvals.data ?? []).filter((a) => runIds.has(a.run_id))

  const scrollRef = React.useRef<HTMLDivElement>(null)
  const prevTurnsRef = React.useRef(current.turns.length)
  const prevEventsRef = React.useRef(events.length)

  // On conversation switch the thread remounts with scrollTop=0 (top). Pin to
  // the latest message instantly — an animated scrollIntoView here is what
  // caused the old "从头滚到底一次" yank; a silent scrollTop assignment paints
  // once, already at the bottom.
  React.useLayoutEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  // A new turn — or new live events while a run streams — sticks the view to
  // the bottom; while reading history the scroll stays put.
  React.useEffect(() => {
    const el = scrollRef.current
    const prevTurns = prevTurnsRef.current
    const prevEvents = prevEventsRef.current
    prevTurnsRef.current = current.turns.length
    prevEventsRef.current = events.length
    if (!el) return
    if (current.turns.length <= prevTurns && events.length <= prevEvents) return
    el.scrollTop = el.scrollHeight
  }, [current.turns.length, events.length])

  return (
    <>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col-reverse gap-3 p-4">
          {/* flex-col-reverse renders DOM order bottom-up: the FIRST DOM child
              is visually at the BOTTOM, so the in-flight reply bubble leads the
              DOM and lands right under the conversation, where the answer will
              appear. Newest turn is also first in DOM (bottom of the history).
              Scroll anchoring is manual (see above) so replays during switch
              don't trigger a full scroll. */}
          {running && activeRunId && (
            <div className="animate-fade-slide-up">
              <RunActivity
                events={eventsByRun.get(activeRunId) ?? []}
                running
                startedAt={activeRun?.created_at ?? null}
              />
            </div>
          )}
          {[...current.turns].reverse().map((turn) => {
            const runId = typeof turn.metadata?.run_id === "string" ? turn.metadata.run_id : null
            const failedError = runId ? failedRunErrors.get(runId) : undefined
            const hasAssistantReply = current.turns.some(
              (t) =>
                t.role === "assistant" &&
                typeof t.metadata?.run_id === "string" &&
                t.metadata.run_id === runId,
            )
            return (
              <React.Fragment key={turn.id}>
                {turn.role === "assistant" && (
                  <div className="flex flex-col gap-1.5">
                    {runId && (
                      <RunActivity
                        events={eventsByRun.get(runId) ?? []}
                        running={running && runId === activeRunId}
                      />
                    )}
                    <Bubble role="avatar" text={turn.content} />
                    {runId && (
                      <RunArtifacts
                        runId={runId}
                        artifacts={artifactsByRun.get(runId) ?? []}
                      />
                    )}
                    {runId && <RunStatsLine runId={runId} />}
                  </div>
                )}
                {turn.role === "user" && (
                  <div className="flex flex-col gap-1">
                    <Bubble role="user" text={turn.content} />
                    {/* A run that ended without answering (cancelled or failed
                        mid-flight) has no assistant turn to hang its work on —
                        keep its activity and any products visible here as a
                        settled block. The still-running case is already shown
                        in the header strip above the thread. */}
                    {runId && !hasAssistantReply && !(running && runId === activeRunId) && (
                      <div className="max-w-[85%]">
                        <RunActivity
                          events={eventsByRun.get(runId) ?? []}
                          running={false}
                        />
                        <RunArtifacts
                          runId={runId}
                          artifacts={artifactsByRun.get(runId) ?? []}
                        />
                      </div>
                    )}
                    {failedError && !hasAssistantReply && (
                      <p
                        className="max-w-[85%] px-1 text-xs text-destructive"
                        title={failedError}
                      >
                        运行失败：{failedError.length > 200 ? `${failedError.slice(0, 200)}…` : failedError}
                      </p>
                    )}
                  </div>
                )}
              </React.Fragment>
            )
          })}
          {!current.turns.length && !running && (
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
            running={running}
            onStop={() => setConfirmStop(true)}
            onSubmit={(text, attachments) =>
              followup.mutate({ taskId: current.id, input: text, attachments })
            }
          />
        </div>
      </div>

      <AlertDialog open={confirmStop} onOpenChange={(open) => !open && setConfirmStop(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>停止任务？</AlertDialogTitle>
            <AlertDialogDescription>
              将中断当前运行，已生成的产物会保留。停止后可在对话里继续下达指令。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              disabled={cancel.isPending}
              onClick={() => {
                cancel.mutate({ taskId: current.id })
                setConfirmStop(false)
              }}
            >
              停止
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

export function TasksView({
  selectedId,
  onSelect,
  presetProjectId,
  onConsumePreset,
}: {
  selectedId: string | null
  onSelect: (taskId: string | null) => void
  presetProjectId?: string | null
  onConsumePreset?: () => void
}) {
  const tasks = useTasks()
  const markRead = useMarkTaskRead()
  const markReadMutate = markRead.mutate
  const taskList = tasks.data ?? []
  const listTask = taskList.find((t) => t.id === selectedId) ?? null

  // Opening a conversation consumes its unread state (green sidebar dot), and
  // follow-up replies while it stays open are read as they land.
  React.useEffect(() => {
    if (listTask?.has_unread) markReadMutate(listTask.id)
  }, [listTask?.id, listTask?.has_unread, markReadMutate])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {listTask ? (
        <ChatThread key={listTask.id} task={listTask} />
      ) : (
        <EmptyState
          presetProjectId={presetProjectId ?? null}
          onSubmitted={(task) => {
            onConsumePreset?.()
            onSelect(task.id)
          }}
        />
      )}
    </div>
  )
}
