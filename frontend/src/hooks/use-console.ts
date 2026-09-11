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
  type DirBrowse,
  type MCPServer,
  type Memory,
  type ModelConfig,
  type ModelConfigUpdate,
  type ModelDiscover,
  type ModelVerify,
  type PermissionMode,
  type Project,
  type ProjectPayload,
  type Run,
  type RunEvent,
  type Schedule,
  type SchedulePayload,
  type Skill,
  type CompactResult,
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

export function useTaskArtifacts(taskId: string | null) {
  return useQuery({
    queryKey: ["task-artifacts", taskId],
    queryFn: () => api.get<Artifact[]>(`/v1/tasks/${encodeURIComponent(taskId!)}/artifacts`),
    enabled: !!taskId,
    staleTime: 30_000,
    // Artifacts are inlined in the chat now — there is no drawer re-open to
    // refresh them, so poll gently and pick up each finished run's manifest.
    refetchInterval: 15_000,
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

export function useMemories() {
  return useQuery({
    queryKey: ["memories"],
    queryFn: () => api.get<Memory[]>("/v1/memories"),
    staleTime: Infinity,
  })
}

export function useMemoryActions() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["memories"] })
  const add = useToastMutation<Memory, { content: string; scope?: string; type?: string }>({
    mutationFn: (payload) => api.post<Memory>("/v1/memories", payload),
    onSuccess: invalidate,
  })
  const update = useToastMutation<
    Memory,
    { id: string; content?: string; scope?: string; type?: string }
  >({
    mutationFn: ({ id, ...patch }) => api.patch<Memory>(`/v1/memories/${id}`, patch),
    onSuccess: invalidate,
  })
  const remove = useToastMutation<Memory, string>({
    mutationFn: (id) => api.del<Memory>(`/v1/memories/${id}`),
    onSuccess: invalidate,
  })
  return { add, update, remove }
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
  return useToastMutation<
    Task,
    {
      input: string
      attachments?: string[]
      project_id?: string | null
      model?: string | null
      permission_mode?: PermissionMode
    }
  >({
    mutationFn: ({ input, attachments, project_id, model, permission_mode }) =>
      api.post<Task>("/v1/tasks", {
        input,
        ...(attachments?.length ? { attachments } : {}),
        ...(project_id ? { project_id } : {}),
        ...(model ? { model } : {}),
        ...(permission_mode ? { permission_mode } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["agents"] })
    },
  })
}

export function useSendFollowup() {
  const queryClient = useQueryClient()
  return useToastMutation<
    Task,
    {
      taskId: string
      input: string
      attachments?: string[]
      model?: string | null
      permission_mode?: PermissionMode
    }
  >({
    mutationFn: ({ taskId, input, attachments, model, permission_mode }) =>
      api.post<Task>(`/v1/tasks/${taskId}/messages`, {
        input,
        ...(attachments?.length ? { attachments } : {}),
        ...(model ? { model } : {}),
        ...(permission_mode ? { permission_mode } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["task"] })
    },
  })
}

/** Upload files dropped/pasted into the chat box; returns workspace-relative paths. */
export function useUploadAttachments() {
  return useToastMutation<{ path: string; name: string; size: number }[], { files: File[] }>({
    mutationFn: ({ files }) => {
      const form = new FormData()
      for (const file of files) form.append("files", file)
      return api.upload(`/v1/attachments`, form)
    },
  })
}

export function useUpdateTask() {
  const queryClient = useQueryClient()
  return useToastMutation<Task, { taskId: string; patch: { title?: string; pinned?: boolean } }>({
    mutationFn: ({ taskId, patch }) => api.patch<Task>(`/v1/tasks/${taskId}`, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["task"] })
    },
  })
}

