<script setup>
// ============================================
// 聊天页：左侧栏（新建对话 + 历史会话）+ 流式对话
// 顶部导航栏已抽到 components/NavBar.vue
// ============================================
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { streamChat, getSessions, getHistory, deleteSession } from '../api'
import { getToken } from '../auth'
import NavBar from '../components/NavBar.vue'

const router = useRouter()

const token = ref(getToken())                    // 登录页存好的 token
const currentSessionId = ref(crypto.randomUUID()) // 当前会话（新建时生成 UUID）
const sessions = ref([])                          // 侧边栏历史会话列表
const messages = ref([])                          // 当前会话的消息列表
const input = ref('')                             // 输入框内容
const sources = ref([])                           // 本次回答的参考来源
const loading = ref(false)                        // 是否正在等待回答
const imageData = ref(null)                       // 待发送图片（data URI，用于预览+识图）

// 进入页面：没 token 弹回登录页；有则拉取历史会话列表
onMounted(async () => {
  if (!getToken()) {
    router.push('/login')
    return
  }
  await loadSessions()
})

// 拉取左侧栏会话列表
async function loadSessions() {
  try {
    sessions.value = await getSessions(token.value)
  } catch (e) {
    console.warn('加载会话列表失败：', e.message)
  }
}

// 新建对话：换一个新 UUID，清空当前消息（上下文从零开始）
function newChat() {
  currentSessionId.value = crypto.randomUUID()
  messages.value = []
  sources.value = []
}

// 点击历史会话：切换并加载它的聊天记录
async function selectSession(sid) {
  currentSessionId.value = sid
  sources.value = []
  messages.value = []
  try {
    messages.value = await getHistory(token.value, sid)
  } catch (e) {
    messages.value = [{ role: 'assistant', content: '加载历史失败：' + e.message }]
  }
}

// 删除历史会话
async function removeSession(sid) {
  try {
    await deleteSession(token.value, sid)
  } catch (e) {
    alert('删除失败：' + e.message)
    return
  }
  if (sid === currentSessionId.value) {
    newChat()
  }
  await loadSessions()
}

// 选择图片：用 canvas 统一转成 JPEG（解决 PNG/WebP 与后端 jpeg 前缀不匹配 + 压缩大图）
function onPickImage(e) {
  const file = e.target.files && e.target.files[0]
  if (!file) return

  const img = new Image()
  const url = URL.createObjectURL(file)
  img.onload = () => {
    // 限制最长边（大图会转成超大 base64，卡请求且易超请求体限制）
    const MAX = 1280
    let { width, height } = img
    if (width > height && width > MAX) {
      height = Math.round((height * MAX) / width)
      width = MAX
    } else if (height >= width && height > MAX) {
      width = Math.round((width * MAX) / height)
      height = MAX
    }

    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    ctx.drawImage(img, 0, 0, width, height)

    // 统一输出 JPEG（质量 0.85），MIME 与后端 "image/jpeg" 前缀一致
    imageData.value = canvas.toDataURL('image/jpeg', 0.85)
    URL.revokeObjectURL(url)
  }
  img.onerror = () => {
    URL.revokeObjectURL(url)
    alert('图片读取失败，请换一张试试')
  }
  img.src = url
  e.target.value = ''   // 清空，允许下次再选同一张图
}

// 取消已选图片
function removeImage() {
  imageData.value = null
}

