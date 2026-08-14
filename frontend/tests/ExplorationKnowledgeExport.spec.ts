import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../src/api/explorationKnowledge', () => ({
  downloadExplorationKnowledge: vi.fn(),
  fetchExplorationKnowledgeSources: vi.fn(),
}))

import {
  downloadExplorationKnowledge,
  fetchExplorationKnowledgeSources,
} from '../src/api/explorationKnowledge'
import ExplorationKnowledgeExport from '../src/components/ExplorationKnowledgeExport.vue'

describe('ExplorationKnowledgeExport', () => {
  it('selects terminal task and comparison sources and requests a JSON download', async () => {
    vi.mocked(fetchExplorationKnowledgeSources).mockResolvedValue([
      {
        source_id: 'task-1',
        source_kind: 'task',
        state: 'completed',
        page_count: 1,
        identity_count: 0,
      },
      {
        source_id: 'comparison-1',
        source_kind: 'comparison',
        state: 'partial',
        page_count: 2,
        identity_count: 2,
      },
    ])

    const wrapper = mount(ExplorationKnowledgeExport)
    await flushPromises()
    await wrapper.get('[data-test="source-task-1"]').setValue(true)
    await wrapper.get('[data-test="source-comparison-1"]').setValue(true)
    await wrapper.get('[data-test="download-knowledge"]').trigger('click')

    expect(downloadExplorationKnowledge).toHaveBeenCalledWith({
      task_ids: ['task-1'],
      comparison_ids: ['comparison-1'],
    })
  })

  it('renders source values as text and emits only a generic error', async () => {
    vi.mocked(fetchExplorationKnowledgeSources).mockResolvedValue([
      {
        source_id: '<img src=x onerror=alert(1)>',
        source_kind: 'task',
        state: 'failed',
        page_count: 0,
        identity_count: 0,
      },
    ])
    const wrapper = mount(ExplorationKnowledgeExport)
    await flushPromises()

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')

    vi.mocked(downloadExplorationKnowledge).mockRejectedValue(new Error('token=do-not-render'))
    await wrapper.get('[data-test="source-<img src=x onerror=alert(1)>"]').setValue(true)
    await wrapper.get('[data-test="download-knowledge"]').trigger('click')

    expect(wrapper.emitted('error')).toEqual([[]])
    expect(wrapper.text()).not.toContain('do-not-render')
  })
})
