import * as React from "react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { eventColor, fmtTime, str } from "@/lib/format"
import type { RunEvent } from "@/lib/types"

export function EventsPanel({ events }: { events: RunEvent[] }) {
  const bottomRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView()
  }, [events.length])

  if (!events.length) {
    return (
      <p className="p-2 text-sm text-muted-foreground">
        （实时事件会在这里出现；历史 run 不保留事件流）
      </p>
    )
  }

  return (
    <ScrollArea className="h-[calc(100vh-26rem)]">
      <div ref={bottomRef} className="flex flex-col gap-1 p-2 font-mono text-xs">
        {events.map((event) => {
          const info = event.tool
            ? `${event.tool} ${str(event.output) || str(event.error)}`
            : str(event.output) || str(event.error)
          return (
            <div key={event.id || `${event.timestamp}-${event.event_type}`} className="flex gap-2">
              <span className="shrink-0 text-muted-foreground">{fmtTime(event.timestamp)}</span>
              <span className={`shrink-0 ${eventColor(event.event_type)}`}>{event.event_type}</span>
              <span className="min-w-0 break-words text-foreground/80">{info.slice(0, 160)}</span>
            </div>
          )
        })}
      </div>
    </ScrollArea>
  )
}
