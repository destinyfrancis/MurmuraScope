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
  /* === Pearl / Emerald Light Theme === */
  --bg-app:     #F3F4F6;
  --bg-graph:   #E9EAEC;
  --bg-card:    #FFFFFF;
  --bg-nav:     #000000;

  --accent:        #059669;
  --accent-warn:   #F59E0B;
  --accent-danger: #DC143C;

  --text-primary: #111827;
  --text-muted:   #9CA3AF;
  --border:       #E5E7EB;

  --font-mono: 'JetBrains Mono', monospace;
  --font-sans: 'Space Grotesk', 'Noto Sans HK', sans-serif;

  /* Legacy aliases (remove as components are updated) */
  --bg-primary:      var(--bg-app);
  --bg-secondary:    var(--bg-app);
  --bg-surface:      var(--bg-card);
  --bg-input:        var(--bg-card);
  --border-color:    var(--border);
  --border-emphasis: var(--border);
  --text-secondary:  var(--text-muted);
  --accent-blue:     var(--accent);
  --accent-green:    var(--accent);
  --accent-orange:   var(--accent-warn);
  --accent-red:      var(--accent-danger);
  --accent-cyan:     var(--accent);
  --accent-purple:   #7C3AED;
  --accent-pink:     #EC4899;

  /* Typography */
  --font-size-base: 14px;
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 10px;
  --shadow-card: 0 1px 3px rgba(0,0,0,0.08);
}

body {
  font-family: var(--font-sans);
  background: var(--bg-app);
  color: var(--text-primary);
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
