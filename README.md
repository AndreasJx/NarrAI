# Narra — plataforma de vídeos explicativos com IA

Aplicação que transforma um tema em vídeo vertical publicado: pesquisa em artigos e vídeos de referência, roteiro com citações, busca e ranking de fotos e clipes licenciados, edição pensada para retenção, narração Kokoro (pt-BR, en-US e en-GB), revisão automática e publicação no YouTube e TikTok. No piloto automático a plataforma escolhe temas, produz e publica sozinha, e aprende com as métricas; você só decide as exceções. A publicação é simulada por padrão e só vai às plataformas quando habilitada explicitamente. Avatar não está disponível nesta versão.

## Arquitetura

A web Next.js chama `/api/v1/*` na própria origem e o Next reescreve para a API FastAPI. A API autentica por cookie de sessão (JWT httpOnly), isola dados por organização, persiste estado no PostgreSQL, enfileira jobs tipados no Redis (render, pesquisa, mídia e etapas do piloto) e emite URLs assinadas do MinIO. O worker executa os jobs, sintetiza a narração com Kokoro, compõe um MP4 1080x1920 com Ken Burns, transições e legendas via FFmpeg, roda o agendador do piloto automático e o ciclo de aprendizado. A IA (Azure OpenAI) entra por adaptadores: sem chave, cada etapa usa a alternativa local.

Dois modos de uso:

- **Manual:** "Criar novo vídeo" → pesquisa (artigos e vídeos) → roteiro → aprovação → storyboard com "Buscar mídias automaticamente" ou uploads → render e prévia → aprovação → publicação → métricas.
- **Piloto automático:** marque "Piloto automático" ao criar o vídeo, use a página **Piloto automático** ou ative a produção na cadência. Pesquisa, roteiro, revisão por nota, mídia, render, revisão do vídeo e publicação acontecem sozinhos; o que for reprovado vai para a **caixa de exceções**. Métricas diárias e curvas de retenção alimentam o **playbook**, que ajusta temas, roteiros e o ritmo da edição.

Documentação:

- [Automação: como funciona e alternativas de ferramentas](docs/AUTOMACAO.md)
- [Arquitetura](docs/ARQUITETURA.md)
- [Segurança, privacidade, retenção e exclusão](docs/SEGURANCA_E_PRIVACIDADE.md)
- [Políticas editoriais, consentimento e direitos](docs/POLITICAS_EDITORIAIS_E_DIREITOS.md)
- [Fornecedores e custos](docs/FORNECEDORES_E_CUSTOS.md)
- [Auditoria TikTok](docs/AUDITORIA_TIKTOK.md)
- [Checklist de lançamento](docs/CHECKLIST_LANCAMENTO.md)

## Requisitos

- Docker Engine/Desktop com Compose v2;
- opcional: GNU Make (no Windows, use WSL/Git Bash ou os comandos Docker diretamente);
- portas locais 3000, 5432, 6379, 8080, 9000 e 9001 livres, ou alteradas no `.env`.

## Setup local

PowerShell:

```powershell
Copy-Item .env.example .env
# Edite .env e substitua todos os valores "change-me".
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Linux/macOS/WSL:

```bash
make setup
# Edite .env e substitua todos os valores "change-me".
make config
make up
make ps
```

Endpoints locais: web `http://localhost:3000` (abra e crie uma conta), API/OpenAPI `http://localhost:8080/docs`, saúde `http://localhost:8080/api/v1/health`, MinIO `http://localhost:9000` e console `http://localhost:9001`.

O primeiro build do worker baixa os modelos Kokoro (~350 MB). A API aplica as migrações Alembic ao iniciar.

### Chaves para automação

Preencha no `.env` e recrie os containers (`docker compose up -d api worker`). Nenhuma é obrigatória: sem chave, a etapa correspondente usa a alternativa local, e a página **Piloto automático → Painel → Integrações** mostra o que está ativo.

