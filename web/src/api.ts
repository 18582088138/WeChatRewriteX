/** API 客户端：fetch 薄封装 + SSE 订阅。访问令牌存 localStorage（局域网模式用）。 */

export function getToken(): string {
  // wra_token 为旧名兼容回退（V1.6 更名文枢）
  return localStorage.getItem('wenshu_token') || localStorage.getItem('wra_token') || ''
}

export function setToken(t: string) {
  localStorage.setItem('wenshu_token', t)
  localStorage.removeItem('wra_token')
}

function authHeaders(json = false): Record<string, string> {
  const headers: Record<string, string> = json ? { 'Content-Type': 'application/json' } : {}
  const token = getToken()
  if (token) headers.Authorization = 'Bearer ' + token
  if (memberCsrf) headers['X-Wenshu-CSRF'] = memberCsrf
  return headers
}

let memberCsrf = ''
const projectRevisions = new Map<string, string>()
const objectProjects = new Map<string, string>()
function projectFor(url:string, body?:any):string|undefined {
  const match=url.match(/\/api\/articles\/([^/?]+)/)
  if(match)return match[1]
  if(body?.article_id)return body.article_id
  const object=url.match(/\/api\/(?:drafts|materials|review-items)\/([^/?]+)/)?.[1]
  return object ? objectProjects.get(object) : undefined
}
function writeHeaders(url:string,body?:unknown,json=false):Record<string,string>{
  const headers=authHeaders(json), aid=projectFor(url,body)
  if(aid && projectRevisions.has(aid))headers['X-Wenshu-Project-Revision']=projectRevisions.get(aid)!
  return headers
}
function remember(resp:Response,result:any){
  const aid=resp.headers.get('X-Wenshu-Project-ID'), revision=resp.headers.get('X-Wenshu-Project-Revision')
  if(aid && revision)projectRevisions.set(aid,revision)
  for(const m of result.materials||[])if(m.article_id)objectProjects.set(m.id,m.article_id)
  const doc=result.draft?.doc || result.draft?.draft?.doc
  if(doc)objectProjects.set(doc.id,doc.article_id)
  for(const i of result.items||[])if(aid)objectProjects.set(i.id,aid)
  for(const i of result.review?.items||[])if(aid)objectProjects.set(i.id,aid)
  return result
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) { super(message) }
}

async function request<T = any>(method: string, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(url, {
    method,
    headers: writeHeaders(url,body,body !== undefined),
    signal, credentials: 'same-origin',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      detail = (await resp.json()).detail || detail
    } catch { /* ignore */ }
    throw new ApiError(detail, resp.status)
  }
  const result = await resp.json()
  if (result.csrf) memberCsrf = result.csrf
  return remember(resp,result) as T
}

export const api = {
  get: <T = any>(url: string, signal?: AbortSignal) => request<T>('GET', url, undefined, signal),
  post: <T = any>(url: string, body?: unknown) => request<T>('POST', url, body),
  put: <T = any>(url: string, body?: unknown) => request<T>('PUT', url, body),
  del: <T = any>(url: string) => request<T>('DELETE', url),

  async upload(url: string, file: File): Promise<any> {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(url, { method: 'POST', body: form, headers: writeHeaders(url), credentials: 'same-origin' })
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText)
    return remember(resp,await resp.json())
  },

  /** 批量上传（本地文件/文件夹收集）：后端逐文件自动识别类型分流入库 */
  async uploadBatch(url: string, files: File[]): Promise<any> {
    const form = new FormData()
    for (const f of files) form.append('files', f, f.name)
    const resp = await fetch(url, { method: 'POST', body: form, headers: writeHeaders(url), credentials: 'same-origin' })
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText)
    return remember(resp,await resp.json())
  },

  fileUrl(rel: string | null | undefined): string {
    return rel ? '/files/' + rel.replace(/^data\//, '').replace(/\\/g, '/').split('/').map(encodeURIComponent).join('/') : ''
  },

  /** 将后端返回的 /files/... 路径补上访问令牌 */
  absUrl(path: string | null | undefined): string {
    return path?.startsWith('/files/') ? this.fileUrl(path.slice(7)) : path || ''
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
  let reconnect: ReturnType<typeof setTimeout> | null = null
  const connect = async () => {
    if (closed) return
    try { await api.get('/api/session') } catch {
      if (!closed) reconnect = setTimeout(connect, 3000)
      return
    }
    if (closed) return
    es = new EventSource('/api/sse')
    // Recover completion events missed while offline by fetching current state.
    es.onopen = () => onEvent({ type: 'connection.ready', ts: Date.now() / 1000 })
    es.onmessage = (ev) => {
      try { onEvent(JSON.parse(ev.data)) } catch { /* heartbeat */ }
    }
    es.onerror = () => {
      es?.close()
      if (!closed) reconnect = setTimeout(connect, 3000)
    }
  }
  connect()
  return () => { closed = true; if (reconnect) clearTimeout(reconnect); es?.close() }
}
