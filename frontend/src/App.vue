<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchHealth, type HealthResponse } from './api/health'

type ConnectionState = 'loading' | 'success' | 'error'

const connectionState = ref<ConnectionState>('loading')
const health = ref<HealthResponse | null>(null)

onMounted(async () => {
  try {
    health.value = await fetchHealth()
    connectionState.value = 'success'
  } catch {
    connectionState.value = 'error'
  }
})
</script>

<template>
  <main class="shell">
    <section class="hero" aria-labelledby="page-title">
      <p class="eyebrow">APPLICATION INTELLIGENCE FOUNDATION</p>
      <h1 id="page-title">AI UI Explorer</h1>
      <p class="summary">企业 Web 应用智能探索与知识建模平台</p>
    </section>

    <section class="status-card" aria-live="polite">
      <div class="status-heading">
        <span
          class="status-dot"
          :class="`status-dot--${connectionState}`"
          aria-hidden="true"
        ></span>
        <div>
          <p class="status-label">工程状态</p>
          <h2 v-if="connectionState === 'loading'">正在连接后端服务</h2>
          <h2 v-else-if="connectionState === 'success'">服务正常</h2>
          <h2 v-else>连接异常</h2>
        </div>
      </div>

      <dl v-if="connectionState === 'success' && health" class="metadata">
        <div>
          <dt>运行环境</dt>
          <dd>{{ health.environment }}</dd>
        </div>
        <div>
          <dt>服务版本</dt>
          <dd>{{ health.version }}</dd>
        </div>
      </dl>

      <p v-else-if="connectionState === 'error'" class="error-help">
        请确认后端服务已经启动，然后刷新页面重试。
      </p>
    </section>

    <section class="boundary">
      <h2>当前范围</h2>
      <p>
        当前版本只验证前后端工程闭环。Playwright、知识模型、LLM 与权限探索将在后续 Sprint
        中逐步实现。
      </p>
    </section>
  </main>
</template>

<style scoped>
:global(*) {
  box-sizing: border-box;
}

:global(body) {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  color: #eaf1f7;
  background:
    radial-gradient(circle at 18% 18%, rgba(22, 119, 255, 0.2), transparent 36%),
    linear-gradient(145deg, #07111b 0%, #0b1a27 48%, #101c25 100%);
  font-family:
    Inter,
    'PingFang SC',
    'Microsoft YaHei',
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    sans-serif;
}

.shell {
  width: min(920px, calc(100% - 40px));
  margin: 0 auto;
  padding: 88px 0 64px;
}

.hero {
  max-width: 720px;
}

.eyebrow,
.status-label {
  margin: 0 0 12px;
  color: #78a9d4;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
}

h1 {
  margin: 0;
  font-size: clamp(42px, 8vw, 76px);
  line-height: 1;
  letter-spacing: -0.04em;
}

.summary {
  margin: 22px 0 0;
  color: #a9bdce;
  font-size: clamp(18px, 3vw, 24px);
}

.status-card {
  margin-top: 56px;
  padding: 28px;
  border: 1px solid rgba(139, 174, 201, 0.18);
  border-radius: 18px;
  background: rgba(11, 28, 42, 0.8);
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.22);
  backdrop-filter: blur(16px);
}

.status-heading {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.status-heading h2,
.boundary h2 {
  margin: 0;
  font-size: 22px;
}

.status-dot {
  width: 12px;
  height: 12px;
  margin-top: 7px;
  border-radius: 50%;
  background: #f2b84b;
  box-shadow: 0 0 18px currentColor;
}

.status-dot--success {
  color: #45d38a;
  background: currentColor;
}

.status-dot--error {
  color: #ff6b6b;
  background: currentColor;
}

.metadata {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 28px 0 0;
}

.metadata div {
  padding: 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.04);
}

.metadata dt {
  color: #7f9aae;
  font-size: 13px;
}

.metadata dd {
  margin: 6px 0 0;
  font-family: 'Cascadia Code', Consolas, monospace;
}

.error-help,
.boundary p {
  color: #9fb3c3;
  line-height: 1.75;
}

.boundary {
  margin-top: 32px;
  padding: 0 4px;
}

@media (max-width: 600px) {
  .shell {
    width: min(100% - 28px, 920px);
    padding-top: 56px;
  }

  .metadata {
    grid-template-columns: 1fr;
  }
}
</style>
