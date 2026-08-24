import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PermissionComparisonForm from '../src/components/PermissionComparisonForm.vue'

describe('PermissionComparisonForm', () => {
  it('requires two safe identity aliases and never renders credential inputs', async () => {
    const wrapper = mount(PermissionComparisonForm)

    expect(wrapper.findAll('[data-test="identity-label"]').length).toBe(2)
    expect(wrapper.html().toLowerCase()).not.toContain('password')
    expect(wrapper.html().toLowerCase()).not.toContain('cookie')
    await wrapper.get('[data-test="add-identity"]').trigger('click')
    expect(wrapper.findAll('[data-test="identity-label"]').length).toBe(3)
  })

  it('emits a common safe configuration with two identities', async () => {
    const wrapper = mount(PermissionComparisonForm)

    await wrapper.get('[data-test="module-id"]').setValue('dashboard')
    await wrapper.get('[data-test="module-url"]').setValue('https://app.example.test/dashboard')
    await wrapper.get('[data-test="allowed-origin"]').setValue('https://app.example.test')
    await wrapper.findAll('[data-test="identity-label"]')[0].setValue('管理员')
    await wrapper.findAll('[data-test="identity-label"]')[1].setValue('普通用户')
    await wrapper.get('form').trigger('submit.prevent')

    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({
      module_entry: { module_id: 'dashboard', url: 'https://app.example.test/dashboard' },
      allowed_origins: ['https://app.example.test'],
      authentication_origins: [],
      allow_local_http: false,
      identities: [
        { identity_id: 'identity-1', label: '管理员', authentication_plan: undefined },
        { identity_id: 'identity-2', label: '普通用户', authentication_plan: undefined },
      ],
    })
  })

  it('copies an explicit human-login plan to every identity only when enabled', async () => {
    const wrapper = mount(PermissionComparisonForm)

    await wrapper.get('[data-test="module-id"]').setValue('dashboard')
    await wrapper.get('[data-test="module-url"]').setValue('http://127.0.0.1:9100/dashboard.html')
    await wrapper.get('[data-test="allowed-origin"]').setValue('http://127.0.0.1:9100')
    await wrapper.findAll('[data-test="identity-label"]')[0].setValue('管理员')
    await wrapper.findAll('[data-test="identity-label"]')[1].setValue('普通用户')
    await wrapper.get('[data-test="manual-login"]').setValue(true)
    await wrapper.get('[data-test="allow-local-http"]').setValue(true)
    await wrapper.get('[data-test="authentication-origin"]').setValue('http://127.0.0.1:9100')
    await wrapper
      .get('[data-test="authentication-url"]')
      .setValue('http://127.0.0.1:9100/login.html')
    await wrapper
      .get('[data-test="post-login-url-prefix"]')
      .setValue('http://127.0.0.1:9100/dashboard.html')
    await wrapper.get('[data-test="checkpoint-css"]').setValue('#signed-in-marker')
    await wrapper.get('form').trigger('submit.prevent')

    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({
      authentication_origins: ['http://127.0.0.1:9100'],
      allow_local_http: true,
      identities: [
        {
          authentication_plan: {
            authentication_url: 'http://127.0.0.1:9100/login.html',
            post_login_url_prefix: 'http://127.0.0.1:9100/dashboard.html',
            checkpoint_css_selector: '#signed-in-marker',
          },
        },
        {
          authentication_plan: {
            authentication_url: 'http://127.0.0.1:9100/login.html',
            post_login_url_prefix: 'http://127.0.0.1:9100/dashboard.html',
            checkpoint_css_selector: '#signed-in-marker',
          },
        },
      ],
    })
    expect(wrapper.html().toLowerCase()).not.toContain('password')
  })
})
