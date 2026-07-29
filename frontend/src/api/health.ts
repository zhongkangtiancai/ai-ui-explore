export interface HealthResponse {
  status: 'ok'
  service: string
  version: string
  environment: string
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl}/health`, {
    headers: {
      Accept: 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error('Health request failed')
  }

  return (await response.json()) as HealthResponse
}
