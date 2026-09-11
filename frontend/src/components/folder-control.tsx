import * as React from "react"
import { FolderPicker } from "@/components/folder-picker"
import { useProjectManage, useProjects } from "@/hooks/use-console"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { folderBasename, folderLabel, FOLDER_NONE_LABEL } from "@/lib/folder"
import { ChevronDownIcon, FolderIcon, FolderOpenIcon, FolderPlusIcon } from "lucide-react"

/** The composer's working-folder control (ZCode-style).
 *
 * Shows the folder this conversation works in and lets you switch it:
 *   - pick an already-registered folder;
 *   - 打开文件夹 → browse the server and register a folder as a project;
 *   - 不在项目中工作 → unbind (work in the default folder).
 *
 * `currentPath` is "" for the unbound/default folder. In an existing
 * conversation changing the folder rebinds it (PATCH /v1/tasks/{id}); if that
 * is not allowed the control is read-only.
 */
export function FolderControl({
  currentPath,
  onSelect,
  readonly = false,
  disabled = false,
}: {
  /** The folder this conversation works in ("" = 不在项目中工作 / default). */
  currentPath: string
  onSelect: (path: string | null) => void
  readonly?: boolean
  disabled?: boolean
}) {
  const projects = useProjects()
  const manage = useProjectManage()
  const [pickerOpen, setPickerOpen] = React.useState(false)
  // A project is just a registered folder: its name *is* the folder name.
  const projectList = projects.data ?? []
  const current = projectList.find((p) => p.path === currentPath) ?? null
  const label = current ? current.name : folderLabel(currentPath)

  const pick = (path: string) => {
    // Register the chosen folder as a project (name = folder name), then bind.
    const name = folderBasename(path) || path
    manage.create.mutate(
      { name, path },
      {
        onSuccess: (project) => {
          setPickerOpen(false)
          onSelect(project.path)
        },
      },
    )
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          disabled={disabled}
          className="flex h-7 items-center gap-1 rounded-md bg-muted px-2 text-xs text-foreground hover:bg-muted/70 disabled:opacity-50"
        >
          <FolderIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="max-w-40 truncate">{label}</span>
          <ChevronDownIcon className="size-3 shrink-0 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-60">
          {projectList.length > 0 && (
            <>
              <DropdownMenuLabel>工作文件夹</DropdownMenuLabel>
              {projectList.map((project) => (
                <DropdownMenuItem
                  key={project.id}
                  disabled={readonly || project.path === currentPath}
                  onClick={() => onSelect(project.path)}
                >
                  <FolderIcon className="size-4" />
                  <span className="min-w-0 flex-1 truncate">{project.name}</span>
                  {project.path === currentPath && <span className="text-xs">✓</span>}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
            </>
          )}
          <DropdownMenuItem disabled={readonly} onClick={() => setPickerOpen(true)}>
            <FolderPlusIcon className="size-4" />
            打开文件夹…
          </DropdownMenuItem>
          <DropdownMenuItem disabled={readonly || currentPath === ""} onClick={() => onSelect(null)}>
            <FolderOpenIcon className="size-4" />
            {FOLDER_NONE_LABEL}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {pickerOpen && (
        <FolderPicker
          allowCreate
          title="打开文件夹"
          description="选择一个服务器上的文件夹作为工作目录，也可以在此新建。"
          onPick={pick}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </>
  )
}
