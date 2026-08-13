import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import ExplorationEvidenceBrowser from '../src/components/ExplorationEvidenceBrowser.vue'

const { fetchPages, fetchDetail, download } = vi.hoisted(() => ({
  fetchPages: vi.fn(),
  fetchDetail: vi.fn(),
  download: vi.fn(),
}))

vi.mock('../src/api/explorationTasks', () => ({
  fetchExplorationTaskPages: fetchPages,
  fetchExplorationTaskPageDetail: fetchDetail,
  downloadExplorationTaskEvidence: download,
}))

describe('ExplorationEvidenceBrowser', () => {
  it('lists pages and shows collected locator details as text only after selection', async () => {
    fetchPages.mockResolvedValue([
      {
        page_id: 'page-1',
        page_key: 'https://app.example.test/dashboard',
        frame_count: 1,
        element_count: 1,
        link_count: 0,
        status: 'observed',
        reason_codes: [],
        evidence_refs: [],
      },
    ])
    fetchDetail.mockResolvedValue({
      page_key: 'https://app.example.test/dashboard',
      evidence_refs: [],
      elements: [
        {
          element_key: 'main:save',
          frame_path: 'main',
          tag: 'button',
          role: 'button',
          accessible_name: 'Save',
          text: null,
          attributes: {},
          href: null,
          visible: true,
          enabled: true,
          bounds: { x: 1, y: 2, width: 100, height: 32 },
          locator_hints: ['locator-save-role'],
          locator_candidates: [{ strategy: 'role', parameters: { name: 'Save' }, rank: 1 }],
          evidence_refs: [],
        },
      ],
    })
    const wrapper = mount(ExplorationEvidenceBrowser, {
      props: { taskId: 'task-1', taskState: 'completed' },
    })
    await flushPromises()
    await wrapper.get('[data-test="evidence-page"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('role')
    expect(wrapper.text()).toContain('Save')
    expect(wrapper.html().toLowerCase()).not.toContain('<html')
  })

  it('shows partial limitations and delegates export download', async () => {
    fetchPages.mockResolvedValue([])
    const wrapper = mount(ExplorationEvidenceBrowser, {
      props: { taskId: 'task-1', taskState: 'partial' },
    })
    await flushPromises()
    await wrapper.get('[data-test="download-evidence"]').trigger('click')

    expect(wrapper.text()).toContain('采集不完整')
    expect(download).toHaveBeenCalledWith('task-1')
  })
})
