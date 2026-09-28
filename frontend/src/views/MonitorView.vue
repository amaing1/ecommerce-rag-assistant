<script setup>
// ============================================
// 检索监控页：统计卡片 + 趋势图 + 检索日志（分页）
// 对应之前 Streamlit 版 pages/monitor_page.py
// ============================================
import { ref, computed, onMounted } from 'vue'
import { getToken } from '../auth'
import { getMonitorStats, getMonitorTrend, getMonitorLogs } from '../api'
import NavBar from '../components/NavBar.vue'

const token = getToken()

const stats = ref(null)          // /monitor/stats 返回的统计对象
const trend = ref([])            // /monitor/trend 返回的耗时点
const logs = ref([])             // /monitor/logs 返回的日志列表
const logsTotal = ref(0)         // 日志总条数（算页数用）
const page = ref(1)              // 当前页
const pageSize = 10
const loadError = ref('')

// 总页数
const totalPages = computed(() => Math.max(1, Math.ceil(logsTotal.value / pageSize)))

onMounted(async () => {
  await Promise.all([loadStats(), loadTrend(), loadLogs()])
})

async function loadStats() {
  try {
    stats.value = await getMonitorStats(token)
  } catch (e) {
    loadError.value = e.message
  }
}

async function loadTrend() {
  try {
    trend.value = await getMonitorTrend(token, 50)
  } catch (e) {
    // 趋势图失败不影响别的
  }
}

async function loadLogs() {
  try {
    const data = await getMonitorLogs(token, page.value, pageSize)
    logs.value = data.logs || []
    logsTotal.value = data.total || 0
  } catch (e) {
    loadError.value = e.message
  }
}

function goPage(p) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  loadLogs()
}

// 把趋势数据换算成折线图的坐标（SVG polyline）
const chart = computed(() => {
  const pts = trend.value
  if (!pts.length) return null
  const w = 600
  const h = 200
  const pad = 12
  const max = Math.max(
    1,
    ...pts.map((p) => Math.max(p.total_time_ms || 0, p.vision_time_ms || 0, p.generation_time_ms || 0))
  )
  const xs = pts.map((_, i) => pad + (i / Math.max(1, pts.length - 1)) * (w - pad * 2))
  const yOf = (v) => h - pad - ((v || 0) / max) * (h - pad * 2)
  const pathOf = (field) =>
    pts.map((p, i) => `${i ? 'L' : 'M'}${xs[i].toFixed(1)},${yOf(p[field]).toFixed(1)}`).join(' ')
  return {
    total: pathOf('total_time_ms'),
    generation: pathOf('generation_time_ms'),
    vision: pathOf('vision_time_ms'),
    max: Math.round(max),
  }
})
</script>

