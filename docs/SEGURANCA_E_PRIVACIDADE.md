# Segurança, privacidade, retenção e exclusão

## Controles mínimos

- OIDC/OAuth 2.0, MFA para funções privilegiadas, RBAC por organização e negação por padrão.
- TLS em trânsito; AES-256 ou equivalente em repouso; chaves em KMS e segredos em secret manager, nunca em repositório, imagem ou frontend.
- URLs assinadas com TTL curto, upload com limite de tamanho/tipo, inspeção de malware e isolamento de arquivos não confiáveis.
- Egress allowlist para fornecedores, webhooks assinados, dependências verificadas e imagens escaneadas/SBOM.
- Logs de auditoria append-only para consentimento, direitos, acesso, aprovação, publicação e exclusão.
- Redação de tokens, prompts, biometria, mídia e dados pessoais dos logs; acesso de suporte temporário e auditado.

## Modelo de ameaça

Tratar como riscos prioritários: IDOR entre organizações, SSRF por URLs de mídia, arquivos maliciosos, prompt injection em mídia/texto, exfiltração por fornecedor, clonagem não autorizada, replay de webhook, abuso de publicação, gasto ilimitado e reidentificação. Testar isolamento entre organizações e autorização em cada objeto.

## Retenção

| Classe | Padrão inicial | Exclusão |
|---|---:|---|
| Upload original e intermediários | 30 dias após conclusão | job diário e lifecycle do bucket |
| Entregável aprovado | enquanto projeto ativo | solicitação ou término contratual |
| Dados biométricos/voz/avatar | mínimo necessário; preferir referência do fornecedor | revogação imediata e confirmação |
| Metadados operacionais | 90 dias | job diário |
| Auditoria/consentimento/licenças | 365 dias ou obrigação legal maior | política legal documentada |
| Backups | 35 dias | expiração automática e exclusão criptográfica |

Os valores são defaults, não parecer jurídico. Documentar base legal, finalidade, região, suboperadores e eventuais legal holds por jurisdição.

## Solicitação de exclusão

1. Autenticar solicitante e localizar dados por organização/sujeito.
2. Bloquear novo processamento e marcar `deletion_pending`.
3. Revogar URLs/tokens; remover filas, banco, objetos, embeddings e cópias nos fornecedores.
4. Propagar para suboperadores dentro do SLA contratual.
5. Registrar somente comprovante mínimo, sem reter o conteúdo excluído.
6. Emitir confirmação e verificar a expiração em backups.

Meta inicial: concluir dados ativos em até 7 dias e backups no ciclo de 35 dias, salvo obrigação legal. Revogação de voz/avatar interrompe novas gerações imediatamente.

## Resposta a incidentes

Classificar, conter, preservar evidências, rotacionar credenciais, avaliar notificações legais/contratuais e produzir post-mortem sem culpa. Manter contatos e exercícios semestrais. Nunca apagar evidência durante incidente sem autorização responsável.
