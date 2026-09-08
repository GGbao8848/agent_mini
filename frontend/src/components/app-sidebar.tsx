"use client"

import * as React from "react"

import { NavMain } from "@/components/nav-main"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { ScheduleDetailDialog } from "@/components/schedules/schedule-detail-dialog"
import { ScheduleToggle } from "@/components/schedules/schedule-toggle"
import {
  useBrowseDir,
  useDeleteTask,
  useProjectManage,
  useProjects,
  useScheduleManage,
  useSchedules,
  useTasks,
  useUpdateTask,
} from "@/hooks/use-console"
import { fmtTimeShort } from "@/lib/format"
import { excerpt, isTerminalTask } from "@/lib/tasks"
import { cn } from "@/lib/utils"
import type { Schedule, Task } from "@/lib/types"
import {
  CalendarClockIcon,
  ChevronRightIcon,
  CopyIcon,
  FolderIcon,
  FolderOpenIcon,
  FolderPlusIcon,
  Loader2Icon,
  PencilIcon,
  PinIcon,
  PlugIcon,
  PlusIcon,
  PuzzleIcon,
  SettingsIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"

const data = {
  brand: {
    name: "Agent Console",
    plan: "Agent Core",
  },
  navMain: [
    { title: "新建任务", url: "#", icon: <PlusIcon /> },
    { title: "技能", url: "#", icon: <PuzzleIcon /> },
    { title: "MCP", url: "#", icon: <PlugIcon /> },
    { title: "工具", url: "#", icon: <WrenchIcon /> },
    { title: "模型配置", url: "#", icon: <SettingsIcon /> },
  ],
}

const RUNNING_STATUSES = new Set(["running", "planning", "created"])
const ATTENTION_STATUSES = new Set(["waiting_approval", "needs_input"])

/** Row status affordance: a live spinner while a run is actually attached, an
 *  amber dot when the human's input is needed (approval / question), a green
 *  unread dot for new replies, nothing otherwise. A stale "created" status
 *  without an active run is NOT running — it must not spin forever. */
function RowIndicator({ task }: { task: Task }) {
  const running = RUNNING_STATUSES.has(task.status) && !!task.active_run_id
  if (running) {
    return <Loader2Icon className="size-3.5 shrink-0 animate-spin text-blue-500" />
  }
  if (ATTENTION_STATUSES.has(task.status)) {
    return <span className="size-2 shrink-0 rounded-full bg-amber-500" />
  }
  if (task.has_unread) {
    return <span className="size-2 shrink-0 rounded-full bg-emerald-500" />
  }
  return null
}

function TaskRow({
  task,
  selectedTaskId,
  onSelectTask,
  onContextMenu,
  inset,
}: {
  task: Task
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
  onContextMenu: (e: React.MouseEvent, task: Task) => void
  /** Nesting level: under a project row, or one level deeper under a
   *  schedule group inside the 日程任务 bar (must out-dent its header). */
  inset?: "project" | "schedule"
}) {
  return (
    <SidebarMenuItem className={cn(inset === "project" && "pl-4", inset === "schedule" && "pl-9")}>
      <SidebarMenuButton
        isActive={task.id === selectedTaskId}
        onClick={() => onSelectTask(task.id)}
        onContextMenu={(e: React.MouseEvent) => onContextMenu(e, task)}
        className="gap-2 py-1.5"
        title={excerpt(task, 160)}
      >
        <RowIndicator task={task} />
        <span className="min-w-0 flex-1 truncate text-xs">{excerpt(task, 60)}</span>
        <span className="shrink-0 text-[0.65rem] tabular-nums text-muted-foreground">
          {fmtTimeShort(task.created_at)}
        </span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

/** The task/workspace section of the sidebar. Two flat modes:
 *  - "任务": every conversation, newest first (pinned on top).
 *  - "项目": host-folder projects; each row expands to its conversations,
 *    indented underneath it (outline style). */
function WorkspaceSection({
  selectedTaskId,
  onSelectTask,
  onNewTaskInProject,
  onViewChange,
}: {
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
  onNewTaskInProject: (projectId: string) => void
  onViewChange: (view: string) => void
}) {
  const tasks = useTasks()
  const schedules = useSchedules()
  const projects = useProjects()
  const manage = useProjectManage()
  const scheduleManage = useScheduleManage()

  const toggleScheduleEnabled = (schedule: Schedule, enabled: boolean) => {
    scheduleManage.update.mutate({
      scheduleId: schedule.id,
      payload: {
        name: schedule.name,
        task_input: schedule.task_input,
        schedule_type: schedule.schedule_type,
        run_at: schedule.run_at,
        cron_expr: schedule.cron_expr,
        interval_minutes: schedule.interval_minutes,
        enabled,
        model: schedule.model,
      },
    })
  }
  const updateTask = useUpdateTask()
  const deleteTask = useDeleteTask()
  const projectList = projects.data ?? []

  const [mode, setMode] = React.useState<"chats" | "schedules" | "projects">("chats")
  const [menu, setMenu] = React.useState<{ x: number; y: number; task: Task } | null>(null)
  const [renaming, setRenaming] = React.useState<Task | null>(null)
  const [renameValue, setRenameValue] = React.useState("")
  const [removing, setRemoving] = React.useState<Task | null>(null)
  const [removingProject, setRemovingProject] = React.useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = React.useState(false)
  // Collapsed projects: null = none collapsed (all open), otherwise the set.
  // Unrecorded ids default to open, so brand-new projects show expanded.
  const [collapsed, setCollapsed] = React.useState<Set<string> | null>(null)
  // Schedule-run bar at the bottom of the task list: collapsed by default
  // (automated runs are reference material, not the primary focus), with a
  // per-schedule second level inside.
  const [scheduleBarOpen, setScheduleBarOpen] = React.useState(false)
  const [openScheduleGroups, setOpenScheduleGroups] = React.useState<Set<string> | null>(null)
  const [scheduleDetail, setScheduleDetail] = React.useState<Schedule | null>(null)

  // Newest first; pinned conversations float to the top. Memoized on the raw
  // query data so the stable sort/map don't rebuild on every render.
  const sortedTasks = React.useMemo(
    () =>
      [...(tasks.data ?? [])].sort(
        (a, b) =>
          Number(b.pinned) - Number(a.pinned) ||
          b.created_at.localeCompare(a.created_at),
      ),
    [tasks.data],
  )

  const tasksByProject = React.useMemo(() => {
    const map = new Map<string | null, Task[]>()
    for (const task of sortedTasks) {
      const key = task.project_id ?? null
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(task)
    }
    return map
  }, [sortedTasks])

  // Schedule-triggered runs, grouped by their source schedule name.
  const manualTasks = React.useMemo(
    () => sortedTasks.filter((t) => !t.metadata?.source_schedule_id),
    [sortedTasks],
  )
  const scheduleGroups = React.useMemo(() => {
    const map = new Map<string, Task[]>()
    for (const task of sortedTasks) {
      const name = task.metadata?.source_schedule_name
      if (typeof name !== "string" || !task.metadata?.source_schedule_id) continue
      if (!map.has(name)) map.set(name, [])
      map.get(name)!.push(task)
    }
    return [...map.entries()]
  }, [sortedTasks])
  const scheduleRunCount = React.useMemo(
    () => scheduleGroups.reduce((n, [, list]) => n + list.length, 0),
    [scheduleGroups],
  )

  const isOpen = (projectId: string) => collapsed === null || !collapsed.has(projectId)

  const toggleProject = (projectId: string) => {
    setCollapsed((prev) => {
      const base = prev === null ? new Set<string>() : new Set(prev)
      if (base.has(projectId)) base.delete(projectId)
      else base.add(projectId)
      return base
    })
  }

  // Right-click context menu: copy id / rename / pin / delete.
  React.useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener("click", close)
    window.addEventListener("contextmenu", close)
    return () => {
      window.removeEventListener("click", close)
      window.removeEventListener("contextmenu", close)
    }
  }, [menu])

  const copyId = async (task: Task) => {
    try {
      await navigator.clipboard.writeText(task.id)
    } catch {
      // clipboard may be unavailable; ignore
    }
    setMenu(null)
  }

  const projectTasks = (projectId: string) => tasksByProject.get(projectId) ?? []

  const openProjectMenu = (e: React.MouseEvent, task: Task) => {
    e.preventDefault()
    e.stopPropagation()
    setMenu({ x: e.clientX, y: e.clientY, task })
  }

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      {/* Mode switch: 任务 / 项目 */}
      <SidebarGroupLabel
        render={
          <div className="flex items-center gap-1">
            <div className="flex flex-1 items-center gap-0.5 rounded-md bg-sidebar-accent/60 p-0.5">
              {(
                [
                  { value: "chats", label: "对话" },
                  { value: "schedules", label: "日程" },
                  { value: "projects", label: "项目" },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => setMode(tab.value)}
                  className={cn(
                    "flex-1 rounded px-1 py-0.5 text-xs font-medium transition-colors",
                    mode === tab.value
                      ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-sm"
                      : "text-muted-foreground hover:text-sidebar-accent-foreground",
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            {mode === "projects" && (
              <button
                type="button"
                title="添加工作文件夹"
                onClick={() => setPickerOpen(true)}
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
              >
                <FolderPlusIcon className="size-3.5" />
              </button>
            )}
            {mode === "schedules" && (
              <button
                type="button"
                title="描述并新建日程"
                onClick={() => onViewChange("日程")}
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
              >
                <PlusIcon className="size-3.5" />
              </button>
            )}
          </div>
        }
      />

      <SidebarGroupContent>
        <SidebarMenu>
          {/* -------- CHATS mode: flat list -------- */}
          {mode === "chats" && (
            <>
              {tasks.isLoading &&
                Array.from({ length: 3 }).map((_, i) => (
                  <SidebarMenuItem key={i}>
                    <Skeleton className="h-7 w-full" />
                  </SidebarMenuItem>
                ))}
              {!tasks.isLoading && sortedTasks.length === 0 && (
                <SidebarMenuItem>
                  <p className="px-2 py-1 text-xs text-muted-foreground">
                    还没有任务，派一个吧
                  </p>
                </SidebarMenuItem>
              )}
              {manualTasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  selectedTaskId={selectedTaskId}
                  onSelectTask={onSelectTask}
                  onContextMenu={openProjectMenu}
                />
              ))}

              {/* Schedule-fired runs live under one collapsible bar at the
                  bottom, grouped per schedule (second collapse level). */}
              {scheduleRunCount > 0 && (
                <>
                  <SidebarMenuItem>
                    <div
                      role="button"
                      tabIndex={0}
                      aria-expanded={scheduleBarOpen}
                      onClick={() => setScheduleBarOpen((v) => !v)}
                      onKeyDown={(e) => {
                        if (e.target !== e.currentTarget) return
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault()
                          setScheduleBarOpen((v) => !v)
                        }
                      }}
                      className="flex w-full cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm outline-none transition-colors hover:bg-sidebar-accent focus-visible:ring-2"
                    >
                      <ChevronRightIcon
                        className={cn(
                          "size-3.5 shrink-0 text-muted-foreground transition-transform",
                          scheduleBarOpen && "rotate-90",
                        )}
                      />
                      <CalendarClockIcon className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                        日程任务
                      </span>
                      <span className="shrink-0 text-[0.65rem] text-muted-foreground/70">
                        {scheduleRunCount}
                      </span>
                    </div>
                  </SidebarMenuItem>
                  {scheduleBarOpen &&
                    scheduleGroups.map(([name, runs]) => {
                      const groupOpen = openScheduleGroups === null || openScheduleGroups.has(name)
                      return (
                        <React.Fragment key={name}>
                          <SidebarMenuItem>
                            <div
                              role="button"
                              tabIndex={0}
                              aria-expanded={groupOpen}
                              onClick={() =>
                                setOpenScheduleGroups((prev) => {
                                  const base =
                                    prev === null
                                      ? new Set(scheduleGroups.map(([n]) => n))
                                      : new Set(prev)
                                  if (base.has(name)) base.delete(name)
                                  else base.add(name)
                                  return base
                                })
                              }
                              onKeyDown={(e) => {
                                if (e.target !== e.currentTarget) return
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault()
                                  setOpenScheduleGroups((prev) => {
                                    const base =
                                      prev === null
                                        ? new Set(scheduleGroups.map(([n]) => n))
                                        : new Set(prev)
                                    if (base.has(name)) base.delete(name)
                                    else base.add(name)
                                    return base
                                  })
                                }
                              }}
                              className="flex w-full cursor-pointer items-center gap-1.5 rounded-md py-1 pl-6 pr-2 text-left text-xs outline-none transition-colors hover:bg-sidebar-accent focus-visible:ring-2"
                              title={name}
                            >
                              <ChevronRightIcon
                                className={cn(
                                  "size-3 shrink-0 text-muted-foreground transition-transform",
                                  groupOpen && "rotate-90",
                                )}
                              />
                              <span className="min-w-0 flex-1 truncate text-muted-foreground">
                                {name}
                              </span>
                              <span className="shrink-0 text-[0.65rem] text-muted-foreground/70">
                                {runs.length}
                              </span>
                            </div>
                          </SidebarMenuItem>
                          {groupOpen &&
                            runs.map((task) => (
                              <TaskRow
                                key={task.id}
                                task={task}
                                inset="schedule"
                                selectedTaskId={selectedTaskId}
                                onSelectTask={onSelectTask}
                                onContextMenu={openProjectMenu}
                              />
                            ))}
                        </React.Fragment>
                      )
                    })}
                </>
              )}
            </>
          )}

          {/* -------- SCHEDULES mode: schedule rows with toggle + detail -------- */}
          {mode === "schedules" && (
            <>
              {schedules.isLoading && (
                <SidebarMenuItem>
                  <Skeleton className="mx-2 h-16 w-auto" />
                </SidebarMenuItem>
              )}
              {!schedules.isLoading && (schedules.data ?? []).length === 0 && (
                <SidebarMenuItem>
                  <p className="px-2 py-1 text-xs text-muted-foreground">
                    还没有日程，点上面的 + 描述并新建
                  </p>
                </SidebarMenuItem>
              )}
              {(schedules.data ?? []).map((schedule) => (
                <SidebarMenuItem key={schedule.id}>
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => setScheduleDetail(schedule)}
                    onKeyDown={(e) => {
                      if (e.target !== e.currentTarget) return
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault()
                        setScheduleDetail(schedule)
                      }
                    }}
                    className="flex w-full cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 text-left outline-none transition-colors hover:bg-sidebar-accent focus-visible:ring-2"
                    title={schedule.task_input}
                  >
                    <ScheduleToggle
                      schedule={schedule}
                      disabled={scheduleManage.update.isPending}
                      onToggle={toggleScheduleEnabled}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium" title={schedule.name}>
                        {schedule.name}
                      </span>
                      <span className="block truncate text-[0.65rem] text-muted-foreground">
                        {schedule.enabled && schedule.next_run_at
                          ? `下次 ${new Date(schedule.next_run_at).toLocaleString()}`
                          : schedule.trigger_text}
                      </span>
                    </span>
                  </div>
                </SidebarMenuItem>
              ))}
            </>
          )}

          {/* -------- PROJECT mode: projects with nested tasks -------- */}
          {mode === "projects" && (
            <>
              {projects.isLoading && (
                <SidebarMenuItem>
                  <Skeleton className="mx-2 h-16 w-auto" />
                </SidebarMenuItem>
              )}
              {!projects.isLoading && projectList.length === 0 && (
                <SidebarMenuItem>
                  <p className="px-2 py-1 text-xs text-muted-foreground">
                    还没有项目，点上面的文件夹图标添加
                  </p>
                </SidebarMenuItem>
              )}
              {projectList.map((project) => {
                const open = isOpen(project.id)
                const children = projectTasks(project.id)
                return (
                  <React.Fragment key={project.id}>
                    <SidebarMenuItem>
                      <div
                        role="button"
                        tabIndex={0}
                        aria-expanded={open}
                        onClick={() => toggleProject(project.id)}
                        onKeyDown={(e) => {
                          // Only the row itself toggles; let child buttons
                          // (new task / remove) handle their own keys.
                          if (e.target !== e.currentTarget) return
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault()
                            toggleProject(project.id)
                          }
                        }}
                        className="group/project flex w-full cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm outline-none transition-colors hover:bg-sidebar-accent focus-visible:ring-2"
                        title={project.path}
                      >
                        <ChevronRightIcon
                          className={cn(
                            "size-3.5 shrink-0 text-muted-foreground transition-transform",
                            open && "rotate-90",
                          )}
                        />
                        {open ? (
                          <FolderOpenIcon className="size-3.5 shrink-0 text-muted-foreground" />
                        ) : (
                          <FolderIcon className="size-3.5 shrink-0 text-muted-foreground" />
                        )}
                        <span className="min-w-0 flex-1 truncate text-xs font-medium">
                          {project.name}
                        </span>
                        {children.length > 0 && (
                          <span className="shrink-0 text-[0.65rem] text-muted-foreground/70">
                            {children.length}
                          </span>
                        )}
                        <button
                          type="button"
                          title={`在「${project.name}」里新建任务`}
                          onClick={(e) => {
                            e.stopPropagation()
                            onNewTaskInProject(project.id)
                          }}
                          className="rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:bg-sidebar-accent hover:text-foreground group-hover/project:opacity-100 focus-visible:opacity-100"
                        >
                          <PlusIcon className="size-3.5" />
                        </button>
                        <button
                          type="button"
                          title="移除项目（任务保留，回到任务目录）"
                          onClick={(e) => {
                            e.stopPropagation()
                            setRemovingProject(project.id)
                          }}
                          className="rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:bg-sidebar-accent hover:text-destructive group-hover/project:opacity-100 focus-visible:opacity-100"
                        >
                          <Trash2Icon className="size-3.5" />
                        </button>
                      </div>
                    </SidebarMenuItem>
                    {open &&
                      (children.length > 0 ? (
                        children.map((task) => (
                          <TaskRow
                            key={task.id}
                            task={task}
                            inset="project"
                            selectedTaskId={selectedTaskId}
                            onSelectTask={onSelectTask}
                            onContextMenu={openProjectMenu}
                          />
                        ))
                      ) : (
                        <SidebarMenuItem>
                          <p className="py-0.5 pl-9 text-[0.65rem] text-muted-foreground/70">
                            这个项目还没有对话
                          </p>
                        </SidebarMenuItem>
                      ))}
                  </React.Fragment>
                )
              })}
            </>
          )}
        </SidebarMenu>
      </SidebarGroupContent>

      <ScheduleDetailDialog
        schedule={scheduleDetail}
        onClose={() => setScheduleDetail(null)}
      />

      {/* folder picker: add project by choosing a server folder */}
      {pickerOpen && (
        <FolderPicker
          onPick={(path) => {
            const name = path.split("/").filter(Boolean).pop() || path
            manage.create.mutate(
              { name, path },
              { onSuccess: () => setPickerOpen(false) },
            )
          }}
          onClose={() => setPickerOpen(false)}
        />
      )}

      {/* context menu */}
      {menu && (
        <div
          className="fixed z-50 min-w-40 rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10"
          style={{ left: menu.x, top: menu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
            onClick={() => copyId(menu.task)}
          >
            <CopyIcon className="size-3.5" />
            复制任务ID
          </button>
          <button
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
            onClick={() => {
              setRenaming(menu.task)
              setRenameValue(menu.task.title)
              setMenu(null)
            }}
          >
            <PencilIcon className="size-3.5" />
            重命名
          </button>
          <button
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
            onClick={() => {
              updateTask.mutate({ taskId: menu.task.id, patch: { pinned: !menu.task.pinned } })
              setMenu(null)
            }}
          >
            <PinIcon className="size-3.5" />
            {menu.task.pinned ? "取消置顶" : "置顶"}
          </button>
          <button
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm text-destructive hover:bg-muted"
            onClick={() => {
              setRemoving(menu.task)
              setMenu(null)
            }}
          >
            <Trash2Icon className="size-3.5" />
            删除
          </button>
        </div>
      )}

      {/* rename dialog */}
      <Dialog open={renaming !== null} onOpenChange={(open) => !open && setRenaming(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>重命名任务</DialogTitle>
            <DialogDescription>改后侧边栏和对话标题都会更新。</DialogDescription>
          </DialogHeader>
          <Input
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && renameValue.trim() && renaming) {
                updateTask.mutate({ taskId: renaming.id, patch: { title: renameValue.trim() } })
                setRenaming(null)
              }
            }}
            autoFocus
          />
          <DialogFooter>
            <Button
              size="sm"
              disabled={!renameValue.trim() || !renaming}
              onClick={() => {
                if (renaming) {
                  updateTask.mutate({ taskId: renaming.id, patch: { title: renameValue.trim() } })
                  setRenaming(null)
                }
              }}
            >
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* delete confirm */}
      <AlertDialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除任务「{removing?.title ?? ""}」？</AlertDialogTitle>
            <AlertDialogDescription>
              {removing && !isTerminalTask(removing)
                ? "任务正在运行，请先停止后再删除。"
                : "任务及其全部运行记录将被删除，此操作不可撤销。"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              disabled={removing !== null && !isTerminalTask(removing)}
              onClick={() => {
                if (removing) deleteTask.mutate({ taskId: removing.id })
                setRemoving(null)
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* remove-project confirm: tasks survive, they just unbind */}
      <AlertDialog
        open={removingProject !== null}
        onOpenChange={(open) => !open && setRemovingProject(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>移除项目？</AlertDialogTitle>
            <AlertDialogDescription>
              只是解除这个文件夹的绑定：项目里的任务不会删除，会回到「任务」列表，之后的对话不再写入该文件夹。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (removingProject) manage.remove.mutate(removingProject)
                setRemovingProject(null)
              }}
            >
              移除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SidebarGroup>
  )
}

