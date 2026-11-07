"""Gera workflows/telegram-bot.json a partir dos prompts em prompts/.

Uso: python scripts/build_workflow.py
O workflow nao contem segredos: tudo vem de variaveis de ambiente do container
(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TG_WEBHOOK_SECRET, LLM_*).

Um unico workflow concentra bot e radar porque o estado (vagas vistas, pipeline)
fica no static data do workflow, compartilhado entre as duas entradas.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
OUT = ROOT / "workflows" / "telegram-bot.json"

WEBHOOK_PATH = "telegram-copiloto"
WORKFLOW_ID = "copilotoTelegram01"
RADAR_CRON = "0 9,15 * * *"  # 9h e 15h, horario de Sao Paulo
RADAR_TERMOS = [
    "n8n",
    "automação",
    "automacao",
    "inteligência artificial",
    "agentes de IA",
    "suporte técnico",
    "help desk",
    "service desk",
    "integrações",
    "customer success",
]


def prompt(nome: str) -> str:
    return (PROMPTS / f"{nome}.md").read_text(encoding="utf-8")


AJUDA = """Copiloto LinkedIn

/post <ideia>  gera 2 versoes de post + prompt de imagem
/comentar <texto do post>  sugere 2 comentarios (ou so cola o texto)
/vagas  roda o radar de vagas remotas agora
/pipeline  lista as vagas que voce marcou como Quero
/status  confere se esta tudo de pe

O radar roda sozinho as 9h e as 15h e so te chama quando acha vaga com nota 70+.
Nada e publicado sozinho: voce copia, ajusta e posta."""

COMUM = r"""
const SISTEMA = __SISTEMA__;
function llmBody(userContent, temperature, maxTokens) {
  return {
    model: $env.LLM_MODEL || 'deepseek-v4.1-flash',
    temperature,
    max_tokens: maxTokens,
    response_format: { type: 'json_object' },
    messages: [
      { role: 'system', content: SISTEMA },
      { role: 'user', content: userContent },
    ],
  };
}
"""

ROTEADOR = r"""
const P_POST = __P_POST__;
const P_COMENT = __P_COMENT__;
const P_CAND = __P_CAND__;
const AJUDA = __AJUDA__;

const input = $input.first().json;
const headers = input.headers || {};
const body = input.body || {};

const secret = $env.TG_WEBHOOK_SECRET;
if (secret && headers['x-telegram-bot-api-secret-token'] !== secret) return [];

const sd = $getWorkflowStaticData('global');
sd.jobs = sd.jobs || {};
sd.pipeline = sd.pipeline || {};

const cq = body.callback_query;
const msg = body.message || body.edited_message || (cq && cq.message);
if (!msg || !msg.chat) return [];
const chatId = String(msg.chat.id);
if (chatId !== String($env.TELEGRAM_CHAT_ID)) return [];

const simples = (text) => [{ json: { chatId, route: 'simples', text } }];
const llm = (kind, ack, userContent, temperature = 0.8) => [{ json: {
  chatId, route: 'llm', kind, ack,
  session: 'copiloto-' + chatId + '-' + kind,
  llmBody: llmBody(userContent, temperature, 3000),
} }];

if (cq) {
  const [tipo, id] = String(cq.data || '').split(':');
  const job = sd.jobs[id];
  if (!job) return simples('Nao achei essa vaga na memoria (pode ser antiga). Abre pelo botao do link.');
  const agora = new Date().toISOString();
  if (tipo === 'x') {
    sd.pipeline[id] = { status: 'ignorada', at: agora, title: job.title };
    return simples('Ignorada: ' + job.title);
  }
  if (tipo === 'q') {
    sd.pipeline[id] = { status: 'quero', at: agora, title: job.title, empresa: job.empresa, link: job.link };
    const vaga = 'Titulo: ' + job.title + '\nEmpresa: ' + job.empresa + '\n\n' + job.desc;
    return llm('candidatura', 'Anotado no pipeline. Preparando mensagem para o recrutador...', P_CAND + vaga, 0.6);
  }
  return [];
}

const text = (msg.text || msg.caption || '').trim();
if (!text) return simples('Por enquanto eu so entendo texto. Manda /menu para ver os comandos.');