| Variáveis | Libera |
| --- | --- |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_CHAT_DEPLOYMENT` | dossiê, roteiro, revisão por nota, consultas visuais, ranking de imagens por visão, pauta e playbook. Use um deployment com visão (ex.: família GPT-4o/4.1). |
| `AZURE_OPENAI_TRANSCRIBE_DEPLOYMENT` | transcrição de vídeos de referência sem legenda (Whisper ou gpt-4o-transcribe) |
| `TAVILY_API_KEY` | busca e leitura de artigos |
| `YOUTUBE_API_KEY` | busca dos vídeos de referência e sinais de pauta (YouTube Data API v3) |
| `PEXELS_API_KEY`, `PIXABAY_API_KEY` | fotos e vídeos de banco; Wikimedia Commons e Openverse funcionam sem chave |
| `FAIR_USE_CLIPS_ENABLED=true` | trechos de até 8 s de vídeos de referência, com crédito (veja os riscos em [docs/AUTOMACAO.md](docs/AUTOMACAO.md)) |

### Login nas plataformas de publicação

YouTube e TikTok não dependem do `.env`. Em **Configurações → Plataformas de publicação**, o proprietário:

1. copia a URI de retorno mostrada ali e a registra no console da plataforma (Google Cloud: "ID do cliente OAuth" do tipo aplicativo da Web, com a YouTube Data API v3 ativada; TikTok: app com Login Kit e Content Posting API);
2. cola o client ID e o client secret (o secret é salvo criptografado com `CREDENTIAL_SECRET` e nunca volta para o navegador);
3. clica em **Conectar conta** e autoriza o canal. A conta fica disponível para todos os projetos da organização e para o piloto automático; o token é renovado automaticamente;
4. marca **Permitir publicação real** quando quiser sair do modo simulado.

Para trocar de canal, conecte outra conta ou desconecte a atual na mesma tela; nada precisa ser reiniciado. Na aba **Publicação** de um projeto, as contas da organização aparecem com "usar neste projeto". `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`, `TIKTOK_CLIENT_KEY`/`TIKTOK_CLIENT_SECRET` no `.env` continuam aceitos como reserva para organizações sem app próprio, e `ALLOW_LIVE_PUBLISH=true` libera a publicação real para todas. Logins feitos por projeto antes desta versão viram contas da organização na migração `0003`.

Exemplo com gateway próprio e modelo de raciocínio: a URL `https://chat.dev.woopi.ai/openai/deployments/gpt-5.6-sol/chat/completions?api-version=2024-10-21` vira

```bash
AZURE_OPENAI_ENDPOINT=https://chat.dev.woopi.ai
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-5.6-sol
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_API_KEY=<a chave real; referências como ${input:...} do editor não funcionam aqui>
AZURE_OPENAI_REASONING=true
```

Alternativa ao `.env`: copie `config/azure-openai.example.json` para `config/azure-openai.json` e preencha (o arquivo é ignorado pelo Git e montado somente leitura em `api` e `worker`). Os valores do JSON preenchem os campos `AZURE_OPENAI_*` que estiverem vazios; um valor não vazio no `.env` continua tendo prioridade. Outro caminho pode ser definido em `AZURE_OPENAI_CONFIG_FILE`. Separar em JSON organiza, mas não protege mais que o `.env`: em produção use Docker Secrets ou Azure Key Vault.

Modelos de raciocínio (GPT-5, o-series) recusam `max_tokens` e temperatura diferente da padrão; com `AZURE_OPENAI_REASONING=true` o Narra envia `max_completion_tokens` e `reasoning_effort`. Para GPT-4o/4.1, use `false`. A chave segue nos cabeçalhos `api-key` e `Authorization: Bearer`. Depois de recriar os containers, use **Piloto automático → Painel → Integrações → Testar IA**: o teste faz uma chamada JSON e outra com imagem e mostra o erro real do gateway (chave inválida, DNS interno não resolvido pelo Docker etc.).

Sem IA, o portão de roteiro usa uma heurística e tende a mandar o vídeo para a caixa de exceções; aprove por lá ou baixe a nota mínima nas configurações do piloto. Se o volume do PostgreSQL tiver o esquema antigo (sem organizações), a migração o descarta automaticamente apenas com `APP_ENV=development`; em outros ambientes recrie o volume conscientemente (`docker compose down --volumes`).

Para desenvolvimento sem Docker (API com SQLite e storage local se `DATABASE_URL`/`S3_*` não estiverem definidos; sem `REDIS_URL` o render roda de forma síncrona na API):

```powershell
$env:PYTHONPATH="apps/api;packages/contracts;workers/pipeline"
python -m pip install -r apps/api/requirements.txt
cd apps/api; alembic upgrade head; cd ../..
python -m uvicorn app.main:app --app-dir apps/api --reload --port 8080
# outro terminal: worker (requer Redis e, opcionalmente, FFmpeg e kokoro-onnx)
python -m pipeline.service
# outro terminal: web (API_INTERNAL_URL padrão http://127.0.0.1:8080)
cd apps/web
npm install
npm run dev
```

