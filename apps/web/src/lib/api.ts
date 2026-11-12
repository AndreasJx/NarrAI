const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | undefined | null>;

function detailMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const entry = item as { loc?: unknown[]; msg?: string };
        const field = entry.loc?.filter((part) => part !== "body").join(".");
        return field ? `${field}: ${entry.msg}` : entry.msg;
      })
      .join("; ");
  }
  return `Erro HTTP ${status}`;
}

export async function request<T>(path: string, init: { method?: string; body?: unknown; query?: Query } = {}): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(init.query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const url = `${BASE}${path}${params.size ? `?${params}` : ""}`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: init.method ?? "GET",
      credentials: "same-origin",
      headers: init.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new ApiError(0, "Não foi possível conectar à API. Verifique se o serviço está em execução.");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let payload: unknown = undefined;
  try {
    payload = text ? JSON.parse(text) : undefined;
  } catch {
    payload = text;
  }
  if (!response.ok) {
    const detail = (payload as { detail?: unknown } | undefined)?.detail ?? payload;
    throw new ApiError(response.status, detailMessage(detail, response.status));
  }
  return payload as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Erro inesperado";
}

export type Role = "owner" | "editor" | "viewer";
export type Language = "pt-BR" | "en-US" | "en-GB";
export type Organization = {
  id: number;
  name: string;
  monthly_budget_cents: number;
  voice: string;
  voices: Partial<Record<Language, string>>;
};
export type User = { id: number; email: string; name: string };
export type Me = { user: User; organization: Organization; role: Role; organizations: Organization[] };
export type Member = { user_id: number; email: string; name: string; role: Role; created_at: string };
export type Voice = { id: string; label: string; language: string; gender: string; sample_available: boolean };

