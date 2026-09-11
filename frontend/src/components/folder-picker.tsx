import * as React from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useBrowseDir, useCreateDir } from "@/hooks/use-console"
import { ChevronRightIcon, FolderIcon, FolderPlusIcon } from "lucide-react"

/** Server folder picker: browse subdirectories, create one, then use it.
 *
 * A working folder is a real host directory, so the browser cannot open a
 * native picker — this walks the server tree instead. ``path`` state is the
 * source of truth for navigation; the fetched entry list only feeds the tree.
 * ``allowCreate`` adds a "新建文件夹" row (the folder is created on the server
 * under the folder you're currently browsing).
 */
export function FolderPicker({
  title = "选择工作文件夹",
  description = "选定后，这次对话直接在这个文件夹里读写文件。",
  allowCreate = false,
  onPick,
  onClose,
}: {
  title?: string
  description?: string
  allowCreate?: boolean
  onPick: (path: string) => void
  onClose: () => void
}) {
  const [path, setPath] = React.useState("") // "" = home, served by the backend
  const [creating, setCreating] = React.useState(false)
  const [newName, setNewName] = React.useState("")
  const [error, setError] = React.useState("")
  const browse = useBrowseDir(path)
  const create = useCreateDir()
  const data = browse.data
  // Prefer the resolved path (after navigation); fall back to the typed one.
  const currentPath = data?.path ?? path
  const folderName = currentPath.split("/").filter(Boolean).pop()

  const startCreate = () => {
    setError("")
    setNewName("")
    setCreating(true)
  }

  const submitCreate = () => {
    const name = newName.trim()
    if (!name) return
    if (!currentPath) {
      setError("请先进入一个文件夹再新建")
      return
    }
    setError("")
    create.mutate(
      { parent: currentPath, name },
      {
        onSuccess: (entry) => {
          setCreating(false)
          setPath(entry.path) // navigate into the folder we just made
        },
        onError: (err) => setError(err instanceof Error ? err.message : String(err)),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-3 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
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
          <span className="min-w-0 flex-1 truncate px-1" title={currentPath}>
            {currentPath || "…"}
          </span>
        </div>

        {creating && (
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <FolderPlusIcon className="size-4 shrink-0 text-muted-foreground" />
              <Input
                autoFocus
                value={newName}
                placeholder="新文件夹名称"
                className="h-8"
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submitCreate()
                  if (e.key === "Escape") setCreating(false)
                }}
              />
              <Button size="sm" disabled={!newName.trim() || create.isPending} onClick={submitCreate}>
                创建
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setCreating(false)}>
                取消
              </Button>
            </div>
            {error && <p className="px-1 text-xs text-destructive">{error}</p>}
          </div>
        )}

        <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
          {allowCreate && !creating && (
            <button
              type="button"
              onClick={startCreate}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <FolderPlusIcon className="size-4 shrink-0" />
              <span>新建文件夹…</span>
            </button>
          )}
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
            将使用：{folderName || "…"}
          </span>
          <Button variant="outline" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button
            size="sm"
            disabled={!folderName || browse.isFetching}
            onClick={() => folderName && onPick(currentPath)}
          >
            使用此文件夹
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