export function useDeleteTask() {
  const queryClient = useQueryClient()
  return useToastMutation<unknown, { taskId: string }>({
    mutationFn: ({ taskId }) => api.del(`/v1/tasks/${taskId}`),
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
  const update = useToastMutation<
    unknown,
    { serverId: string; patch: { enabled?: boolean; exposed_tools?: string[] | null } }
  >({
    mutationFn: ({ serverId, patch }) =>
      api.patch(`/v1/mcp/servers/${serverId}`, patch),
    onSuccess: invalidate,
  })
  const remove = useToastMutation<unknown, string>({
    mutationFn: (serverId) => api.del(`/v1/mcp/servers/${serverId}`),
    onSuccess: invalidate,
  })
  return { create, action, update, remove }
}

export function useSkillManage() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["skills"] })
    queryClient.invalidateQueries({ queryKey: ["agents"] })
  }
  const update = useToastMutation<unknown, { id: string; enabled: boolean }>({
    mutationFn: ({ id, enabled }) => api.patch(`/v1/skills/${id}`, { enabled }),
    onSuccess: invalidate,
  })
  const remove = useToastMutation<unknown, string>({
    mutationFn: (skillId) => api.del(`/v1/skills/${skillId}`),
    onSuccess: invalidate,
  })
  return { update, remove }
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

/** Whole-conversation event feed: one stream per task that replays every run's
 * recorded events and keeps streaming across follow-up messages, so a
 * conversation's timeline (the "运行详情" drawer) never resets when a new turn
 * starts a fresh run. Dedupes by id and stays open indefinitely — a task can
 * always be continued. */
export function useTaskEvents(taskId: string | null): RunEvent[] {
  const [events, setEvents] = React.useState<RunEvent[]>([])
  const seenIds = React.useRef(new Set<string>())
  const queryClient = useQueryClient()

  React.useEffect(() => {
    setEvents([])
    seenIds.current = new Set()
    if (!taskId) return

    let close: (() => void) | null = null
    close = openEventStream(
      `/v1/tasks/${encodeURIComponent(taskId)}/events`,
      {
        onEvent: (type, data) => {
          const event = data as RunEvent
          if (event?.id) {
            if (seenIds.current.has(event.id)) return
            seenIds.current.add(event.id)
          }
          setEvents((prev) => [...prev, event])
          if (TERMINAL_RUN_EVENT_TYPES.has(type)) {
            // Refresh task status but keep the stream open for the next turn.
            queryClient.invalidateQueries({ queryKey: ["tasks"] })
            queryClient.invalidateQueries({ queryKey: ["task"] })
          }
        },
      },
      EVENT_TYPES,
    )
    return () => close?.()
  }, [taskId, queryClient])

  return events
}

/* ------------------------------------------------------ model config */

export function useModelConfig() {
  return useQuery({
    queryKey: ["model-config"],
    queryFn: () => api.get<ModelConfig>("/v1/model-config"),
  })
}

export function useUpdateModelConfig() {
  const queryClient = useQueryClient()
  return useToastMutation<ModelConfig, ModelConfigUpdate>({
    mutationFn: (payload) => api.put<ModelConfig>("/v1/model-config", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["model-config"] })
    },
  })
}

export function useVerifyModel() {
  return useToastMutation<ModelVerify, { model?: string }>({
    mutationFn: (payload) => api.post<ModelVerify>("/v1/model-config/verify", payload),
  })
}

/* ------------------------------------------------- custom model endpoints */

export function useDiscoverModels() {
  return useToastMutation<ModelDiscover, { base_url: string; api_format: string; api_key?: string }>({
    mutationFn: (payload) => api.post<ModelDiscover>("/v1/model-config/discover", payload),
  })
}

