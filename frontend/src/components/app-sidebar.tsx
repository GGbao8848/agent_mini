"use client"

import * as React from "react"

import { NavMain } from "@/components/nav-main"
import { Button } from "@/components/ui/button"
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
import { Label } from "@/components/ui/label"
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
import {
  useDeleteTask,
  useProjectManage,
  useProjects,
  useTasks,
  useUpdateTask,
} from "@/hooks/use-console"
import { fmtTimeShort } from "@/lib/format"
import { excerpt, isTerminalTask } from "@/lib/tasks"
import type { Task } from "@/lib/types"
import {
  CalendarDaysIcon,
  ChevronRightIcon,
  FolderIcon,
  PlusIcon,
  CopyIcon,
  PencilIcon,
  PinIcon,
  PlugIcon,
  PlusCircleIcon,
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
    {
      title: "模型配置",
      url: "#",
      icon: <SettingsIcon />,
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

/** Group tasks by their source (bound project first, then schedule); pinned
 *  first, then named groups, then the rest — each newest first. */
function groupTasks(
  tasks: Task[],
  projectName: (projectId: string | null) => string | null,
): { label: string | null; tasks: Task[] }[] {
  const byTime = (a: Task, b: Task) => b.created_at.localeCompare(a.created_at)
  const pinned = tasks.filter((t) => t.pinned).sort(byTime)
  const rest = tasks.filter((t) => !t.pinned)
  const groups = new Map<string | null, Task[]>()
  for (const task of rest) {
    const source =
      projectName(task.project_id) ??
      (task.metadata?.source_schedule_name as string | undefined) ??
      null
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
  const projects = useProjects()
  const updateTask = useUpdateTask()
  const deleteTask = useDeleteTask()
  const list = tasks.data ?? []

  // Right-click context menu state.
  const [menu, setMenu] = React.useState<{ x: number; y: number; task: Task } | null>(null)
  const [renaming, setRenaming] = React.useState<Task | null>(null)
  const [renameValue, setRenameValue] = React.useState("")
  const [removing, setRemoving] = React.useState<Task | null>(null)

  const projectName = React.useCallback(
    (projectId: string | null) =>
      projectId
        ? (projects.data?.find((p) => p.id === projectId)?.name ?? null)
        : null,
    [projects.data],
  )
  const groups = React.useMemo(
    () => groupTasks(list, projectName),
    [list, projectName],
  )

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

/** Sidebar projects section, ZCode-style: a "+" beside the section title adds
 *  a host folder; each project row spawns a bound task (+) or deletes itself.
 *  The tasks of a project show up in the task list, grouped under its name. */
function SidebarProjects({ onNewTaskInProject }: { onNewTaskInProject: (projectId: string) => void }) {
  const projects = useProjects()
  const manage = useProjectManage()
  const [adding, setAdding] = React.useState(false)
  const [name, setName] = React.useState("")
  const [path, setPath] = React.useState("")

  const submit = () => {
    if (!name.trim() || !path.trim()) return
    manage.create.mutate(
      { name: name.trim(), path: path.trim() },
      {
        onSuccess: () => {
          setName("")
          setPath("")
          setAdding(false)
        },
      },
    )
  }

  return (
    <SidebarGroup>
      <SidebarGroupLabel>
        <span className="flex-1">项目</span>
        <button
          type="button"
          title="添加文件夹（项目）"
          onClick={() => setAdding(true)}
          className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
        >
          <PlusIcon className="size-3.5" />
        </button>
      </SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {(projects.data ?? []).map((project) => (
            <SidebarMenuItem key={project.id}>
              <div className="group/project flex items-center gap-1 rounded-md px-2 py-1 text-sm transition-colors hover:bg-sidebar-accent">
                <FolderIcon className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate" title={project.path}>
                  {project.name}
                </span>
                <button
                  type="button"
                  title={`在「${project.name}」里新建任务`}
                  onClick={() => onNewTaskInProject(project.id)}
                  className="rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover/project:opacity-100"
                >
                  <PlusIcon className="size-3.5" />
                </button>
                <button
                  type="button"
                  title="移除项目（任务保留，回到任务目录）"
                  onClick={() => manage.remove.mutate(project.id)}
                  className="rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover/project:opacity-100"
                >
                  <Trash2Icon className="size-3.5" />
                </button>
              </div>
            </SidebarMenuItem>
          ))}
          {(projects.data ?? []).length === 0 && (
            <SidebarMenuItem>
              <span className="px-2 py-1 text-xs text-muted-foreground">
                点右上角 + 添加工作文件夹
              </span>
            </SidebarMenuItem>
          )}
        </SidebarMenu>
      </SidebarGroupContent>
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>添加项目文件夹</DialogTitle>
            <DialogDescription>
              绑定项目的对话直接在这个文件夹里读写文件、执行命令。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="sidebar-project-name">名称</Label>
              <Input
                id="sidebar-project-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：画册小程序"
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="sidebar-project-path">服务器上的文件夹（绝对路径）</Label>
              <Input
                id="sidebar-project-path"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="/Users/you/mycode/my-app"
                className="font-mono"
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setAdding(false)}>
              取消
            </Button>
            <Button
              size="sm"
              disabled={manage.create.isPending || !name.trim() || !path.trim()}
              onClick={submit}
            >
              添加
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SidebarGroup>
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
        <SidebarProjects onNewTaskInProject={onNewTaskInProject} />
        <SidebarTasks selectedTaskId={selectedTaskId} onSelectTask={onSelectTask} />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
