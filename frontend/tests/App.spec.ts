import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.vue'

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
})
