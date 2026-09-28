<script setup>
// ============================================
// 知识库管理页：上传文档 + 检索测试
// 对应之前 Streamlit 版 pages/knowledge_page.py
// ============================================
import { ref } from 'vue'
import { getToken } from '../auth'
import { uploadKnowledge, queryKnowledge } from '../api'
import NavBar from '../components/NavBar.vue'

const token = getToken()

// ---------- 上传区状态 ----------
const fileInput = ref(null)      // 指向 <input type=file> 元素，用于清空
const file = ref(null)           // 当前选中的文件对象
const uploadMsg = ref('')        // 上传提示文字
const uploadMsgType = ref('')    // 'success' | 'error'
const uploading = ref(false)

// ---------- 检索测试状态 ----------
const question = ref('')
const mode = ref('混合检索')     // 混合检索 / 纯BM25检索
const results = ref([])          // [{content, score}]
const searching = ref(false)
const searchMsg = ref('')

const modeOptions = ['混合检索', '纯BM25检索']

function setUploadMsg(text, type) {
  uploadMsg.value = text
  uploadMsgType.value = type
}

// 选择文件
function onFileChange(e) {
  file.value = e.target.files[0] || null
  uploadMsg.value = ''
}

// 上传文档
async function onUpload() {
  if (!file.value) {
    setUploadMsg('请先选择文件', 'error')
    return
  }
  uploading.value = true
  uploadMsg.value = ''
  try {
    const data = await uploadKnowledge(token, file.value)
    setUploadMsg(`上传成功！共 ${data.chunk_count} 个分块`, 'success')
    // 清空选择，方便下次选同一个文件
    file.value = null
    fileInput.value.value = ''
  } catch (e) {
    setUploadMsg(e.message || '上传失败', 'error')
  } finally {
    uploading.value = false
  }
}

// 检索测试
async function onSearch() {
  const q = question.value.trim()
  if (!q) {
    searchMsg.value = '请输入问题'
    return
  }
  searching.value = true
  results.value = []
  searchMsg.value = ''
  try {
    const data = await queryKnowledge(token, q, mode.value)
    results.value = data.results || []
    if (!results.value.length) searchMsg.value = '未找到相关结果'
  } catch (e) {
    searchMsg.value = e.message || '检索失败'
  } finally {
    searching.value = false
  }
}
</script>

<template>
  <div class="page">
    <NavBar />

    <main class="content">
      <h1 class="title">📚 知识库管理</h1>

      <!-- 上传文档 -->
      <section class="card">
        <h2 class="sub">📤 上传文档</h2>
        <p class="caption">支持格式：PDF、TXT、MD、Word、Excel、HTML、CSV 等</p>

        <div class="row">
          <input
            ref="fileInput"
            type="file"
            accept=".pdf,.txt,.md,.docx,.xlsx,.xls,.html,.htm,.pptx,.ppt,.json,.csv"
            @change="onFileChange"
          />
          <button class="btn" :disabled="uploading" @click="onUpload">
            {{ uploading ? '处理中…' : '上传' }}
          </button>
        </div>

        <p v-if="file" class="filename">已选择：{{ file.name }}</p>
        <p v-if="uploadMsg" class="msg" :class="uploadMsgType">{{ uploadMsg }}</p>
      </section>

      <!-- 检索测试 -->
      <section class="card">
        <h2 class="sub">🔍 检索测试</h2>

        <div class="row">
          <input
            v-model="question"
            type="text"
            class="grow"
            placeholder="例如：K80 的电池容量是多少"
            @keyup.enter="onSearch"
          />
          <select v-model="mode" class="select">
            <option v-for="m in modeOptions" :key="m">{{ m }}</option>
          </select>
          <button class="btn" :disabled="searching" @click="onSearch">
            {{ searching ? '检索中…' : '检索' }}
          </button>
        </div>

        <p v-if="searchMsg" class="msg info">{{ searchMsg }}</p>

        <div v-if="results.length" class="results">
          <div v-for="(r, i) in results" :key="i" class="result">
            <span class="score">相关度 {{ r.score }}</span>
            <p class="content">{{ r.content }}</p>
          </div>
        </div>
      </section>
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
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 20px;
}

.title {
  font-size: 22px;
  color: #333;
  margin-bottom: 18px;
}

.card {
  background: #fff;
  border-radius: 10px;
  border: 1px solid #e8e8e8;
  padding: 20px;
  margin-bottom: 18px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.sub {
  font-size: 16px;
  color: #333;
  margin-bottom: 6px;
}

.caption {
  font-size: 13px;
  color: #999;
  margin-bottom: 14px;
}

.row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.grow {
  flex: 1;
}

.row input[type='text'],
.select {
  padding: 9px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
}

.row input[type='text']:focus {
  border-color: #2563eb;
}

.btn {
  padding: 9px 20px;
  border: none;
  border-radius: 6px;
  background: #2563eb;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn:disabled {
  background: #b9c6f0;
  cursor: not-allowed;
}

.filename {
  margin-top: 10px;
  font-size: 13px;
  color: #555;
}

.msg {
  margin-top: 10px;
  font-size: 13px;
}

.msg.success {
  color: #52c41a;
}

.msg.error {
  color: #ff4d4f;
}

.msg.info {
  color: #999;
}

.results {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.result {
  border: 1px solid #eef2ff;
  background: #f8faff;
  border-radius: 8px;
  padding: 12px 14px;
}

.score {
  display: inline-block;
  font-size: 12px;
  color: #2563eb;
  background: #eef2ff;
  padding: 2px 8px;
  border-radius: 10px;
  margin-bottom: 8px;
}

.content {
  font-size: 14px;
  color: #333;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>