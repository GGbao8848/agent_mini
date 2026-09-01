"use client"

import * as React from "react"

import { NavMain } from "@/components/nav-main"
import { StatusDot } from "@/components/runs/status-dot"
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
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
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
import { Skeleton } from "@/components/ui/skeleton"
import { useDeleteTask, useTasks, useUpdateTask } from "@/hooks/use-console"
import { fmtTimeShort } from "@/lib/format"
import { excerpt, isTerminalTask } from "@/lib/tasks"
import type { Task } from "@/lib/types"
import {
  CalendarDaysIcon,
  ChevronRightIcon,
  CopyIcon,
  PencilIcon,
  PinIcon,
  PlugIcon,
  PlusCircleIcon,
  PuzzleIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"

const data = {
  brand: {
    name: "Agent Console",
    plan: "Agent Core",
  },
  navMain: [
    {
      title: "新建任务",
      url: "#",
      icon: <PlusCircleIcon />,
    },
    {
      title: "日程",
      url: "#",
      icon: <CalendarDaysIcon />,
    },
    {
      title: "技能",
      url: "#",
      icon: <PuzzleIcon />,
    },
    {
      title: "MCP",
      url: "#",
      icon: <PlugIcon />,
    },
    {
      title: "工具",
      url: "#",
      icon: <WrenchIcon />,
    },
  ],
}

function TaskRow({
  task,
  selectedTaskId,
  onSelectTask,
  onContextMenu,
}: {
  task: Task
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
  onContextMenu: (e: React.MouseEvent, task: Task) => void
}) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        isActive={task.id === selectedTaskId}
        onClick={() => onSelectTask(task.id)}
        onContextMenu={(e: React.MouseEvent) => onContextMenu(e, task)}
        className="gap-2 py-1.5"
        title={excerpt(task, 160)}
      >
        <StatusDot status={task.status} />
        <span className="flex-1 truncate text-xs">{excerpt(task, 60)}</span>
        <span className="shrink-0 text-[0.65rem] tabular-nums text-muted-foreground">
          {fmtTimeShort(task.created_at)}
        </span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

/** Group tasks by their source schedule; pinned first, then schedule groups,
 *  then the rest — each newest first. */
function groupTasks(tasks: Task[]): { label: string | null; tasks: Task[] }[] {
  const byTime = (a: Task, b: Task) => b.created_at.localeCompare(a.created_at)
  const pinned = tasks.filter((t) => t.pinned).sort(byTime)
  const rest = tasks.filter((t) => !t.pinned)
  const groups = new Map<string | null, Task[]>()
  for (const task of rest) {
    const source = (task.metadata?.source_schedule_name as string | undefined) ?? null
    const key = source ?? null
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(task)
  }
  const out: { label: string | null; tasks: Task[] }[] = []
  if (pinned.length) out.push({ label: "置顶", tasks: pinned })
  for (const [label, list] of groups) {
    if (label !== null) out.push({ label, tasks: [...list].sort(byTime) })
  }
  const plain = groups.get(null) ?? []
  if (plain.length) out.push({ label: null, tasks: [...plain].sort(byTime) })
  return out
}

function SidebarTasks({
  selectedTaskId,
  onSelectTask,
}: {
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
}) {
  const tasks = useTasks()
  const updateTask = useUpdateTask()
  const deleteTask = useDeleteTask()
  const list = tasks.data ?? []

  // Right-click context menu state.
  const [menu, setMenu] = React.useState<{ x: number; y: number; task: Task } | null>(null)
  const [renaming, setRenaming] = React.useState<Task | null>(null)
  const [renameValue, setRenameValue] = React.useState("")
  const [removing, setRemoving] = React.useState<Task | null>(null)

  const groups = React.useMemo(() => groupTasks(list), [list])

  const openMenu = (e: React.MouseEvent, task: Task) => {
    e.preventDefault()
    setMenu({ x: e.clientX, y: e.clientY, task })
  }
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
      // clipboard may be unavailable; fall back to nothing
    }
    setMenu(null)
  }

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>任务</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {tasks.isLoading &&
            Array.from({ length: 3 }).map((_, i) => (
              <SidebarMenuItem key={i}>
                <Skeleton className="h-8 w-full" />
              </SidebarMenuItem>
            ))}
          {!tasks.isLoading && list.length === 0 && (
            <p className="px-2 py-1 text-xs text-muted-foreground">还没有任务，派一个吧</p>
          )}
          {groups.map((group, gi) => (
            <React.Fragment key={group.label ?? `plain-${gi}`}>
              {group.label ? (
                <Collapsible defaultOpen className="group/collapsible">
                  <SidebarMenuItem>
                    <CollapsibleTrigger render={<SidebarMenuButton className="gap-2 py-1 text-xs font-medium text-muted-foreground" />}>
                      <ChevronRightIcon className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-90" />
                      {group.label}
                      <span className="ml-auto text-[0.65rem] text-muted-foreground/60">
                        {group.tasks.length}
                      </span>
                    </CollapsibleTrigger>
                  </SidebarMenuItem>
                  <CollapsibleContent>
                    {group.tasks.map((task) => (
                      <TaskRow
                        key={task.id}
                        task={task}
                        selectedTaskId={selectedTaskId}
                        onSelectTask={onSelectTask}
                        onContextMenu={openMenu}
                      />
                    ))}
                  </CollapsibleContent>
                </Collapsible>
              ) : (
                group.tasks.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    selectedTaskId={selectedTaskId}
                    onSelectTask={onSelectTask}
                    onContextMenu={openMenu}
                  />
                ))
              )}
            </React.Fragment>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>

      {/* context menu */}
      {menu && (
        <div
          className="fixed z-50 min-w-40 rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10"
          style={{ left: menu.x, top: menu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
            onClick={() => {
              copyId(menu.task)
            }}
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
      <Dialog
        open={renaming !== null}
        onOpenChange={(open) => !open && setRenaming(null)}
      >
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
            <button
              className="rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground"
              disabled={!renameValue.trim() || !renaming}
              onClick={() => {
                if (renaming) {
                  updateTask.mutate({ taskId: renaming.id, patch: { title: renameValue.trim() } })
                  setRenaming(null)
                }
              }}
            >
              保存
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* delete confirm */}
      <AlertDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
      >
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
    </SidebarGroup>
  )
}

export function AppSidebar({
  view,
  onViewChange,
  selectedTaskId,
  onSelectTask,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  view: string
  onViewChange: (view: string) => void
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
}) {
  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" className="pointer-events-none" tabIndex={-1}>
              <div className="flex aspect-square size-8 items-center justify-center overflow-hidden rounded-lg bg-sidebar-primary">
                <img src="./app-icon.png" alt="Agent Console" className="size-full object-cover" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
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
        <SidebarTasks selectedTaskId={selectedTaskId} onSelectTask={onSelectTask} />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
