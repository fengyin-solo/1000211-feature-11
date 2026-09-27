<template>
  <section class="page" data-module="weather">
    <header class="page-head">
      <div>
        <h2>气象监测管理</h2>
        <p class="page-desc">维护气象数据，围绕站点编号、辐照度、风速、风向做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记气象数据</button>
        <button class="btn" type="button" @click="exportRows">导出气象监测清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="queue-panel">
      <header class="queue-head">
        <div>
          <h3>待补队列</h3>
          <p class="page-desc">按站点归组缺辐照度、风速或风向的记录，整组补录后剩余与异常数量同时重算。</p>
        </div>
        <div class="queue-side">
          <span class="queue-count">剩余 {{ queueRemaining }} 条</span>
          <span class="queue-count">异常 {{ queueAbnormal }} 条</span>
          <button class="btn" type="button" :disabled="queueLoading" @click="loadQueue">
            {{ queueLoading ? '生成中…' : '生成待补队列' }}
          </button>
        </div>
      </header>

      <article v-for="group in queueGroups" :key="group.站点编号" class="queue-group">
        <header class="queue-group-head">
          <strong>{{ group.站点编号 }}</strong>
          <span class="queue-count">{{ group.items.length }} 条待补</span>
          <button
            class="btn primary"
            type="button"
            :disabled="submittingGroup !== null"
            @click="submitGroup(group)"
          >
            {{ submittingGroup === group.站点编号 ? '补录中…' : '整组补录' }}
          </button>
        </header>
        <table class="data-table">
          <thead>
            <tr>
              <th>编号</th>
              <th>站点编号</th>
              <th>待补字段</th>
              <th>辐照度</th>
              <th>风速</th>
              <th>风向</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in group.items" :key="String(item.id)">
              <td>{{ item.id }}</td>
              <td><input v-model="item.站点编号" placeholder="站点编号" /></td>
              <td>{{ item.missing.join('、') }}</td>
              <td><input v-model="item.辐照度" placeholder="补录辐照度" /></td>
              <td><input v-model="item.风速" placeholder="补录风速" /></td>
              <td><input v-model="item.风向" placeholder="补录风向" /></td>
            </tr>
          </tbody>
        </table>
      </article>

      <p v-if="queueLoaded && !queueGroups.length" class="empty-state">没有待补数据，辐照度、风速、风向都已补齐</p>
      <p v-if="queueMessage" class="queue-message">{{ queueMessage }}</p>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无气象监测数据，可先登记气象数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条气象监测记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type QueueItem = {
  id: number
  站点编号: string
  辐照度: string
  风速: string
  风向: string
  missing: string[]
}

type QueueGroup = { 站点编号: string; items: QueueItem[] }

const ENDPOINT = '/api/weather'
const columns = ["站点编号", "辐照度", "风速", "风向", "气温", "湿度", "降雨量", "记录时间"]
const actions = ["发布预警", "升级预警", "解除预警"]
const statuses = ["正常", "大风预警", "暴雨预警", "冰雹预警"]
const stats = [{"label": "当前辐照", "value": 0}, {"label": "今日峰值", "value": 0}, {"label": "预警次数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const queueGroups = ref<QueueGroup[]>([])
const queueRemaining = ref(0)
const queueAbnormal = ref(0)
const queueLoaded = ref(false)
const queueLoading = ref(false)
const submittingGroup = ref<string | null>(null)
const queueMessage = ref('')

async function loadQueue() {
  queueLoading.value = true
  try {
    const response = await request(`${ENDPOINT}/backfill-queue`)
    if (!response.ok) {
      throw new Error('待补队列生成失败')
    }
    const payload = await response.json()
    queueGroups.value = payload.groups ?? []
    queueRemaining.value = payload.remaining ?? 0
    queueAbnormal.value = payload.abnormal ?? 0
    queueLoaded.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '待补队列生成失败'
  } finally {
    queueLoading.value = false
  }
}

async function submitGroup(group: QueueGroup) {
  // 连续点同一个整组动作只提交一次；后端对相同内容也会只保留一份结果
  if (submittingGroup.value !== null) {
    return
  }
  submittingGroup.value = group.站点编号
  queueMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/backfill`, {
      method: 'POST',
      body: JSON.stringify({ values: { 站点编号: group.站点编号, rows: group.items } }),
    })
    const payload = await response.json()
    queueMessage.value = payload.message ?? '整组补录已提交'
    if (payload.entry) {
      queueRemaining.value = payload.entry.remaining ?? queueRemaining.value
      queueAbnormal.value = payload.entry.abnormal ?? queueAbnormal.value
    }
    await Promise.all([loadQueue(), reload()])
  } catch (error) {
    queueMessage.value = error instanceof Error ? error.message : '整组补录失败'
  } finally {
    submittingGroup.value = null
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '气象数据登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('气象监测动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '气象监测操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('气象数据列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '气象监测列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadQueue()
})
</script>
