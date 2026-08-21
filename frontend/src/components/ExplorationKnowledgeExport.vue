<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  downloadExplorationKnowledge,
  fetchExplorationKnowledgeSources,
  type ExplorationSourceView,
} from '../api/explorationKnowledge'

const emit = defineEmits<{ error: [] }>()

const sources = ref<ExplorationSourceView[]>([])
const selectedIds = ref<string[]>([])
const isLoading = ref(true)

const canDownload = computed(() => selectedIds.value.length > 0)

onMounted(async () => {
  try {
    const loaded = await fetchExplorationKnowledgeSources()
    if (!Array.isArray(loaded)) throw new Error('invalid source catalog')
    sources.value = loaded
  } catch {
    emit('error')
  } finally {
    isLoading.value = false
  }
})

async function download(): Promise<void> {
  const selected = new Set(selectedIds.value)
  const taskIds = sources.value
    .filter((source) => source.source_kind === 'task' && selected.has(source.source_id))
    .map((source) => source.source_id)
  const comparisonIds = sources.value
    .filter((source) => source.source_kind === 'comparison' && selected.has(source.source_id))
    .map((source) => source.source_id)
  try {
    await downloadExplorationKnowledge({ task_ids: taskIds, comparison_ids: comparisonIds })
  } catch {
    emit('error')
  }
}
</script>

<template>
  <section class="knowledge-export" aria-labelledby="knowledge-export-title">
    <p class="section-kicker">UNIFIED KNOWLEDGE PACKAGE</p>
    <h2 id="knowledge-export-title">导出统一探索知识包</h2>
    <p class="help-text">
      仅列出已结束且已脱敏的任务与权限对比来源。部分采集仅表示证据不完整，不代表权限结论；服务重启后仍可查询已持久化的终态来源，登录态不会保存或恢复。
    </p>
    <p v-if="isLoading" class="help-text">正在读取可导出来源…</p>
    <ul v-else class="source-list">
      <li v-for="source in sources" :key="source.source_id">
        <label>
          <input
            v-model="selectedIds"
            type="checkbox"
            :value="source.source_id"
            :data-test="`source-${source.source_id}`"
          />
          <span
            >{{ source.source_kind === 'task' ? '任务' : '权限对比' }}：{{ source.source_id }}</span
          >
          <small>
            {{ source.state }} · 页面 {{ source.page_count }} · 身份 {{ source.identity_count }}
          </small>
        </label>
      </li>
    </ul>
    <p v-if="!isLoading && sources.length === 0" class="help-text">暂无可导出的终态来源。</p>
    <button data-test="download-knowledge" type="button" :disabled="!canDownload" @click="download">
      下载 JSON 知识包
    </button>
  </section>
</template>

<style scoped>
.knowledge-export {
  margin-top: 32px;
  padding: 28px;
  border: 1px solid rgba(111, 196, 255, 0.3);
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

.help-text,
small {
  color: #a9bdce;
  line-height: 1.65;
}

.source-list {
  display: grid;
  gap: 10px;
  margin: 20px 0;
  padding: 0;
  list-style: none;
}

label {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px 10px;
  align-items: start;
  padding: 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
}

small {
  grid-column: 2;
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

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
</style>
