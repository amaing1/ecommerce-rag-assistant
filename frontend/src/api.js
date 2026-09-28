// ============================================================
// api.js — 前端调用后端的所有接口（统一封装：自动带 token + 处理 401）
// ============================================================

// 后端地址
const BASE_URL = "http://127.0.0.1:8000"

// token 失效（过期/无效）时：清掉本地登录态，跳回登录页重新登录
function handleAuthExpired() {
  localStorage.removeItem('user_auth')
  if (window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

// 通用请求封装：
//   - 有 token 就自动带 Authorization 头
//   - 传了 token 却返回 401 → 判定 token 过期，清登录态 + 跳登录页
//   - 其余错误统一取后端 { detail: "..." } 抛出
async function request(path, { method = 'GET', token, json, formData } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`

  let body
  if (formData) {
    body = formData // FormData：让浏览器自动带 multipart 边界
  } else if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  }

  const res = await fetch(BASE_URL + path, { method, headers, body })

  // 带 token 的请求被 401 = token 失效
  // （登录/注册/游客这些公开接口不传 token，它们的 401 是"密码错误"，走下面的 detail）
  if (res.status === 401 && token) {
    handleAuthExpired()
    throw new Error('登录已过期，请重新登录')
  }

  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || '请求失败')
  return data
}

// ------------------------------------------------------------
// 认证相关
// ------------------------------------------------------------

export async function login(username, password) {
  return request('/auth/login', { method: 'POST', json: { username, password } })
}

export async function register(username, email, password) {
  return request('/auth/register', { method: 'POST', json: { username, email, password } })
}

export async function guestLogin() {
  return request('/auth/demo', { method: 'POST' })
}

// ------------------------------------------------------------
// 会话 / 聊天历史
// ------------------------------------------------------------

export async function getSessions(token) {
  const data = await request('/chat/sessions', { token })
  return data.sessions || []
}

export async function getHistory(token, sessionId) {
  const data = await request(
    `/chat/history?session_id=${encodeURIComponent(sessionId)}`,
    { token }
  )
  return data.history || []
}

export async function deleteSession(token, sessionId) {
  await request(`/chat/session/${encodeURIComponent(sessionId)}`, { method: 'DELETE', token })
  return true
}

// ------------------------------------------------------------
// 知识库
// ------------------------------------------------------------

export async function uploadKnowledge(token, file) {
  const form = new FormData()
  form.append('file', file)
  return request('/knowledge/upload', { method: 'POST', token, formData: form })
}

export async function queryKnowledge(token, question, mode = '混合检索') {
  return request('/knowledge/query', {
    method: 'POST',
    token,
    json: { question, top_k: 5, mode },
  })
}

// ------------------------------------------------------------
// 监控
// ------------------------------------------------------------

export async function getMonitorStats(token) {
  return request('/monitor/stats', { token })
}

export async function getMonitorTrend(token, limit = 50) {
  const data = await request(`/monitor/trend?limit=${limit}`, { token })
  return data.points || []
}

export async function getMonitorLogs(token, page = 1, pageSize = 10) {
  return request(`/monitor/logs?page=${page}&page_size=${pageSize}`, { token })
}

// ------------------------------------------------------------
// 聊天：流式请求（打字机效果）
// ------------------------------------------------------------

export async function streamChat({ token, question, sessionId, image, onMeta, onChunk }) {
  const body = { question, session_id: sessionId }
  if (image) body.image = image
  const res = await fetch(`${BASE_URL}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  })

  if (res.status === 401) {
    handleAuthExpired()
    throw new Error('登录已过期，请重新登录')
  }
  if (!res.ok || !res.body) throw new Error('请求失败')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let cut
    while ((cut = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      handleFrame(frame)
    }

    function handleFrame(frame) {
      if (!frame.startsWith('data:')) return
      const payload = frame.slice(5).trim()
      if (payload === '[DONE]') return

      let data
      try {
        data = JSON.parse(payload)
      } catch {
        data = payload
      }

      if (data && typeof data === 'object' && 'can_answer' in data) {
        onMeta?.(data)
      } else if (data && typeof data === 'object' && 'error' in data) {
        throw new Error(data.error)
      } else {
        onChunk?.(data)
      }
    }
  }
}