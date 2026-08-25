import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ExplorationTaskDetail from '../src/components/ExplorationTaskDetail.vue'
import type { TaskSummary } from '../src/api/explorationTasks'

const pausedTask: TaskSummary = {
  task_id: 'task-1',
  state: 'paused_for_human',
  phase: 'awaiting_human',
  created_at: '2026-08-11T00:00:00Z',
  updated_at: '2026-08-11T00:00:01Z',
  redaction_count: 0,
  events: [
    {
      event_type: 'paused_for_human',
      reason_code: 'authentication_required',
      checkpoint_id: null,
      occurred_at: '2026-08-11T00:00:01Z',
    },
  ],
  result: {
    page_count: 0,
    element_count: 0,
    link_count: 0,
    source_summary: 'redacted source',
  },
}

describe('ExplorationTaskDetail', () => {
  it('shows confirm only while paused for human', () => {
    const wrapper = mount(ExplorationTaskDetail, { props: { task: pausedTask } })

    expect(wrapper.find('[data-test="confirm-login"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('请在本机可见浏览器完成登录')
  })

  it('emits confirmation and cancellation requests from the safe action buttons', async () => {
    const wrapper = mount(ExplorationTaskDetail, { props: { task: pausedTask } })

    await wrapper.get('[data-test="confirm-login"]').trigger('click')
    await wrapper.get('[data-test="cancel-task"]').trigger('click')

    expect(wrapper.emitted('confirm-login')).toEqual([[]])
    expect(wrapper.emitted('cancel')).toEqual([[]])
  })

  it('hides confirm and cancel actions after a terminal state', () => {
    const wrapper = mount(ExplorationTaskDetail, {
      props: {
        task: {
          ...pausedTask,
          state: 'completed',
          phase: 'completed',
        },
      },
    })

    expect(wrapper.find('[data-test="confirm-login"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="cancel-task"]').exists()).toBe(false)
  })

  it('explains that a task interrupted by restart cannot be resumed', () => {
    const wrapper = mount(ExplorationTaskDetail, {
      props: {
        task: {
          ...pausedTask,
          state: 'failed',
          phase: 'interrupted',
          events: [
            {
              event_type: 'process_restarted',
              reason_code: 'process_restarted',
              checkpoint_id: null,
              occurred_at: '2026-08-20T00:00:00Z',
            },
          ],
        },
      },
    })

    expect(wrapper.text()).toContain('服务重启时任务尚未完成，已安全终止且不能继续。')
    expect(wrapper.find('[data-test="confirm-login"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="cancel-task"]').exists()).toBe(false)
  })

  it('renders only the safe audit and result summary values', () => {
    const wrapper = mount(ExplorationTaskDetail, { props: { task: pausedTask } })

    expect(wrapper.text()).toContain('paused_for_human')
    expect(wrapper.text()).toContain('页面：0')
    expect(wrapper.text()).toContain('redacted source')
  })
})
