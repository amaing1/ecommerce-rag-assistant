// ============================================================
// auth.js — 前端登录态存储（替代 Streamlit 版里的 Cookie）
// ============================================================
// 作用：把 token 和用户名存进浏览器的 localStorage，
//       刷新页面后登录状态还在（和之前 Cookie 的效果一样）。
// 对应后端返回的登录结果：{ access_token, token_type }
// ============================================================

const STORAGE_KEY = "user_auth"

/**
 * 读取登录态
 * 返回：{ token, username } 或 null（没登录）
 */
export function getAuth() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    // JSON 解析失败 / 被篡改，就当没登录
    return null
  }
}

/**
 * 保存登录态（登录 / 注册 / 一键体验成功后调用）
 */
export function saveAuth(token, username) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, username }))
}

/**
 * 清除登录态（退出登录时调用）
 */
export function clearAuth() {
  localStorage.removeItem(STORAGE_KEY)
}

/**
 * 只拿 token（发请求时用），没有就返回空字符串
 */
export function getToken() {
  const auth = getAuth()
  return auth ? auth.token : ""
}