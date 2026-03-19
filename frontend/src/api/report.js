import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export function generateReport(data) {
  return api.post('/report/generate', data)
}

export function getReport(reportId) {
  return api.get(`/report/${reportId}`)
}

export function getReportStatus(reportId) {
  return api.get(`/report/${reportId}/status`)
}

export function chatWithReport(data) {
  return api.post('/report/chat', data)
}

export function chatWithAgent(data) {
  // data: { session_id, agent_id, message }
  // Maps to /report/interview endpoint
  return api.post('/report/interview', {
    session_id: data.session_id,
    agent_id: data.agent_id,
    question: data.message,
  })
}

export function shareReport(reportId) {
  return api.post(`/report/${reportId}/share`)
}

export function getPublicReport(token) {
  return api.get(`/report/public/${token}`)
}

export async function invokeXaiTool(sessionId, toolName, params = {}) {
  const res = await api.post(`/report/${sessionId}/xai-tool`, {
    tool_name: toolName,
    params,
  })
  return res.data?.data
}
