/* Data layer: react-query hooks + SSE wiring for the console. */

import * as React from "react"
import { useMutation, useQuery, useQueryClient, type UseMutationOptions } from "@tanstack/react-query"
import { toast } from "sonner"

import { api, ApiError, openEventStream } from "@/lib/api"
import {
  EVENT_TYPES,
  TERMINAL_RUN_STATUSES,
  type Agent,
  type Approval,
  type Artifact,
  type MCPServer,
  type Run,
  type RunEvent,
  type Schedule,
  type SchedulePayload,
  type Skill,
  type Task,
  type Tool,
} from "@/lib/types"

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return String(err)
}

/* ------------------------------------------------------------ queries */

export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => api.get<Agent[]>("/v1/agents"),
    staleTime: 60_000,
  })
}

export function useTasks() {
  return useQuery({
    queryKey: ["tasks"],
    queryFn: () => api.get<Task[]>("/v1/tasks"),
    refetchInterval: 15_000,
  })
}

export function useTask(taskId: string | null) {
  return useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.get<Task>(`/v1/tasks/${taskId}`),
    enabled: !!taskId,
    refetchInterval: (query) =>
      query.state.data && !TERMINAL_RUN_STATUSES.has(query.state.data.status)
        ? 10_000
        : false,
  })
}

