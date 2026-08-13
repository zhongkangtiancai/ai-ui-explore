<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  downloadExplorationTaskEvidence,
  fetchExplorationTaskPageDetail,
  fetchExplorationTaskPages,
  type PageElementEvidence,
  type PageEvidence,
  type TaskPageView,
  type TaskState,
} from '../api/explorationTasks'

const props = defineProps<{
  taskId: string
  taskState: TaskState
}>()

const pages = ref<TaskPageView[]>([])
const detail = ref<PageEvidence | null>(null)
const selectedElementKey = ref<string | null>(null)
const loading = ref(false)
const loadFailed = ref(false)
const downloadFailed = ref(false)

const groupedElements = computed(() => {
  const groups = new Map<string, PageElementEvidence[]>()
  for (const element of detail.value?.elements ?? []) {
    const group = groups.get(element.frame_path) ?? []
    group.push(element)
    groups.set(element.frame_path, group)
  }
  return [...groups.entries()]
})

const selectedElement = computed(
  () =>
    detail.value?.elements.find((element) => element.element_key === selectedElementKey.value) ??
    null,
)

const isPartial = computed(
  () => props.taskState === 'partial' || pages.value.some((page) => page.reason_codes.length > 0),
)

watch(
  () => props.taskId,
  () => void loadPages(),
  { immediate: true },
)

