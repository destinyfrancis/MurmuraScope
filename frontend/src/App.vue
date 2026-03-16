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
  /* Dark scientific theme */
  --bg-primary: #0d1117;
  --bg-secondary: #1a1f2e;
  --bg-card: #15202b;
  --bg-input: #1a2332;
  --bg-surface: #161d28;
  --border-color: #2a3d52;
  --border-emphasis: #3a5068;
  --border-glow: rgba(0, 212, 255, 0.2);
  --text-primary: #e8eef5;
  --text-secondary: #9aa8ba;
  --text-muted: #5a6e82;
  --accent-blue: #00d4ff;
  --accent-blue-light: rgba(0, 212, 255, 0.12);
  --accent-green: #00d965;
  --accent-green-light: rgba(0, 217, 101, 0.12);
  --accent-orange: #ff9f43;
  --accent-orange-light: rgba(255, 159, 67, 0.12);
  --accent-purple: #a78bfa;
  --accent-purple-light: rgba(167, 139, 250, 0.12);
  --accent-red: #ff4444;
  --accent-red-light: rgba(255, 68, 68, 0.12);
  --accent-cyan: #00d4ff;
  --accent-cyan-light: rgba(0, 212, 255, 0.12);
  --accent-pink: #f472b6;
  --glass-bg: rgba(21, 32, 43, 0.8);
  --glass-blur: 12px;
  --glass-border: #2a3d52;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.4), 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.4);
  --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.5);
  --shadow-glow-blue: 0 0 20px rgba(0, 212, 255, 0.15);
  --shadow-glow-cyan: 0 0 20px rgba(0, 212, 255, 0.15);
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Noto Sans TC', 'PingFang HK', 'Microsoft JhengHei', sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-pill: 9999px;
  --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  --transition-expand: 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  --transition-modal: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
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
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
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
  0%, 100% { box-shadow: 0 0 0 0 rgba(0, 212, 255, 0.4); }
  70% { box-shadow: 0 0 0 8px rgba(0, 212, 255, 0); }
}

.status-pulse { animation: pulse-subtle 2s infinite; }

/* Skeleton loading shimmer */
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.skeleton {
  background: linear-gradient(90deg, #1a2332 25%, #2a3d52 50%, #1a2332 75%);
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

/* ── Animation Polish (Phase 5) ────────────────────────────────── */

/* Card hover lift */
.card-hover-lift {
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.card-hover-lift:hover {
  transform: translateY(-2px);
  box-shadow: 0 0 20px rgba(0, 212, 255, 0.1);
}

/* Table row hover */
table tbody tr {
  transition: background 0.15s cubic-bezier(0.4, 0, 0.2, 1);
}
table tbody tr:hover {
  background: rgba(0, 212, 255, 0.04);
}

/* Focus glow ring */
input:focus-visible,
select:focus-visible,
textarea:focus-visible,
button:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--bg-primary), 0 0 0 4px rgba(0, 212, 255, 0.4);
}

/* Smooth transitions for interactive elements */
a, button, input, select, textarea {
  transition: color 0.2s cubic-bezier(0.4, 0, 0.2, 1),
              background 0.2s cubic-bezier(0.4, 0, 0.2, 1),
              border-color 0.2s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

/* Scrollbar styling */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #2a3d52;
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: #3a5068;
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
  background: var(--bg-card);
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
  background: rgba(0, 212, 255, 0.08);
}

.app-main {
  flex: 1;
}
</style>
