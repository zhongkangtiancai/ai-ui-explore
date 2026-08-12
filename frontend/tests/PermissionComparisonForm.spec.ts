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
      identities: [
        { identity_id: 'identity-1', label: '管理员' },
        { identity_id: 'identity-2', label: '普通用户' },
      ],
    })
  })
})
