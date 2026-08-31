import { SchedulesPanel } from "@/components/schedules/schedules-panel"

export function SchedulesView({
  onOpenTask,
}: {
  onOpenTask?: (taskId: string) => void
}) {
  return <SchedulesPanel onOpenTask={onOpenTask} />
}
