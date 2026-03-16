import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export function buildGraph(data) {
  return api.post('/graph/build', data)
}

export function getGraph(graphId) {
  return api.get(`/graph/${graphId}`)
}

export function getGraphStatus(graphId) {
  return api.get(`/graph/${graphId}/status`)
}

export function uploadScenarioFile(file, scenarioType) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('scenario_type', scenarioType)
  return api.post('/graph/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function analyzeSeed(data) {
  return api.post('/graph/analyze-seed', data)
}

export function getGraphSnapshots(graphId) {
  return api.get(`/graph/${graphId}/snapshots`)
}

export function getGraphSnapshot(graphId, roundNumber) {
  return api.get(`/graph/${graphId}/snapshot/${roundNumber}`)
}

export function uploadSeedFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/graph/upload-seed', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getNodeEvidence(graphId, nodeId) {
  return api.get(`/graph/${graphId}/node/${nodeId}/evidence`)
}

export function getNodeNeighborhood(graphId, nodeId, hops = 2) {
  return api.get(`/graph/${graphId}/node/${nodeId}/neighborhood`, { params: { hops } })
}
