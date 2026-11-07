"""Gera workflows/telegram-bot.json a partir dos prompts em prompts/.

Uso: python scripts/build_workflow.py
O workflow nao contem segredos: tudo vem de variaveis de ambiente do container
(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TG_WEBHOOK_SECRET, LLM_*, LINKEDIN_CLIENT_*).
O token OAuth do LinkedIn fica no static data do workflow (banco do n8n na VPS).

Um unico workflow concentra bot e radar porque o estado (vagas vistas, pipeline)
fica no static data do workflow, compartilhado entre as duas entradas.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
OUT = ROOT / "workflows" / "telegram-bot.json"

WEBHOOK_PATH = "telegram-copiloto"
LI_CALLBACK_PATH = "linkedin-callback"
LI_SCOPES = "openid profile email w_member_social"
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
/publicar <texto>  publica um texto seu (pede confirmacao)
Imagem: responde a versao escolhida com a foto, ou manda a foto com /post <ideia> na legenda
/conectar  liga (ou renova) sua conta do LinkedIn
/comentar <texto do post>  sugere 2 comentarios (ou so cola o texto)
/vagas  roda o radar de vagas remotas agora
/pipeline  lista as vagas que voce marcou como Quero
/status  confere se esta tudo de pe

O radar roda sozinho as 9h e as 15h e so te chama quando acha vaga com nota 70+.
Nada vai para o LinkedIn sem voce tocar em Publicar e confirmar."""

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
const LI_REDIRECT = String($env.WEBHOOK_URL || '').replace(/\/+$/, '') + '/webhook/__LI_PATH__';
const dataBR = (ms) => new Date(ms).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' });
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

const simples = (text, reply_markup) => [{ json: { chatId, route: 'simples', text, reply_markup } }];
sd.drafts = sd.drafts || {};

