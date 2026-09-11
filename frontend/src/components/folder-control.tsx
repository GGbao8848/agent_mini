import * as React from "react"
import { FolderPicker } from "@/components/folder-picker"
import { useProjectManage, useProjects } from "@/hooks/use-console"
import { cn } from "@/lib/utils"
import { DEFAULT_FOLDER_LABEL, FOLDER_NONE_LABEL, folderBasename } from "@/lib/folder"
import { CheckIcon, ChevronDownIcon, FolderIcon, FolderOpenIcon, FolderPlusIcon } from "lucide-react"

/** The composer's working-folder control (ZCode-style).
 *
 * Shows the folder this conversation works in and lets you switch it:
 *   - pick an already-registered folder;
 *   - 打开文件夹… → browse the server and register a folder as a project;
 *   - 回到 default 文件夹 → unbind (work in the default folder).
 *
 * Built as a plain popover (like the model / permission pickers) rather than a
 * menu primitive: those are the patterns this codebase already exercises.
 *
 * The control deals in **project ids** (not paths): a folder just created is
 * not in the project list yet, so resolving a path back to an id from a cached
 * list would silently select nothing. `currentProjectId` is null when unbound.
 */
export function FolderControl({
  currentProjectId,
  onSelect,
  readonly = false,
  disabled = false,
}: {
  /** The folder this conversation is bound to (null = the default folder). */
  currentProjectId: string | null
  onSelect: (projectId: string | null) => void
  readonly?: boolean
  disabled?: boolean
}) {
  const projects = useProjects()
  const manage = useProjectManage()
  const [open, setOpen] = React.useState(false)
  const [pickerOpen, setPickerOpen] = React.useState(false)
  const rootRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener("mousedown", close)
    return () => window.removeEventListener("mousedown", close)
  }, [open])

  // A project is just a registered folder: its name *is* the folder name.
  const projectList = projects.data ?? []
  const current = projectList.find((p) => p.id === currentProjectId) ?? null
  const label = current ? current.name : DEFAULT_FOLDER_LABEL

  const choose = (projectId: string | null) => {
    setOpen(false)
    onSelect(projectId)
  }

  const pick = (path: string) => {
    // Register the chosen folder as a project (name = folder name), then bind
    // the id the server handed back — never a path looked up in a stale list.
    const name = folderBasename(path) || path
    manage.create.mutate(
      { name, path },
      {
        onSuccess: (project) => {
          setPickerOpen(false)
          choose(project.id)
        },
      },
    )
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        title="选择这次对话的工作文件夹"
        className="flex h-7 items-center gap-1 rounded-md bg-muted px-2 text-xs text-foreground hover:bg-muted/70 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <FolderIcon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="max-w-40 truncate">{label}</span>
        <ChevronDownIcon className="size-3 shrink-0 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-64 overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-md">
          {projectList.length > 0 && (
            <>
              <div className="px-3 pt-2 pb-1 text-xs font-medium text-muted-foreground">
                工作文件夹
              </div>
              {projectList.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  disabled={readonly || project.id === currentProjectId}
                  onClick={() => choose(project.id)}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent",
                    (readonly || project.id === currentProjectId) && "cursor-default opacity-60",
                  )}
                  title={project.path}
                >
                  <CheckIcon
                    className={cn(
                      "size-4 shrink-0",
                      project.id === currentProjectId ? "text-primary" : "invisible",
                    )}
                  />
                  <span className="min-w-0 flex-1 truncate">{project.name}</span>
                </button>
              ))}
              <div className="border-t" />
            </>
          )}
          <button
            type="button"
            disabled={readonly}
            onClick={() => {
              setOpen(false)
              setPickerOpen(true)
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <FolderPlusIcon className="size-4 shrink-0 text-muted-foreground" />
            打开文件夹…
          </button>
          <button
            type="button"
            disabled={readonly || currentProjectId === null}
            onClick={() => choose(null)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <FolderOpenIcon className="size-4 shrink-0 text-muted-foreground" />
            {FOLDER_NONE_LABEL}
          </button>
        </div>
      )}

      {pickerOpen && (
        <FolderPicker
          allowCreate
          title="打开文件夹"
          description="选择一个服务器上的文件夹作为工作目录，也可以在此新建。"
          onPick={pick}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </div>
  )
}
