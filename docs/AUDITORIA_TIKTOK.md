# Processo de auditoria e publicação TikTok

Esta é uma trilha operacional, não garantia de aprovação. Usar somente APIs oficiais e conferir requisitos atuais no [TikTok for Developers](https://developers.tiktok.com/).

## Antes da integração

1. Registrar entidade, domínio verificado, contatos, política de privacidade, termos e fluxo de exclusão.
2. Criar app no portal e solicitar somente produtos/escopos necessários para Content Posting.
3. Documentar telas e vídeo do fluxo completo: login, consentimento, seleção da conta, preview, edição, disclosure de IA, publicação e revogação.
4. Usar OAuth com `state`, PKCE quando suportado, redirect URI exata e tokens criptografados; nunca pedir senha TikTok.
5. Confirmar diretrizes de conteúdo, música, branded content, conteúdo sintético e limites técnicos.

## Evidências por publicação

Manter ID interno/correlação, organização e ator; versão/hash do arquivo; origem e licença dos ativos; consentimentos; resultado de moderação; revisor e aprovação; disclosure aplicado; legenda/configuração escolhida pelo usuário; scopes; horários de envio e resposta; ID TikTok/status; erros e tentativas. Não registrar token ou conteúdo pessoal desnecessário.

## Controles do fluxo

- Exibir preview e obter ação explícita do usuário; sem publicação automática por padrão.
- Validar formato/duração/tamanho e consultar capacidades/limites atuais antes do upload.
- Respeitar rate limits e `Retry-After`; usar backoff com jitter e idempotência.
- Validar respostas/webhooks, reconciliar estados e permitir revogar conexão/excluir dados.
- Separar ambientes, restringir redirect URIs e rotacionar segredo após exposição ou troca de equipe.

## Pacote de revisão do app

Entregar descrição objetiva do caso de uso, conta de teste, instruções reproduzíveis, screencast sem cortes, justificativa de cada escopo, URLs públicas, contatos e diagrama de dados. As telas enviadas devem coincidir com produção. Responder aos revisores preservando histórico e corrigir antes de reenviar.

## Auditoria periódica

Mensalmente: amostrar publicações e conferir consentimento, licença, disclosure, aprovação e reconciliação. Trimestralmente: revisar scopes, membros, redirects, políticas e exclusões. Anualmente ou após mudança relevante: renovar avaliação jurídica/segurança, teste de incidente e pacote de revisão.

Incidente ou abuso exige pausar publicação, preservar evidências, revogar tokens afetados, avaliar notificação e registrar ação corretiva.

Referências oficiais:

- [Content Posting API](https://developers.tiktok.com/products/content-posting-api/)
- [Diretrizes para desenvolvedores](https://developers.tiktok.com/doc/our-guidelines-developer-guidelines/)
- [Login Kit](https://developers.tiktok.com/products/login-kit/)
- [Central de transparência e políticas](https://www.tiktok.com/transparency/)
