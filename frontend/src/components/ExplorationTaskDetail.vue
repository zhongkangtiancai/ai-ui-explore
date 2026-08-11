<script setup lang="ts">
import { computed } from 'vue'

import type { TaskSummary } from '../api/explorationTasks'

const props = defineProps<{
  task: TaskSummary
}>()

const emit = defineEmits<{
  'confirm-login': []
  cancel: []
}>()

const isTerminal = computed(() =>
  ['completed', 'partial', 'failed', 'cancelled'].includes(props.task.state),
)
const canConfirmLogin = computed(() => props.task.state === 'paused_for_human')
</script>

<template>
  <section class="task-detail-card" aria-labelledby="task-detail-title">
    <div class="task-heading">
      <div>
        <p class="section-kicker">当前任务</p>
        <h2 id="task-detail-title">{{ task.task_id }}</h2>
      </div>
      <span class="task-state">{{ task.state }}</span>
    </div>

    <p v-if="canConfirmLogin" class="human-login-help">
      请在本机可见浏览器完成登录，再确认继续验证。不要在此页面输入或上传登录信息。
    </p>

    <div v-if="canConfirmLogin || !isTerminal" class="task-actions">
      <button
        v-if="canConfirmLogin"
        data-test="confirm-login"
        type="button"
        @click="emit('confirm-login')"
      >
        我已完成登录，继续验证
      </button>
      <button data-test="cancel-task" class="cancel-button" type="button" @click="emit('cancel')">
        取消任务
      </button>
    </div>

    <section class="detail-section" aria-labelledby="audit-title">
      <h3 id="audit-title">最小审计事件</h3>
      <ul>
        <li v-for="event in task.events" :key="`${event.event_type}-${event.occurred_at}`">
          <span>{{ event.event_type }}</span>
          <span v-if="event.reason_code"> · {{ event.reason_code }}</span>
        </li>
      </ul>
    </section>

    <section class="detail-section" aria-labelledby="result-title">
      <h3 id="result-title">探索结果摘要</h3>
      <dl class="result-grid">
        <div>
          <dt>页面</dt>
          <dd>页面：{{ task.result.page_count }}</dd>
        </div>
        <div>
          <dt>元素</dt>
          <dd>元素：{{ task.result.element_count }}</dd>
        </div>
        <div>
          <dt>链接</dt>
          <dd>链接：{{ task.result.link_count }}</dd>
        </div>
      </dl>
      <p class="source-summary">{{ task.result.source_summary }}</p>
    </section>
  </section>
</template>

<style scoped>
.task-detail-card {
  margin-top: 32px;
  padding: 28px;
  border: 1px solid rgba(111, 196, 255, 0.3);
  border-radius: 18px;
  background: rgba(11, 28, 42, 0.8);
}

.task-heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.section-kicker {
  margin: 0 0 8px;
  color: #78a9d4;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

h2,
h3 {
  margin: 0;
}

h2 {
  font-size: 22px;
}

h3 {
  font-size: 16px;
}

.task-state {
  align-self: start;
  padding: 6px 9px;
  border-radius: 999px;
  color: #a9d9ff;
  background: rgba(111, 196, 255, 0.12);
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
}

.human-login-help,
.source-summary,
li {
  color: #c8d7e3;
  line-height: 1.65;
}

.task-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 20px;
}

button {
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

.cancel-button {
  color: #ffd9d9;
  background: rgba(255, 107, 107, 0.2);
}

.detail-section {
  margin-top: 24px;
}

ul {
  display: grid;
  gap: 6px;
  margin: 12px 0 0;
  padding-left: 20px;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 12px 0 0;
}

.result-grid div {
  padding: 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
}

dt {
  color: #7f9aae;
  font-size: 12px;
}

dd {
  margin: 5px 0 0;
  color: #eaf1f7;
}

@media (max-width: 600px) {
  .task-heading {
    display: grid;
  }

  .result-grid {
    grid-template-columns: 1fr;
  }
}
</style>
