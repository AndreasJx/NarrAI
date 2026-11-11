# Decisão de fornecedores e custos

Nenhum fornecedor pago é selecionado automaticamente. Preços e termos mudam; validar cotação, região, DPA, política de IA e direitos antes de contratar. Fazer prova com dados sintéticos e aprovação de Segurança, Privacidade, Jurídico, Produto e Finanças.

## Matriz textual de decisão

Pontuar cada critério de 0 a 5 e anexar evidência. Pesos iniciais: segurança/privacidade 25%, direitos/consentimento 20%, qualidade 15%, custo total 15%, confiabilidade 10%, latência 5%, portabilidade 5% e suporte/saída 5%.

| Categoria | Alternativas a avaliar | Critérios eliminatórios |
|---|---|---|
| LLM/roteiro | OpenAI, Anthropic, Google, modelo hospedado | DPA; opt-out de treino; região; moderação; exportação |
| Transcrição | Deepgram, AssemblyAI, Google/Azure/AWS, Whisper hospedado | idiomas; diarização; retenção; custo real-time/batch |
| TTS/voz | ElevenLabs, Azure, Google, AWS, OpenAI | consentimento verificável; revogação; detecção; proibição de abuso |
| Avatar | HeyGen, Synthesia, Tavus, solução interna | verificação de identidade; remoção; marca d'água/proveniência; licença |
| Vídeo/storage | FFmpeg + cloud gerenciada ou API especializada | codecs; egress; isolamento; SLA; exclusão |
| Publicação | API oficial TikTok e demais plataformas | escopos mínimos; auditoria; rate limits; revisão do app |

Para finalistas, registrar: nota ponderada, preço unitário e mínimo, custos de egress/suporte, subprocessadores, residência, SLA, prazo de exclusão, lock-in, plano de migração e resultado do teste. Empate favorece menor coleta, melhor saída e menor custo variável.

## Orçamento padrão por minuto

Guardrail inicial, não cotação: **US$ 0,35 por minuto final**, com teto de **US$ 5 por vídeo** e **US$ 100/mês** em desenvolvimento. Exemplo de envelope por minuto:

- transcrição: US$ 0,01;
- roteiro/LLM: US$ 0,02;
- TTS: US$ 0,04;
- avatar/generativo: US$ 0,20;
- composição/storage/egress: US$ 0,05;
- observabilidade e margem de retry: US$ 0,03.

Fórmula: `estimativa = minutos × soma das tarifas + custos fixos + egress`, acrescida da margem de retry. Reservar orçamento antes do job, reconciliar uso real por fornecedor/modelo e bloquear quando exceder teto. Não fazer retry de operação cobrada sem idempotência.

Alertar em 50/80/100% do orçamento; exigir aprovação em 80% e interromper novas gerações não essenciais em 100%. Revisar tarifas mensalmente e sempre que fornecedor/modelo mudar.
