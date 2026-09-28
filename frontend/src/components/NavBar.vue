<script setup>
// ============================================
// 顶部导航栏：三个页面共用（对话 / 知识库 / 监控）+ 用户名 + 退出
// ============================================
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { clearAuth, getAuth } from '../auth'

const router = useRouter()
const route = useRoute()

// 导航项：path 是路由地址，label 是显示文字
const links = [
  { path: '/', label: '💬 对话' },
  { path: '/knowledge', label: '📚 知识库' },
  { path: '/monitor', label: '📊 监控' },
]

// 当前登录用户名
const username = computed(() => {
  const auth = getAuth()
  return auth ? auth.username : ''
})

function logout() {
  clearAuth()
  router.push('/login')
}
</script>

<template>
  <header class="topbar">
    <div class="left">
      <span class="brand">🛒 电商智能客服</span>
      <nav class="nav">
        <RouterLink
          v-for="l in links"
          :key="l.path"
          :to="l.path"
          class="link"
          :class="{ active: route.path === l.path }"
        >{{ l.label }}</RouterLink>
      </nav>
    </div>

    <div class="user">
      <span class="name">👤 {{ username }}</span>
      <button class="logout" @click="logout">退出登录</button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 54px;
  padding: 0 20px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.left {
  display: flex;
  align-items: center;
  gap: 24px;
}

.brand {
  font-size: 16px;
  font-weight: 600;
  color: #333;
}

.nav {
  display: flex;
  gap: 6px;
}

.link {
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 14px;
  color: #555;
  text-decoration: none;
  transition: all 0.15s;
}

.link:hover {
  background: #f3f4f6;
  color: #2563eb;
}

.link.active {
  background: #eef2ff;
  color: #2563eb;
  font-weight: 600;
}

.user {
  display: flex;
  align-items: center;
  gap: 12px;
}

.name {
  font-size: 14px;
  color: #555;
}

.logout {
  padding: 6px 14px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  color: #555;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.logout:hover {
  border-color: #ef4444;
  color: #ef4444;
}
</style>