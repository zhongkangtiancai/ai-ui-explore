<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  fetchExplorationTaskWorkflow,
  type TaskState,
  type TaskWorkflowExport,
} from '../api/explorationTasks'

const props = defineProps<{
  taskId: string
  taskState: TaskState
}>()

const workflow = ref<TaskWorkflowExport | null>(null)
const loading = ref(false)
const loadFailed = ref(false)
const isPartial = computed(
  () => props.taskState === 'partial' || workflow.value?.state === 'partial',
)

watch(
  () => props.taskId,
  () => void loadWorkflow(),
  { immediate: true },
)

async function loadWorkflow(): Promise<void> {
  loading.value = true
  loadFailed.value = false
  workflow.value = null
  try {
    workflow.value = await fetchExplorationTaskWorkflow(props.taskId)
  } catch {
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="workflow-browser" aria-labelledby="workflow-title">
    <p class="section-kicker">只读交互流程</p>
    <h3 id="workflow-title">已观察到的状态变化</h3>
    <p class="notice">
      仅展示经验证的白名单只读交互；流程不代表业务完成、业务规则、后端数据范围或权限结论。
    </p>
    <p v-if="isPartial" data-test="workflow-partial" class="partial-notice">
      流程观察不完整：未执行、暂停或失败的候选不会形成流程边。
    </p>
    <p v-if="loading">正在加载已观察流程…</p>
    <p v-else-if="loadFailed" class="error">流程暂时无法读取。</p>
    <template v-else-if="workflow">
      <section class="workflow-section" aria-labelledby="workflow-nodes-title">
        <h4 id="workflow-nodes-title">状态节点（{{ workflow.nodes.length }}）</h4>
        <ul v-if="workflow.nodes.length">
          <li v-for="node in workflow.nodes" :key="node.state">{{ node.state }}</li>
        </ul>
        <p v-else class="empty">暂无已验证的状态节点。</p>
      </section>
      <section class="workflow-section" aria-labelledby="workflow-edges-title">
        <h4 id="workflow-edges-title">已验证转换（{{ workflow.edges.length }}）</h4>
        <ul v-if="workflow.edges.length">
          <li v-for="edge in workflow.edges" :key="edge.edge_id">
            <strong>{{ edge.kind }}</strong> · {{ edge.source_state }} → {{ edge.target_state }} ·
            观察次数：{{ edge.observation_count }}
          </li>
        </ul>
        <p v-else class="empty">暂无已验证的流程转换。</p>
      </section>
      <section class="workflow-section" aria-labelledby="workflow-steps-title">
        <h4 id="workflow-steps-title">交互步骤（{{ workflow.steps.length }}）</h4>
        <ul v-if="workflow.steps.length">
          <li v-for="step in workflow.steps" :key="step.step_id">
            <strong>{{ step.kind }}</strong> · {{ step.target_summary }} · {{ step.status }}
          </li>
        </ul>
        <p v-else class="empty">暂无已记录的只读交互步骤。</p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.workflow-browser {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid rgba(139, 174, 201, 0.2);
}
.section-kicker {
  margin: 0 0 8px;
  color: #78a9d4;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
}
h3,
h4 {
  margin: 0;
}
.notice,
.empty,
li {
  color: #c8d7e3;
  line-height: 1.6;
}
.partial-notice {
  color: #ffd185;
  line-height: 1.6;
}
.error {
  color: #ffb4b4;
}
.workflow-section {
  margin-top: 16px;
  padding: 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.035);
}
ul {
  display: grid;
  gap: 6px;
  margin: 10px 0 0;
  padding-left: 20px;
  overflow-wrap: anywhere;
}
</style>
