import { SchedulesPanel } from "@/components/schedules/schedules-panel"

export function SchedulesView({
  onOpenTask,
}: {
  onOpenTask?: (taskId: string) => void
}) {
  return (
    <div className="grid items-start gap-4 p-4 lg:grid-cols-2 xl:grid-cols-3">
      <div className="lg:col-span-2 xl:col-span-1">
        <SchedulesPanel onOpenTask={onOpenTask} />
      </div>
    </div>
  )
}
