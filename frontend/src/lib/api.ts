/* API client: token gate + JSON fetch + SSE helpers. */

export const TOKEN_KEY = 'console_token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

/** Raised on any non-2xx; `unauthorized` drives the token dialog. */
export class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, path: string, body: unknown) {
    const detail =
      body && typeof body === 'object' && 'error' in body
        ? String((body as { error: { message?: string } }).error?.message ?? '')
        : ''
    super(detail || `${status} ${path}`)
    this.status = status
    this.body = body
  }

  get unauthorized() {
    return this.status === 401
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  // FormData carries its own multipart content-type (with boundary); JSON bodies
  // get the default application/json. Don't override either.
  if (!headers.has('Content-Type') && options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getToken()
  if (token) headers.set('X-Console-Token', token)

  const response = await fetch(path, { ...options, headers })
  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      /* non-JSON error body */
    }
    if (response.status === 401) {
      // Any unauthorized reply pops the token dialog (App listens for this).
      window.dispatchEvent(new Event('console:unauthorized'))
    }
    throw new ApiError(response.status, path, body)
  }
  // 204 No Content (e.g. DELETE) carries no body — calling .json() on it
  // throws "Unexpected end of JSON input".
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  /** Multipart upload: sends FormData; the browser sets the content type + boundary. */
  upload: <T>(path: string, formData: FormData) =>
    request<T>(path, { method: 'POST', body: formData }),
}

/** EventSource cannot send headers — the API accepts the token as a query param. */
export function withToken(url: string): string {
  const token = getToken()
  if (!token) return url
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
}

/** Download/preview URL for artifacts (token in query, browser navigates directly). */
export function artifactUrl(runId: string, path: string): string {
  return withToken(`/v1/artifacts/${runId}/download?path=${encodeURIComponent(path)}`)
}

/** Subscribe to the global event stream; returns a closer. */
export function openEventStream(
  url: string,
  handlers: {
    onOpen?: () => void
    onEvent?: (eventType: string, data: unknown) => void
    onError?: () => void
  },
  eventTypes: readonly string[],
): () => void {
  const source = new EventSource(withToken(url))
  source.onopen = () => handlers.onOpen?.()
  source.onerror = () => handlers.onError?.()
  for (const type of eventTypes) {
    source.addEventListener(type, (e: MessageEvent) => {
      let data: unknown = null
      try {
        data = JSON.parse(e.data)
      } catch {
        data = e.data
      }
      handlers.onEvent?.(type, data)
    })
  }
  return () => source.close()
}
