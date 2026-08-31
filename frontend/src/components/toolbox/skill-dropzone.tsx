import * as React from "react"
import { Button } from "@/components/ui/button"
import { useSkillManage } from "@/hooks/use-console"
import { UploadCloudIcon } from "lucide-react"

/** Drag-and-drop (or click-to-browse) skill zip uploader.
 *
 * Used in two sizes: a large dropzone as the empty-state of the skills page,
 * and a compact one inside the install dialog.
 */
export function SkillDropzone({
  size = "large",
  onUploaded,
}: {
  size?: "large" | "compact"
  onUploaded?: () => void
}) {
  const manage = useSkillManage()
  const inputRef = React.useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = React.useState(false)

  const uploadFile = (file: File | undefined) => {
    if (!file) return
    manage.upload.mutate({ file }, { onSuccess: () => onUploaded?.() })
  }

  const large = size === "large"

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="上传技能 zip 包"
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") inputRef.current?.click()
      }}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        uploadFile(e.dataTransfer.files?.[0])
      }}
      className={
        large
          ? "flex w-full max-w-md cursor-pointer flex-col items-center gap-3 rounded-xl border-2 border-dashed p-10 text-center transition-colors hover:bg-muted/50 " +
            (dragging ? "border-primary bg-muted/50" : "border-muted-foreground/30")
          : "flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed p-6 text-center transition-colors hover:bg-muted/50 " +
            (dragging ? "border-primary bg-muted/50" : "border-muted-foreground/30")
      }
    >
      <input
        ref={inputRef}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={(e) => {
          uploadFile(e.target.files?.[0])
          e.target.value = ""
        }}
      />
      <UploadCloudIcon className={large ? "size-10 text-muted-foreground" : "size-6 text-muted-foreground"} />
      <div className="flex flex-col gap-1">
        <p className={large ? "text-base font-medium" : "text-sm font-medium"}>
          {manage.upload.isPending ? "正在上传安装…" : "点击选择或拖拽 zip 到此处"}
        </p>
        <p className="text-xs text-muted-foreground">技能包需含 SKILL.md（+ references/ scripts/ 可选）</p>
      </div>
      {!manage.upload.isPending && (
        <Button variant="outline" size="sm" onClick={(e) => {
          e.stopPropagation()
          inputRef.current?.click()
        }}>
          选择文件
        </Button>
      )}
    </div>
  )
}
