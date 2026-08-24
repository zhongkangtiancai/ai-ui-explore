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
const needsManualLogin = ref(false)
const allowLocalHttp = ref(false)
const authenticationOrigin = ref('')
const authenticationUrl = ref('')
const postLoginUrlPrefix = ref('')
const checkpointCss = ref('')
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
  const authenticationPlan = needsManualLogin.value
    ? {
        authentication_url: authenticationUrl.value.trim(),
        post_login_url_prefix: postLoginUrlPrefix.value.trim(),
        checkpoint_css_selector: checkpointCss.value.trim(),
      }
    : undefined
  emit('submit', {
    module_entry: { module_id: moduleId.value, url: moduleUrl.value },
    allowed_origins: [allowedOrigin.value],
    authentication_origins: needsManualLogin.value ? [authenticationOrigin.value.trim()] : [],
    budget: { max_pages: 20, max_depth: 2, max_queue_size: 100 },
    identities: identities.value.map((identity) => ({
      identity_id: identity.identity_id,
      label: identity.label.trim(),
      authentication_plan: authenticationPlan ? { ...authenticationPlan } : undefined,
    })),
    allow_local_http: allowLocalHttp.value,
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
      <label class="manual-login-option">
        <input v-model="needsManualLogin" data-test="manual-login" type="checkbox" />
        需要人工登录
      </label>
      <label class="manual-login-option">
        <input v-model="allowLocalHttp" data-test="allow-local-http" type="checkbox" />
        仅本地验收：允许 HTTP（127.0.0.1 / localhost）
      </label>
      <fieldset v-if="needsManualLogin" class="authentication-fields">
        <legend>人工登录验证配置</legend>
        <label
          >认证 Origin
          <input
            v-model="authenticationOrigin"
            data-test="authentication-origin"
            required
            type="url"
          />
        </label>
        <label
          >认证 URL
          <input v-model="authenticationUrl" data-test="authentication-url" required type="url" />
        </label>
        <label
          >登录后 URL 前缀
          <input
            v-model="postLoginUrlPrefix"
            data-test="post-login-url-prefix"
            required
            type="url"
          />
        </label>
        <label
          >认证检查点
          <input v-model="checkpointCss" data-test="checkpoint-css" required />
        </label>
      </fieldset>
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

<style scoped>
.comparison-form {
  display: grid;
  gap: 16px;
}

form,
fieldset,
label {
  display: grid;
  gap: 8px;
}

.manual-login-option {
  display: flex;
  align-items: center;
  gap: 10px;
}

.authentication-fields {
  padding: 16px;
}
</style>
