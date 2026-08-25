<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import type { CreateExplorationTaskRequest } from '../api/explorationTasks'

const emit = defineEmits<{
  submit: [payload: CreateExplorationTaskRequest]
}>()

const needsManualLogin = ref(false)
const allowLocalHttp = ref(false)
const form = reactive({
  moduleId: '',
  moduleUrl: '',
  moduleLabel: '',
  allowedOrigin: '',
  authenticationOrigin: '',
  authenticationUrl: '',
  postLoginUrlPrefix: '',
  checkpointCss: '',
  maxPages: 20,
  maxDepth: 2,
  maxQueueSize: 100,
})

const submitLabel = computed(() => (needsManualLogin.value ? '创建登录探索任务' : '创建探索任务'))

function submitTask(): void {
  const moduleLabel = form.moduleLabel.trim()
  emit('submit', {
    module_entry: {
      module_id: form.moduleId.trim(),
      url: form.moduleUrl.trim(),
      label: moduleLabel || undefined,
    },
    allowed_origins: [form.allowedOrigin.trim()],
    authentication_origins: needsManualLogin.value ? [form.authenticationOrigin.trim()] : [],
    budget: {
      max_pages: Number(form.maxPages),
      max_depth: Number(form.maxDepth),
      max_queue_size: Number(form.maxQueueSize),
    },
    authentication_plan: needsManualLogin.value
      ? {
          authentication_url: form.authenticationUrl.trim(),
          post_login_url_prefix: form.postLoginUrlPrefix.trim(),
          checkpoint_css_selector: form.checkpointCss.trim(),
        }
      : undefined,
    allow_local_http: allowLocalHttp.value,
  })
}
</script>

<template>
  <section class="task-form-card" aria-labelledby="task-create-title">
    <div>
      <p class="section-kicker">受控只读探索</p>
      <h2 id="task-create-title">创建探索任务</h2>
      <p class="form-help">请显式配置模块入口、允许 Origin 与探索预算。</p>
    </div>

    <form class="task-form" @submit.prevent="submitTask">
      <label>
        模块 ID
        <input v-model="form.moduleId" data-test="module-id" required maxlength="100" />
      </label>
      <label>
        模块入口 URL
        <input v-model="form.moduleUrl" data-test="module-url" required type="url" />
      </label>
      <label>
        模块名称（可选）
        <input v-model="form.moduleLabel" data-test="module-label" maxlength="200" />
      </label>
      <label>
        允许 Origin
        <input v-model="form.allowedOrigin" data-test="allowed-origin" required type="url" />
      </label>

      <div class="budget-grid">
        <label>
          最大页面数
          <input
            v-model.number="form.maxPages"
            data-test="max-pages"
            min="1"
            max="1000"
            required
            type="number"
          />
        </label>
        <label>
          最大深度
          <input
            v-model.number="form.maxDepth"
            data-test="max-depth"
            min="0"
            max="20"
            required
            type="number"
          />
        </label>
        <label>
          最大队列数
          <input
            v-model.number="form.maxQueueSize"
            data-test="max-queue-size"
            min="1"
            max="10000"
            required
            type="number"
          />
        </label>
      </div>

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
        <label>
          认证 Origin
          <input
            v-model="form.authenticationOrigin"
            data-test="authentication-origin"
            required
            type="url"
          />
        </label>
        <label>
          认证 URL
          <input
            v-model="form.authenticationUrl"
            data-test="authentication-url"
            required
            type="url"
          />
        </label>
        <label>
          登录后 URL 前缀
          <input
            v-model="form.postLoginUrlPrefix"
            data-test="post-login-url-prefix"
            required
            type="url"
          />
        </label>
        <label>
          认证检查点
          <input v-model="form.checkpointCss" data-test="checkpoint-css" required />
        </label>
      </fieldset>

      <button data-test="create-task" type="submit">{{ submitLabel }}</button>
    </form>
  </section>
</template>

<style scoped>
.task-form-card {
  margin-top: 32px;
  padding: 28px;
  border: 1px solid rgba(139, 174, 201, 0.18);
  border-radius: 18px;
  background: rgba(11, 28, 42, 0.8);
}

.section-kicker {
  margin: 0 0 8px;
  color: #78a9d4;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

h2 {
  margin: 0;
  font-size: 22px;
}

.form-help,
legend {
  color: #9fb3c3;
  line-height: 1.6;
}

.task-form {
  display: grid;
  gap: 16px;
  margin-top: 24px;
}

label {
  display: grid;
  gap: 8px;
  color: #c8d7e3;
  font-size: 14px;
}

input {
  width: 100%;
  min-height: 40px;
  padding: 9px 11px;
  border: 1px solid rgba(139, 174, 201, 0.34);
  border-radius: 8px;
  color: #eaf1f7;
  background: rgba(255, 255, 255, 0.05);
  font: inherit;
}

.budget-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.manual-login-option {
  display: flex;
  align-items: center;
  gap: 10px;
}

.manual-login-option input {
  width: 16px;
  min-height: 16px;
}

.authentication-fields {
  display: grid;
  gap: 16px;
  padding: 16px;
  border: 1px solid rgba(120, 169, 212, 0.28);
  border-radius: 10px;
}

button {
  justify-self: start;
  min-height: 40px;
  padding: 0 16px;
  border: 0;
  border-radius: 8px;
  color: #041019;
  background: #6fc4ff;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

@media (max-width: 600px) {
  .budget-grid {
    grid-template-columns: 1fr;
  }
}
</style>