export type Project = {
  id: number;
  name: string;
  status: string;
  budget_cents: number;
  spent_cents: number;
  language: Language;
  autopilot: boolean;
  autopilot_stage: string | null;
  autopilot_reason: string | null;
  created_at: string;
  updated_at: string | null;
};
export type BriefInput = {
  topic: string;
  audience: string;
  objective: string;
  language: Language;
  constraints: Record<string, unknown>;
};
export type Brief = BriefInput & { id: number; project_id: number; created_at: string };
export type Source = {
  id: number;
  project_id: number;
  title: string;
  url: string | null;
  summary: string;
  provider: string;
  created_at: string;
};
export type DossierFact = { id: string; text: string; source_url?: string | null; timestamp?: number | null };
export type VideoMoment = {
  video_id: string;
  url: string;
  title: string;
  channel?: string;
  start: number;
  end: number;
  description: string;
};
export type Dossier = {
  id: number;
  project_id: number;
  language: string;
  summary: string;
  facts: DossierFact[];
  angles: string[];
  hooks: string[];
  controversies: string[];
  video_moments: VideoMoment[];
  provider: string;
  cost_cents: number;
  created_at: string;
};
export type Script = {
  id: number;
  project_id: number;
  version: number;
  content: string;
  estimated_cost_cents: number;
  author: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
};
export type Scene = {
  id: number;
  script_version_id: number;
  position: number;
  narration: string;
  visual_prompt: string;
  duration_seconds: number;
  media_asset_id: number | null;
};
export type Asset = {
  id: number;
  project_id: number;
  kind: string;
  filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  status: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
};
export type Shot = {
  id: number;
  scene_id: number;
  position: number;
  asset_id: number | null;
  start: number;
  duration: number;
  effect: string;
  clip_start: number;
  role: "hook" | "clip" | "reveal" | "broll" | string;
};
export type MediaSummary = {
  queued: boolean;
  scenes?: number;
  scenes_with_media?: number;
  assets?: number;
  clips?: number;
  shots?: number;
  candidates?: number;
};
export type AutopilotSettings = {
  enabled: boolean;
  script_threshold: number;
  cadence_hours: number;
  auto_publish: boolean;
  live_publish: boolean;
  platform: "local" | "youtube" | "tiktok";
  language: Language;
  niche: string;
  audience: string;
  duration_seconds: number;
  video_budget_cents: number;
  banned_topics: string[];
  press_kit_urls: string[];
};
export type StageRun = {
  id: number;
  project_id: number;
  stage: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number;
  cost_cents: number;
  score: number | null;
  detail: Record<string, unknown>;
};
export type InboxItem = { project: Project; stage: string; reason: string; blocked_at: string | null };
export type Topic = {
  id: number;
  topic: string;
  angle: string;
  predicted_score: number;
  reason: string;
  source: Record<string, unknown>;
  status: string;
  project_id: number | null;
  created_at: string;
};
export type PlaybookRule = {
  id: number;
  key: string;
  text: string;
  value: Record<string, unknown>;
  confidence: number;
  evidence: Record<string, unknown>;
  active: boolean;
  created_at: string;
};
export type StageStat = {
  stage: string;
  runs: number;
  avg_seconds: number;
  avg_cost_cents: number;
  blocked: number;
  failed: number;
  avg_score: number | null;
};
export type AutopilotOverview = {
  enabled: boolean;
  produced: number;
  published: number;
  in_flight: Project[];
  inbox_count: number;
  auto_approval_rate: number;
  approvals_total: number;
  stage_stats: StageStat[];
  retention_curve: [number, number][];
  retention_samples: number;
  rules: PlaybookRule[];
  topics_proposed: number;
  recent_runs: StageRun[];
  integrations: Record<string, boolean>;
};
export type RetentionDrop = {
  at: number;
  ratio: number;
  loss: number;
  scene: number | null;
  shot: number | null;
  role: string | null;
  kind: string | null;
};
export type Retention = { publication_id: number; points: [number, number][]; drops: RetentionDrop[]; captured_at: string };
export type AITestReport = {
  endpoint: string;
  deployment: string;
  source: string;
  ok: boolean;
  json: boolean;
  latency_ms: number;
  error?: string;
  vision?: boolean;
  vision_answer?: string;
  vision_error?: string;
  usage?: Record<string, number>;
};
export type AutopilotStart = {
  topic?: string;
  angle?: string;
  language?: Language;
  audience?: string;
  duration_seconds?: number;
};
export type UploadTicket = { asset: Asset; upload_url: string; method: "PUT"; headers: Record<string, string> };
export type Approval = {
  id: number;
  gate: "script" | "render" | "publish";
  target_id: number;
  approved: boolean;
  actor: string;
  note: string;
  created_at: string;
};
export type Render = {
  id: number;
  project_id: number;
  script_version_id: number;
  status: string;
  artifact_kind: string | null;
  progress: number;
  attempts: number;
  cost_cents: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};
