const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const dateTime = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" });
const compact = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });

function parse(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
}

export const money = (cents: number) => currency.format(cents / 100);
export const formatDateTime = (value: string | null | undefined) => (value ? dateTime.format(parse(value)) : "—");
export const formatDate = (value: string | null | undefined) => (value ? dateOnly.format(parse(value)) : "—");
export const compactNumber = (value: number) => compact.format(value);
export const toDate = parse;

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

export const STATUS: Record<string, { label: string; tone: string }> = {
  draft: { label: "Rascunho", tone: "neutral" },
  processing: { label: "Renderizando", tone: "blue" },
  review: { label: "Em revisão", tone: "violet" },
  approved: { label: "Aprovado", tone: "green" },
  publishing: { label: "Publicando", tone: "blue" },
  published: { label: "Publicado", tone: "green" },
  failed: { label: "Falhou", tone: "red" },
  queued: { label: "Na fila", tone: "neutral" },
  completed: { label: "Concluído", tone: "green" },
  scheduled: { label: "Agendado", tone: "violet" },
  cancelled: { label: "Cancelado", tone: "neutral" },
  pending: { label: "Pendente", tone: "neutral" },
};

export const statusInfo = (status: string) => STATUS[status] ?? { label: status, tone: "neutral" };

export const PLATFORM_LABEL: Record<string, string> = {
  youtube: "YouTube Shorts",
  tiktok: "TikTok",
  local: "Exportação local",
};

export const ROLE_LABEL: Record<string, string> = { owner: "Proprietário", editor: "Editor", viewer: "Leitor" };

export const STAGE_ORDER = ["research", "script", "script_gate", "media", "render", "render_gate", "publish"] as const;

export const STAGE_LABEL: Record<string, string> = {
  research: "Pesquisa",
  script: "Roteiro",
  script_gate: "Revisão do roteiro",
  media: "Mídias e retenção",
  render: "Renderização",
  render_gate: "Revisão do vídeo",
  publish: "Publicação",
  done: "Concluído",
  needs_review: "Aguardando você",
  failed: "Falhou",
  stopped: "Pausado",
};

export const LANGUAGE_LABEL: Record<string, string> = {
  "pt-BR": "Português (Brasil)",
  "en-US": "Inglês (EUA)",
  "en-GB": "Inglês (Reino Unido)",
};

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function newKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}
