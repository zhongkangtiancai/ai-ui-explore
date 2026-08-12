<script setup lang="ts">
import { computed, ref } from 'vue'

import type { PermissionComparison } from '../api/permissionComparisons'

const props = defineProps<{ comparison: PermissionComparison }>()
const emit = defineEmits<{
  'confirm-login': [identityId: string]
  cancel: []
  download: []
}>()
const showUncertain = ref(false)

const differences = computed(() => {
  const items = props.comparison.result?.differences ?? []
  return showUncertain.value
    ? items
    : items.filter((item) => ['high', 'medium'].includes(item.reliability))
})
</script>

<template>
  <section class="comparison-detail">
    <header>
      <h2>权限比较：{{ comparison.comparison_id }}</h2>
      <span>{{ comparison.state }}</span>
    </header>
    <ul>
      <li v-for="(state, identityId) in comparison.identities" :key="identityId">
        {{ identityId }}：{{ state }}
        <button
          v-if="state === 'paused_for_human'"
          :data-test="`confirm-${identityId}`"
          @click="emit('confirm-login', identityId)"
        >
          确认已完成登录
        </button>
      </li>
    </ul>
    <button
      v-if="!['completed', 'partial', 'cancelled'].includes(comparison.state)"
      data-test="cancel-comparison"
      @click="emit('cancel')"
    >
      取消比较
    </button>
    <button v-if="comparison.result" data-test="download-comparison" @click="emit('download')">
      下载 JSON
    </button>
    <label><input type="checkbox" v-model="showUncertain" /> 显示低可靠性与无法确认的差异</label>
    <p
      v-if="
        !showUncertain &&
        comparison.result?.differences.some((item) =>
          ['low', 'inconclusive'].includes(item.reliability),
        )
      "
    >
      部分差异默认隐藏：请开启筛选查看低可靠性和无法确认的结果。
    </p>
    <ul data-test="differences">
      <li v-for="difference in differences" :key="difference.difference_id">
        <strong>{{ difference.subject_key }}</strong>
        <span v-if="difference.reliability === 'inconclusive'">无法确认</span>
        <span v-else>{{ difference.reliability }}</span>
        <small v-if="difference.reason_codes.length">{{
          difference.reason_codes.join(', ')
        }}</small>
      </li>
    </ul>
  </section>
</template>