export type Preview = { url: string; kind: string };
export type Connection = {
  id: number;
  project_id: number;
  platform: string;
  external_account_id: string;
  enabled: boolean;
  authorized: boolean;
  created_at: string;
  account_id: number | null;
  display_name: string;
};
export type Platform = {
  id: string;
  label: string;
  live_supported: boolean;
  oauth_configured: boolean;
  live_enabled: boolean;
  accounts: number;
};
export type PlatformCredential = {
  platform: string;
  label: string;
  client_id: string;
  has_secret: boolean;
  source: "organization" | "env" | "none";
  live_enabled: boolean;
  live_forced_by_env: boolean;
  redirect_uri: string;
  console_url: string;
  updated_by: string;
  updated_at: string | null;
};
export type ChannelAccount = {
  id: number;
  platform: string;
  external_account_id: string;
  display_name: string;
  enabled: boolean;
  authorized: boolean;
  can_refresh: boolean;
  expires_at: string | null;
  projects: number;
  updated_at: string;
};
export type Publication = {
  id: number;
  project_id: number;
  render_id: number;
  connection_id: number;
  title: string;
  description: string;
  live: boolean;
  status: string;
  error: string | null;
  external_id: string | null;
  url: string | null;
  simulated: boolean;
  scheduled_at: string | null;
  published_at: string | null;
  created_at: string;
};
export type CalendarItem = Publication & { project_name: string; platform: string };
export type MetricInput = {
  views: number;
  likes: number;
  comments: number;
  shares: number;
  window_hours: number;
};
export type Metric = MetricInput & {
  id: number;
  publication_id: number;
  average_view_duration: number | null;
  average_view_percentage: number | null;
  captured_at: string;
};
export type ProjectMetrics = {
  views: number;
  likes: number;
  comments: number;
  shares: number;
  engagement_rate: number;
  publications_measured: number;
};
export type Insight = {
  id: number;
  project_id: number;
  kind: string;
  text: string;
  evidence: Record<string, unknown>;
  created_at: string;
};
export type Experiment = {
  id: number;
  project_id: number;
  name: string;
  hypothesis: string;
  variants: Record<string, unknown>;
  status: string;
  created_at: string;
};
export type AuditEvent = {
  id: number;
  action: string;
  actor: string;
  entity_type: string;
  entity_id: number | null;
  payload: Record<string, unknown>;
  created_at: string;
};
export type Overview = {
  project: Project;
  brief: Brief | null;
  sources: Source[];
  scripts: Script[];
  latest_script: Script | null;
  scenes: Scene[];
  approvals: Approval[];
  latest_render: Render | null;
  connections: Connection[];
  publications: Publication[];
  assets: Asset[];
};
export type Dashboard = {
  projects: Project[];
  project_count: number;
  status_counts: Record<string, number>;
  spent_cents: number;
  monthly_budget_cents: number;
  connected_channels: number;
  active_render: { render: Render; project: Project; scenes: number } | null;
  latest_insight: Insight | null;
  published_count: number;
};

const json = (method: string, body?: unknown) => ({ method, body });