// "little text format" do LinkedIn: parenteses e afins sem escape cortam o post.
// Hashtag (# seguido de letra) fica sem escape para continuar clicavel.
const little = (s) => String(s).replace(/[\\|{}@\[\]()<>*_~]/g, (m) => '\\' + m)
  .replace(/#(?![\p{L}\p{N}_])/gu, '\\#');
const confirmar = (id, n, texto) => simples(
  'Publicar no seu perfil, visivel para todos? Depois so apagando no app.' +
  ((sd.drafts[id] || {}).img ? '\nVai junto a imagem que voce mandou.' : '') + '\n\n' + texto,
  { inline_keyboard: [[{ text: 'Sim, publicar', callback_data: 'c' + n + ':' + id }, { text: 'Cancelar', callback_data: 'n:' + id }]] });
const novoDraft = (campos) => {
  const id = Date.now().toString(36);
  sd.drafts[id] = Object.assign({ at: Date.now() }, campos);
  const ids = Object.keys(sd.drafts).sort((a, b) => sd.drafts[b].at - sd.drafts[a].at);
  for (const velho of ids.slice(30)) delete sd.drafts[velho];
  return id;
};
// Botoes de um rascunho: uma linha por versao, e "Tirar imagem" quando tiver imagem.
const botoesDraft = (id) => {
  const d = sd.drafts[id];
  const tag = d.img ? ' com imagem' : '';
  const kb = [[{ text: 'Publicar versao 1' + tag, callback_data: 'p1:' + id }]];
  if (d.v2) kb.push([{ text: 'Publicar versao 2' + tag, callback_data: 'p2:' + id }]);
  if (d.img) kb.push([{ text: 'Tirar imagem', callback_data: 'r:' + id }]);
  return { inline_keyboard: kb };
};
const llm = (kind, ack, userContent, temperature = 0.8) => [{ json: {
  chatId, route: 'llm', kind, ack,
  session: 'copiloto-' + chatId + '-' + kind,
  llmBody: llmBody(userContent, temperature, 8000),
} }];

if (cq) {
  const [tipo, id] = String(cq.data || '').split(':');
  if (/^[pcnr]\d?$/.test(tipo)) {
    const d = sd.drafts[id];
    if (!d) return simples('Esse rascunho saiu da memoria. Gera de novo com /post ou manda /publicar <texto>.');
    if (tipo === 'n') return simples('Ok, nao publiquei.');
    if (tipo === 'r') {
      delete d.img;
      return simples('Imagem removida. O post sai so com texto.', botoesDraft(id));
    }
    const n = tipo.slice(1) || '1';
    const texto = d['v' + n];
    if (!texto) return [];
    if (d.publicado) return simples('Esse ja foi publicado: ' + d.publicado);
    if (tipo[0] === 'p') return confirmar(id, n, texto);
    const li = sd.li;
    if (!li || !li.token) return simples('LinkedIn ainda nao conectado. Manda /conectar e depois toca em Publicar de novo.');
    if (li.exp < Date.now()) return simples('O acesso ao LinkedIn venceu. Manda /conectar para renovar e toca em Publicar de novo.');
    if (d.publicando && Date.now() - d.publicando < 120000) return simples('Ja estou publicando esse, espera um pouco.');
    d.publicando = Date.now();
    return [{ json: {
      chatId, route: 'publicar', draftId: id, token: li.token, img: d.img || null,
      liBody: {
        author: 'urn:li:person:' + li.sub,
        commentary: little(texto),
        visibility: 'PUBLIC',
        distribution: { feedDistribution: 'MAIN_FEED', targetEntities: [], thirdPartyDistributionChannels: [] },
        lifecycleState: 'PUBLISHED',
        isReshareDisabledByAuthor: false,
      },
    } }];
  }
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

// Imagem: foto comprimida (maior resolucao e a ultima) ou arquivo JPG/PNG/GIF.
const foto = (msg.photo && msg.photo.length) ? msg.photo[msg.photo.length - 1].file_id
  : (msg.document && /^image\/(jpeg|png|gif)$/i.test(msg.document.mime_type || '') ? msg.document.file_id : null);
if (msg.document && !foto) return simples('Esse tipo de arquivo eu nao uso. Imagem precisa ser JPG, PNG ou GIF.');
if (foto) {
  const leg = (msg.caption || '').trim();
  const mc = leg.match(/^\/(\w+)(?:@\w+)?\s*([\s\S]*)$/);
  const ccmd = mc ? mc[1].toLowerCase() : null;
  const carg = mc ? mc[2].trim() : '';
  if (ccmd === 'post') {
    if (!carg) return simples('Coloca a ideia na legenda da foto: /post <ideia>.');
    sd.imgPendente = { img: foto, at: Date.now() };
    return llm('post', 'Escrevendo 2 versoes do post (a imagem vai junto)...', P_POST + carg);
  }
  if (ccmd === 'publicar') {
    if (!carg) return simples('Coloca o texto na legenda da foto: /publicar <texto do post>.');
    if (carg.length > 3000) return simples('O LinkedIn aceita ate 3000 caracteres. Esse tem ' + carg.length + '.');
    return confirmar(novoDraft({ v1: carg, img: foto }), '1', carg);
  }
  // Foto respondendo a uma mensagem com botoes de rascunho; senao, o rascunho mais recente (ate 24h).
  let id = null;
  const rm = msg.reply_to_message;
  for (const row of (rm && rm.reply_markup && rm.reply_markup.inline_keyboard) || []) {
    for (const b of row) {
      const mm = String(b.callback_data || '').match(/^[pcr]\d?:(\w+)$/);
      if (mm && sd.drafts[mm[1]]) id = mm[1];
    }
  }
  if (!id) {
    const recentes = Object.keys(sd.drafts).filter((k) => !sd.drafts[k].publicado)
      .sort((a, b) => sd.drafts[b].at - sd.drafts[a].at);
    if (recentes.length && Date.now() - sd.drafts[recentes[0]].at < 24 * 3600000) id = recentes[0];
  }
  if (!id) return simples('Recebi a imagem, mas nao achei rascunho para ela. Manda a foto com a legenda /post <ideia> ou /publicar <texto>.');
  const d = sd.drafts[id];
  if (d.publicado) return simples('Esse rascunho ja foi publicado: ' + d.publicado);
  d.img = foto;
  const previa = String(d.v1 || '').slice(0, 140) + (String(d.v1 || '').length > 140 ? '...' : '');
  return simples('Imagem anexada ao rascunho que comeca assim:\n\n' + previa +
    '\n\nEscolhe a versao para publicar com a imagem.', botoesDraft(id));
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
  const li = sd.li;
  const liTxt = !li ? 'nao conectado (/conectar)' : (li.exp < Date.now() ? 'vencido (/conectar)' :
    'conectado como ' + li.nome + ', vale ate ' + dataBR(li.exp));
  return simples('No ar.\nModelo: ' + ($env.LLM_MODEL || '?') + '\nHora do servidor: ' + agora +
    '\nLinkedIn: ' + liTxt + '\nVagas ja analisadas: ' + vistas + '\nNo pipeline (Quero): ' + quero);
}
if (cmd === 'conectar') {
  if (!$env.LINKEDIN_CLIENT_ID) return simples('Falta configurar LINKEDIN_CLIENT_ID e LINKEDIN_CLIENT_SECRET no Coolify.');
  const state = Date.now().toString(36) + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
  sd.oauth = { state, at: Date.now() };
  const url = 'https://www.linkedin.com/oauth/v2/authorization?response_type=code' +
    '&client_id=' + encodeURIComponent($env.LINKEDIN_CLIENT_ID) +
    '&redirect_uri=' + encodeURIComponent(LI_REDIRECT) +
    '&state=' + state + '&scope=' +
    // '+' no lugar de %20: o Telegram Desktop no Windows decodifica %20 e o navegador quebra o link nos espacos
    encodeURIComponent($env.LINKEDIN_SCOPES || __LI_SCOPES__).replace(/%20/g, '+');
  return simples('Toca no botao, entra no LinkedIn e autoriza o app. O link vale 15 minutos. ' +
    'O acesso dura 60 dias; eu te aviso antes de vencer.',
    { inline_keyboard: [[{ text: 'Conectar LinkedIn', url }]] });
}
if (cmd === 'publicar') {
  if (!arg) return simples('Manda o texto junto: /publicar <texto do post>. Eu mostro antes e so publico se voce confirmar.');
  if (arg.length > 3000) return simples('O LinkedIn aceita ate 3000 caracteres. Esse tem ' + arg.length + '.');
  return confirmar(novoDraft({ v1: arg }), '1', arg);
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
const limpo = raw.replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '');
// JSON quebrado ou cortado: recupera cada campo de texto pelo nome, mesmo sem aspas de fechamento.
function campo(nome) {
  const m = limpo.match(new RegExp('"' + nome + '"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)'));
  if (!m) return null;
  try { return JSON.parse('"' + m[1].replace(/\\$/, '') + '"'); }
  catch (e) { return m[1].replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\'); }
}
function campoLista(nome) {
  const m = limpo.match(new RegExp('"' + nome + '"\\s*:\\s*\\[([\\s\\S]*?)(\\]|$)'));
  if (!m) return [];
  return (m[1].match(/"((?:[^"\\]|\\.)*)"/g) || []).map((s) => { try { return JSON.parse(s); } catch (e) { return s; } });
}
let data, cortado = false;
try {
  data = JSON.parse(limpo);
} catch (e) {
  cortado = true;
  data = { v1: campo('v1'), v2: campo('v2'), imagem: campo('imagem'), c1: campo('c1'), c2: campo('c2'), aviso: campo('aviso'),
    nota_recrutador: campo('nota_recrutador'), destaques: campoLista("destaques"), lacunas: campoLista("lacunas"), palavras_chave: campoLista("palavras_chave") };
  const algo = ctx.kind === 'post' ? data.v1 : (ctx.kind === 'candidatura' ? data.nota_recrutador : data.c1);
  if (!algo) return [{ json: { chatId, text: 'A IA respondeu fora do formato. Tenta de novo em instantes.' } }];
}

const out = [];
const add = (text, reply_markup) => out.push({ json: { chatId, text, reply_markup } });
if (ctx.kind === 'post') {
  const v1 = limpa(data.v1), v2 = limpa(data.v2);
  if (cortado) add('A resposta da IA veio cortada; recuperei o que deu. Confere o final do texto antes de publicar.');
  const sd = $getWorkflowStaticData('global');
  sd.drafts = sd.drafts || {};
  const id = Date.now().toString(36);
  sd.drafts[id] = { at: Date.now(), v1, v2 };
  const pend = sd.imgPendente;
  if (pend && Date.now() - pend.at < 15 * 60000) sd.drafts[id].img = pend.img;
  delete sd.imgPendente;
  const comImg = !!sd.drafts[id].img;
  const ids = Object.keys(sd.drafts).sort((a, b) => sd.drafts[b].at - sd.drafts[a].at);
  for (const velho of ids.slice(30)) delete sd.drafts[velho];
  const botao = (n) => ({ inline_keyboard: [[{ text: 'Publicar versao ' + n + (comImg ? ' com imagem' : ''), callback_data: 'p' + n + ':' + id }]] });
  add('VERSAO 1 · Bastidores (' + v1.length + ' caracteres)\n\n' + v1, botao(1));
  if (v2) add('VERSAO 2 · Arquitetura (' + v2.length + ' caracteres)\n\n' + v2, botao(2));
  add('Quer ajustar antes? Copia, edita e manda /publicar <texto editado>. Se tiver [colchetes], complete antes de publicar.');
  if (comImg) add('A imagem que voce mandou vai junto com a versao que voce publicar.');
  else if (data.imagem) add('Prompt de imagem (cola no Gemini ou no Meta AI):\n\n' + String(data.imagem).trim() +
    '\n\nPara publicar com imagem: gera a imagem, depois responde a versao escolhida mandando a foto.');
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


LI_VALIDAR = r"""
const q = $input.first().json.query || {};
const sd = $getWorkflowStaticData('global');
const pagina = (titulo, msg) => '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">' +
  '<body style="font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:32px;max-width:520px;margin:auto">' +
  '<h2>' + titulo + '</h2><p>' + msg + '</p><p>Pode fechar esta aba e voltar ao Telegram.</p></body>';
const erro = (msg) => [{ json: { ok: false, html: pagina('Nao conectou', msg) } }];
if (q.error) return erro('O LinkedIn recusou: ' + String(q.error_description || q.error).replace(/[<>]/g, ''));
const o = sd.oauth;
if (!o || !q.state || q.state !== o.state) return erro('Link invalido. Manda /conectar de novo no Telegram.');
if (Date.now() - o.at > 15 * 60000) return erro('Link expirou. Manda /conectar de novo no Telegram.');
if (!q.code) return erro('Faltou o codigo de autorizacao.');
delete sd.oauth;
return [{ json: { ok: true, code: q.code, redirectUri: LI_REDIRECT, pagina: null } }];
"""

LI_SALVAR = r"""
const tok = $('LinkedIn: token').first().json;
const eu = $input.first().json;
const chatId = String($env.TELEGRAM_CHAT_ID);
const pagina = (titulo, msg) => '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">' +
  '<body style="font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:32px;max-width:520px;margin:auto">' +
  '<h2>' + titulo + '</h2><p>' + msg + '</p><p>Pode fechar esta aba e voltar ao Telegram.</p></body>';
if (!tok.access_token || !eu.sub) {
  const motivo = String(tok.error_description || tok.error || eu.message || 'resposta inesperada').replace(/[<>]/g, '');
  return [{ json: { chatId, html: pagina('Nao conectou', motivo), text: 'LinkedIn: falhou ao conectar (' + motivo + ').' } }];
}
const sd = $getWorkflowStaticData('global');
const exp = Date.now() + Number(tok.expires_in || 5184000) * 1000;
sd.li = { token: tok.access_token, exp, sub: eu.sub, nome: eu.name || eu.given_name || '?', at: Date.now(), escopo: tok.scope || '' };
return [{ json: { chatId,
  html: pagina('LinkedIn conectado', 'Conta: ' + String(sd.li.nome).replace(/[<>]/g, '') + '. Acesso vale ate ' + dataBR(exp) + '.'),
  text: 'LinkedIn conectado como ' + sd.li.nome + '. Vale ate ' + dataBR(exp) + '. Agora os botoes Publicar funcionam.',
} }];
"""

LI_RESULTADO = r"""
const ctx = $('Roteador').first().json;
const r = $input.first().json;
const sd = $getWorkflowStaticData('global');
const d = (sd.drafts || {})[ctx.draftId] || {};
delete d.publicando;
const status = Number(r.statusCode || 0);
const headers = r.headers || {};
const urn = headers['x-restli-id'] || headers['x-linkedin-id'] || '';
if (status === 201 && urn) {
  const url = 'https://www.linkedin.com/feed/update/' + urn + '/';
  d.publicado = url;
  sd.publicados = (sd.publicados || []).concat([{ urn, url, at: Date.now() }]).slice(-100);
  return [{ json: { chatId: ctx.chatId, text: 'Publicado no LinkedIn.\n' + url } }];
}
let motivo = '';
try { motivo = (r.body && (r.body.message || JSON.stringify(r.body))) || ''; } catch (e) { motivo = ''; }
if (status === 401) motivo = 'acesso vencido ou revogado, manda /conectar. ' + motivo;
return [{ json: { chatId: ctx.chatId, text: 'Nao publiquei (HTTP ' + status + '): ' + String(motivo).slice(0, 500) } }];
"""

LI_MONTAR_IMG = r"""
// Depois de baixar a foto do Telegram e enviar ao LinkedIn: confere cada etapa e monta o post com a imagem.
const ctx = $('Roteador').first().json;
const sd = $getWorkflowStaticData('global');
const d = (sd.drafts || {})[ctx.draftId] || {};
const arq = $('Telegram: arquivo').first().json;
const init = $('LinkedIn: iniciar upload').first().json;
const put = $input.first().json;
const falha = (motivo) => {
  delete d.publicando;
  return [{ json: { ok: false, chatId: ctx.chatId, text: 'Nao publiquei: ' + motivo } }];
};
if (!arq.ok || !arq.result || !arq.result.file_path) {
  return falha('nao consegui pegar a imagem no Telegram (' + (arq.description || 'sem detalhe') +
    '). O limite e 20 MB. Manda a foto de novo respondendo a versao.');
}
const urn = init.value && init.value.image;
if (!urn) return falha('o LinkedIn recusou o upload da imagem (' + String(init.message || JSON.stringify(init)).slice(0, 300) + ').');
const st = Number(put.statusCode || 0);
if (st < 200 || st >= 300) return falha('o envio da imagem para o LinkedIn falhou (HTTP ' + st + ').');
const liBody = Object.assign({}, ctx.liBody, { content: { media: { id: urn } } });
return [{ json: { ok: true, chatId: ctx.chatId, token: ctx.token, liBody } }];
"""

LI_LEMBRETE = r"""
const sd = $getWorkflowStaticData('global');
const li = sd.li;
if (!li || !li.exp) return [];
const dias = Math.floor((li.exp - Date.now()) / 86400000);
if (dias > 10) return [];
const hoje = new Date().toISOString().slice(0, 10);
if (li.lembrado === hoje) return [];
li.lembrado = hoje;
const text = dias < 0 ? 'O acesso ao LinkedIn venceu. Manda /conectar para renovar (leva 10 segundos).'
  : 'O acesso ao LinkedIn vence em ' + dias + ' dias. Manda /conectar para renovar (leva 10 segundos).';
return [{ json: { chatId: String($env.TELEGRAM_CHAT_ID), text } }];
"""


def js(s: object) -> str:
    return json.dumps(s, ensure_ascii=False)


comum = COMUM.replace("__SISTEMA__", js(prompt("sistema"))).replace("__LI_PATH__", LI_CALLBACK_PATH)
# COMUM curto (sem o prompt de sistema) para os nos do LinkedIn
li_comum = COMUM.split("const SISTEMA")[0] + COMUM[COMUM.index("const LI_REDIRECT"):].replace("__LI_PATH__", LI_CALLBACK_PATH)
roteador_code = comum + (
    ROTEADOR.replace("__P_POST__", js(prompt("post")))
    .replace("__P_COMENT__", js(prompt("comentario")))
    .replace("__P_CAND__", js(prompt("candidatura")))
    .replace("__AJUDA__", js(AJUDA))
    .replace("__LI_SCOPES__", js(LI_SCOPES))
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
    code_node("Lembrete token", "n-li-lembrete", [720, -160], LI_LEMBRETE),
    tg_node("Avisar token", "n-li-lembrete-send", [960, -160]),
    # Publicacao no LinkedIn (depois do OK no Telegram)
    if_string("E publicar?", "n-if-publicar", [720, 700], "={{ $json.route }}", "publicar"),
    {
        "id": "n-li-post",
        "name": "LinkedIn: publicar",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [960, 700],
        "parameters": {
            "method": "POST",
            "url": "https://api.linkedin.com/rest/posts",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "=Bearer {{ $json.token }}"},
                    {"name": "LinkedIn-Version", "value": "={{ $env.LINKEDIN_VERSION || '202610' }}"},
                    {"name": "X-Restli-Protocol-Version", "value": "2.0.0"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json.liBody) }}",
            "options": {"timeout": 30000, "response": {"response": {"fullResponse": True, "neverError": True}}},
        },
    },
    # Post com imagem: Telegram (getFile + download) -> LinkedIn Images API -> post com content.media
    if_bool("Tem imagem?", "n-if-img", [840, 820], "={{ !!$json.img }}"),
    {
        "id": "n-tg-getfile",
        "name": "Telegram: arquivo",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [1000, 900],
        "parameters": {
            "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/getFile?file_id={{ encodeURIComponent($json.img) }}",
            "options": {"timeout": 30000, "response": {"response": {"neverError": True}}},
        },
    },
    {
        "id": "n-li-img-init",
        "name": "LinkedIn: iniciar upload",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [1160, 900],
        "parameters": {
            "method": "POST",
            "url": "https://api.linkedin.com/rest/images?action=initializeUpload",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "=Bearer {{ $('Roteador').first().json.token }}"},
                    {"name": "LinkedIn-Version", "value": "={{ $env.LINKEDIN_VERSION || '202610' }}"},
                    {"name": "X-Restli-Protocol-Version", "value": "2.0.0"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ initializeUploadRequest: { owner: $('Roteador').first().json.liBody.author } }) }}",
            "options": {"timeout": 30000, "response": {"response": {"neverError": True}}},
        },
    },
    {
        "id": "n-tg-download",
        "name": "Telegram: baixar imagem",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [1320, 900],
        "parameters": {
            "url": "=https://api.telegram.org/file/bot{{ $env.TELEGRAM_BOT_TOKEN }}/"
                   "{{ ($('Telegram: arquivo').first().json.result || {}).file_path || 'sem-arquivo' }}",
            "options": {
                "timeout": 60000,
                "response": {"response": {"neverError": True, "responseFormat": "file", "outputPropertyName": "data"}},
            },
        },
    },
    {
        "id": "n-li-img-put",
        "name": "LinkedIn: enviar imagem",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [1480, 900],
        "parameters": {
            "method": "PUT",
            "url": "={{ ($('LinkedIn: iniciar upload').first().json.value || {}).uploadUrl || 'https://api.linkedin.com/rest/images/sem-upload' }}",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "=Bearer {{ $('Roteador').first().json.token }}"},
                ]
            },
            "sendBody": True,
            "contentType": "binaryData",
            "inputDataFieldName": "data",
            "options": {"timeout": 120000, "response": {"response": {"fullResponse": True, "neverError": True}}},
        },
    },
    code_node("Montar post com imagem", "n-li-img-montar", [1640, 900], LI_MONTAR_IMG),
    if_bool("Imagem ok?", "n-if-img-ok", [1800, 900], "={{ $json.ok }}"),
    code_node("LinkedIn: resultado", "n-li-resultado", [1200, 700], LI_RESULTADO),
    tg_node("Enviar publicacao", "n-li-send", [1440, 700]),
    # OAuth do LinkedIn (o navegador volta aqui depois de autorizar)
    {
        "id": "n-li-webhook",
        "name": "LinkedIn callback",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 1000],
        "webhookId": "6f0c7a52-1d1e-4b8e-9a39-0c0b1a7e0002",
        "parameters": {"httpMethod": "GET", "path": LI_CALLBACK_PATH, "responseMode": "responseNode", "options": {}},
    },
    code_node("LinkedIn: validar", "n-li-validar", [240, 1000], li_comum + LI_VALIDAR),
    if_bool("Codigo ok?", "n-li-if", [480, 1000], "={{ $json.ok }}"),
    {
        "id": "n-li-token",
        "name": "LinkedIn: token",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [720, 940],
        "parameters": {
            "method": "POST",
            "url": "https://www.linkedin.com/oauth/v2/accessToken",
            "sendBody": True,
            "contentType": "form-urlencoded",
            "bodyParameters": {
                "parameters": [
                    {"name": "grant_type", "value": "authorization_code"},
                    {"name": "code", "value": "={{ $json.code }}"},
                    {"name": "client_id", "value": "={{ $env.LINKEDIN_CLIENT_ID }}"},
                    {"name": "client_secret", "value": "={{ $env.LINKEDIN_CLIENT_SECRET }}"},
                    {"name": "redirect_uri", "value": "={{ $json.redirectUri }}"},
                ]
            },
            "options": {"timeout": 30000, "response": {"response": {"neverError": True}}},
        },
    },
    {
        "id": "n-li-userinfo",
        "name": "LinkedIn: perfil",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [960, 940],
        "parameters": {
            "url": "https://api.linkedin.com/v2/userinfo",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [{"name": "Authorization", "value": "=Bearer {{ $json.access_token }}"}]
            },
            "options": {"timeout": 30000, "response": {"response": {"neverError": True}}},
        },
    },
    code_node("LinkedIn: salvar", "n-li-salvar", [1200, 940], li_comum + LI_SALVAR),
    tg_node("Avisar conexao", "n-li-avisar", [1440, 860]),
    {
        "id": "n-li-respond",
        "name": "Pagina de retorno",
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": [1440, 1060],
        "parameters": {
            "respondWith": "text",
            "responseBody": "={{ $json.html }}",
            "options": {"responseHeaders": {"entries": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}]}},
        },
    },
]


