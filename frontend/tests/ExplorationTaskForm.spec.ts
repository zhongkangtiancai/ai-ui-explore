import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ExplorationTaskForm from '../src/components/ExplorationTaskForm.vue'

describe('ExplorationTaskForm', () => {
  it('only reveals login fields when manual login is selected', async () => {
    const wrapper = mount(ExplorationTaskForm)

    expect(wrapper.text()).not.toContain('认证检查点')

    await wrapper.get('[data-test="manual-login"]').setValue(true)

    expect(wrapper.text()).toContain('认证检查点')
  })

  it('emits an allowlisted creation request without login configuration by default', async () => {
    const wrapper = mount(ExplorationTaskForm)

    await wrapper.get('[data-test="module-id"]').setValue('dashboard')
    await wrapper.get('[data-test="module-url"]').setValue('https://app.example.test/dashboard')
    await wrapper.get('[data-test="allowed-origin"]').setValue('https://app.example.test')
    await wrapper.get('form').trigger('submit.prevent')

    expect(wrapper.emitted('submit')).toEqual([
      [
        {
          module_entry: {
            module_id: 'dashboard',
            url: 'https://app.example.test/dashboard',
            label: undefined,
          },
          allowed_origins: ['https://app.example.test'],
          authentication_origins: [],
          budget: { max_pages: 20, max_depth: 2, max_queue_size: 100 },
          authentication_plan: undefined,
          allow_local_http: false,
        },
      ],
    ])
  })

  it('allows local HTTP only after the user explicitly enables it', async () => {
    const wrapper = mount(ExplorationTaskForm)

    await wrapper.get('[data-test="module-id"]').setValue('local-dashboard')
    await wrapper.get('[data-test="module-url"]').setValue('http://127.0.0.1:9100')
    await wrapper.get('[data-test="allowed-origin"]').setValue('http://127.0.0.1:9100')
    await wrapper.get('[data-test="allow-local-http"]').setValue(true)
    await wrapper.get('form').trigger('submit.prevent')

    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({
      allow_local_http: true,
    })
  })

  it('emits explicit authentication configuration only when manual login is selected', async () => {
    const wrapper = mount(ExplorationTaskForm)

    await wrapper.get('[data-test="module-id"]').setValue('dashboard')
    await wrapper.get('[data-test="module-url"]').setValue('https://app.example.test/dashboard')
    await wrapper.get('[data-test="allowed-origin"]').setValue('https://app.example.test')
    await wrapper.get('[data-test="manual-login"]').setValue(true)
    await wrapper.get('[data-test="authentication-origin"]').setValue('https://login.example.test')
    await wrapper
      .get('[data-test="authentication-url"]')
      .setValue('https://login.example.test/sign-in')
    await wrapper
      .get('[data-test="post-login-url-prefix"]')
      .setValue('https://app.example.test/dashboard')
    await wrapper.get('[data-test="checkpoint-css"]').setValue('#authenticated-marker')
    await wrapper.get('form').trigger('submit.prevent')

    expect(wrapper.emitted('submit')?.[0]?.[0]).toEqual({
      module_entry: {
        module_id: 'dashboard',
        url: 'https://app.example.test/dashboard',
        label: undefined,
      },
      allowed_origins: ['https://app.example.test'],
      authentication_origins: ['https://login.example.test'],
      budget: { max_pages: 20, max_depth: 2, max_queue_size: 100 },
      authentication_plan: {
        authentication_url: 'https://login.example.test/sign-in',
        post_login_url_prefix: 'https://app.example.test/dashboard',
        checkpoint_css_selector: '#authenticated-marker',
      },
      allow_local_http: false,
    })
  })
})
