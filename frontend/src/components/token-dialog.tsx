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
import { Label } from "@/components/ui/label"
import { getToken, setToken } from "@/lib/api"
import { useQueryClient } from "@tanstack/react-query"

export function TokenDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [value, setValue] = React.useState("")
  const queryClient = useQueryClient()

  React.useEffect(() => {
    if (open) setValue(getToken())
  }, [open])

  const save = () => {
    setToken(value.trim())
    onOpenChange(false)
    queryClient.invalidateQueries()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>控制台令牌</DialogTitle>
          <DialogDescription>
            服务端设置了 AGENT_CORE_CONSOLE_TOKEN 时需要填写；令牌只保存在本机浏览器。
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => { e.preventDefault(); save() }}>
          <div className="grid gap-2 py-2">
            <Label htmlFor="console-token">令牌</Label>
            <Input
              id="console-token"
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="留空表示无令牌"
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button type="submit">保存并重连</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