/** Server folder picker: browse subdirectories, then confirm. Projects are
 *  host folders so the browser cannot open a native picker — this walks the
 *  server tree instead (read-only). The project name becomes the folder name.
 *  ``path`` state is the source of truth for navigation and submission; the
 *  fetched entry list only feeds the tree. */
function FolderPicker({
  onPick,
  onClose,
}: {
  onPick: (path: string) => void
  onClose: () => void
}) {
  const [path, setPath] = React.useState("") // "" = home, served by the backend
  const browse = useBrowseDir(path)
  const data = browse.data
  const folderName = path.split("/").filter(Boolean).pop()

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-3 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>选择工作文件夹</DialogTitle>
          <DialogDescription>
            项目名使用所选文件夹的名称。绑定后，该项目的对话直接在这个文件夹里读写文件。
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-1 rounded-md border bg-muted/40 px-1 py-0.5 font-mono text-xs">
          <button
            type="button"
            onClick={() => data?.parent && setPath(data.parent)}
            disabled={!data?.parent || browse.isFetching}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30"
            title="上一级"
          >
            <ChevronRightIcon className="size-3.5 -rotate-90" />
          </button>
          <span className="min-w-0 flex-1 truncate px-1" title={data?.path ?? path}>
            {data?.path ?? (path || "…")}
          </span>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
          {browse.isFetching && <Skeleton className="h-10 w-full" />}
          {browse.error && (
            <p className="px-1 py-2 text-xs text-destructive">
              {browse.error instanceof Error ? browse.error.message : String(browse.error)}
            </p>
          )}
          {!browse.isFetching && data && data.entries.length === 0 && (
            <p className="px-1 py-2 text-xs text-muted-foreground">这个文件夹里没有子目录</p>
          )}
          {(data?.entries ?? []).map((entry) => (
            <button
              key={entry.path}
              type="button"
              onClick={() => setPath(entry.path)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent"
              title={entry.path}
            >
              <FolderIcon className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{entry.name}</span>
            </button>
          ))}
        </div>
        <DialogFooter className="items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
            将添加：{folderName || "…"}
          </span>
          <Button variant="outline" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button
            size="sm"
            disabled={!folderName || browse.isFetching}
            onClick={() => folderName && onPick(path)}
          >
            选择此文件夹
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function AppSidebar({
  view,
  onViewChange,
  selectedTaskId,
  onSelectTask,
  onNewTaskInProject,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  view: string
  onViewChange: (view: string) => void
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
  onNewTaskInProject: (projectId: string) => void
}) {
  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" className="pointer-events-none" tabIndex={-1}>
              <div className="flex aspect-square size-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-black/10">
                <img
                  src="./app-icon.png?v=2"
                  alt="Agent Console"
                  className="size-full object-contain"
                  draggable={false}
                />
              </div>
              <div className="grid min-w-0 flex-1 text-left text-sm leading-tight group-data-[collapsible=icon]:hidden">
                <span className="truncate font-medium">{data.brand.name}</span>
                <span className="truncate text-xs">{data.brand.plan}</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain
          items={data.navMain.map((item) => ({
            ...item,
            isActive: item.title === view,
            onSelect: () => onViewChange(item.title),
          }))}
        />
        <WorkspaceSection
          selectedTaskId={selectedTaskId}
          onSelectTask={onSelectTask}
          onNewTaskInProject={onNewTaskInProject}
          onViewChange={onViewChange}
        />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
