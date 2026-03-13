"""
Agente de Alertas de Vagas — Analista de Dados
Monitora LinkedIn a cada 30 min e envia email só com vagas NOVAS.
Custo: R$0
"""

import os
import json
import smtplib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from pathlib import Path

# =============================================
# CONFIGURAÇÕES
# =============================================
CONFIG = {
    "email_remetente":    os.getenv("EMAIL_REMETENTE",    "seu_email@gmail.com"),
    "email_senha_app":    os.getenv("EMAIL_SENHA_APP",    "xxxx xxxx xxxx xxxx"),
    "email_destinatario": os.getenv("EMAIL_DESTINATARIO", "seu_email@gmail.com"),

    "termos_busca": [
        "analista de dados",
        "data analyst",
        "analista BI",
        "analytics engineer",
    ],
    "localidade": "Brasil",

    "arquivo_historico": "vagas_vistas.json",
}


# ══════════════════════════════════════════════
# 1. HISTÓRICO
# ══════════════════════════════════════════════

def carregar_historico() -> set:
    repo = os.getenv("GITHUB_REPOSITORY", "")
    url = f"https://raw.githubusercontent.com/{repo}/main/vagas_vistas.json"
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return set(json.loads(resp.read()))
    except Exception:
        return set()


def salvar_historico(ids: set):
    lista = list(ids)[-500:]
    Path(CONFIG["arquivo_historico"]).write_text(json.dumps(lista))


# ══════════════════════════════════════════════
# 2. BUSCA
# ══════════════════════════════════════════════

