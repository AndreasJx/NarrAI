# Checklist de lançamento

## Produto e conteúdo

- [ ] Caso de uso, público, países e conteúdo proibido aprovados.
- [ ] Preview e aprovação humana testados; disclosure de IA visível.
- [ ] Política editorial, recurso e canal de denúncia publicados.
- [ ] Consentimentos de voz/avatar e cadeia de direitos validados.
- [ ] Acessibilidade, localização e experiência de falha revisadas.

## Segurança e privacidade

- [ ] Threat model, teste de isolamento entre organizações e pentest concluídos.
- [ ] MFA/RBAC, KMS, secret manager, TLS, WAF/rate limit e egress configurados.
- [ ] SAST/SCA, scan de imagem, SBOM e patches críticos sem pendência.
- [ ] DPA/subprocessadores, base legal, residência e transferência aprovados.
- [ ] Retenção, exclusão, revogação e restauração de backup testadas.
- [ ] Plano de incidente, contatos e exercício realizados.

## Operação e custo

- [ ] SLOs, dashboards e alertas de erro, fila, DLQ, latência e orçamento ativos.
- [ ] Idempotência, timeouts, backoff, circuit breaker e reconciliação testados.
- [ ] Capacidade/carga, quotas e degradação de fornecedor testadas.
- [ ] Tarifas verificadas; tetos por vídeo/organização/mês e kill switch ativos.
- [ ] Runbooks de deploy, rollback, fornecedor indisponível e exclusão disponíveis.

## Fornecedores e publicação

- [ ] Matriz aprovada sem contratação automática; plano de saída registrado.
- [ ] Licenças, SLA, retenção, uso para treino e exclusão contratual confirmados.
- [ ] App TikTok aprovado, scopes mínimos e evidências de auditoria completas.
- [ ] Conta de teste, redirects, webhooks, rate limits e revogação testados.

## Go/no-go

- [ ] Responsáveis de Produto, Engenharia, Segurança, Privacidade/Jurídico, Editorial e Operações assinaram.
- [ ] Riscos aceitos têm dono, prazo e compensação documentados.
- [ ] Rollback e kill switches foram exercitados.
- [ ] Data de revisão pós-lançamento definida.
