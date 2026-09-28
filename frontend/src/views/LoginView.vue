<script setup>
// ============================================================
// 登录 / 注册页（对照之前 Streamlit 版 web/app.py 重写为 Vue）
// 功能：
//   1. 登录 / 注册 两种模式切换
//   2. 一键体验：免注册直接进聊天页（调后端 /auth/demo）
//   3. 登录 / 注册成功后把 token 存进 localStorage，跳转聊天页
// ============================================================
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { login, register, guestLogin } from '../api'
import { saveAuth } from '../auth'

const router = useRouter()

// 当前模式：'登录' 或 '注册'
const mode = ref('登录')

// 表单字段（用同一个表单，注册时多一个邮箱）
const username = ref('')
const password = ref('')
const email = ref('')

// 提示信息（成功/失败都显示在同一处）
const message = ref('')
const messageType = ref('') // 'error' | 'success'

// 是否正在请求（防止重复提交）
const loading = ref(false)

// 按钮文字根据模式切换
const submitText = computed(() => (mode.value === '登录' ? '登录' : '注册'))

function showError(text) {
  message.value = text
  messageType.value = 'error'
}

function showSuccess(text) {
  message.value = text
  messageType.value = 'success'
}

// 切换 登录/注册 时清空提示
function switchMode(m) {
  mode.value = m
  message.value = ''
}

// 登录 / 注册 表单提交
async function onSubmit() {
  // 1. 前端先做基础校验（和后端校验一致）
  if (!username.value || !password.value) {
    showError('用户名和密码不能为空')
    return
  }
  if (mode.value === '注册' && !email.value) {
    showError('注册时请填写邮箱')
    return
  }

  loading.value = true
  message.value = ''
  try {
    if (mode.value === '注册') {
      // 注册：成功后不直接登录，提示用户切换到登录
      await register(username.value, email.value, password.value)
      showSuccess('注册成功！请前往登录')
      mode.value = '登录'
      password.value = ''
    } else {
      // 登录：成功后存 token，跳转聊天页
      const data = await login(username.value, password.value)
      saveAuth(data.access_token, username.value)
      router.push('/')
    }
  } catch (e) {
    // 网络不通 or 后端报错（detail 已是中文）
    showError(e.message || '请求失败，请确认后端服务已启动')
  } finally {
    loading.value = false
  }
}

// 一键体验：调 /auth/demo，免注册直接进聊天页
async function onGuest() {
  loading.value = true
  message.value = ''
  try {
    const data = await guestLogin()
    saveAuth(data.access_token, '游客')
    router.push('/')
  } catch (e) {
    showError(e.message || '无法连接到后端服务，请确认 FastAPI 已启动')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="card">
      <!-- 标题（沿用 Streamlit 版文案） -->
      <h1 class="title">📚 电商售后知识库</h1>
      <p class="caption">基于 RAG 的智能客服辅助系统</p>

      <!-- 登录 / 注册 切换 -->
      <div class="tabs">
        <button
          class="tab"
          :class="{ active: mode === '登录' }"
          @click="switchMode('登录')"
        >登录</button>
        <button
          class="tab"
          :class="{ active: mode === '注册' }"
          @click="switchMode('注册')"
        >注册</button>
      </div>

      <!-- 表单 -->
      <form class="form" @submit.prevent="onSubmit">
        <input
          v-model="username"
          type="text"
          placeholder="请输入用户名"
          autocomplete="username"
        />
        <input
          v-model="password"
          type="password"
          placeholder="请输入密码"
          autocomplete="current-password"
        />
        <input
          v-if="mode === '注册'"
          v-model="email"
          type="email"
          placeholder="请输入邮箱"
          autocomplete="email"
        />
        <button class="submit" type="submit" :disabled="loading">
          {{ loading ? '请稍候…' : submitText }}
        </button>
      </form>

      <!-- 提示信息 -->
      <p v-if="message" class="message" :class="messageType">{{ message }}</p>

      <p class="hint">💡 首次使用请先注册账号</p>

      <div class="divider"><span>或</span></div>

      <!-- 游客一键体验 -->
      <button class="guest" type="button" :disabled="loading" @click="onGuest">
        🚀 一键体验（免注册，直接进入问答）
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 页面背景：和 Streamlit 版保持一致 */
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f5f5;
  padding: 20px;
}

/* 卡片：居中白底 */
.card {
  width: 100%;
  max-width: 380px;
  background: #fff;
  padding: 32px 28px;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  border: 1px solid #e8e8e8;
}

.title {
  font-size: 22px;
  text-align: center;
  color: #333;
  margin-bottom: 6px;
}

.caption {
  text-align: center;
  color: #888;
  font-size: 13px;
  margin-bottom: 24px;
}

/* 登录/注册 切换 */
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 18px;
}

.tab {
  flex: 1;
  padding: 9px 0;
  border: 1px solid #d9d9d9;
  background: #fff;
  border-radius: 6px;
  font-size: 14px;
  color: #555;
  cursor: pointer;
  transition: all 0.2s;
}

.tab:hover {
  border-color: #1677ff;
  color: #1677ff;
}

.tab.active {
  background: #1677ff;
  border-color: #1677ff;
  color: #fff;
}

/* 表单 */
.form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form input {
  padding: 11px 14px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.form input:focus {
  border-color: #1677ff;
}

/* 主按钮 */
.submit {
  padding: 11px 0;
  border: none;
  border-radius: 6px;
  background: #1677ff;
  color: #fff;
  font-size: 15px;
  cursor: pointer;
  transition: background 0.2s;
}

.submit:hover:not(:disabled) {
  background: #0958d9;
}

.submit:disabled {
  background: #9ec3ff;
  cursor: not-allowed;
}

/* 提示信息 */
.message {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.5;
}

.message.error {
  color: #ff4d4f;
}

.message.success {
  color: #52c41a;
}

/* 小字提示 */
.hint {
  margin-top: 12px;
  font-size: 13px;
  color: #999;
}

/* 分割线 */
.divider {
  display: flex;
  align-items: center;
  margin: 18px 0;
  color: #bbb;
  font-size: 13px;
}

.divider::before,
.divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: #e8e8e8;
}

.divider span {
  padding: 0 12px;
}

/* 一键体验按钮 */
.guest {
  width: 100%;
  padding: 11px 0;
  border: 1px solid #1677ff;
  border-radius: 6px;
  background: #fff;
  color: #1677ff;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.guest:hover:not(:disabled) {
  background: #e6f4ff;
}

.guest:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>