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
        <span class="brand">Morai</span>
      </div>
      <nav class="header-nav">
        <router-link to="/" class="nav-link">首頁</router-link>
        <router-link to="/app" class="nav-link">工作區</router-link>
        <router-link to="/learn" class="nav-link">教學</router-link>
        <router-link to="/landing" class="nav-link">關於</router-link>
        <router-link to="/god-view" class="nav-link">神眼終端</router-link>
        <router-link to="/dashboard" class="nav-link">預測面板</router-link>
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
  /* === Monochromatic + Orange Accent (MiroFish-aligned) === */
  --bg-app:     #FAFAFA;
  --bg-graph:   #F5F5F5;
  --bg-card:    #FFFFFF;
  --bg-nav:     #FFFFFF;
  --bg-input:   #F9F9F9;

  --accent:        #FF6B35;
  --accent-hover:  #FF4500;
  --accent-subtle: rgba(255, 107, 53, 0.08);
  --accent-warn:   #FF9800;
  --accent-danger: #DC2626;
  --accent-success:#10B981;

  --text-primary:   #000000;
  --text-secondary: #666666;
  --text-muted:     #999999;
  --text-quaternary:#9CA3AF;
  --border:         #EAEAEA;
  --border-hover:   #999999;

  --font-mono: 'JetBrains Mono', monospace;
  --font-sans: 'Space Grotesk', 'Noto Sans HK', sans-serif;
  --font-body: 'Inter', 'Noto Sans HK', system-ui, sans-serif;

  /* Legacy aliases */
  --bg-primary:      var(--bg-app);
  --bg-secondary:    var(--bg-app);
  --bg-surface:      var(--bg-card);
  --border-color:    var(--border);
  --border-emphasis: var(--border-hover);
  --accent-blue:     var(--accent);
  --accent-green:    var(--accent-success);
  --accent-orange:   var(--accent-warn);
  --accent-red:      var(--accent-danger);
  --accent-cyan:     var(--accent-hover);
  --accent-purple:   #7C3AED;
  --accent-pink:     #EC4899;
  --accent-blue-light: var(--accent-subtle);
  --accent-rgb: 255, 107, 53;

  /* Geometry */
  --font-size-base: 14px;
  --radius-xs: 2px;
  --radius-sm: 2px;
  --radius-md: 4px;
  --radius-lg: 6px;
  --radius-xl: 8px;
  --shadow-card:    0 1px 2px rgba(0,0,0,0.05);
  --shadow-hover:   0 4px 12px rgba(0,0,0,0.05);
  --shadow-elevated:0 8px 32px rgba(0,0,0,0.1);

  /* Motion */
  --transition: all 0.2s ease;
  --ease-standard: cubic-bezier(0.4, 0, 0.2, 1);
  --ease-decelerate: cubic-bezier(0.0, 0, 0.2, 1);
  --ease-spring: cubic-bezier(0.23, 1, 0.32, 1);
  --duration-fast: 0.15s;
  --duration-standard: 0.2s;
  --duration-medium: 0.3s;
  --duration-layout: 0.35s;

  /* Legacy glow + glass tokens */
  --shadow-glow-cyan: 0 4px 20px rgba(255, 107, 53, 0.25);
  --glass-bg: rgba(255, 255, 255, 0.85);
  --glass-blur: 12px;
}

body {
  font-family: var(--font-sans);
  background: var(--bg-app);
  color: var(--text-primary);
}

a {
  color: var(--accent);
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
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.font-mono { font-family: var(--font-mono); }

.text-accent-cyan {
  color: var(--accent-cyan);
}

.text-accent-blue {
  color: var(--accent);
}

@keyframes pulse-subtle {
  0%, 100% { box-shadow: 0 0 0 0 rgba(var(--accent-rgb), 0.4); }
  70% { box-shadow: 0 0 0 8px rgba(var(--accent-rgb), 0); }
}

.status-pulse { animation: pulse-subtle 2s infinite; }

/* Skeleton loading shimmer */
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.skeleton {
  background: linear-gradient(90deg, #F0F0F0 25%, #E0E0E0 50%, #F0F0F0 75%);
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
  box-shadow: var(--shadow-hover);
}

/* Table row hover */
table tbody tr {
  transition: background 0.15s cubic-bezier(0.4, 0, 0.2, 1);
}
table tbody tr:hover {
  background: rgba(0, 0, 0, 0.02);
}

/* Focus glow ring */
input:focus-visible,
select:focus-visible,
textarea:focus-visible,
button:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--bg-card), 0 0 0 4px rgba(255, 107, 53, 0.3);
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
  background: rgba(0,0,0,0.15);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(0,0,0,0.3);
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
  padding: 0 40px;
  height: 60px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
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
  color: var(--text-primary);
}

.brand {
  font-size: 18px;
  font-weight: 800;
  font-family: var(--font-mono);
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--text-primary);
}

.header-nav {
  display: flex;
  gap: 16px;
}

.nav-link {
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
}

.nav-link:hover {
  opacity: 0.7;
  color: var(--text-primary);
  background: none;
}

.nav-link.router-link-active {
  color: var(--text-primary);
  background: none;
}

.app-main {
  flex: 1;
}
</style>
