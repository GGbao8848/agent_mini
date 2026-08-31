import * as React from "react"
import { Badge } from "@/components/ui/badge"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { SkillDropzone } from "@/components/toolbox/skill-dropzone"
import { useSkillManage, useSkills } from "@/hooks/use-console"
import { PackageIcon, PlusIcon, Trash2Icon } from "lucide-react"

const EMPTY_FORM = { id: "", name: "", version: "0.1.0", description: "", path: "" }

/** Install dialog: upload a skill zip (primary) or register a server dir (fallback). */
function InstallSkillDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const skills = useSkillManage()
  const [tab, setTab] = React.useState("upload")
  const [form, setForm] = React.useState(EMPTY_FORM)
  const [error, setError] = React.useState("")

  const close = () => {
    onOpenChange(false)
    setError("")
    setForm(EMPTY_FORM)
  }

  const submitPath = () => {
    setError("")
    const payload = {
      id: form.id.trim(),
      name: form.name.trim(),
      version: form.version.trim() || "0.1.0",
      description: form.description.trim(),
      path: form.path.trim(),
    }
    if (!payload.id || !payload.name || !payload.path) {
      setError("id、名称、目录路径必填")
      return
    }
    skills.install.mutate(payload, {
      onSuccess: close,
    })
  }

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>安装技能</DialogTitle>
          <DialogDescription>
            技能目录约定：目录内放 SKILL.md（+ references/ scripts/）。
          </DialogDescription>
        </DialogHeader>
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="upload">上传 zip</TabsTrigger>
            <TabsTrigger value="path">登记服务器路径</TabsTrigger>
          </TabsList>
          <TabsContent value="upload" className="flex justify-center py-2">
            <SkillDropzone size="compact" onUploaded={close} />
          </TabsContent>
          <TabsContent value="path" className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-2">
              <div className="grid gap-1.5">
                <Label htmlFor="sk-id">id</Label>
                <Input id="sk-id" placeholder="my-skill" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="sk-name">名称</Label>
                <Input id="sk-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="grid gap-1.5">
                <Label htmlFor="sk-version">版本</Label>
                <Input id="sk-version" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="sk-desc">描述</Label>
                <Input id="sk-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="sk-path">服务器上的目录路径</Label>
              <Input
                id="sk-path"
                placeholder="/home/user/skills/my-skill（目录内需有 SKILL.md）"
                value={form.path}
                onChange={(e) => setForm({ ...form, path: e.target.value })}
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <DialogFooter>
              <Button disabled={skills.install.isPending} onClick={submitPath}>
                安装
              </Button>
            </DialogFooter>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

export function SkillsPanel() {
  const skills = useSkills()
  const manage = useSkillManage()
  const [installOpen, setInstallOpen] = React.useState(false)
  const [removingId, setRemovingId] = React.useState<string | null>(null)

  const skillList = skills.data ?? []

  // Empty state: a centered dropzone is the whole page.
  if (!skills.isLoading && skillList.length === 0) {
    return (
      <div className="flex min-h-full flex-1 flex-col items-center justify-center gap-4 p-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
            <PackageIcon className="size-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-medium">还没有安装任何技能</h2>
          <p className="text-sm text-muted-foreground">上传一个技能 zip 包，或登记服务器上的技能目录</p>
        </div>
        <SkillDropzone size="large" onUploaded={() => undefined} />
        <Button size="sm" variant="outline" onClick={() => setInstallOpen(true)}>
          <PlusIcon data-icon="inline-start" />
          登记服务器目录路径
        </Button>
        <InstallSkillDialog open={installOpen} onOpenChange={setInstallOpen} />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">Skills 技能（{skillList.length} 个）</h2>
        <Button size="sm" onClick={() => setInstallOpen(true)}>
          <PlusIcon data-icon="inline-start" />
          安装技能
        </Button>
      </div>

      {skills.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {skillList.map((skill) => (
            <div key={skill.id} className="flex flex-col gap-2 rounded-lg border p-4">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium">{skill.name}</span>
                <Badge variant="secondary" className="shrink-0">v{skill.version}</Badge>
              </div>
              <p className="line-clamp-2 min-h-8 text-xs text-muted-foreground">
                {skill.description || "无描述"}
              </p>
              <p className="truncate text-xs text-muted-foreground" title={skill.path ?? ""}>
                id: {skill.id}
              </p>
              <Button
                size="xs"
                variant="ghost"
                className="mt-auto self-end text-destructive"
                onClick={() => setRemovingId(skill.id)}
              >
                <Trash2Icon data-icon="inline-start" />
                删除
              </Button>
            </div>
          ))}
        </div>
      )}

      <InstallSkillDialog open={installOpen} onOpenChange={setInstallOpen} />

      <AlertDialog open={removingId !== null} onOpenChange={(isOpen) => !isOpen && setRemovingId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除技能 {removingId}？</AlertDialogTitle>
            <AlertDialogDescription>
              技能目录仍保留在服务器磁盘上，但不再对 agent 生效。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (removingId) manage.remove.mutate(removingId)
                setRemovingId(null)
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
