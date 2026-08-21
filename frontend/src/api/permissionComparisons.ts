const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export type ComparisonState =
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

export interface AuthenticationPlan {
  authentication_url: string
  post_login_url_prefix: string
  checkpoint_css_selector: string
}

export interface IdentityProfile {
  identity_id: string
  label: string
  authentication_plan?: AuthenticationPlan
}

export interface CreatePermissionComparisonRequest {
  module_entry: { module_id: string; url: string; label?: string }
  allowed_origins: string[]
  authentication_origins: string[]
  budget: ExplorationBudget
  identities: IdentityProfile[]
  allow_local_http: boolean
}

export interface VisibilityDifference {
  difference_id: string
  kind: string
  subject_key: string
  identity_states: Record<string, string>
  evidence_refs: object[]
  reason_codes: string[]
  reliability: 'high' | 'medium' | 'low' | 'inconclusive'
}

export interface PermissionComparisonResult {
  comparison_id: string
  status: 'completed' | 'partial' | 'failed' | 'cancelled'
  identities: object[]
  differences: VisibilityDifference[]
}

export interface PermissionComparison {
  comparison_id: string
  state: ComparisonState
  identities: Record<string, string>
  result: PermissionComparisonResult | null
}

export class PermissionComparisonApiError extends Error {
  constructor() {
    super('Permission comparison request failed')
  }
}

export async function createPermissionComparison(
  payload: CreatePermissionComparisonRequest,
): Promise<PermissionComparison> {
  return request<PermissionComparison>('/permission-comparisons', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  })
}

export async function fetchPermissionComparison(
  comparisonId: string,
): Promise<PermissionComparison> {
  return request<PermissionComparison>(
    `/permission-comparisons/${encodeURIComponent(comparisonId)}`,
    {
      headers: acceptHeaders(),
    },
  )
}

export async function confirmPermissionComparisonLogin(
  comparisonId: string,
  identityId: string,
): Promise<PermissionComparison> {
  return request<PermissionComparison>(
    `/permission-comparisons/${encodeURIComponent(comparisonId)}/identities/${encodeURIComponent(identityId)}/confirm-login`,
    { method: 'POST', headers: acceptHeaders() },
  )
}

export async function cancelPermissionComparison(
  comparisonId: string,
): Promise<PermissionComparison> {
  return request<PermissionComparison>(
    `/permission-comparisons/${encodeURIComponent(comparisonId)}/cancel`,
    { method: 'POST', headers: acceptHeaders() },
  )
}

export async function downloadPermissionComparison(comparisonId: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(
      `${apiBaseUrl}/permission-comparisons/${encodeURIComponent(comparisonId)}/export`,
      {
        headers: acceptHeaders(),
      },
    )
  } catch {
    throw new PermissionComparisonApiError()
  }
  if (!response.ok) {
    throw new PermissionComparisonApiError()
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'permission-comparison.json'
  anchor.click()
  URL.revokeObjectURL(url)
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, init)
  } catch {
    throw new PermissionComparisonApiError()
  }
  if (!response.ok) {
    throw new PermissionComparisonApiError()
  }
  try {
    return (await response.json()) as T
  } catch {
    throw new PermissionComparisonApiError()
  }
}

function acceptHeaders(): HeadersInit {
  return { Accept: 'application/json' }
}

function jsonHeaders(): HeadersInit {
  return { ...acceptHeaders(), 'Content-Type': 'application/json' }
}
