<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

function goHome() {
  router.push('/')
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="header-left" @click="goHome">
        <span class="logo">⬡</span>
        <span class="brand">HKSimEngine</span>
      </div>
      <nav class="header-nav">
        <router-link to="/" class="nav-link">首頁</router-link>
        <router-link to="/app" class="nav-link">工作區</router-link>
        <router-link to="/learn" class="nav-link">教學</router-link>
        <router-link to="/landing" class="nav-link">關於</router-link>
      </nav>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style>
*,
*::before,
*::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  /* Light theme — analytical, trust-building, data-dense */
  --bg-primary: #FAFBFC;
  --bg-secondary: #F3F4F6;
  --bg-card: #FFFFFF;
  --bg-input: #FFFFFF;
  --bg-surface: #F9FAFB;
  --border-color: #E5E7EB;
  --border-emphasis: #D1D5DB;
  --border-glow: rgba(37, 99, 235, 0.2);
  --text-primary: #111827;
  --text-secondary: #4B5563;
  --text-muted: #9CA3AF;
  --accent-blue: #2563EB;
  --accent-blue-light: #DBEAFE;
  --accent-green: #059669;
  --accent-green-light: #D1FAE5;
  --accent-orange: #D97706;
  --accent-orange-light: #FEF3C7;
  --accent-purple: #7C3AED;
  --accent-purple-light: #EDE9FE;
  --accent-red: #DC2626;
  --accent-red-light: #FEE2E2;
  --accent-cyan: #0891B2;
  --accent-cyan-light: #CFFAFE;
  --accent-pink: #DB2777;
  --glass-bg: #FFFFFF;
  --glass-blur: 0px;
  --glass-border: #E5E7EB;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.1), 0 1px 2px rgba(0, 0, 0, 0.06);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.07);
  --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
  --shadow-glow-blue: 0 4px 6px rgba(37, 99, 235, 0.1);
  --shadow-glow-cyan: 0 4px 6px rgba(8, 145, 178, 0.1);
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Noto Sans TC', 'PingFang HK', 'Microsoft JhengHei', sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-pill: 9999px;
  --transition: 0.15s ease;
  --transition-expand: 0.2s ease;
  --transition-modal: 0.3s ease-out;
}

body {
  font-family: var(--font-sans);
  background: var(--bg-primary);
  color: var(--text-primary);
  line-height: 1.6;
  min-height: 100vh;
}

a {
  color: var(--accent-blue);
  text-decoration: none;
}

button {
  cursor: pointer;
  font-family: inherit;
}

input,
select,
textarea {
  font-family: inherit;
}

.glass-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.font-mono { font-family: var(--font-mono); }

.text-accent-cyan {
  color: var(--accent-cyan);
}

.text-accent-blue {
  color: var(--accent-blue);
}

@keyframes pulse-subtle {
  0%, 100% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.4); }
  70% { box-shadow: 0 0 0 8px rgba(37, 99, 235, 0); }
}

.status-pulse { animation: pulse-subtle 2s infinite; }

/* Skeleton loading shimmer */
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.skeleton {
  background: linear-gradient(90deg, #F3F4F6 25%, #E5E7EB 50%, #F3F4F6 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: var(--radius-sm);
}

.skeleton-text {
  height: 14px;
  margin-bottom: 8px;
}

.skeleton-title {
  height: 20px;
  width: 60%;
  margin-bottom: 12px;
}

.skeleton-circle {
  border-radius: 50%;
}

.skeleton-card {
  height: 120px;
  border-radius: var(--radius-md);
}
</style>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
  background: #FFFFFF;
  border-bottom: 1px solid var(--border-color);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
}

.logo {
  font-size: 24px;
  color: var(--accent-blue);
}

.brand {
  font-size: 18px;
  font-weight: 700;
  font-family: var(--font-mono);
  letter-spacing: 1.5px;
  text-transform: uppercase;
}

.header-nav {
  display: flex;
  gap: 16px;
}

.nav-link {
  color: var(--text-secondary);
  font-size: 14px;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  transition: var(--transition);
}

.nav-link:hover,
.nav-link.router-link-active {
  color: var(--accent-blue);
  background: var(--accent-blue-light);
}

.app-main {
  flex: 1;
}
</style>
