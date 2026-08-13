import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  cancelExplorationTask,
  confirmExplorationTaskLogin,
  createExplorationTask,
  downloadExplorationTaskEvidence,
  fetchExplorationTaskPageDetail,
  fetchExplorationTaskPages,
} from '../src/api/explorationTasks'

describe('exploration task API client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('creates an allowlisted task request through the configured API base URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ task_id: 'task-1' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await createExplorationTask({
      module_entry: {
        module_id: 'dashboard',
        url: 'https://app.example.test/dashboard',
      },
      allowed_origins: ['https://app.example.test'],
      authentication_origins: [],
      budget: { max_pages: 20, max_depth: 2, max_queue_size: 100 },
      allow_local_http: false,
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/exploration-tasks', {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        module_entry: {
          module_id: 'dashboard',
          url: 'https://app.example.test/dashboard',
        },
        allowed_origins: ['https://app.example.test'],
        authentication_origins: [],
        budget: { max_pages: 20, max_depth: 2, max_queue_size: 100 },
        allow_local_http: false,
      }),
    })
  })

  it('sends confirm and cancel requests without a body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ task_id: 'task-1' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await confirmExplorationTaskLogin('task-1')
    await cancelExplorationTask('task-1')

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/exploration-tasks/task-1/confirm-login', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/exploration-tasks/task-1/cancel', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    })
  })

  it('reads page evidence and downloads its export through read-only endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ page_id: 'page-1' }],
      blob: async () => new Blob(['{}'], { type: 'application/json' }),
    })
    const click = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:fixture'), revokeObjectURL: vi.fn() })
    vi.spyOn(document, 'createElement').mockReturnValue({ click } as unknown as HTMLAnchorElement)

    await fetchExplorationTaskPages('task-1')
    await fetchExplorationTaskPageDetail('task-1', 'page-1')
    await downloadExplorationTaskEvidence('task-1')

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/exploration-tasks/task-1/pages', {
      headers: { Accept: 'application/json' },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/exploration-tasks/task-1/pages/page-1', {
      headers: { Accept: 'application/json' },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/v1/exploration-tasks/task-1/export', {
      headers: { Accept: 'application/json' },
    })
    expect(click).toHaveBeenCalledOnce()
  })
})
