"""Gera workflows/telegram-bot.json a partir dos prompts em prompts/.

Uso: python scripts/build_workflow.py
O workflow nao contem segredos: tudo vem de variaveis de ambiente do container
(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TG_WEBHOOK_SECRET, LLM_*).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
OUT = ROOT / "workflows" / "telegram-bot.json"

WEBHOOK_PATH = "telegram-copiloto"
WORKFLOW_ID = "copilotoTelegram01"

sistema = (PROMPTS / "sistema.md").read_text(encoding="utf-8")
p_post = (PROMPTS / "post.md").read_text(encoding="utf-8")
p_coment = (PROMPTS / "comentario.md").read_text(encoding="utf-8")

AJUDA = """Copiloto LinkedIn

/post <ideia>  gera 2 versoes de post (Bastidores e Arquitetura) + prompt de imagem
/comentar <texto do post>  sugere 2 comentarios
Colar o texto de um post (sem comando) tambem gera comentarios.
/status  confere se esta tudo de pe
/menu  mostra esta ajuda

Nada e publicado sozinho: voce copia, ajusta e posta."""

ROTEADOR = r"""
const SISTEMA = __SISTEMA__;
const P_POST = __P_POST__;
const P_COMENT = __P_COMENT__;
const AJUDA = __AJUDA__;

const input = $input.first().json;
const headers = input.headers || {};
const body = input.body || {};

const secret = $env.TG_WEBHOOK_SECRET;
if (secret && headers['x-telegram-bot-api-secret-token'] !== secret) return [];

const msg = body.message || body.edited_message;
if (!msg || !msg.chat) return [];
const chatId = String(msg.chat.id);
if (chatId !== String($env.TELEGRAM_CHAT_ID)) return [];

const text = (msg.text || msg.caption || '').trim();
if (!text) {
  return [{ json: { chatId, needsLlm: false, reply: 'Por enquanto eu so entendo texto. Manda /menu para ver os comandos.' } }];
}

const m = text.match(/^\/(\w+)(?:@\w+)?\s*([\s\S]*)$/);
const cmd = m ? m[1].toLowerCase() : null;
const arg = m ? m[2].trim() : text;

function llm(kind, userContent) {
  return {
    chatId,
    needsLlm: true,
    kind,
    session: 'copiloto-' + chatId + '-' + kind,
    ack: kind === 'post' ? 'Escrevendo 2 versoes do post...' : 'Lendo o post e pensando nos comentarios...',
    llmBody: {
      model: $env.LLM_MODEL || 'deepseek-v4.1-flash',
      temperature: 0.8,
      max_tokens: 3000,
      response_format: { type: 'json_object' },
      messages: [
        { role: 'system', content: SISTEMA },
        { role: 'user', content: userContent },
      ],
    },
  };
}

if (cmd === 'start' || cmd === 'menu' || cmd === 'ajuda' || cmd === 'help') {
  return [{ json: { chatId, needsLlm: false, reply: AJUDA } }];
}
if (cmd === 'status') {
  const agora = new Date().toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' });
  return [{ json: { chatId, needsLlm: false, reply: 'No ar.\nModelo: ' + ($env.LLM_MODEL || '?') + '\nHora do servidor: ' + agora } }];
}
if (cmd === 'post') {
  if (!arg) return [{ json: { chatId, needsLlm: false, reply: 'Manda a ideia junto. Ex.: /post o dia em que meu agente de IA estourou o limite da API e como eu resolvi com fila' } }];
  return [{ json: llm('post', P_POST + arg) }];
}
if (cmd === 'comentar') {
  if (!arg) return [{ json: { chatId, needsLlm: false, reply: 'Cola o texto do post depois do comando, ou so cola o texto direto sem comando.' } }];
  return [{ json: llm('comentario', P_COMENT + arg) }];
}
if (cmd) {
  return [{ json: { chatId, needsLlm: false, reply: 'Comando desconhecido. /menu mostra o que eu sei fazer.' } }];
}
if (/linkedin\.com|lnkd\.in/i.test(text) && text.length < 300) {
  return [{ json: { chatId, needsLlm: false, reply: 'Eu nao abro links do LinkedIn (para proteger sua conta). Copia o texto do post no app e cola aqui.' } }];
}
if (text.length < 40) {
  return [{ json: { chatId, needsLlm: false, reply: 'Nao entendi. Para comentar um post, cola o texto inteiro dele. /menu mostra os comandos.' } }];
}
return [{ json: llm('comentario', P_COMENT + text) }];
"""

FORMATAR = r"""
const ctx = $('Roteador').first().json;
const resp = $input.first().json;
const chatId = ctx.chatId;

function limpa(s) {
  return String(s || '')
    .replace(/\s*[—–]\s*/g, ', ')
    .replace(/, ,/g, ',')
    .trim();
}

