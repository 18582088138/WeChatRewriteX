/** API 客户端：fetch 薄封装 + SSE 订阅。访问令牌存 localStorage（局域网模式用）。 */

export function getToken(): string {
  return localStorage.getItem('wra_token') || ''
}

export function setToken(t: string) {
  localStorage.setItem('wra_token', t)
}

function withToken(url: string): string {
  const t = getToken()
  return t ? url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(t) : url
}

async function request<T = any>(method: string, url: string, body?: unknown): Promise<T> {
  const resp = await fetch(withToken(url), {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      detail = (await resp.json()).detail || detail
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return resp.json() as Promise<T>
}

export const api = {
  get: <T = any>(url: string) => request<T>('GET', url),
  post: <T = any>(url: string, body?: unknown) => request<T>('POST', url, body),
  put: <T = any>(url: string, body?: unknown) => request<T>('PUT', url, body),
  del: <T = any>(url: string) => request<T>('DELETE', url),

  async upload(url: string, file: File): Promise<any> {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(withToken(url), { method: 'POST', body: form })
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText)
    return resp.json()
  },

  fileUrl(rel: string | null | undefined): string {
    return rel ? withToken('/files/' + rel.replace(/^data\//, '')) : ''
  },

  /** 将后端返回的 /files/... 路径补上访问令牌 */
  absUrl(path: string | null | undefined): string {
    return path ? withToken(path) : ''
  },
}

export interface SseEvent {
  type: string
  article_id?: string
  ts: number
  [k: string]: unknown
}

export function subscribeSse(onEvent: (e: SseEvent) => void): () => void {
  let closed = false
  let es: EventSource | null = null
  const connect = () => {
    if (closed) return
    es = new EventSource(withToken('/api/sse'))
    es.onmessage = (ev) => {
      try { onEvent(JSON.parse(ev.data)) } catch { /* heartbeat */ }
    }
    es.onerror = () => {
      es?.close()
      if (!closed) setTimeout(connect, 3000)
    }
  }
  connect()
  return () => { closed = true; es?.close() }
}
