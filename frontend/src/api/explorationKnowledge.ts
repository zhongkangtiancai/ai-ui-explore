const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export type ExplorationSourceState = 'completed' | 'partial' | 'failed' | 'cancelled'

export interface ExplorationSourceView {
  source_id: string
  source_kind: 'task' | 'comparison'
  state: ExplorationSourceState
  page_count: number
  identity_count: number
}

export interface ExplorationKnowledgeExportRequest {
  task_ids: string[]
  comparison_ids: string[]
}

export class ExplorationKnowledgeApiError extends Error {
  constructor() {
    super('Exploration knowledge request failed')
  }
}

export async function fetchExplorationKnowledgeSources(): Promise<ExplorationSourceView[]> {
  const response = await request('/exploration-knowledge-packages/sources', {
    headers: acceptHeaders(),
  })
  if (!Array.isArray(response) || !response.every(isExplorationSourceView)) {
    throw new ExplorationKnowledgeApiError()
  }
  return response
}

export async function downloadExplorationKnowledge(
  request: ExplorationKnowledgeExportRequest,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}/exploration-knowledge-packages/export`, {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify(request),
    })
  } catch {
    throw new ExplorationKnowledgeApiError()
  }
  if (!response.ok) {
    throw new ExplorationKnowledgeApiError()
  }
  triggerJsonDownload(await response.blob(), 'exploration-knowledge-package.json')
}

async function request(path: string, init: RequestInit): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, init)
  } catch {
    throw new ExplorationKnowledgeApiError()
  }
  if (!response.ok) {
    throw new ExplorationKnowledgeApiError()
  }
  try {
    return (await response.json()) as unknown
  } catch {
    throw new ExplorationKnowledgeApiError()
  }
}

function isExplorationSourceView(value: unknown): value is ExplorationSourceView {
  if (typeof value !== 'object' || value === null) return false
  const source = value as Record<string, unknown>
  return (
    typeof source.source_id === 'string' &&
    (source.source_kind === 'task' || source.source_kind === 'comparison') &&
    ['completed', 'partial', 'failed', 'cancelled'].includes(String(source.state)) &&
    Number.isInteger(source.page_count) &&
    Number.isInteger(source.identity_count) &&
    Number(source.page_count) >= 0 &&
    Number(source.identity_count) >= 0
  )
}

function triggerJsonDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function acceptHeaders(): HeadersInit {
  return { Accept: 'application/json' }
}

function jsonHeaders(): HeadersInit {
  return { ...acceptHeaders(), 'Content-Type': 'application/json' }
}
