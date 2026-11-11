# Arquitetura

## Objetivo e princípios

A plataforma recebe mídia autorizada, orquestra processamento assíncrono e entrega um vídeo revisável antes de qualquer publicação. Os princípios são: consentimento verificável, revisão humana, privilégio mínimo, portabilidade de fornecedores, idempotência e rastreabilidade.

## Componentes

- **Web (Next.js 16, App Router)**: login/cadastro, painel, projetos, editor de roteiro, storyboard, uploads, render com prévia, publicação, calendário, fontes, voz e configurações. Todas as chamadas vão para `/api/v1/*` na própria origem; o Next reescreve para a API (`API_INTERNAL_URL`, fixado no build). `src/proxy.ts` apenas redireciona quem não tem cookie de sessão; a autorização real é sempre da API.
- **API (FastAPI)**: autenticação, autorização por organização e papel, metadados, URLs assinadas, orçamento, aprovações e orquestração. Routers em `apps/api/app/routers/`; migrações Alembic em `apps/api/alembic/` aplicadas na inicialização do container.
- **Worker (`workers/pipeline`)**: consome `video-ai:render-jobs` no Redis, com jobs tipados (`render` por padrão, `research`, `media` e `autopilot`). No render, sintetiza a narração por cena com Kokoro (`kokoro-onnx`; o idioma sai do prefixo da voz: `p` pt-BR, `a` en-US, `b` en-GB), monta cada cena a partir dos shots planejados (Ken Burns em fotos, clipes cortados, `xfade` entre shots, áudio do clipe abaixado sob a narração), queima legendas ASS e grava o MP4 1080x1920 e a linha do tempo dos shots. Também executa publicações agendadas, gera as amostras de voz, roda o agendador do piloto automático (a cada 5 min) e o ciclo de aprendizado (métricas diárias, playbook semanal).
- **Automação (`apps/api/app`)**: `ai.py` (Azure OpenAI), `research.py` (artigos e vídeos de referência, dossiê), `writer.py` (roteiro), `media.py` (busca, ranking e download de mídia licenciada), `retention.py` (plano de shots e créditos), `gates.py` (portões de qualidade), `autopilot.py` (máquina de estados) e `learning.py` (métricas, retenção, playbook e pauta). Detalhes e alternativas em [AUTOMACAO.md](AUTOMACAO.md).
- **PostgreSQL**: organizações, usuários, projetos, versões de roteiro, cenas, ativos, renders, aprovações, conexões, publicações, métricas e auditoria.
- **Redis**: fila de render e dead-letter queue (`video-ai:render-dead-letter`); não é fonte de verdade.
- **MinIO/S3**: uploads (`orgs/{org}/projects/{id}/uploads/…`), renders e amostras de voz. O navegador recebe URLs assinadas curtas apontando para `S3_PUBLIC_ENDPOINT`.
- **Fornecedores externos**: YouTube e TikTok via OAuth, apenas quando habilitados. Pesquisa e roteiro usam adaptadores locais determinísticos (`LocalResearch`, `LocalLLM`); avatar não está disponível nesta versão.

## Autenticação e autorização

O cadastro cria usuário, organização e vínculo `owner`. A sessão é um JWT HS256 (`JWT_SECRET`) em cookie `narra_session` httpOnly, SameSite=Lax (`COOKIE_SECURE=true` em produção com TLS). Senhas usam Argon2. Cada usuário pode pertencer a várias organizações e alternar a ativa.

Papéis: `owner` (configurações, membros, voz e orçamento), `editor` (produz, aprova, renderiza e publica) e `viewer` (somente leitura). Todo recurso é resolvido pelo projeto da organização ativa; recursos de outra organização retornam 404.

## Fluxo

briefing → pesquisa (artigos + vídeos de referência → dossiê com citações) → roteiro (versões editáveis) → aprovação do roteiro → storyboard com mídia automática ou enviada e plano de shots → render (fila) → prévia → aprovação de publicação → publicação simulada ou real (imediata ou agendada, com créditos na descrição) → métricas, curva de retenção, insights e experimentos.

Piloto automático: o projeto ganha `autopilot=true` e um `autopilot_stage` (`research → script → script_gate → media → render → render_gate → publish → done`). Cada etapa grava um `StageRun` (tempo, custo, nota, detalhes). Os portões aprovam com `actor="autopilot"`; se reprovarem, o roteiro é reescrito uma vez com as críticas e, persistindo, o projeto fica em `needs_review` na caixa de exceções, onde uma pessoa aprova (o aprovador vira o ator) ou pede nova tentativa. O render libera a próxima etapa ao terminar (`after_render` no worker).

Uploads: a API emite um ticket (URL assinada PUT no MinIO, ou rota local nos testes), o navegador envia o arquivo diretamente e confirma; a API verifica tamanho e assinatura binária (JPEG, PNG, WebP, MP4, MOV, WebM) antes de marcar o ativo como pronto.

Render: a API exige roteiro aprovado e orçamento, cria o render idempotente e enfileira. O worker tenta até `RENDER_MAX_ATTEMPTS` vezes com backoff exponencial; depois move o job para a DLQ e marca o projeto como `failed`. Sem FFmpeg o worker grava um manifesto JSON; sem o modelo Kokoro as cenas ficam silenciosas.

Retroalimentação: o worker coleta métricas e a curva `audienceRetention` do YouTube Analytics, mapeia as maiores quedas para o shot que estava na tela (pela `timeline` do render) e, semanalmente, deriva regras do `PlaybookRule` (ritmo de troca visual, duração, estilo de gancho e de título). As regras entram nos prompts de pauta e roteiro e nos parâmetros do planejador de retenção.

## Estados e contratos

Projeto: `draft → review → approved → processing → review → approved → publishing → published`, com `failed`. Cada transição gera `project.status_changed` na auditoria, com ator, estado anterior e novo e motivo.

Jobs possuem `idempotency_key`, limite de tentativas, custo estimado e DLQ. Objetos usam IDs opacos; nomes originais não compõem chaves. O retorno OAuth passa pela origem web (`/api/v1/oauth/callback/{platform}`) para que o cookie de sessão valide o `state`.

## Ambientes e implantação

O Compose é apenas para desenvolvimento. Produção deve usar banco/Redis/storage gerenciados, TLS, WAF/rate limit, KMS/secret manager, backups testados, imagens imutáveis por digest, rede privada e observabilidade centralizada. API e worker escalam de forma independente; o worker tem limite de memória (`WORKER_MEMORY_LIMIT`, padrão 3g) por causa do modelo de voz.

As imagens executam os serviços com usuários sem privilégio: Next.js em modo standalone, FastAPI/Uvicorn (`alembic upgrade head` antes de subir) e worker Python com FFmpeg, espeak-ng e modelos Kokoro baixados no build.

## Observabilidade e continuidade

Use logs JSON sem conteúdo de mídia, `trace_id`, métricas de duração/falha/custo/fila e alertas de orçamento, DLQ e exclusão atrasada. Defina SLOs antes do lançamento. Backups criptografados devem ter RPO/RTO aprovados e restauração exercitada trimestralmente.