export function useRun(runId: string | null) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.get<Run>(`/v1/runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (query) =>
      query.state.data && !TERMINAL_RUN_STATUSES.has(query.state.data.status) ? 10_000 : false,
  })
}

export function useApprovals() {
  return useQuery({
    queryKey: ["approvals"],
    queryFn: () => api.get<Approval[]>("/v1/approvals/pending"),
    refetchInterval: 8_000,
  })
}

export function useArtifacts(runId: string | null) {
  return useQuery({
    queryKey: ["artifacts", runId],
    queryFn: () => api.get<Artifact[]>(`/v1/artifacts/${runId}`),
    enabled: !!runId,
    staleTime: 30_000,
  })
}

export function useTools() {
  return useQuery({
    queryKey: ["tools"],
    queryFn: () => api.get<Tool[]>("/v1/tools"),
    staleTime: Infinity,
  })
}

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: () => api.get<Skill[]>("/v1/skills"),
    staleTime: Infinity,
  })
}

export function useMcpServers() {
  return useQuery({
    queryKey: ["mcp"],
    queryFn: () => api.get<MCPServer[]>("/v1/mcp/servers"),
    staleTime: Infinity,
  })
}

export function useSchedules() {
  return useQuery({
    queryKey: ["schedules"],
    queryFn: () => api.get<Schedule[]>("/v1/schedules"),
    refetchInterval: 15_000,
  })
}

export function useToolReload() {
  const queryClient = useQueryClient()
  return useToastMutation<Tool[], unknown>({
    mutationFn: () => api.post<Tool[]>("/v1/tools/reload"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] })
    },
  })
}

export function useScheduleManage() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["schedules"] })
    queryClient.invalidateQueries({ queryKey: ["tasks"] })
  }
  const create = useToastMutation<Schedule, SchedulePayload>({
    mutationFn: (payload) => api.post<Schedule>("/v1/schedules", payload),
    onSuccess: invalidate,
  })
  const update = useToastMutation<Schedule, { scheduleId: string; payload: SchedulePayload }>({
    mutationFn: ({ scheduleId, payload }) =>
      api.put<Schedule>(`/v1/schedules/${scheduleId}`, payload),
    onSuccess: invalidate,
  })
  const remove = useToastMutation<unknown, string>({
    mutationFn: (scheduleId) => api.del(`/v1/schedules/${scheduleId}`),
    onSuccess: invalidate,
  })
  const runNow = useToastMutation<{ schedule_id: string; task_id: string }, string>({
    mutationFn: (scheduleId) => api.post(`/v1/schedules/${scheduleId}/run`),
    onSuccess: invalidate,
  })
  return { create, update, remove, runNow }
}

/* ---------------------------------------------------------- mutations */

function useToastMutation<TData, TVars>(options: UseMutationOptions<TData, Error, TVars>) {
  return useMutation<TData, Error, TVars>({
    ...options,
    onError: (error) => toast.error("操作失败", { description: errMessage(error) }),
  })
}

export function useSubmitTask() {
  const queryClient = useQueryClient()
  return useToastMutation<Task, { agentId: string; input: string }>({
    mutationFn: ({ agentId, input }) =>
      api.post<Task>("/v1/tasks", { agent_id: agentId, input }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["agents"] })
    },
  })
}

export function useSendFollowup() {
  const queryClient = useQueryClient()
  return useToastMutation<Task, { taskId: string; input: string }>({
    mutationFn: ({ taskId, input }) =>
      api.post<Task>(`/v1/tasks/${taskId}/messages`, { input }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["task"] })
    },
  })
}

export function useCancelTask() {
  const queryClient = useQueryClient()
  return useToastMutation<Task, { taskId: string }>({
    mutationFn: ({ taskId }) => api.post<Task>(`/v1/tasks/${taskId}/cancel`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["task"] })
    },
  })
}

export function useResolveApproval() {
  const queryClient = useQueryClient()
  return useToastMutation<unknown, { approvalId: string; decision: string; note: string | null }>({
    mutationFn: ({ approvalId, decision, note }) =>
      api.post(`/v1/approvals/${approvalId}/resolve`, {
        decision,
        resolved_by: "console",
        note,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["approvals"] })
      queryClient.invalidateQueries({ queryKey: ["runs"] })
    },
  })
}

export function useMcpAction() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["mcp"] })
    queryClient.invalidateQueries({ queryKey: ["tools"] })
    queryClient.invalidateQueries({ queryKey: ["agents"] })
  }
  const create = useToastMutation<unknown, unknown>({
    mutationFn: (payload) => api.post("/v1/mcp/servers", payload),
    onSuccess: invalidate,
  })
  const action = useToastMutation<unknown, { serverId: string; action: "connect" | "disconnect" }>({
    mutationFn: ({ serverId, action }) => api.post(`/v1/mcp/servers/${serverId}/${action}`),
    onSuccess: invalidate,
  })
  const remove = useToastMutation<unknown, string>({
    mutationFn: (serverId) => api.del(`/v1/mcp/servers/${serverId}`),
    onSuccess: invalidate,
  })
  return { create, action, remove }
}

export function useSkillManage() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["skills"] })
    queryClient.invalidateQueries({ queryKey: ["agents"] })
  }
  const install = useToastMutation<unknown, Record<string, unknown>>({
    mutationFn: (payload) => api.post("/v1/skills", payload),
    onSuccess: invalidate,
  })
  const remove = useToastMutation<unknown, string>({
    mutationFn: (skillId) => api.del(`/v1/skills/${skillId}`),
    onSuccess: invalidate,
  })
  return { install, remove }
}

export function useUpdateAgent() {
  const queryClient = useQueryClient()
  return useToastMutation<Agent, { agentId: string; patch: { tools?: string[]; skills?: string[] } }>({
    mutationFn: ({ agentId, patch }) => api.put<Agent>(`/v1/agents/${agentId}`, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] })
    },
  })
}

/* ---------------------------------------------------------------- sse */

export type ConnState = "connecting" | "live" | "offline"

/** Global event stream: keeps run/approval queries fresh in real time. */
export function useGlobalEvents(): ConnState {
  const [conn, setConn] = React.useState<ConnState>("connecting")
  const queryClient = useQueryClient()

  React.useEffect(() => {
    const close = openEventStream(
      "/v1/events",
      {
        onOpen: () => setConn("live"),
        onError: () => setConn("offline"),
        onEvent: (type) => {
          if (type.startsWith("run_") || type.startsWith("agent_")) {
            queryClient.invalidateQueries({ queryKey: ["tasks"] })
            queryClient.invalidateQueries({ queryKey: ["task"] })
          }
          if (type.startsWith("action_")) {
            queryClient.invalidateQueries({ queryKey: ["approvals"] })
          }
        },
      },
      EVENT_TYPES,
    )
    return close
  }, [queryClient])

  return conn
}

const TERMINAL_RUN_EVENT_TYPES = new Set(["run_finished", "run_failed", "run_cancelled"])

/** Per-run live event feed (mirrors the old console: replay+live, dedupe by id,
 * close on terminal, and give already-terminal runs 3s to replay). */
export function useRunEvents(runId: string | null, runStatus: string | undefined): RunEvent[] {
  const [events, setEvents] = React.useState<RunEvent[]>([])
  const seenIds = React.useRef(new Set<string>())
  const queryClient = useQueryClient()

  React.useEffect(() => {
    setEvents([])
    seenIds.current = new Set()
    if (!runId) return

    let close: (() => void) | null = null
    let timeout: ReturnType<typeof setTimeout> | null = null
    close = openEventStream(
      `/v1/runs/${runId}/events`,
      {
        onEvent: (type, data) => {
          const event = data as RunEvent
          if (event?.id) {
            if (seenIds.current.has(event.id)) return
            seenIds.current.add(event.id)
          }
          setEvents((prev) => [...prev, event])
          if (TERMINAL_RUN_EVENT_TYPES.has(type)) {
            queryClient.invalidateQueries({ queryKey: ["tasks"] })
            queryClient.invalidateQueries({ queryKey: ["task"] })
            close?.()
          }
        },
      },
      EVENT_TYPES,
    )
    if (runStatus && TERMINAL_RUN_STATUSES.has(runStatus)) {
      timeout = setTimeout(() => close?.(), 3000)
    }
    return () => {
      if (timeout) clearTimeout(timeout)
      close?.()
    }
  }, [runId, runStatus, queryClient])

  return events
}