const m = text.match(/^\/(\w+)(?:@\w+)?\s*([\s\S]*)$/);
const cmd = m ? m[1].toLowerCase() : null;
const arg = m ? m[2].trim() : text;

if (cmd === 'start' || cmd === 'menu' || cmd === 'ajuda' || cmd === 'help') return simples(AJUDA);
if (cmd === 'status') {
  const agora = new Date().toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' });
  const vistas = Object.keys(sd.seen || {}).length;
  const quero = Object.values(sd.pipeline).filter((p) => p.status === 'quero').length;
  return simples('No ar.\nModelo: ' + ($env.LLM_MODEL || '?') + '\nHora do servidor: ' + agora +
    '\nVagas ja analisadas: ' + vistas + '\nNo pipeline (Quero): ' + quero);
}
if (cmd === 'vagas' || cmd === 'radar') {
  return [{ json: { chatId, route: 'radar', ack: 'Buscando vagas remotas novas no Remotar e dando nota. Leva uns 30 a 60 segundos...' } }];
}
if (cmd === 'pipeline') {
  const itens = Object.entries(sd.pipeline)
    .filter(([, p]) => p.status === 'quero')
    .sort((a, b) => (a[1].at < b[1].at ? 1 : -1))
    .slice(0, 20);
  if (!itens.length) return simples('Pipeline vazio. Quando o radar mandar uma vaga, toque em Quero.');
  const linhas = itens.map(([, p], i) => (i + 1) + '. ' + p.title + ' · ' + (p.empresa || '') +
    '\n   marcada em ' + new Date(p.at).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' }) + '\n   ' + (p.link || ''));
  return simples('Vagas marcadas como Quero:\n\n' + linhas.join('\n\n'));
}
if (cmd === 'post') {
  if (!arg) return simples('Manda a ideia junto. Ex.: /post o dia em que meu agente de IA estourou o limite da API e como eu resolvi com fila');
  return llm('post', 'Escrevendo 2 versoes do post...', P_POST + arg);
}
if (cmd === 'comentar') {
  if (!arg) return simples('Cola o texto do post depois do comando, ou so cola o texto direto sem comando.');
  return llm('comentario', 'Lendo o post e pensando nos comentarios...', P_COMENT + arg);
}
if (cmd) return simples('Comando desconhecido. /menu mostra o que eu sei fazer.');
if (/linkedin\.com|lnkd\.in/i.test(text) && text.length < 300) {
  return simples('Eu nao abro links do LinkedIn (para proteger sua conta). Copia o texto do post no app e cola aqui.');
}
if (text.length < 40) return simples('Nao entendi. Para comentar um post, cola o texto inteiro dele. /menu mostra os comandos.');
return llm('comentario', 'Lendo o post e pensando nos comentarios...', P_COMENT + text);
"""

FORMATAR = r"""
const ctx = $('Roteador').first().json;
const resp = $input.first().json;
const chatId = ctx.chatId;

function limpa(s) {
  return String(s || '').replace(/\s*[—–]\s*/g, ', ').replace(/, ,/g, ',').trim();
}
const lista = (arr) => (Array.isArray(arr) ? arr : [arr]).filter(Boolean).map((x) => '• ' + limpa(x)).join('\n');

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
const add = (text) => out.push({ json: { chatId, text } });
if (ctx.kind === 'post') {
  const v1 = limpa(data.v1), v2 = limpa(data.v2);
  add('VERSAO 1 · Bastidores (' + v1.length + ' caracteres)\n\n' + v1);
  add('VERSAO 2 · Arquitetura (' + v2.length + ' caracteres)\n\n' + v2);
  if (data.imagem) add('Prompt de imagem (Meta AI):\n\n' + String(data.imagem).trim());
} else if (ctx.kind === 'candidatura') {
  add('MENSAGEM PARA O RECRUTADOR\n\n' + limpa(data.nota_recrutador));
  add('O QUE DESTACAR\n' + lista(data.destaques) +
      '\n\nLACUNAS E COMO TRATAR\n' + lista(data.lacunas) +
      '\n\nPALAVRAS-CHAVE (so se forem verdade)\n' + (data.palavras_chave || []).join(', '));
} else {
  if (data.aviso) add('Aviso: ' + limpa(data.aviso));
  add('COMENTARIO 1\n\n' + limpa(data.c1));
  add('COMENTARIO 2\n\n' + limpa(data.c2));
}
return out;
"""

RADAR_BUSCAS = r"""
const TERMOS = __TERMOS__;
let manual = false;
let chatId = String($env.TELEGRAM_CHAT_ID);
try {
  const r = $('Roteador').first().json;
  if (r && r.route === 'radar') { manual = true; chatId = r.chatId; }
} catch (e) { /* disparo pela agenda */ }
return TERMOS.map((t) => ({ json: {
  manual, chatId,
  url: 'https://api.remotar.com.br/jobs?search=' + encodeURIComponent(t) + '&page=1',
} }));
"""

RADAR_FILTRAR = r"""
const P_RADAR = __P_RADAR__;
const ctx = $('Radar: buscas').first().json;
const sd = $getWorkflowStaticData('global');
sd.seen = sd.seen || {};
sd.jobs = sd.jobs || {};

const agora = Date.now();
const DIA = 86400000;
for (const [id, t] of Object.entries(sd.seen)) if (agora - t > 45 * DIA) delete sd.seen[id];

const POS = ['n8n', 'automa', 'integra', 'api', 'agente', ' ia ', 'ia generativa', 'inteligência artificial',
  'inteligencia artificial', 'llm', 'chatbot', 'rpa', 'suporte', 'help desk', 'helpdesk', 'service desk',
  'implanta', 'onboarding', 'customer success', 'no-code', 'low-code', 'python', 'zapier', 'make.com', 'sistemas'];
const NEG_TITULO = ['sênior', 'senior', 'sr ', 'sr.', 'especialista', 'lead', 'head', 'gerente', 'diretor',
  'coordenador', 'vendas', 'sales', 'advogad', 'jurídic', 'contábil', 'account executive', 'sdr', 'bdr', 'manager',
  'híbrido', 'hibrido', 'hybrid', 'presencial', 'principal', 'staff', 'líder', 'lider'];

const semHtml = (s) => String(s || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
  .replace(/\s+/g, ' ').trim();

const porId = {};
for (const item of $input.all()) {
  for (const j of (item.json && item.json.data) || []) porId[String(j.id)] = j;
}

const candidatas = [];
for (const [id, j] of Object.entries(porId)) {
  if (sd.seen[id]) continue;
  if (j.active === false || j.expired === true) continue;
  const criada = Date.parse(j.createdAt || '');
  if (!criada || agora - criada > 4 * DIA) continue;
  const titulo = String(j.title || '').toLowerCase();
  const texto = ' ' + (titulo + ' ' + (j.subtitle || '') + ' ' + semHtml(j.description)).toLowerCase() + ' ';
  const score = POS.reduce((n, k) => n + (texto.includes(k) ? 1 : 0), 0);
  if (score <= 0 || NEG_TITULO.some((k) => (' ' + titulo + ' ').includes(k))) { sd.seen[id] = agora; continue; }
  candidatas.push({ id, score, j, criada });
}
candidatas.sort((a, b) => b.score - a.score);
const lote = candidatas.slice(0, 25);

for (const c of lote) {
  sd.jobs[c.id] = {
    id: c.id,
    title: c.j.title,
    empresa: (c.j.company && c.j.company.name) || '',
    link: c.j.externalLink || ('https://remotar.com.br/job/' + c.id),
    desc: semHtml((c.j.subtitle || '') + ' ' + c.j.description).slice(0, 2500),
    created: c.criada,
  };
}
const ids = Object.keys(sd.jobs).sort((a, b) => sd.jobs[b].created - sd.jobs[a].created);
for (const id of ids.slice(400)) delete sd.jobs[id];

if (!lote.length) {
  if (!ctx.manual) return [];
  return [{ json: { chatId: ctx.chatId, temVagas: false, text: 'Radar: nenhuma vaga nova relevante desde a ultima busca.' } }];
}

const vagas = lote.map((c) => ({
  id: c.id,
  titulo: c.j.title,
  empresa: sd.jobs[c.id].empresa,
  descricao: sd.jobs[c.id].desc.slice(0, 700),
}));
return [{ json: {
  chatId: ctx.chatId,
  manual: ctx.manual,
  temVagas: true,
  ids: lote.map((c) => c.id),
  llmBody: llmBody(P_RADAR + JSON.stringify(vagas), 0.2, 4000),
} }];
"""

RADAR_RESULTADO = r"""
const ctx = $('Radar: filtrar').first().json;
const resp = $input.first().json;
const sd = $getWorkflowStaticData('global');
sd.seen = sd.seen || {};
const chatId = ctx.chatId;

let raw = '';
try { raw = resp.choices[0].message.content || ''; } catch (e) { raw = ''; }
let data = null;
try { data = JSON.parse(raw.replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '')); } catch (e) { data = null; }
if (!data || !Array.isArray(data.vagas)) {
  const erro = resp.error ? (resp.error.message || JSON.stringify(resp.error)) : 'resposta fora do formato';
  return [{ json: { chatId, text: 'Radar: a IA falhou ao dar nota (' + erro + '). Tento de novo na proxima rodada.' } }];
}

const notas = {};
for (const v of data.vagas) notas[String(v.id)] = v;
const agora = Date.now();
for (const id of ctx.ids) sd.seen[id] = agora;

const boas = ctx.ids
  .map((id) => ({ id, job: sd.jobs[id], nota: Number((notas[id] || {}).nota || 0), motivo: (notas[id] || {}).motivo || '' }))
  .filter((v) => v.job && v.nota >= 70)
  .sort((a, b) => b.nota - a.nota)
  .slice(0, 8);

if (!boas.length && !ctx.manual) return [];

const out = [{ json: { chatId, text: 'Radar: ' + ctx.ids.length + ' vagas novas analisadas, ' + boas.length + ' com nota 70 ou mais.' } }];
for (const v of boas) {
  const data = new Date(v.job.created).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' });
  out.push({ json: {
    chatId,
    text: v.nota + '/100 · ' + v.job.title + '\n' + v.job.empresa + ' · publicada em ' + data + '\n\n' + v.motivo,
    reply_markup: { inline_keyboard: [
      [{ text: 'Quero', callback_data: 'q:' + v.id }, { text: 'Ignorar', callback_data: 'x:' + v.id }],
      [{ text: 'Abrir vaga', url: v.job.link }],
    ] },
  } });
}
return out;
"""


def js(s: object) -> str:
    return json.dumps(s, ensure_ascii=False)


comum = COMUM.replace("__SISTEMA__", js(prompt("sistema")))
roteador_code = comum + (
    ROTEADOR.replace("__P_POST__", js(prompt("post")))
    .replace("__P_COMENT__", js(prompt("comentario")))
    .replace("__P_CAND__", js(prompt("candidatura")))
    .replace("__AJUDA__", js(AJUDA))
)
radar_buscas_code = RADAR_BUSCAS.replace("__TERMOS__", js(RADAR_TERMOS))
radar_filtrar_code = comum + RADAR_FILTRAR.replace("__P_RADAR__", js(prompt("radar")))

TG_SEND = "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendMessage"
TG_BODY = (
    "={{ JSON.stringify({ chat_id: $json.chatId, text: __TEXT__, "
    "reply_markup: $json.reply_markup, disable_web_page_preview: true }) }}"
)


def tg_node(name, node_id, pos, text_expr="$json.text"):
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
            "jsonBody": TG_BODY.replace("__TEXT__", text_expr),
            "options": {"response": {"response": {"neverError": True}}},
        },
    }


def llm_node(name, node_id, pos, source_node, session_expr):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": pos,
        "parameters": {
            "method": "POST",
            "url": "={{ $env.LLM_BASE_URL }}/chat/completions",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "=Bearer {{ $env.LLM_API_KEY }}"},
                    {"name": "User-Agent", "value": "copiloto-linkedin/0.2"},
                    {"name": "x-opencode-session", "value": session_expr},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($('" + source_node + "').first().json.llmBody) }}",
            "options": {"timeout": 180000, "response": {"response": {"neverError": True}}},
        },
    }


def code_node(name, node_id, pos, code):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": pos,
        "parameters": {"jsCode": code},
    }


def if_string(name, node_id, pos, expr, value):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 1,
        "position": pos,
        "parameters": {"conditions": {"string": [{"value1": expr, "value2": value}]}},
    }


def if_bool(name, node_id, pos, expr):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 1,
        "position": pos,
        "parameters": {"conditions": {"boolean": [{"value1": expr, "value2": True}]}},
    }


nodes = [
    {
        "id": "n-webhook",
        "name": "Telegram Webhook",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 300],
        "webhookId": "6f0c7a52-1d1e-4b8e-9a39-0c0b1a7e0001",
        "parameters": {"httpMethod": "POST", "path": WEBHOOK_PATH, "responseMode": "onReceived", "options": {}},
    },
    code_node("Roteador", "n-roteador", [240, 300], roteador_code),
    if_string("E radar?", "n-if-radar", [480, 300], "={{ $json.route }}", "radar"),
    if_string("Precisa de IA?", "n-if", [720, 420], "={{ $json.route }}", "llm"),
    tg_node("Aviso processando", "n-ack", [960, 340], "$json.ack"),
    llm_node("LLM", "n-llm", [1200, 340], "Roteador", "={{ $('Roteador').first().json.session }}"),
    code_node("Formatar", "n-formatar", [1440, 340], FORMATAR),
    tg_node("Enviar resultado", "n-send-llm", [1680, 340]),
    tg_node("Responder", "n-send-simple", [960, 540]),
    # Radar
    {
        "id": "n-cron",
        "name": "Agenda radar",
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": [480, 0],
        "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": RADAR_CRON}]}},
    },
    tg_node("Aviso radar", "n-ack-radar", [720, 160], "$json.ack"),
    code_node("Radar: buscas", "n-radar-buscas", [960, 80], radar_buscas_code),
    {
        "id": "n-remotar",
        "name": "Remotar",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [1200, 80],
        "parameters": {
            "url": "={{ $json.url }}",
            "options": {"timeout": 30000, "response": {"response": {"neverError": True}}},
        },
    },
    code_node("Radar: filtrar", "n-radar-filtrar", [1440, 80], radar_filtrar_code),
    if_bool("Tem vagas novas?", "n-if-vagas", [1680, 80], "={{ $json.temVagas }}"),
    llm_node("LLM radar", "n-llm-radar", [1920, 0], "Radar: filtrar", "copiloto-radar"),
    code_node("Radar: resultado", "n-radar-resultado", [2160, 0], RADAR_RESULTADO),
    tg_node("Enviar vagas", "n-send-vagas", [2400, 80]),
]


def link(*targets):
    return {"main": [[{"node": t, "type": "main", "index": 0}] if t else [] for t in targets]}


connections = {
    "Telegram Webhook": link("Roteador"),
    "Roteador": link("E radar?"),
    "E radar?": link("Aviso radar", "Precisa de IA?"),
    "Precisa de IA?": link("Aviso processando", "Responder"),
    "Aviso processando": link("LLM"),
    "LLM": link("Formatar"),
    "Formatar": link("Enviar resultado"),
    "Agenda radar": link("Radar: buscas"),
    "Aviso radar": link("Radar: buscas"),
    "Radar: buscas": link("Remotar"),
    "Remotar": link("Radar: filtrar"),
    "Radar: filtrar": link("Tem vagas novas?"),
    "Tem vagas novas?": link("LLM radar", "Enviar vagas"),
    "LLM radar": link("Radar: resultado"),
    "Radar: resultado": link("Enviar vagas"),
}

workflow = {
    "id": WORKFLOW_ID,
    "name": "Copiloto · Bot Telegram + Radar de vagas",
    "active": False,
    "nodes": nodes,
    "connections": connections,
    "settings": {"executionOrder": "v1", "timezone": "America/Sao_Paulo"},
    "pinData": {},
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"ok: {OUT} ({OUT.stat().st_size} bytes)")