def link(*targets):
    return {"main": [[{"node": t, "type": "main", "index": 0}] if t else [] for t in targets]}


connections = {
    "Telegram Webhook": link("Roteador"),
    "Roteador": link("E radar?"),
    "E radar?": link("Aviso radar", "Precisa de IA?"),
    "Precisa de IA?": link("Aviso processando", "E publicar?"),
    "E publicar?": link("Tem imagem?", "Responder"),
    "Tem imagem?": link("Telegram: arquivo", "LinkedIn: publicar"),
    "Telegram: arquivo": link("LinkedIn: iniciar upload"),
    "LinkedIn: iniciar upload": link("Telegram: baixar imagem"),
    "Telegram: baixar imagem": link("LinkedIn: enviar imagem"),
    "LinkedIn: enviar imagem": link("Montar post com imagem"),
    "Montar post com imagem": link("Imagem ok?"),
    "Imagem ok?": link("LinkedIn: publicar", "Enviar publicacao"),
    "LinkedIn: publicar": link("LinkedIn: resultado"),
    "LinkedIn: resultado": link("Enviar publicacao"),
    "LinkedIn callback": link("LinkedIn: validar"),
    "LinkedIn: validar": link("Codigo ok?"),
    "Codigo ok?": link("LinkedIn: token", "Pagina de retorno"),
    "LinkedIn: token": link("LinkedIn: perfil"),
    "LinkedIn: perfil": link("LinkedIn: salvar"),
    "LinkedIn: salvar": {"main": [[{"node": "Avisar conexao", "type": "main", "index": 0},
                                   {"node": "Pagina de retorno", "type": "main", "index": 0}]]},
    "Lembrete token": link("Avisar token"),
    "Aviso processando": link("LLM"),
    "LLM": link("Formatar"),
    "Formatar": link("Enviar resultado"),
    "Agenda radar": {"main": [[{"node": "Radar: buscas", "type": "main", "index": 0},
                               {"node": "Lembrete token", "type": "main", "index": 0}]]},
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