let raw = '';
try { raw = resp.choices[0].message.content || ''; } catch (e) { raw = ''; }
if (!raw) {
  const erro = resp.error ? (resp.error.message || JSON.stringify(resp.error)) : 'resposta vazia';
  return [{ json: { chatId, text: 'A IA nao respondeu: ' + erro } }];
}

let data;
try {
  data = JSON.parse(raw.replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, ''));
} catch (e) {
  return [{ json: { chatId, text: 'Resposta fora do formato, segue crua:\n\n' + limpa(raw).slice(0, 3800) } }];
}

const out = [];
if (ctx.kind === 'post') {
  const v1 = limpa(data.v1), v2 = limpa(data.v2);
  out.push({ json: { chatId, text: 'VERSAO 1 · Bastidores (' + v1.length + ' caracteres)\n\n' + v1 } });
  out.push({ json: { chatId, text: 'VERSAO 2 · Arquitetura (' + v2.length + ' caracteres)\n\n' + v2 } });
  if (data.imagem) out.push({ json: { chatId, text: 'Prompt de imagem (Meta AI):\n\n' + String(data.imagem).trim() } });
} else {
  if (data.aviso) out.push({ json: { chatId, text: 'Aviso: ' + limpa(data.aviso) } });
  out.push({ json: { chatId, text: 'COMENTARIO 1\n\n' + limpa(data.c1) } });
  out.push({ json: { chatId, text: 'COMENTARIO 2\n\n' + limpa(data.c2) } });
}
return out;
"""


def js_const(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


roteador_code = (
    ROTEADOR.replace("__SISTEMA__", js_const(sistema))
    .replace("__P_POST__", js_const(p_post))
    .replace("__P_COMENT__", js_const(p_coment))
    .replace("__AJUDA__", js_const(AJUDA))
)

TG_SEND = "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendMessage"


def tg_node(name, node_id, pos, text_expr):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": pos,
        "parameters": {
            "method": "POST",
            "url": TG_SEND,
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ chat_id: $json.chatId, text: " + text_expr + ", disable_web_page_preview: true }) }}",
            "options": {},
        },
    }


nodes = [
    {
        "id": "n-webhook",
        "name": "Telegram Webhook",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 300],
        "webhookId": "6f0c7a52-1d1e-4b8e-9a39-0c0b1a7e0001",
        "parameters": {
            "httpMethod": "POST",
            "path": WEBHOOK_PATH,
            "responseMode": "onReceived",
            "options": {},
        },
    },
    {
        "id": "n-roteador",
        "name": "Roteador",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [240, 300],
        "parameters": {"jsCode": roteador_code},
    },
    {
        "id": "n-if",
        "name": "Precisa de IA?",
        "type": "n8n-nodes-base.if",
        "typeVersion": 1,
        "position": [480, 300],
        "parameters": {
            "conditions": {
                "boolean": [{"value1": "={{ $json.needsLlm }}", "value2": True}]
            }
        },
    },
    tg_node("Aviso processando", "n-ack", [720, 180], "$json.ack"),
    {
        "id": "n-llm",
        "name": "LLM",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [960, 180],
        "parameters": {
            "method": "POST",
            "url": "={{ $env.LLM_BASE_URL }}/chat/completions",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "=Bearer {{ $env.LLM_API_KEY }}"},
                    {"name": "User-Agent", "value": "copiloto-linkedin/0.1"},
                    {"name": "x-opencode-session", "value": "={{ $('Roteador').first().json.session }}"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($('Roteador').first().json.llmBody) }}",
            "options": {
                "timeout": 180000,
                "response": {"response": {"neverError": True}},
            },
        },
    },
    {
        "id": "n-formatar",
        "name": "Formatar",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1200, 180],
        "parameters": {"jsCode": FORMATAR},
    },
    tg_node("Enviar resultado", "n-send-llm", [1440, 180], "$json.text"),
    tg_node("Responder", "n-send-simple", [720, 420], "$json.reply"),
]

connections = {
    "Telegram Webhook": {"main": [[{"node": "Roteador", "type": "main", "index": 0}]]},
    "Roteador": {"main": [[{"node": "Precisa de IA?", "type": "main", "index": 0}]]},
    "Precisa de IA?": {
        "main": [
            [{"node": "Aviso processando", "type": "main", "index": 0}],
            [{"node": "Responder", "type": "main", "index": 0}],
        ]
    },
    "Aviso processando": {"main": [[{"node": "LLM", "type": "main", "index": 0}]]},
    "LLM": {"main": [[{"node": "Formatar", "type": "main", "index": 0}]]},
    "Formatar": {"main": [[{"node": "Enviar resultado", "type": "main", "index": 0}]]},
}

workflow = {
    "id": WORKFLOW_ID,
    "name": "Copiloto · Bot Telegram",
    "active": False,
    "nodes": nodes,
    "connections": connections,
    "settings": {"executionOrder": "v1", "timezone": "America/Sao_Paulo"},
    "pinData": {},
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"ok: {OUT} ({OUT.stat().st_size} bytes)")
