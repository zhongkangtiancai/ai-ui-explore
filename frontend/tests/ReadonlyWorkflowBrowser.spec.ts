import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import ReadonlyWorkflowBrowser from '../src/components/ReadonlyWorkflowBrowser.vue'

const { fetchWorkflow } = vi.hoisted(() => ({
  fetchWorkflow: vi.fn(),
}))

vi.mock('../src/api/explorationTasks', () => ({
  fetchExplorationTaskWorkflow: fetchWorkflow,
}))

describe('ReadonlyWorkflowBrowser', () => {
  it('renders untrusted workflow text through interpolation and labels partial results incomplete', async () => {
    fetchWorkflow.mockResolvedValue({
      task_id: 'task-1',
      state: 'partial',
      nodes: [{ state: 'a'.repeat(64) }, { state: 'b'.repeat(64) }],
      steps: [
        {
          step_id: 'step-1111111111111111',
          kind: 'open_menu',
          target_summary: '<img src=x onerror=alert(1)>',
          before_state: 'a'.repeat(64),
          after_state: 'b'.repeat(64),
          status: 'executed',
          reason_code: 'executed',
          evidence_refs: [],
        },
      ],
      edges: [
        {
          edge_id: 'edge-2222222222222222',
          source_state: 'a'.repeat(64),
          target_state: 'b'.repeat(64),
          kind: 'open_menu',
          observation_count: 1,
          evidence_refs: [],
        },
      ],
    })

    const wrapper = mount(ReadonlyWorkflowBrowser, {
      props: { taskId: 'task-1', taskState: 'partial' },
    })
    await flushPromises()

    expect(wrapper.get('[data-test="workflow-partial"]').text()).toContain('不完整')
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
    expect(wrapper.html()).not.toContain('<img src=x')
    expect(wrapper.text()).toContain('open_menu')
    expect(wrapper.text()).toContain('观察次数：1')
  })

  it('shows a fixed safe error when the workflow response is unavailable', async () => {
    fetchWorkflow.mockRejectedValue(new Error('token=not-for-display'))

    const wrapper = mount(ReadonlyWorkflowBrowser, {
      props: { taskId: 'task-1', taskState: 'completed' },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('流程暂时无法读取。')
    expect(wrapper.text()).not.toContain('not-for-display')
  })
})