<template>
  <div class="page">
    <NavBar />

    <main class="content">
      <h1 class="title">📊 检索监控</h1>

      <p v-if="loadError" class="error">加载失败：{{ loadError }}</p>

      <!-- 概览统计 -->
      <div v-if="stats" class="stat-grid">
        <div class="stat-card">
          <div class="stat-label">总查询数</div>
          <div class="stat-value">{{ stats.total_queries }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">回答数</div>
          <div class="stat-value">{{ stats.answered_count }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">回答率</div>
          <div class="stat-value">{{ stats.answer_rate }}%</div>
        </div>
      </div>

      <!-- 平均耗时 -->
      <div v-if="stats" class="section">
        <h2 class="sub">⏱️ 平均耗时（毫秒）</h2>
        <div class="grid7">
          <div class="mini"><span class="k">总耗时</span><b>{{ stats.avg_total_ms }}</b></div>
          <div class="mini"><span class="k">改写</span><b>{{ stats.avg_rewrite_ms }}</b></div>
          <div class="mini"><span class="k">向量检索</span><b>{{ stats.avg_vec_search_ms }}</b></div>
          <div class="mini"><span class="k">BM25</span><b>{{ stats.avg_bm25_search_ms }}</b></div>
          <div class="mini"><span class="k">精排</span><b>{{ stats.avg_rerank_ms }}</b></div>
          <div class="mini"><span class="k">生成</span><b>{{ stats.avg_generation_ms }}</b></div>
          <div class="mini"><span class="k">识图</span><b>{{ stats.avg_vision_ms }}</b></div>
        </div>
      </div>

      <!-- 分位数 -->
      <div v-if="stats" class="section">
        <h2 class="sub">📐 分位数（毫秒）</h2>
        <div class="grid6">
          <div class="mini"><span class="k">P50 总耗时</span><b>{{ stats.p50_total_ms }}</b></div>
          <div class="mini"><span class="k">P95 总耗时</span><b>{{ stats.p95_total_ms }}</b></div>
          <div class="mini"><span class="k">P99 总耗时</span><b>{{ stats.p99_total_ms }}</b></div>
          <div class="mini"><span class="k">P50 识图</span><b>{{ stats.p50_vision_ms }}</b></div>
          <div class="mini"><span class="k">P95 识图</span><b>{{ stats.p95_vision_ms }}</b></div>
          <div class="mini"><span class="k">P99 识图</span><b>{{ stats.p99_vision_ms }}</b></div>
        </div>
      </div>

      <!-- 成本 -->
      <div v-if="stats" class="section">
        <h2 class="sub">💰 成本统计</h2>
        <div class="grid4">
          <div class="mini"><span class="k">总成本(元)</span><b>{{ stats.total_cost }}</b></div>
          <div class="mini"><span class="k">RAG 成本</span><b>{{ stats.rag_cost }}</b></div>
          <div class="mini"><span class="k">识图成本</span><b>{{ stats.vision_cost }}</b></div>
          <div class="mini"><span class="k">总 token</span><b>{{ stats.total_tokens }}</b></div>
        </div>
      </div>

      <!-- 趋势图 -->
      <div class="section">
        <h2 class="sub">📈 耗时趋势（最近查询，毫秒）</h2>
        <div v-if="chart" class="chart-box">
          <svg :viewBox="'0 0 600 200'" preserveAspectRatio="none" class="chart">
            <path :d="chart.total" fill="none" stroke="#2563eb" stroke-width="2" />
            <path :d="chart.generation" fill="none" stroke="#16a34a" stroke-width="2" />
            <path :d="chart.vision" fill="none" stroke="#f59e0b" stroke-width="2" />
          </svg>
          <div class="legend">
            <span><i class="dot total"></i>总耗时</span>
            <span><i class="dot gen"></i>生成</span>
            <span><i class="dot vision"></i>识图</span>
            <span class="max">峰值 {{ chart.max }}ms</span>
          </div>
        </div>
        <p v-else class="empty">暂无趋势数据</p>
      </div>

      <!-- 检索日志 -->
      <div class="section">
        <h2 class="sub">📋 检索日志</h2>

        <div v-if="logs.length">
          <div v-for="log in logs" :key="log.id" class="log">
            <details>
              <summary>
                <span class="log-id">#{{ log.id }}</span>
                <span class="log-q">{{ log.question }}</span>
                <span class="log-status">{{ log.can_answer ? '✅' : '❌' }}</span>
                <span class="log-time">{{ log.total_time_ms }}ms</span>
              </summary>
              <div class="log-body">
                <div class="line"><span>改写耗时：{{ log.rewrite_time_ms }}ms</span><span>向量检索：{{ log.vec_search_time_ms }}ms</span></div>
                <div class="line"><span>BM25：{{ log.bm25_search_time_ms }}ms</span><span>精排：{{ log.rerank_time_ms }}ms</span></div>
                <div class="line"><span>生成：{{ log.generation_time_ms }}ms</span><span>候选数：{{ log.candidate_count }} → 最终：{{ log.valid_doc_count }}</span></div>
                <div class="line"><span>回答字数：{{ log.answer_length }}</span></div>
                <div v-if="log.error_message" class="error">错误：{{ log.error_message }}</div>
              </div>
            </details>
          </div>
        </div>
        <p v-else class="empty">暂无日志数据</p>

        <!-- 分页 -->
        <div class="pager">
          <button class="pg" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
          <span class="pg-info">第 {{ page }} / {{ totalPages }} 页</span>
          <button class="pg" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f0f2f5;
}

.content {
  width: 100%;
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 20px;
}

.title {
  font-size: 22px;
  color: #333;
  margin-bottom: 18px;
}

.error {
  color: #ff4d4f;
  font-size: 14px;
  margin-bottom: 12px;
}

.section {
  background: #fff;
  border-radius: 10px;
  border: 1px solid #e8e8e8;
  padding: 18px 20px;
  margin-bottom: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.sub {
  font-size: 15px;
  color: #333;
  margin-bottom: 14px;
}

/* 概览三卡 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}

.stat-card {
  background: #fff;
  border-radius: 10px;
  border: 1px solid #e8e8e8;
  padding: 18px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.stat-label {
  font-size: 13px;
  color: #999;
  margin-bottom: 6px;
}

.stat-value {
  font-size: 26px;
  font-weight: 600;
  color: #2563eb;
}

/* 若干小指标格 */
.grid4,
.grid6,
.grid7 {
  display: grid;
  gap: 12px;
}

.grid4 { grid-template-columns: repeat(4, 1fr); }
.grid6 { grid-template-columns: repeat(3, 1fr); }
.grid7 { grid-template-columns: repeat(4, 1fr); }

.mini {
  background: #f8faff;
  border: 1px solid #eef2ff;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.mini .k {
  font-size: 12px;
  color: #888;
}

.mini b {
  font-size: 17px;
  color: #333;
  font-weight: 600;
}

/* 趋势图 */
.chart-box {
  width: 100%;
}

.chart {
  width: 100%;
  height: 200px;
  background: #fafbfc;
  border: 1px solid #eef2ff;
  border-radius: 8px;
}

.legend {
  display: flex;
  gap: 16px;
  align-items: center;
  margin-top: 8px;
  font-size: 12px;
  color: #666;
}

.legend .dot {
  display: inline-block;
  width: 10px;
  height: 3px;
  border-radius: 2px;
  margin-right: 4px;
  vertical-align: middle;
}

.dot.total { background: #2563eb; }
.dot.gen { background: #16a34a; }
.dot.vision { background: #f59e0b; }

.legend .max {
  margin-left: auto;
  color: #999;
}

.empty {
  font-size: 13px;
  color: #bbb;
  padding: 8px 0;
}

/* 日志 */
.log {
  border: 1px solid #eef2ff;
  border-radius: 8px;
  margin-bottom: 8px;
  overflow: hidden;
}

.log summary {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  cursor: pointer;
  list-style: none;
  background: #fafbfc;
}

.log summary::-webkit-details-marker { display: none; }

.log-id {
  color: #2563eb;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}

.log-q {
  flex: 1;
  font-size: 13px;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-time {
  font-size: 12px;
  color: #999;
  flex-shrink: 0;
}

.log-body {
  padding: 10px 12px;
  border-top: 1px solid #f0f2f5;
  font-size: 13px;
  color: #555;
}

.log-body .line {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
}

.log-body .error {
  margin-top: 6px;
  color: #ff4d4f;
}

/* 分页 */
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 14px;
}

.pg {
  padding: 7px 16px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  color: #555;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.pg:hover:not(:disabled) {
  border-color: #2563eb;
  color: #2563eb;
}

.pg:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.pg-info {
  font-size: 13px;
  color: #666;
}
</style>