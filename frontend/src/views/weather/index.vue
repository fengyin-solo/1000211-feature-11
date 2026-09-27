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
      <article class="stat-card">
        <span class="stat-label">待补数量</span>
        <strong class="stat-value">{{ remaining }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">异常数量</span>
        <strong class="stat-value">{{ abnormal }}</strong>
      </article>
    </div>

    <section class="fill-queue">
      <header class="page-head">
        <div>
          <h3>待补队列</h3>
          <p class="page-desc">按站点生成待补队列，整组逐条补录辐照度、风速或风向；缺站点编号的行会被退回。</p>
        </div>
        <div class="page-actions">
          <select v-model="station" class="station-select" @change="reloadQueue">
            <option value="">全部站点</option>
            <option v-for="item in stations" :key="item" :value="item">{{ item }}</option>
          </select>
          <button class="btn" type="button" @click="reloadQueue">生成待补队列</button>
          <button
            class="btn primary"
            type="button"
            :disabled="submitting || !queueRows.length"
            @click="submitQueue"
          >
            {{ submitting ? '提交中…' : '提交整组补录' }}
          </button>
        </div>
      </header>

      <table class="data-table">
        <thead>
          <tr>
            <th>站点编号</th>
            <th>记录时间</th>
            <th>缺项</th>
            <th>辐照度</th>
            <th>风速</th>
            <th>风向</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in queueRows" :key="row.id ?? `new-${index}`">
            <td><input v-model="row.站点编号" placeholder="必填" /></td>
            <td>{{ row.记录时间 || '—' }}</td>
            <td>{{ row.缺项.join('、') || '—' }}</td>
            <td><input v-model="row.辐照度" placeholder="补录辐照度" /></td>
            <td><input v-model="row.风速" placeholder="补录风速" /></td>
            <td><input v-model="row.风向" placeholder="补录风向" /></td>
          </tr>
          <tr v-if="!queueRows.length">
            <td colspan="6" class="empty-state">当前站点没有待补记录</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span v-if="queueMessage">{{ queueMessage }}</span>
        <span v-else>共 {{ queueRows.length }} 条待补记录</span>
      </footer>

      <ul v-if="rejectedRows.length" class="reject-list">
        <li v-for="(item, index) in rejectedRows" :key="index" class="error-text">
          第 {{ index + 1 }} 条（记录时间 {{ item.row.记录时间 || '—' }}）：{{ item.reason }}
        </li>
      </ul>
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

type QueueRow = {
  id: number | null
  站点编号: string
  辐照度: string
  风速: string
  风向: string
  记录时间: string
  缺项: string[]
}

type RejectedRow = { row: QueueRow; reason: string }

const ENDPOINT = '/api/weather'
const columns = ["站点编号", "辐照度", "风速", "风向", "气温", "湿度", "降雨量", "记录时间"]
const actions = ["发布预警", "升级预警", "解除预警"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stations = ref<string[]>([])
const station = ref('')
const queueRows = ref<QueueRow[]>([])
const remaining = ref(0)
const abnormal = ref(0)
const submitting = ref(false)
const queueMessage = ref('')
const rejectedRows = ref<RejectedRow[]>([])
// 每次重新生成队列都会换新的 requestId；同一整组动作重复提交时键不变，服务端只保留一份结果
let requestId = newRequestId()

function newRequestId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `fill-${Date.now()}-${Math.random().toString(36).slice(2)}`
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

async function loadQueue() {
  const query = station.value ? `?station=${encodeURIComponent(station.value)}` : ''
  const response = await request(`${ENDPOINT}/fill-queue${query}`)
  if (!response.ok) {
    throw new Error('待补队列读取失败')
  }
  const payload = await response.json()
  stations.value = payload.stations ?? []
  queueRows.value = (payload.items ?? []) as QueueRow[]
  remaining.value = payload.remaining ?? 0
  abnormal.value = payload.abnormal ?? 0
  requestId = newRequestId()
}

async function reloadQueue() {
  errorMessage.value = ''
  queueMessage.value = ''
  rejectedRows.value = []
  try {
    await loadQueue()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '待补队列读取失败'
  }
}

async function submitQueue() {
  if (submitting.value || !queueRows.value.length) {
    return
  }
  submitting.value = true
  errorMessage.value = ''
  queueMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/fill-queue/commit`, {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId, rows: queueRows.value }),
    })
    if (!response.ok) {
      throw new Error('整组补录提交失败，请稍后重试')
    }
    const payload = await response.json()
    // 剩余数量与异常数量以服务端重算结果为准，同时更新
    remaining.value = payload.remaining ?? 0
    abnormal.value = payload.abnormal ?? 0
    rejectedRows.value = (payload.rejected ?? []) as RejectedRow[]
    queueMessage.value = payload.message ?? '整组补录完成'
    await loadQueue()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '整组补录提交失败'
  } finally {
    submitting.value = false
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
  void reloadQueue()
  void reload()
})
</script>

<style scoped>
.fill-queue {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
}
.fill-queue h3 {
  margin: 0;
}
.station-select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  background: #fff;
}
.fill-queue input {
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 6px;
  width: 100%;
}
.reject-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12px;
}
</style>
