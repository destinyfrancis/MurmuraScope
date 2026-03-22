import axios, { type AxiosResponse } from 'axios'
import type {
  APIResponse,
  AgentInterviewPayload,
  AgentInterviewResponse,
  ChatPayload,
  GenerateReportPayload,
  Report,
  XaiToolParams,
} from './types'

const api = axios.create({ baseURL: '/api' })

export function generateReport(
  data: GenerateReportPayload,
): Promise<AxiosResponse<APIResponse<Report>>> {
  return api.post('/report/generate', data)
}

export function getReport(reportId: string): Promise<AxiosResponse<APIResponse<Report>>> {
  return api.get(`/report/${reportId}`)
}

export function getReportStatus(
  reportId: string,
): Promise<AxiosResponse<APIResponse<{ status: string; progress?: number }>>> {
  return api.get(`/report/${reportId}/status`)
}

export function chatWithReport(
  data: ChatPayload,
): Promise<AxiosResponse<APIResponse<{ reply: string }>>> {
  return api.post('/report/chat', data)
}

export function chatWithAgent(
  data: AgentInterviewPayload,
): Promise<AxiosResponse<APIResponse<AgentInterviewResponse>>> {
  // Maps to /report/interview endpoint
  return api.post('/report/interview', {
    session_id: data.session_id,
    agent_id: data.agent_id,
    question: data.message,
  })
}

export function shareReport(
  reportId: string,
): Promise<AxiosResponse<APIResponse<{ token: string; url: string }>>> {
  return api.post(`/report/${reportId}/share`)
}

export function getPublicReport(token: string): Promise<AxiosResponse<APIResponse<Report>>> {
  return api.get(`/report/public/${token}`)
}

export async function invokeXaiTool(
  sessionId: string,
  toolName: string,
  params: XaiToolParams = {},
): Promise<any> {
  const res = await api.post(`/report/${sessionId}/xai-tool`, {
    tool_name: toolName,
    params,
  })
  return res.data?.data
}
