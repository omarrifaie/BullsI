export const BASE_URL = 'http://localhost:8000'

async function request(path, options) {
  const res = await fetch(`${BASE_URL}${path}`, options)
  if (!res.ok) {
    let detail = ''
    try {
      detail = JSON.stringify((await res.json()).detail)
    } catch {
      detail = res.statusText
    }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

export const getHealth = () => request('/health')
export const getJobs = (mode, refresh = false) =>
  request(`/jobs?mode=${mode}${refresh ? '&refresh=true' : ''}`)
export const queueJob = (id) => request(`/queue/${id}`, { method: 'POST' })
export const getQueue = () => request('/queue')
export const prepare = () => request('/prepare', { method: 'POST' })
export const auto = (threshold) =>
  request(`/auto?threshold=${threshold}`, { method: 'POST' })
export const apply = () => request('/apply', { method: 'POST' })
export const getApplyStatus = () => request('/apply/status')
export const postProfile = (formData) =>
  request('/profile', { method: 'POST', body: formData })
