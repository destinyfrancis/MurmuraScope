import axios, { type AxiosResponse } from 'axios'
import type {
  APIResponse,
  BuildGraphPayload,
  GraphData,
  GraphSnapshot,
  NodeEvidence,
  KGNode,
  KGEdge,
  RelationshipState,
  SeedAnalysis,
} from './types'

const api = axios.create({ baseURL: '/api' })

export function buildGraph(
  data: BuildGraphPayload,
): Promise<AxiosResponse<APIResponse<GraphData>>> {
  return api.post('/graph/build', data)
}

export function getGraph(graphId: string): Promise<AxiosResponse<APIResponse<GraphData>>> {
  return api.get(`/graph/${graphId}`)
}

export function getGraphStatus(
  graphId: string,
): Promise<AxiosResponse<APIResponse<{ status: string }>>> {
  return api.get(`/graph/${graphId}/status`)
}

export function uploadScenarioFile(
  file: File,
  scenarioType: string,
): Promise<AxiosResponse<APIResponse<GraphData>>> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('scenario_type', scenarioType)
  return api.post('/graph/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function analyzeSeed(
  data: BuildGraphPayload,
): Promise<AxiosResponse<APIResponse<SeedAnalysis>>> {
  return api.post('/graph/analyze-seed', data)
}

export function getGraphSnapshots(
  graphId: string,
): Promise<AxiosResponse<APIResponse<GraphSnapshot[]>>> {
  return api.get(`/graph/${graphId}/snapshots`)
}

export function getGraphSnapshot(
  graphId: string,
  roundNumber: number,
): Promise<AxiosResponse<APIResponse<GraphSnapshot>>> {
  return api.get(`/graph/${graphId}/snapshot/${roundNumber}`)
}

export function uploadSeedFile(
  file: File,
): Promise<AxiosResponse<APIResponse<{ seed_text: string }>>> {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/graph/upload-seed', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getNodeEvidence(
  graphId: string,
  nodeId: string,
): Promise<AxiosResponse<APIResponse<NodeEvidence>>> {
  return api.get(`/graph/${graphId}/node/${nodeId}/evidence`)
}

export function getNodeNeighborhood(
  graphId: string,
  nodeId: string,
  hops: number = 2,
): Promise<AxiosResponse<APIResponse<{ nodes: KGNode[]; edges: KGEdge[] }>>> {
  return api.get(`/graph/${graphId}/node/${nodeId}/neighborhood`, { params: { hops } })
}

export function getRelationshipStates(
  sessionId: string,
  roundNumber: number = -1,
): Promise<AxiosResponse<APIResponse<RelationshipState[]>>> {
  return api.get(`/graph/${sessionId}/relationships`, { params: { round_number: roundNumber } })
}

export function uploadPersonas(
  graphId: string,
  file: File,
): Promise<AxiosResponse<APIResponse<{ imported: number }>>> {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`/graph/${graphId}/personas`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