async function loadPages(): Promise<void> {
  loading.value = true
  loadFailed.value = false
  detail.value = null
  selectedElementKey.value = null
  try {
    pages.value = await fetchExplorationTaskPages(props.taskId)
  } catch {
    pages.value = []
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

async function selectPage(page: TaskPageView): Promise<void> {
  loadFailed.value = false
  detail.value = null
  selectedElementKey.value = null
  try {
    const loaded = await fetchExplorationTaskPageDetail(props.taskId, page.page_id)
    detail.value = loaded
    selectedElementKey.value = loaded.elements[0]?.element_key ?? null
  } catch {
    loadFailed.value = true
  }
}

async function download(): Promise<void> {
  downloadFailed.value = false
  try {
    await downloadExplorationTaskEvidence(props.taskId)
  } catch {
    downloadFailed.value = true
  }
}
</script>

<template>
  <section class="evidence-browser" aria-labelledby="evidence-title">
    <div class="evidence-heading">
      <div>
        <p class="section-kicker">已采集证据</p>
        <h3 id="evidence-title">探索明细</h3>
      </div>
      <button data-test="download-evidence" type="button" @click="download">下载 JSON</button>
    </div>

    <p class="notice">
      这是当前进程内已采集的脱敏证据，不代表页面完整性或业务权限；不会显示原始
      HTML、Cookie、Token、输入值或浏览器对象。
    </p>
    <p v-if="isPartial" class="partial-notice">
      采集不完整：已展示可用页面，未采集部分不能据此推断权限或页面不存在。
    </p>
    <p v-if="loading">正在加载已采集明细…</p>
    <p v-if="loadFailed" class="error">明细暂时无法读取。</p>
    <p v-if="downloadFailed" class="error">导出未完成。</p>

    <div v-if="!loading" class="evidence-layout">
      <aside aria-label="已采集页面">
        <p class="list-label">页面（{{ pages.length }}）</p>
        <button
          v-for="page in pages"
          :key="page.page_id"
          data-test="evidence-page"
          class="page-item"
          type="button"
          @click="selectPage(page)"
        >
          <strong>{{ page.page_id }}</strong>
          <span>{{ page.page_key }}</span>
          <small
            >{{ page.frame_count }} Frame · {{ page.element_count }} 元素 ·
            {{ page.link_count }} 链接</small
          >
        </button>
        <p v-if="pages.length === 0" class="empty">暂无已采集页面。</p>
      </aside>

      <div v-if="detail" class="page-detail">
        <p class="detail-url">{{ detail.page_key }}</p>
        <section
          v-for="[framePath, elements] in groupedElements"
          :key="framePath"
          class="frame-group"
        >
          <h4>Frame：{{ framePath }}</h4>
          <div class="element-list">
            <button
              v-for="element in elements"
              :key="element.element_key"
              class="element-item"
              type="button"
              @click="selectedElementKey = element.element_key"
            >
              {{ element.tag }} · {{ element.role || '无角色' }} ·
              {{ element.accessible_name || element.text || element.element_key }}
            </button>
          </div>
        </section>

        <section v-if="selectedElement" class="selected-element">
          <h4>元素详情</h4>
          <dl>
            <div>
              <dt>标签</dt>
              <dd>{{ selectedElement.tag }}</dd>
            </div>
            <div>
              <dt>角色</dt>
              <dd>{{ selectedElement.role || '无' }}</dd>
            </div>
            <div>
              <dt>可访问名称</dt>
              <dd>{{ selectedElement.accessible_name || '无' }}</dd>
            </div>
            <div>
              <dt>可见 / 可用</dt>
              <dd>{{ selectedElement.visible }} / {{ selectedElement.enabled }}</dd>
            </div>
            <div v-if="selectedElement.href">
              <dt>链接</dt>
              <dd>{{ selectedElement.href }}</dd>
            </div>
            <div v-if="selectedElement.bounds">
              <dt>位置</dt>
              <dd>
                {{ selectedElement.bounds.x }}, {{ selectedElement.bounds.y }} ·
                {{ selectedElement.bounds.width }} × {{ selectedElement.bounds.height }}
              </dd>
            </div>
          </dl>
          <h5>属性</h5>
          <ul>
            <li v-for="(value, key) in selectedElement.attributes" :key="key">
              {{ key }} = {{ value }}
            </li>
          </ul>
          <h5>定位器候选</h5>
          <ol>
            <li
              v-for="candidate in selectedElement.locator_candidates"
              :key="`${candidate.strategy}-${candidate.rank}`"
            >
              {{ candidate.rank }}. {{ candidate.strategy }} · {{ candidate.parameters }}
            </li>
          </ol>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.evidence-browser {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid rgba(139, 174, 201, 0.2);
}
.evidence-heading {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 12px;
}
.section-kicker,
.list-label {
  margin: 0 0 8px;
  color: #78a9d4;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
}
h3,
h4,
h5 {
  margin: 0;
}
.notice,
.partial-notice,
.detail-url,
.empty {
  color: #c8d7e3;
  line-height: 1.6;
}
.partial-notice {
  color: #ffd185;
}
.error {
  color: #ffb4b4;
}
.evidence-heading button,
.page-item,
.element-item {
  font: inherit;
  cursor: pointer;
}
.evidence-heading button {
  min-height: 36px;
  padding: 0 12px;
  border: 0;
  border-radius: 8px;
  color: #041019;
  background: #6fc4ff;
  font-weight: 700;
}
.evidence-layout {
  display: grid;
  grid-template-columns: minmax(180px, 0.75fr) minmax(0, 2fr);
  gap: 16px;
}
.page-item,
.element-item {
  display: grid;
  width: 100%;
  gap: 4px;
  margin: 0 0 8px;
  padding: 10px;
  border: 1px solid rgba(139, 174, 201, 0.22);
  border-radius: 8px;
  color: #dceaf4;
  text-align: left;
  background: rgba(255, 255, 255, 0.03);
}
.page-item span,
.page-item small {
  overflow-wrap: anywhere;
  color: #9fb3c3;
}
.frame-group,
.selected-element {
  margin-top: 16px;
  padding: 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.035);
}
.element-list {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}
dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
dt {
  color: #7f9aae;
  font-size: 12px;
}
dd {
  margin: 3px 0 0;
  overflow-wrap: anywhere;
}
ul,
ol {
  margin: 8px 0 0;
  padding-left: 20px;
  overflow-wrap: anywhere;
}
@media (max-width: 600px) {
  .evidence-layout {
    grid-template-columns: 1fr;
  }
  dl {
    grid-template-columns: 1fr;
  }
}
</style>