export const api = {
  auth: {
    me: () => request<Me>("/auth/me"),
    login: (email: string, password: string) => request<Me>("/auth/login", json("POST", { email, password })),
    signup: (body: { name: string; email: string; password: string; organization_name: string }) =>
      request<Me>("/auth/signup", json("POST", body)),
    logout: () => request<void>("/auth/logout", json("POST")),
    switchOrganization: (organization_id: number) =>
      request<Me>("/auth/switch-organization", json("POST", { organization_id })),
  },
  organization: {
    get: () => request<Organization>("/organization"),
    update: (body: Partial<Pick<Organization, "name" | "monthly_budget_cents" | "voice">>) =>
      request<Organization>("/organization", json("PATCH", body)),
    members: () => request<Member[]>("/organization/members"),
    addMember: (body: { email: string; name: string; role: Role; password?: string }) =>
      request<Member>("/organization/members", json("POST", body)),
    updateMember: (userId: number, role: Role) =>
      request<Member>(`/organization/members/${userId}`, json("PATCH", { role })),
    removeMember: (userId: number) => request<void>(`/organization/members/${userId}`, json("DELETE")),
    voices: () => request<Voice[]>("/voices"),
  },
  autopilot: {
    settings: () => request<AutopilotSettings>("/autopilot/settings"),
    updateSettings: (body: Partial<AutopilotSettings>) => request<AutopilotSettings>("/autopilot/settings", json("PUT", body)),
    integrations: () => request<Record<string, boolean>>("/autopilot/integrations"),
    testAI: () => request<AITestReport>("/autopilot/integrations/test", { method: "POST" }),
    overview: () => request<AutopilotOverview>("/autopilot/overview"),
    start: (body: AutopilotStart) => request<Project>("/autopilot/projects", json("POST", body)),
    enable: (projectId: number) => request<Project>(`/projects/${projectId}/autopilot/start`, { method: "POST" }),
    stop: (projectId: number) => request<Project>(`/projects/${projectId}/autopilot/stop`, { method: "POST" }),
    resume: (projectId: number, approve: boolean) =>
      request<Project>(`/projects/${projectId}/autopilot/resume`, json("POST", { approve })),
    runs: (projectId: number) => request<StageRun[]>(`/projects/${projectId}/autopilot/runs`),
    inbox: () => request<InboxItem[]>("/autopilot/inbox"),
    topics: (status = "proposed") => request<Topic[]>("/autopilot/topics", { query: { status } }),
    planTopics: () => request<Topic[]>("/autopilot/topics/plan", { method: "POST" }),
    useTopic: (topicId: number) => request<Project>(`/autopilot/topics/${topicId}/use`, { method: "POST" }),
    rejectTopic: (topicId: number) => request<void>(`/autopilot/topics/${topicId}`, { method: "DELETE" }),
    playbook: () => request<PlaybookRule[]>("/autopilot/playbook"),
    refreshPlaybook: () => request<PlaybookRule[]>("/autopilot/playbook/refresh", { method: "POST" }),
    retention: (publicationId: number) => request<Retention | null>(`/publications/${publicationId}/retention`),
    addRetention: (publicationId: number, points: [number, number][]) =>
      request<Retention>(`/publications/${publicationId}/retention`, json("POST", { points })),
  },
  media: {
    auto: (projectId: number, scriptId: number) =>
      request<MediaSummary>(`/projects/${projectId}/media/auto`, { method: "POST", query: { script_version_id: scriptId } }),
    shots: (projectId: number, scriptId: number) =>
      request<Shot[]>(`/projects/${projectId}/shots`, { query: { script_version_id: scriptId } }),
    credits: (projectId: number, scriptId: number) =>
      request<string[]>(`/projects/${projectId}/credits`, { query: { script_version_id: scriptId } }),
  },
  dashboard: () => request<Dashboard>("/dashboard"),
  sources: () => request<Source[]>("/sources"),
  calendar: () => request<CalendarItem[]>("/calendar"),
  projects: {
    list: (query: { status?: string; q?: string } = {}) => request<Project[]>("/projects", { query }),
    create: (name: string, language: Language = "pt-BR", budget_cents = 25000) =>
      request<Project>("/projects", json("POST", { name, budget_cents, language })),
    update: (id: number, body: { name?: string; budget_cents?: number }) =>
      request<Project>(`/projects/${id}`, json("PATCH", body)),
    overview: (id: number) => request<Overview>(`/projects/${id}/overview`),
    saveBrief: (id: number, brief: BriefInput) => request<Brief>(`/projects/${id}/brief`, json("PUT", brief)),
    research: (id: number) =>
      request<Source>(`/projects/${id}/generate/research`, json("POST", { estimated_cost_cents: 5 })),
    researchJob: (id: number) => request<{ queued: boolean }>(`/projects/${id}/research/jobs`, { method: "POST" }),
    dossier: (id: number) => request<Dossier | null>(`/projects/${id}/dossier`),
    generateScript: (id: number) =>
      request<Script>(`/projects/${id}/generate/script`, json("POST", { estimated_cost_cents: 10 })),
    editScript: (id: number, scriptId: number, content: string) =>
      request<Script>(`/projects/${id}/scripts/${scriptId}`, json("PUT", { content })),
    storyboard: (id: number, scriptId: number) =>
      request<Scene[]>(`/projects/${id}/generate/storyboard`, { method: "POST", query: { script_version_id: scriptId } }),
    scenes: (id: number, scriptId: number) => request<Scene[]>(`/projects/${id}/scripts/${scriptId}/scenes`),
    approve: (id: number, gate: Approval["gate"], target_id: number, approved = true, note = "") =>
      request<Approval>(`/projects/${id}/approvals`, json("POST", { gate, target_id, approved, note })),
    audit: (id: number) => request<AuditEvent[]>(`/projects/${id}/audit`),
    metrics: (id: number) => request<ProjectMetrics>(`/projects/${id}/metrics`),
    insights: (id: number) => request<Insight[]>(`/projects/${id}/insights`),
    generateInsight: (id: number) => request<Insight>(`/projects/${id}/insights`, json("POST")),
    experiments: (id: number) => request<Experiment[]>(`/projects/${id}/experiments`),
    createExperiment: (id: number, body: { name: string; hypothesis: string; variants: Record<string, unknown> }) =>
      request<Experiment>(`/projects/${id}/experiments`, json("POST", body)),
  },
  scenes: {
    update: (sceneId: number, body: { narration?: string; duration_seconds?: number; media_asset_id?: number; clear_media?: boolean }) =>
      request<Scene>(`/scenes/${sceneId}`, json("PATCH", body)),
  },
  renders: {
    create: (projectId: number, scriptId: number, idempotencyKey: string) =>
      request<Render>(
        `/projects/${projectId}/renders`,
        json("POST", { script_version_id: scriptId, idempotency_key: idempotencyKey, estimated_cost_cents: 100 }),
      ),
    get: (renderId: number) => request<Render>(`/renders/${renderId}`),
    retry: (renderId: number) => request<Render>(`/renders/${renderId}/retry`, json("POST")),
    preview: (renderId: number) => request<Preview>(`/renders/${renderId}/preview`),
  },
  uploads: {
    create: (projectId: number, file: File) =>
      request<UploadTicket>(
        `/projects/${projectId}/uploads`,
        json("POST", { filename: file.name, content_type: file.type, size_bytes: file.size }),
      ),
    complete: (assetId: number) => request<Asset>(`/uploads/${assetId}/complete`, json("POST")),
    url: (assetId: number) => request<Preview>(`/assets/${assetId}/url`),
    remove: (assetId: number) => request<void>(`/assets/${assetId}`, json("DELETE")),
  },
  channels: {
    platforms: () => request<Platform[]>("/platforms"),
    create: (projectId: number, platform: string, external_account_id: string) =>
      request<Connection>(`/projects/${projectId}/connections`, json("POST", { platform, external_account_id })),
    link: (projectId: number, account: ChannelAccount) =>
      request<Connection>(`/projects/${projectId}/connections`, json("POST", { platform: account.platform, account_id: account.id })),
    disable: (connectionId: number) => request<void>(`/connections/${connectionId}`, json("DELETE")),
    authorize: (platform: string, projectId?: number) =>
      request<{ authorization_url: string }>(`/platforms/${platform}/oauth/authorize`, { query: { project_id: projectId } }),
    credentials: () => request<PlatformCredential[]>("/platform-credentials"),
    saveCredentials: (platform: string, body: { client_id: string; client_secret?: string; live_enabled: boolean }) =>
      request<PlatformCredential>(`/platform-credentials/${platform}`, json("PUT", body)),
    removeCredentials: (platform: string) => request<void>(`/platform-credentials/${platform}`, json("DELETE")),
    accounts: () => request<ChannelAccount[]>("/channel-accounts"),
    disconnectAccount: (accountId: number) => request<void>(`/channel-accounts/${accountId}`, json("DELETE")),
  },
  publications: {
    create: (
      projectId: number,
      body: {
        render_id: number;
        connection_id: number;
        title: string;
        description: string;
        idempotency_key: string;
        live: boolean;
        scheduled_at?: string | null;
      },
    ) => request<Publication>(`/projects/${projectId}/publications`, json("POST", body)),
    run: (publicationId: number) => request<Publication>(`/publications/${publicationId}/run`, json("POST")),
    cancel: (publicationId: number) => request<void>(`/publications/${publicationId}`, json("DELETE")),
    reconcile: (publicationId: number) => request<Publication>(`/publications/${publicationId}/reconcile`, json("POST")),
    metrics: (publicationId: number) => request<Metric[]>(`/publications/${publicationId}/metrics`),
    addMetrics: (publicationId: number, body: MetricInput) =>
      request<Metric>(`/publications/${publicationId}/metrics`, json("POST", body)),
    refreshMetrics: (publicationId: number) =>
      request<Metric>(`/publications/${publicationId}/metrics/refresh`, json("POST")),
  },
};

export function uploadFile(ticket: UploadTicket, file: File, onProgress: (percent: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(ticket.method, ticket.upload_url);
    xhr.withCredentials = ticket.upload_url.startsWith("/");
    for (const [key, value] of Object.entries(ticket.headers)) xhr.setRequestHeader(key, value);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new ApiError(xhr.status, `Falha no envio do arquivo (HTTP ${xhr.status})`));
    xhr.onerror = () => reject(new ApiError(0, "Falha de rede durante o envio do arquivo"));
    xhr.send(file);
  });
}
