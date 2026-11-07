# ADR 0001: API oficial + aprovação humana, sem navegador automatizado

**Status:** aceita (2026-11-07)

## Contexto
A versão anterior (`linkedin-automacao-ia`) controlava o LinkedIn por Playwright com sessão logada: lia o feed, curtia e comentava. Os termos de uso do LinkedIn proíbem automação de navegador e scraping em conta pessoal, e a plataforma detecta esse padrão. Para quem está buscando emprego, uma restrição de conta custa mais que qualquer ganho de alcance.

## Decisão
- Publicação de posts somente pela API oficial (produto "Share on LinkedIn", escopo `w_member_social`), sempre depois de aprovação no Telegram.
- Comentários, curtidas e convites: a IA sugere o texto, o humano executa no app.
- Nenhum login, cookie ou navegador headless apontando para o LinkedIn.
- Vagas vêm de fontes que permitem consumo (APIs públicas de portais e e-mails de alerta que o próprio LinkedIn envia).

## Consequências
- Sem analytics automáticos de posts pessoais (a API não libera): métricas entram por comando no Telegram.
- Token OAuth do LinkedIn expira em 60 dias sem refresh: lembrete automático no dia 50.
- Engajamento exige alguns minutos por dia do humano, que é justamente o que mantém autenticidade.