def buscar_vagas_rss(termo: str, localidade: str) -> list[dict]:
    query = f'site:linkedin.com/jobs "{termo}" "{localidade}"'
    encoded = urllib.parse.quote(query)
    url = (
        f"https://news.google.com/rss/search"
        f"?q={encoded}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    )
    vagas = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            root = ET.fromstring(resp.read())

        for item in root.findall(".//item"):
            titulo    = item.findtext("title", "").strip()
            link      = item.findtext("link",  "").strip()
            descricao = re.sub(r"<[^>]+>", "", item.findtext("description", ""))
            pub_date  = item.findtext("pubDate", "")

            vaga_id = re.sub(r"\W+", "", (titulo + link).lower())[:80]

            vagas.append({
                "id":        vaga_id,
                "titulo":    titulo,
                "link":      link,
                "descricao": descricao.strip()[:350],
                "data":      pub_date,
                "termo":     termo,
            })
    except Exception as e:
        print(f"  ⚠ Erro ao buscar '{termo}': {e}")
    return vagas


def coletar_vagas_novas(historico: set) -> list[dict]:
    todas = []
    for termo in CONFIG["termos_busca"]:
        print(f"  🔍 Buscando: '{termo}'…")
        todas.extend(buscar_vagas_rss(termo, CONFIG["localidade"]))

    agora = datetime.now(timezone.utc)

    novas = []
    for v in todas:
        if v["id"] in historico:
            continue
        try:
            data_vaga = parsedate_to_datetime(v["data"])
            horas = (agora - data_vaga).total_seconds() / 3600
            if horas > 48:
                continue
        except Exception:
            pass
        novas.append(v)

    vistas, unicas = set(), []
    for v in novas:
        if v["id"] not in vistas:
            vistas.add(v["id"])
            unicas.append(v)

    for v in unicas:
        t = v["titulo"].lower()
        v["score"] = (
            (3 if ("remoto" in t or "remote" in t) else 0) +
            (2 if "analista de dados" in t else 0) +
            (1 if any(k in t for k in ["python", "sql", "bi", "power bi"]) else 0)
        )

    return sorted(unicas, key=lambda x: x["score"], reverse=True)


# ══════════════════════════════════════════════
# 3. EMAIL
# ══════════════════════════════════════════════

def gerar_html_alerta(vagas: list[dict]) -> str:
    agora   = datetime.now().strftime("%d/%m/%Y %H:%M")
    total   = len(vagas)
    remotas = sum(1 for v in vagas if "remoto" in v["titulo"].lower() or "remote" in v["titulo"].lower())

    cards = ""
    for v in vagas:
        badge_remoto = (
            '<span style="background:#d1fae5;color:#065f46;padding:3px 10px;'
            'border-radius:20px;font-size:11px;font-weight:700;">🏠 REMOTO</span>'
            if ("remoto" in v["titulo"].lower() or "remote" in v["titulo"].lower())
            else ""
        )
        estrelas = "⭐" * min(v.get("score", 0), 5) or "—"
        cards += f"""
        <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;
                    padding:18px 20px;margin-bottom:14px;
                    border-left:4px solid #6366f1;">
          <div style="display:flex;justify-content:space-between;
                      align-items:flex-start;gap:8px;flex-wrap:wrap;">
            <p style="margin:0;font-size:15px;font-weight:700;
                      color:#1e293b;line-height:1.4;">{v['titulo']}</p>
            {badge_remoto}
          </div>
          <p style="margin:8px 0 4px;font-size:13px;color:#64748b;
                    line-height:1.5;">{v['descricao'][:220]}…</p>
          <div style="margin-top:12px;display:flex;
                      align-items:center;gap:14px;flex-wrap:wrap;">
            <span style="font-size:12px;color:#94a3b8;">🕐 {v['data'][:22]}</span>
            <span style="font-size:12px;color:#94a3b8;">Relevância: {estrelas}</span>
            <a href="{v['link']}"
               style="background:#6366f1;color:#ffffff;padding:7px 16px;
                      border-radius:8px;text-decoration:none;
                      font-size:13px;font-weight:600;">Ver vaga →</a>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:620px;margin:0 auto;padding:24px;">
    <div style="background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);
                border-radius:16px;padding:28px 32px;
                text-align:center;margin-bottom:20px;">
      <div style="font-size:32px;margin-bottom:6px;">🎯</div>
      <h1 style="color:#ffffff;margin:0;font-size:22px;font-weight:700;">
        {total} vaga{'s' if total > 1 else ''} nova{'s' if total > 1 else ''}!
      </h1>
      <p style="color:#c7d2fe;margin:6px 0 0;font-size:13px;">
        Detectadas em {agora} — candidate-se agora!
      </p>
    </div>
    <div style="background:#ffffff;border-radius:12px;padding:16px 20px;
                margin-bottom:20px;border:1px solid #e2e8f0;
                display:flex;justify-content:space-around;text-align:center;">
      <div>
        <div style="font-size:26px;font-weight:800;color:#6366f1;">{total}</div>
        <div style="font-size:12px;color:#94a3b8;margin-top:2px;">Novas vagas</div>
      </div>
      <div style="width:1px;background:#e2e8f0;"></div>
      <div>
        <div style="font-size:26px;font-weight:800;color:#10b981;">{remotas}</div>
        <div style="font-size:12px;color:#94a3b8;margin-top:2px;">Remotas</div>
      </div>
      <div style="width:1px;background:#e2e8f0;"></div>
      <div>
        <div style="font-size:26px;font-weight:800;color:#f59e0b;">
          {sum(1 for v in vagas if v.get('score', 0) >= 3)}
        </div>
        <div style="font-size:12px;color:#94a3b8;margin-top:2px;">Alta relevância</div>
      </div>
    </div>
    {cards}
    <p style="text-align:center;font-size:11px;color:#cbd5e1;margin-top:20px;">
      Agente de Vagas • checagem a cada 30 min • candidate-se nas primeiras horas 🚀
    </p>
  </div>
</body>
</html>"""


def enviar_email(vagas: list[dict]):
    total = len(vagas)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"🚨 {total} vaga{'s' if total > 1 else ''} nova{'s' if total > 1 else ''} "
        f"— Analista de Dados [{datetime.now().strftime('%d/%m %H:%M')}]"
    )
    msg["From"] = CONFIG["email_remetente"]
    msg["To"]   = CONFIG["email_destinatario"]
    msg.attach(MIMEText(gerar_html_alerta(vagas), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(CONFIG["email_remetente"], CONFIG["email_senha_app"])
        s.sendmail(CONFIG["email_remetente"], CONFIG["email_destinatario"], msg.as_string())

    print(f"  ✅ Email enviado: {total} vagas novas!")


# ══════════════════════════════════════════════
# 4. MAIN
# ══════════════════════════════════════════════

def main():
    print(f"\n🤖 [{datetime.now().strftime('%H:%M:%S')}] Iniciando checagem…")

    historico = carregar_historico()
    print(f"  📂 Histórico: {len(historico)} vagas já vistas")

    novas = coletar_vagas_novas(historico)
    print(f"  🆕 Vagas novas encontradas: {len(novas)}")

    historico.update(v["id"] for v in novas)
    salvar_historico(historico)

    if novas:
        enviar_email(novas)
    else:
        print("  💤 Nenhuma vaga nova. Nenhum email enviado.")

    print("  ✔ Checagem concluída.\n")


if __name__ == "__main__":
    main()
