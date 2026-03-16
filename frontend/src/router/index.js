import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/Process.vue'
import SimulationRun from '../views/SimulationRun.vue'
import Report from '../views/Report.vue'
import Interaction from '../views/Interaction.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home,
  },
  {
    path: '/process/:scenarioType',
    name: 'Process',
    component: Process,
    props: true,
  },
  {
    path: '/simulation/:sessionId',
    name: 'SimulationRun',
    component: SimulationRun,
    props: true,
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: Report,
    props: true,
  },
  {
    path: '/interaction/:sessionId',
    name: 'Interaction',
    component: Interaction,
    props: true,
  },
  {
    path: '/app',
    name: 'Workspace',
    component: () => import('../views/Workspace.vue'),
  },
  {
    path: '/app/graph/:sessionId',
    name: 'GraphExplorer',
    component: () => import('../views/GraphExplorer.vue'),
    props: true,
  },
  {
    path: '/public/report/:token',
    name: 'PublicReport',
    component: () => import('../views/PublicReport.vue'),
    props: true,
  },
  {
    path: '/learn',
    name: 'Learn',
    component: () => import('../views/Learn.vue'),
  },
  {
    path: '/app/evidence/:sessionId',
    name: 'EvidenceExplorer',
    component: () => import('../views/EvidenceExplorer.vue'),
    props: true,
  },
  {
    path: '/landing',
    name: 'Landing',
    component: () => import('../views/Landing.vue'),
  },
  {
    path: '/dashboard',
    name: 'PredictionDashboard',
    component: () => import('../views/PredictionDashboard.vue'),
  },
  {
    path: '/god-view',
    name: 'GodViewTerminal',
    component: () => import('../views/GodViewTerminal.vue'),
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
