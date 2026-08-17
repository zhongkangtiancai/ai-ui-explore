import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../src/api/explorationTasks', () => ({
  cancelExplorationTask: vi.fn(),
  confirmExplorationTaskLogin: vi.fn(),
  createExplorationTask: vi.fn(),
  downloadExplorationTaskEvidence: vi.fn(),
  fetchExplorationTask: vi.fn(),
  fetchExplorationTaskPageDetail: vi.fn(),
  fetchExplorationTaskPages: vi.fn(),
  fetchExplorationTaskWorkflow: vi.fn(),
}))

vi.mock('../src/api/permissionComparisons', () => ({
  cancelPermissionComparison: vi.fn(),
  confirmPermissionComparisonLogin: vi.fn(),
  createPermissionComparison: vi.fn(),
  downloadPermissionComparison: vi.fn(),
  fetchPermissionComparison: vi.fn(),
}))

vi.mock('../src/api/explorationKnowledge', () => ({
  downloadExplorationKnowledge: vi.fn(),
  fetchExplorationKnowledgeSources: vi.fn(),
}))

import App from '../src/App.vue'
import {
  confirmExplorationTaskLogin,
  createExplorationTask,
  fetchExplorationTask,
  fetchExplorationTaskPages,
  fetchExplorationTaskWorkflow,
  type TaskSummary,
} from '../src/api/explorationTasks'
import {
  createPermissionComparison,
  fetchPermissionComparison,
  type PermissionComparison,
} from '../src/api/permissionComparisons'

const createdTask: TaskSummary = {
  task_id: 'task-1',
  state: 'paused_for_human',
  phase: 'awaiting_human',
  created_at: '2026-08-11T00:00:00Z',
  updated_at: '2026-08-11T00:00:00Z',
  redaction_count: 0,
  events: [],
  result: {
    page_count: 0,
    element_count: 0,
    link_count: 0,
    source_summary: 'redacted source',
  },
}

const completedComparison: PermissionComparison = {
  comparison_id: 'comparison-1',
  state: 'completed',
  identities: { 'identity-1': 'completed', 'identity-2': 'completed' },
  result: { comparison_id: 'comparison-1', status: 'completed', identities: [], differences: [] },
}

describe('App', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a connecting state while the health request is pending', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => undefined)),
    )

    const wrapper = mount(App)

    expect(wrapper.text()).toContain('正在连接后端服务')
  })

  it('shows service metadata after a successful health request', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: 'ok',
          service: 'ai-ui-explorer-backend',
          version: '0.1.0',
          environment: 'development',
        }),
      }),
    )

    const wrapper = mount(App)
    await flushPromises()

    expect(wrapper.text()).toContain('服务正常')
    expect(wrapper.text()).toContain('development')
    expect(wrapper.text()).toContain('0.1.0')
  })

  it('shows a safe error state when the backend is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('secret internal error')))

    const wrapper = mount(App)
    await flushPromises()

    expect(wrapper.text()).toContain('连接异常')
    expect(wrapper.text()).toContain('请确认后端服务已经启动')
    expect(wrapper.text()).not.toContain('secret internal error')
  })

  it('shows a safe task error instead of API failure details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: 'ok',
          service: 'ai-ui-explorer-backend',
          version: '0.1.0',
          environment: 'development',
        }),
      }),
    )
    vi.mocked(createExplorationTask).mockRejectedValue(new Error('token=secret-value'))

    const wrapper = mount(App)
    await flushPromises()
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('任务操作未完成，请检查安全配置后重试。')
    expect(wrapper.text()).not.toContain('secret-value')
  })

  it('confirms a paused task and starts polling it', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: 'ok',
          service: 'ai-ui-explorer-backend',
          version: '0.1.0',
          environment: 'development',
        }),
      }),
    )
    vi.mocked(createExplorationTask).mockResolvedValue(createdTask)
    vi.mocked(confirmExplorationTaskLogin).mockResolvedValue({
      ...createdTask,
      state: 'collecting',
      phase: 'collecting',
    })
    vi.mocked(fetchExplorationTask).mockResolvedValue({
      ...createdTask,
      state: 'collecting',
      phase: 'collecting',
    })

    const wrapper = mount(App)
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    await wrapper.get('[data-test="confirm-login"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(2000)

    expect(confirmExplorationTaskLogin).toHaveBeenCalledWith('task-1')
    expect(fetchExplorationTask).toHaveBeenCalledWith('task-1')

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('stops polling a terminal task', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: 'ok',
          service: 'ai-ui-explorer-backend',
          version: '0.1.0',
          environment: 'development',
        }),
      }),
    )
    vi.mocked(createExplorationTask).mockResolvedValue({
      ...createdTask,
      state: 'completed',
      phase: 'completed',
    })

    const wrapper = mount(App)
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(4000)

    expect(fetchExplorationTask).not.toHaveBeenCalled()

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('embeds the read-only evidence browser for a completed task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: 'ok',
          service: 'backend',
          version: '0.1.0',
          environment: 'development',
        }),
      }),
    )
    vi.mocked(fetchExplorationTaskPages).mockResolvedValue([])
    vi.mocked(fetchExplorationTaskWorkflow).mockResolvedValue({
      task_id: 'task-1',
      state: 'completed',
      nodes: [],
      steps: [],
      edges: [],
    })
    vi.mocked(createExplorationTask).mockResolvedValue({
      ...createdTask,
      state: 'completed',
      phase: 'completed',
    })

    const wrapper = mount(App)
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('探索明细')
    expect(wrapper.text()).toContain('已采集的脱敏证据')
    expect(wrapper.text()).toContain('已观察到的状态变化')
  })

  it('stops polling after a terminal comparison', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: 'ok',
          service: 'backend',
          version: '0.1.0',
          environment: 'development',
        }),
      }),
    )
    vi.mocked(createPermissionComparison).mockResolvedValue(completedComparison)

    const wrapper = mount(App)
    await wrapper.get('[data-test="comparison-mode"]').trigger('click')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(4000)

    expect(fetchPermissionComparison).not.toHaveBeenCalled()
    wrapper.unmount()
    vi.useRealTimers()
  })
})
