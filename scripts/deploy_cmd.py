"""Gera o comando de deploy para colar no terminal da VPS (Coolify > Terminal).

Uso: python scripts/deploy_cmd.py > cmd.txt

O comando:
1. recria workflows/telegram-bot.json na VPS (gzip + base64);
2. exporta o workflow que esta rodando e copia o staticData dele para o novo JSON,
   para que o import nao apague a conexao do LinkedIn, rascunhos e vagas vistas;
3. importa, publica e reinicia o n8n.
Nenhum segredo vai no comando.
"""
import base64
import gzip
import hashlib
import pathlib

WF_ID = "copilotoTelegram01"
RAIZ = pathlib.Path(__file__).resolve().parent.parent
dados = (RAIZ / "workflows" / "telegram-bot.json").read_bytes()
b64 = base64.b64encode(gzip.compress(dados)).decode()

# Roda dentro do container do n8n (usuario node): junta staticData atual ao JSON novo.
MERGE_JS = (
    "const fs=require('fs');"
    "let cur={};"
    "try{const c=JSON.parse(fs.readFileSync('/tmp/cur.json','utf8'));cur=Array.isArray(c)?c[0]:c;}catch(e){}"
    "let sd=cur&&cur.staticData;"
    "if(typeof sd==='string'){try{sd=JSON.parse(sd)}catch(e){sd=null}}"
    "const n=JSON.parse(fs.readFileSync('/tmp/wf.json','utf8'));"
    "if(sd&&typeof sd==='object')n.staticData=sd;"
    "fs.writeFileSync('/tmp/wf-merged.json',JSON.stringify(n));"
    "const g=(sd&&sd.global)||{};"
    "console.log('STATIC_KEYS='+Object.keys(g).join(','));"
)

cmd = (
    f"clear; echo '{b64}' | base64 -d | gunzip > /root/wf.json"
    " && sha256sum /root/wf.json | cut -c1-16"
    " && C=$(docker ps --format '{{.Names}}' | grep '^n8n-qc26')"
    " && docker cp /root/wf.json $C:/tmp/wf.json"
    f" && (docker exec $C n8n export:workflow --id={WF_ID} --output=/tmp/cur.json >/dev/null 2>&1 || true)"
    f" && docker exec $C node -e \"{MERGE_JS}\""
    " && docker exec $C n8n import:workflow --input=/tmp/wf-merged.json"
    f" && docker exec $C n8n publish:workflow --id={WF_ID}"
    " && docker restart $C && echo DEPLOY_OK"
)

print(cmd)
print("# sha256:", hashlib.sha256(dados).hexdigest()[:16], file=__import__("sys").stderr)
