import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { PermissionComparison } from '../src/api/permissionComparisons'
import PermissionComparisonDetail from '../src/components/PermissionComparisonDetail.vue'

const inconclusiveComparison: PermissionComparison = {
  comparison_id: 'comparison-1',
  state: 'partial',
  identities: { 'identity-1': 'completed', 'identity-2': 'partial' },
  result: {
    comparison_id: 'comparison-1',
    status: 'partial',
    identities: [],
    differences: [
      {
        difference_id: 'difference-1',
        kind: 'observed_in_only_one_identity',
        subject_key: 'page:https://app.example.test/admin',
        identity_states: { 'identity-1': 'observed', 'identity-2': 'collection_incomplete' },
        evidence_refs: [],
        reason_codes: ['collection_truncated'],
        reliability: 'inconclusive',
      },
    ],
  },
}

describe('PermissionComparisonDetail', () => {
  it('shows inconclusive differences with their reason instead of a permission denial', async () => {
    const wrapper = mount(PermissionComparisonDetail, {
      props: { comparison: inconclusiveComparison },
    })

    await wrapper.get('input[type="checkbox"]').setValue(true)

    expect(wrapper.text()).toContain('无法确认')
    expect(wrapper.text()).not.toContain('无权限')
    expect(wrapper.text()).toContain('collection_truncated')
  })

  it('emits safe confirmation, cancellation, and download actions', async () => {
    const wrapper = mount(PermissionComparisonDetail, {
      props: {
        comparison: {
          ...inconclusiveComparison,
          state: 'paused_for_human',
          identities: { 'identity-1': 'paused_for_human', 'identity-2': 'created' },
        },
      },
    })

    await wrapper.get('[data-test="confirm-identity-1"]').trigger('click')
    await wrapper.get('[data-test="cancel-comparison"]').trigger('click')
    await wrapper.get('[data-test="download-comparison"]').trigger('click')

    expect(wrapper.emitted('confirm-login')).toEqual([['identity-1']])
    expect(wrapper.emitted('cancel')).toEqual([[]])
    expect(wrapper.emitted('download')).toEqual([[]])
  })

  it('does not offer cancellation for a failed terminal comparison', () => {
    const wrapper = mount(PermissionComparisonDetail, {
      props: {
        comparison: {
          ...inconclusiveComparison,
          state: 'failed',
          identities: { 'identity-1': 'failed', 'identity-2': 'failed' },
          result: null,
        },
      },
    })

    expect(wrapper.find('[data-test="cancel-comparison"]').exists()).toBe(false)
  })
})