## Testes

```powershell
cd apps/api; python -m pytest -q          # API, autorização, storage (moto), worker, piloto automático e aprendizado (IA e buscas falsas)
cd apps/web; npm run lint; npx tsc --noEmit
npm run e2e:install; npm run e2e        # na raiz: smoke Playwright contra a pilha em execução
```

O smoke usa `E2E_BASE_URL` (padrão `http://localhost:3000`) e cria uma conta nova a cada execução.

## Papéis

- **Proprietário**: tudo, mais organização, orçamento, voz padrão, membros e apps OAuth das plataformas.
- **Editor**: cria projetos, edita e aprova roteiros, renderiza, conecta canais e publica.
- **Leitor**: acompanha projetos, prévias e métricas.

## Operação

```powershell
docker compose logs -f --tail 200
docker compose restart worker
docker compose down              # preserva volumes
docker compose down --volumes    # destrói dados locais
```

Migrações (`alembic upgrade head`) e criação do bucket são automáticas na inicialização; backups e rotação de segredos não. Renders que esgotam as tentativas vão para a lista Redis `video-ai:render-dead-letter` e podem ser reenviados pela interface ("Tentar novamente"). Em produção use serviços gerenciados, secret manager/KMS, TLS, rede privada, imagens por digest e restauração testada. Nunca use os valores do `.env.example`.

Antes de processar, estime e reserve custo; após concluir, reconcilie o custo real. Pare novas gerações ao atingir tetos. Monitore fila/DLQ, falhas, p95, armazenamento, exclusões pendentes e gasto por organização/fornecedor.

## Limites das APIs

Não fixe limites externos no código: consulte documentação e respostas atuais do fornecedor. Para toda integração:

- aplique limites próprios por usuário e organização, tamanho, duração, concorrência e custo;
- respeite HTTP 429 e `Retry-After`, com backoff exponencial e jitter;
- use timeout, número máximo de tentativas, circuit breaker e idempotência;
- limite upload inicialmente a 500 MiB e vídeo a 10 minutos (configuráveis);
- não repita automaticamente operações cobradas ou publicações sem chave idempotente;
- trate quotas, formatos, regiões, retenção e preços como configuração versionada;
- registre metadados de uso, nunca tokens ou conteúdo sensível.

O TikTok exige app/revisão, scopes e limites próprios; não contorne APIs oficiais nem automatize login. Confira os requisitos imediatamente antes de cada release.

## Segurança e segredos

O Compose lê segredos de `.env`, que não deve ser versionado. Produção deve injetá-los pelo orquestrador/secret manager e rotacioná-los. Restrinja CORS, egress e permissões por organização; valide uploads; use URLs assinadas curtas; criptografe tokens; exija MFA para administradores e guarde auditoria append-only.

Credenciais de fornecedor permanecem vazias até decisão formal. A matriz não autoriza contratação. Antes do lançamento, obtenha avaliação jurídica aplicável (incluindo LGPD), DPA e aprovação da checklist.

## Referências oficiais

- [Docker Compose](https://docs.docker.com/compose/)
- [PostgreSQL](https://www.postgresql.org/docs/)
- [Redis Security](https://redis.io/docs/latest/operate/oss_and_stack/management/security/)
- [MinIO Documentation](https://min.io/docs/minio/container/index.html)
- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [ANPD — LGPD](https://www.gov.br/anpd/pt-br)
- [TikTok for Developers](https://developers.tiktok.com/)
- [TikTok Content Posting API](https://developers.tiktok.com/products/content-posting-api/)
- [YouTube Data API](https://developers.google.com/youtube/v3)
- [YouTube Analytics API](https://developers.google.com/youtube/analytics)
- [OpenAI API](https://platform.openai.com/docs/) e [preços](https://openai.com/api/pricing/)
- [Anthropic API](https://docs.anthropic.com/) e [preços](https://www.anthropic.com/pricing)
- [Google Cloud AI](https://cloud.google.com/docs) e [preços](https://cloud.google.com/pricing)
- [Azure AI](https://learn.microsoft.com/azure/ai-services/) e [preços](https://azure.microsoft.com/pricing/)
- [AWS AI Services](https://aws.amazon.com/machine-learning/ai-services/) e [preços](https://aws.amazon.com/pricing/)

Links e preços devem ser revalidados: documentação externa pode mudar sem aviso.
