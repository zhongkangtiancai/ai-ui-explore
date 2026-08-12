<script setup lang="ts">
import { ref } from 'vue'

import type {
  CreatePermissionComparisonRequest,
  IdentityProfile,
} from '../api/permissionComparisons'

const emit = defineEmits<{ submit: [payload: CreatePermissionComparisonRequest] }>()

const moduleId = ref('')
const moduleUrl = ref('')
const allowedOrigin = ref('')
const identities = ref<IdentityProfile[]>([
  { identity_id: 'identity-1', label: '' },
  { identity_id: 'identity-2', label: '' },
])

function addIdentity(): void {
  if (identities.value.length >= 5) return
  identities.value.push({ identity_id: `identity-${identities.value.length + 1}`, label: '' })
}

function submit(): void {
  if (identities.value.some((identity) => !identity.label.trim())) return
  emit('submit', {
    module_entry: { module_id: moduleId.value, url: moduleUrl.value },
    allowed_origins: [allowedOrigin.value],
    authentication_origins: [],
    budget: { max_pages: 20, max_depth: 2, max_queue_size: 100 },
    identities: identities.value.map((identity) => ({
      identity_id: identity.identity_id,
      label: identity.label.trim(),
    })),
    allow_local_http: false,
  })
}
</script>

<template>
  <section class="comparison-form">
    <h2>权限差异探索</h2>
    <form @submit.prevent="submit">
      <label>模块标识<input data-test="module-id" v-model="moduleId" required /></label>
      <label
        >模块地址<input data-test="module-url" v-model="moduleUrl" required type="url"
      /></label>
      <label
        >允许来源<input data-test="allowed-origin" v-model="allowedOrigin" required type="url"
      /></label>
      <fieldset>
        <legend>身份别名（2–5 个）</legend>
        <label v-for="identity in identities" :key="identity.identity_id">
          {{ identity.identity_id }}
          <input data-test="identity-label" v-model="identity.label" required maxlength="80" />
        </label>
      </fieldset>
      <button
        data-test="add-identity"
        type="button"
        :disabled="identities.length >= 5"
        @click="addIdentity"
      >
        添加身份
      </button>
      <button type="submit">创建权限比较</button>
    </form>
  </section>
</template>
