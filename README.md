# Copiloto LinkedIn

Assistente pessoal para manter presença ativa no LinkedIn e caçar vagas remotas, operado pelo Telegram e orquestrado em n8n.

**Princípio:** nada acontece no LinkedIn sem aprovação humana, e nada roda em navegador logado. Posts saem pela API oficial (`w_member_social`); comentários e conexões são sugeridos pela IA e postados à mão. Decisão registrada em [docs/adr/0001-api-oficial.md](docs/adr/0001-api-oficial.md).

## Arquitetura

```
Telegram (whitelist por chat_id)
   │  comandos / botões
   ▼
n8n (Coolify, HTTPS) ── DeepSeek API (textos, score de vagas)
   │       │        └── Postgres (fila de posts, vagas, pipeline, métricas)
   │       ├── LinkedIn API oficial (publica após aprovação)
   │       ├── Gupy / Remotar + alertas de vaga no Gmail
   │       └── GitHub API (commits viram pautas)
   └── Error workflow → alerta no Telegram
```

## Módulos

| Módulo | Status |
|--------|--------|
| Infra (n8n + Postgres no Coolify, HTTPS) | no ar |
| Bot Telegram: /post e comentários sugeridos (DeepSeek via OpenCode Go) | no ar |
| Publicação via API oficial | planejado |
| Radar de vagas remotas + pipeline | planejado |
| Engajamento assistido + relatório semanal | planejado |

## Estrutura

```
docker-compose.yml   n8n + Postgres (variáveis SERVICE_* geradas pelo Coolify)
CONTEXT.md           voz, persona e regras editoriais
prompts/             prompts versionados
workflows/           export dos workflows n8n (sem credenciais)
db/schema.sql        tabelas da aplicação
docs/                setup e decisões
```

## Segurança

Nenhum token, chave ou cookie fica neste repositório. Credenciais vivem nas variáveis do Coolify e no cofre de credenciais do n8n.

## Deploy do workflow

```bash
python scripts/build_workflow.py   # gera workflows/telegram-bot.json a partir de prompts/
```

Importar no container: `n8n import:workflow --input=telegram-bot.json`, depois `n8n publish:workflow --id=copilotoTelegram01` e reiniciar o n8n. O webhook do Telegram aponta para `/webhook/telegram-copiloto` com `secret_token` (variável `TG_WEBHOOK_SECRET`).
