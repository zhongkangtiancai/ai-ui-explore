const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export type TaskState =
  | 'created'
  | 'paused_for_human'
  | 'collecting'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'cancelled'

export interface ExplorationBudget {
  max_pages: number
  max_depth: number
  max_queue_size: number
}

export interface ModuleEntry {
  module_id: string
  url: string
  label?: string
}

export interface AuthenticationPlan {
  authentication_url: string
  post_login_url_prefix: string
  checkpoint_css_selector: string
}

export interface CreateExplorationTaskRequest {
  module_entry: ModuleEntry
  allowed_origins: string[]
  authentication_origins: string[]
  budget: ExplorationBudget
  authentication_plan?: AuthenticationPlan
  allow_local_http: boolean
}

export interface TaskEventView {
  event_type: string
  reason_code: string | null
  checkpoint_id: string | null
  occurred_at: string
}

export interface TaskResultSummary {
  page_count: number
  element_count: number
  link_count: number
  source_summary: string
}

export interface TaskSummary {
  task_id: string
  state: TaskState
  phase: string
  created_at: string
  updated_at: string
  redaction_count: number
  events: TaskEventView[]
  result: TaskResultSummary
}

export interface EvidenceReference {
  evidence_id: string
  snapshot_id: string
  snapshot_schema_version: string
  snapshot_sha256: string
  json_pointer: string
  excerpt: string
}

export interface TaskPageView {
  page_id: string
  page_key: string
  frame_count: number
  element_count: number
  link_count: number
  status: 'observed'
  reason_codes: string[]
  evidence_refs: EvidenceReference[]
}

export interface LocatorCandidateEvidence {
  locator_id?: string
  strategy: string
  parameters: Record<string, string | boolean | number>
  rank: number
  recommended?: boolean
  uniqueness?: string
  stability?: string
  confidence?: number
  frame_path?: string
  limitations?: string[]
  evidence_refs?: EvidenceReference[]
}

export interface PageElementEvidence {
  element_key: string
  frame_path: string
  tag: string
  role: string | null
  accessible_name: string | null
  text: string | null
  attributes: Record<string, string>
  href: string | null
  visible: boolean | null
  enabled: boolean | null
  bounds: { x: number; y: number; width: number; height: number } | null
  locator_hints: string[]
  locator_candidates: LocatorCandidateEvidence[]
  evidence_refs: EvidenceReference[]
}

export interface PageEvidence {
  page_key: string
  elements: PageElementEvidence[]
  evidence_refs: EvidenceReference[]
}

export class ExplorationTaskApiError extends Error {
  constructor() {
    super('Exploration task request failed')
  }
}

export async function createExplorationTask(
  payload: CreateExplorationTaskRequest,
): Promise<TaskSummary> {
  return request<TaskSummary>('/exploration-tasks', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })
}

export async function fetchExplorationTask(taskId: string): Promise<TaskSummary> {
  return request<TaskSummary>(`/exploration-tasks/${encodeURIComponent(taskId)}`, {
    headers: acceptHeaders(),
  })
}

export async function fetchExplorationTaskEvents(taskId: string): Promise<TaskEventView[]> {
  const response = await request<{ events: TaskEventView[] }>(
    `/exploration-tasks/${encodeURIComponent(taskId)}/events`,
    { headers: acceptHeaders() },
  )
  return response.events
}

export async function fetchExplorationTaskResult(taskId: string): Promise<TaskResultSummary> {
  return request<TaskResultSummary>(`/exploration-tasks/${encodeURIComponent(taskId)}/result`, {
    headers: acceptHeaders(),
  })
}

export async function fetchExplorationTaskPages(taskId: string): Promise<TaskPageView[]> {
  return request<TaskPageView[]>(`/exploration-tasks/${encodeURIComponent(taskId)}/pages`, {
    headers: acceptHeaders(),
  })
}

export async function fetchExplorationTaskPageDetail(
  taskId: string,
  pageId: string,
): Promise<PageEvidence> {
  return request<PageEvidence>(
    `/exploration-tasks/${encodeURIComponent(taskId)}/pages/${encodeURIComponent(pageId)}`,
    { headers: acceptHeaders() },
  )
}

export async function downloadExplorationTaskEvidence(taskId: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}/exploration-tasks/${encodeURIComponent(taskId)}/export`, {
      headers: acceptHeaders(),
    })
  } catch {
    throw new ExplorationTaskApiError()
  }
  if (!response.ok) {
    throw new ExplorationTaskApiError()
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'exploration-evidence.json'
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function confirmExplorationTaskLogin(taskId: string): Promise<TaskSummary> {
  return request<TaskSummary>(`/exploration-tasks/${encodeURIComponent(taskId)}/confirm-login`, {
    method: 'POST',
    headers: acceptHeaders(),
  })
}

export async function cancelExplorationTask(taskId: string): Promise<TaskSummary> {
  return request<TaskSummary>(`/exploration-tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: 'POST',
    headers: acceptHeaders(),
  })
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, init)
  } catch {
    throw new ExplorationTaskApiError()
  }

  if (!response.ok) {
    throw new ExplorationTaskApiError()
  }

  try {
    return (await response.json()) as T
  } catch {
    throw new ExplorationTaskApiError()
  }
}

function acceptHeaders(): HeadersInit {
  return { Accept: 'application/json' }
}

function jsonHeaders(): HeadersInit {
  return {
    ...acceptHeaders(),
    'Content-Type': 'application/json',
  }
}