export function useCustomModelManage() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["model-config"] })
  const upsert = useToastMutation<
    ModelConfig,
    {
      name: string
      base_url: string
      api_format: string
      api_key?: string
      models?: string[]
      catalog?: { id: string; context_window?: number | null; enabled?: boolean }[]
      context_window?: number | null
      enabled?: boolean
    }
  >({
    mutationFn: ({ name, ...payload }) => api.put(`/v1/model-config/custom/${encodeURIComponent(name)}`, payload),
    onSuccess: invalidate,
  })
  const remove = useToastMutation<ModelConfig, string>({
    mutationFn: (name) => api.del(`/v1/model-config/custom/${encodeURIComponent(name)}`),
    onSuccess: invalidate,
  })
  /** Partial edit of one provider: enable/disable, rename, endpoint fields. */
  const patch = useToastMutation<
    ModelConfig,
    {
      name: string
      newName?: string
      base_url?: string
      api_format?: string
      api_key?: string
      enabled?: boolean
      context_window?: number | null
    }
  >({
    mutationFn: ({ name, newName, ...payload }) =>
      api.patch<ModelConfig>(
        `/v1/model-config/custom/${encodeURIComponent(name)}`,
        newName ? { ...payload, name: newName } : payload,
      ),
    onSuccess: invalidate,
  })
  /** Add or update one model under a provider. */
  const upsertModel = useToastMutation<
    ModelConfig,
    { provider: string; modelId: string; context_window?: number | null; enabled?: boolean }
  >({
    mutationFn: ({ provider, modelId, ...payload }) =>
      api.put<ModelConfig>(
        `/v1/model-config/custom/${encodeURIComponent(provider)}/models/${encodeURIComponent(modelId)}`,
        payload,
      ),
    onSuccess: invalidate,
  })
  const removeModel = useToastMutation<ModelConfig, { provider: string; modelId: string }>({
    mutationFn: ({ provider, modelId }) =>
      api.del<ModelConfig>(
        `/v1/model-config/custom/${encodeURIComponent(provider)}/models/${encodeURIComponent(modelId)}`,
      ),
    onSuccess: invalidate,
  })
  return { upsert, remove, patch, upsertModel, removeModel }
}


/* ---------------------------------------------------------- projects */

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/v1/projects"),
    staleTime: Infinity,
  })
}

export function useProjectManage() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["projects"] })
    queryClient.invalidateQueries({ queryKey: ["tasks"] })
  }
  const create = useToastMutation<Project, ProjectPayload>({
    mutationFn: (payload) => api.post<Project>("/v1/projects", payload),
    onSuccess: invalidate,
  })
  const remove = useToastMutation<unknown, string>({
    mutationFn: (projectId) => api.del(`/v1/projects/${projectId}`),
    onSuccess: invalidate,
  })
  return { create, remove }
}

/** Browse a host directory's subfolders (folder-picker for adding a project).
 *  An empty path lists the home directory — always enabled while mounted. */
export function useBrowseDir(path: string | null) {
  return useQuery({
    queryKey: ["dirs", path ?? ""],
    queryFn: () =>
      api.get<DirBrowse>(`/v1/dirs/browse?path=${encodeURIComponent(path ?? "")}`),
    staleTime: 10_000,
  })
}

/* --------------------------------------------------------- task actions */

export function useCompactTask() {
  const queryClient = useQueryClient()
  return useToastMutation<CompactResult, string>({
    mutationFn: (taskId) => api.post<CompactResult>(`/v1/tasks/${taskId}/compact`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['task'] })
      queryClient.invalidateQueries({ queryKey: ['run'] })
    },
  })
}

export function useMarkTaskRead() {
  const queryClient = useQueryClient()
  return useToastMutation<Task, string>({
    mutationFn: (taskId) => api.post<Task>(`/v1/tasks/${taskId}/read`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["task"] })
    },
  })
}

/** Fetch a provider's plaintext key on demand (explicit 显示 action only). */
export function useRevealProviderKey() {
  return useToastMutation<
    { name: string; api_key: string | null; source: "page" | "env" | null },
    string
  >({
    mutationFn: (name) => api.get(`/v1/model-config/custom/${encodeURIComponent(name)}/key`),
  })
}

/** Probe a SAVED provider's model list (server uses its stored key). */
export function useDiscoverProviderModels() {
  return useToastMutation<ModelDiscover, string>({
    mutationFn: (name) =>
      api.post<ModelDiscover>(`/v1/model-config/custom/${encodeURIComponent(name)}/discover`),
  })
}

/** Batch-add discovered models to an existing provider. */
export function useAddProviderModels() {
  const queryClient = useQueryClient()
  return useToastMutation<
    ModelConfig,
    { provider: string; models: string[]; context_window?: number | null }
  >({
    mutationFn: ({ provider, ...payload }) =>
      api.post<ModelConfig>(
        `/v1/model-config/custom/${encodeURIComponent(provider)}/models`,
        payload,
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["model-config"] }),
  })
}