// 发送消息
async function send() {
  const q = input.value.trim()
  // 允许"只发图片不带文字"（识图：拍商品问"这是什么/多少钱"）
  if ((!q && !imageData.value) || loading.value) return

  // 后端只要 base64 部分（去掉 "data:image/...;base64," 前缀）
  const imageBase64 = imageData.value ? imageData.value.split(',')[1] : null

  messages.value.push({ role: 'user', content: q, image: imageData.value })
  input.value = ''
  removeImage()
  loading.value = true
  sources.value = []

  const aiIndex = messages.value.length
  messages.value.push({ role: 'assistant', content: '' })

  try {
    await streamChat({
      token: token.value,
      question: q,
      sessionId: currentSessionId.value,
      image: imageBase64,
      onMeta: (meta) => {
        sources.value = meta.sources || []
      },
      onChunk: (text) => {
        messages.value[aiIndex].content += text
      },
    })
    await loadSessions()
  } catch (e) {
    messages.value[aiIndex].content = '出错了：' + e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <NavBar />

    <div class="body">
      <!-- 左侧栏：新建对话 + 历史会话 -->
      <aside class="sidebar">
        <button class="new-btn" @click="newChat">✨ 新建对话</button>

        <div class="sessions-title">📋 历史会话</div>
        <div class="sessions">
          <div
            v-for="s in sessions"
            :key="s.session_id"
            :class="['session', { active: s.session_id === currentSessionId }]"
          >
            <button
              class="session-title"
              :title="s.title"
              @click="selectSession(s.session_id)"
            >
              {{ (s.title || '新对话').slice(0, 15) }}
            </button>
            <button
              class="session-del"
              title="删除该会话"
              @click="removeSession(s.session_id)"
            >🗑️</button>
          </div>
          <div v-if="!sessions.length" class="empty">暂无历史会话</div>
        </div>
      </aside>

      <!-- 右侧聊天区 -->
      <div class="chat">
        <div class="messages">
          <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
            <span class="role">{{ m.role === 'user' ? '我' : 'AI' }}</span>
            <div class="bubble">
              <img v-if="m.image" :src="m.image" class="msg-img" alt="用户上传的图片" />
              <span v-if="m.content">{{ m.content }}</span>
            </div>
          </div>
        </div>

        <div v-if="sources.length" class="sources">
          <b>参考来源：</b>
          <div v-for="(s, i) in sources" :key="i" class="src">{{ s }}</div>
        </div>

        <div v-if="imageData" class="img-preview">
          <img :src="imageData" alt="待发送图片" />
          <button type="button" class="img-cancel" title="移除图片" @click="removeImage">✕</button>
        </div>

        <form class="input-bar" @submit.prevent="send">
          <label class="img-btn" title="上传图片识图">
            🖼️
            <input type="file" accept="image/*" class="file-input" @change="onPickImage" />
          </label>
          <input v-model="input" placeholder="输入你的问题…（可上传商品图片识图）" :disabled="loading" />
          <button type="submit" :disabled="loading">
            {{ loading ? '回复中…' : '发送' }}
          </button>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* 左侧栏 */
.sidebar {
  width: 250px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid #e5e7eb;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.new-btn {
  padding: 9px 0;
  border: none;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.new-btn:hover {
  background: #1d4ed8;
}

.sessions-title {
  margin: 18px 4px 8px;
  font-size: 13px;
  color: #888;
}

.sessions {
  flex: 1;
  overflow-y: auto;
}

.session {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 8px;
  margin-bottom: 2px;
  transition: background 0.15s;
}

.session.active {
  background: #eef2ff;
}

.session:hover {
  background: #f3f4f6;
}

.session.active:hover {
  background: #e0e7ff;
}

.session-title {
  flex: 1;
  text-align: left;
  padding: 7px 6px;
  border: none;
  background: transparent;
  font-size: 13px;
  color: #333;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-del {
  border: none;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  opacity: 0.5;
  transition: opacity 0.15s;
}

.session-del:hover {
  opacity: 1;
  background: #fee2e2;
}

.empty {
  font-size: 13px;
  color: #bbb;
  text-align: center;
  padding: 20px 0;
}

/* 聊天区 */
.chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  max-width: 760px;
  width: 100%;
  margin: 0 auto;
  padding: 16px;
  overflow: hidden;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.msg {
  display: flex;
  flex-direction: column;
  margin-bottom: 14px;
}

.role {
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}

.bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg.user { align-items: flex-end; }
.msg.user .bubble {
  background: #2563eb;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.msg.assistant { align-items: flex-start; }
.msg.assistant .bubble {
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  border-bottom-left-radius: 4px;
}

.sources {
  background: #eef2ff;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  color: #555;
  margin-bottom: 10px;
}

.src {
  margin-top: 6px;
  padding-left: 10px;
  border-left: 3px solid #2563eb;
  color: #777;
}

.input-bar {
  display: flex;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid #e5e7eb;
}

.input-bar input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 15px;
}

.input-bar button {
  padding: 10px 22px;
  border: none;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-size: 15px;
  cursor: pointer;
  transition: background 0.2s;
}

.input-bar button:hover:not(:disabled) { background: #1d4ed8; }
.input-bar button:disabled { background: #b9c6f0; cursor: not-allowed; }

/* 图片上传 + 预览 */
.file-input { display: none; }

.img-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: #fff;
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
}
.img-btn:hover { background: #f3f4f6; }

.img-preview {
  position: relative;
  display: inline-block;
  margin-bottom: 10px;
}
.img-preview img {
  max-width: 160px;
  max-height: 160px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  display: block;
}
.img-cancel {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 50%;
  background: #ef4444;
  color: #fff;
  font-size: 12px;
  cursor: pointer;
  line-height: 1;
}

.msg-img {
  display: block;
  max-width: 220px;
  max-height: 220px;
  border-radius: 8px;
  margin-bottom: 8px;
}
</style>