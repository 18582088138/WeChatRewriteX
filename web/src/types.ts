export interface Article {
  id: string
  url: string
  title: string
  source_site: string
  published_at: string | null
  status: string
  ui_status: 'New' | 'Process' | 'Done' | 'Failed'
  error: string | null
  created_at: string
  progress?: { running: string[]; pending: string[]; last_done: string | null }
  materials_count?: number
  versions?: DraftRow[]
  selected_material_ids?: string[]
  user_notes?: string
  latest_review?: { id: string } | null
  publish_jobs?: PublishJob[]
}

export interface Block {
  id: string
  type: 'heading' | 'paragraph' | 'quote' | 'image' | 'video' | 'divider'
  level?: number
  text: string
  asset_id?: string | null
  caption?: string | null
  source?: string | null
  citations?: string[]
}

export interface DraftDoc {
  id: string
  article_id: string
  version: number
  blocks: Block[]
  meta: {
    subtitle: string
    ref_links: { title: string; url: string }[]
    keywords: string[]
    one_liner: string
    title_candidates: string[]
    word_count: number
    xhs_pages: { title: string; block_ids: string[]; asset_id?: string | null }[]
  }
}

export interface DraftRow {
  id: string
  article_id: string
  version: number
  word_count: number
  status: string
  origin: string
  created_at: string
  doc?: DraftDoc
}

export interface Material {
  id: string
  scope: 'article' | 'common'
  article_id?: string
  kind: 'text' | 'image' | 'video' | 'audio' | 'doc' | 'link'
  path?: string
  url?: string | null
  title: string
  note: string
  ref_type?: string
  fetch_status: string
  watermark?: number | null
  width?: number
  duration?: number | null
  height?: number
  source_material_id?: string | null
  source_url?: string
  created_at: string
}

export interface ReviewItem {
  id: string
  category: 'layout' | 'fact' | 'attribution' | 'compliance' | 'originality' | 'ai_flavor'
  severity: 'info' | 'warn' | 'blocker'
  block_id?: string | null
  message: string
  suggestion: string
  auto_fixable: number
  status: 'pending' | 'accepted' | 'dismissed' | 'fixed'
  resolved_note?: string
}

export interface PublishJob {
  id: string
  platform: string
  status: string
  result_json: string
  created_at: string
}

export interface VersionRow {
  id: string
  version: number
  word_count: number
  status: string
  origin: string
  created_at: string
}


export interface DraftView {
  draft: DraftRow & { doc: DraftDoc }
  versions: VersionInfo[]
}
export interface VersionInfo {
  version: number
  origin: string
  status: string
  checkpoint: boolean
  saved?: boolean
  note?: string
  draft_id?: string
  word_count: number | null
  created_at: string
}
export interface ArticlePage {
  articles: Article[]
  total: number
  counts: Record<string, number>
}
