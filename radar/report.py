"""Gera o e-mail diário e envia por SMTP."""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger("radar")

VERDE = "#0B6E4F"
TINTA = "#16201B"
CINZA = "#5B6660"
FUNDO = "#F3F5F2"


def _e(s) -> str:
    return html.escape(str(s or ""))


def _n(x) -> str:
    """12345 -> '12,3 mil'; 2500000 -> '2,5 mi'."""
    x = int(x or 0)
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f} mi".replace(".", ",")
    if x >= 10_000:
        return f"{x / 1000:.0f} mil"
    if x >= 1000:
        return f"{x / 1000:.1f} mil".replace(".", ",")
    return str(x)


def _cor_nota(n: float) -> str:
    return "#0B6E4F" if n >= 60 else ("#B7791F" if n >= 40 else "#5B6660")


def montar_email(dados: dict, top: int, painel_url: str | None) -> tuple[str, str, str]:
    data_br = dados["data_br"]
    temas = dados["temas"][:top]
    assunto = f"Radar Nações da Bola: {len(temas)} pautas para hoje ({data_br[:5]})"

    blocos = []
    for i, t in enumerate(temas, 1):
        s = t["sugestao"]
        clubes = ", ".join(t["clubes"]) or "Geral"
        manchetes = "".join(
            f'<li style="margin:0 0 4px"><a href="{_e(m["url"])}" style="color:{VERDE}">{_e(m["titulo"])}</a>'
            f' <span style="color:{CINZA}">({_e(m["fonte"])})</span></li>'
            for m in t["manchetes"][:2])
        coberto = ""
        if t.get("ja_coberto"):
            coberto = (f'<p style="margin:8px 0 0;font-size:13px;color:#8A5A00">Atenção: o canal já tem vídeo '
                       f'parecido: <a href="{_e(t["ja_coberto"]["url"])}" style="color:#8A5A00">'
                       f'{_e(t["ja_coberto"]["titulo"])}</a>. Busque um ângulo novo.</p>')
        busca = (f' · buscas no Google: {t["trafego_google"]:,}+'.replace(",", ".")
                 if t["trafego_google"] else "")
        if t.get("busca_torcedor"):
            busca += f' · torcedor pesquisando “{_e(t["busca_torcedor"])}”'
        yt = ""
        if t.get("youtube") and t["youtube"]["n_videos"]:
            y = t["youtube"]
            itens_yt = "".join(
                f'<li style="margin:0 0 3px"><a href="{_e(v["url"])}" style="color:{VERDE}">{_e(v["titulo"])}</a>'
                f' <span style="color:{CINZA}">({_e(v["canal"])} · {_n(v["views"])} views)</span></li>' for v in y["top"])
            yt = (f'<p style="margin:10px 0 4px;font:12px Arial,sans-serif;color:{CINZA}"><b style="color:{TINTA}">No YouTube (48 h):</b> '
                  f'{y["n_videos"]}{"+" if y.get("mais_de") else ""} vídeos, {_n(y["views"])} views. Mais vistos:</p>'
                  f'<ul style="margin:0;padding-left:18px;font:13px/1.4 Arial,sans-serif">{itens_yt}</ul>')

        blocos.append(f"""
<tr><td style="padding:0 0 14px">
 <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #DDE3DE;border-radius:8px">
  <tr><td style="padding:16px 18px">
   <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td style="font:600 12px Arial,sans-serif;color:{CINZA};text-transform:uppercase;letter-spacing:.06em">#{i} · {_e(t["categoria"])} · {_e(clubes)}</td>
    <td align="right" style="font:700 20px Arial,sans-serif;color:{_cor_nota(t["nota"])}">{t["nota"]:.0f}</td>
   </tr></table>
   <h2 style="margin:6px 0 10px;font:700 18px/1.3 Arial,sans-serif;color:{TINTA}">{_e(t["tema"])}</h2>
   <p style="margin:0 0 6px;font:15px/1.45 Arial,sans-serif;color:{TINTA}"><b>Gancho:</b> “{_e(s["gancho"])}”</p>
   <p style="margin:0 0 6px;font:15px/1.45 Arial,sans-serif;color:{TINTA}"><b>Texto da thumb:</b> {_e(s["titulo_thumb"])}</p>
   <p style="margin:0 0 10px;font:15px/1.45 Arial,sans-serif;color:{TINTA}"><b>Formato:</b> {_e(s["formato"])}</p>
   <p style="margin:0 0 4px;font:12px Arial,sans-serif;color:{CINZA}">{t["n_fontes"]} veículos falando do tema{busca}</p>
   <ul style="margin:0;padding-left:18px;font:13px/1.4 Arial,sans-serif">{manchetes}</ul>
   {yt}
   {coberto}
  </td></tr>
 </table>
</td></tr>""")

    ag = dados.get("agenda") or {}
    linhas_jogo = []
    for e in (ag.get("resultados") or [])[:3]:
        linhas_jogo.append(
            f'<li style="margin:0 0 8px"><b>Pós-jogo · {_e(e["casa"])} {e["placar_casa"]} x {e["placar_fora"]} {_e(e["fora"])}</b>'
            f'<br>“{_e(e["gancho"])}” <span style="color:{CINZA}">({_e(e["formato"])})</span></li>')
    for e in (ag.get("proximos") or [])[:3]:
        quando = "hoje" if e.get("em_horas", 99) < 20 else ("amanhã" if e.get("em_horas", 99) < 44 else f'em {round(e["em_horas"] / 24)} dias')
        linhas_jogo.append(
            f'<li style="margin:0 0 8px"><b>Pré-jogo · {_e(e["casa"])} x {_e(e["fora"])} ({quando})</b>'
            f'<br>“{_e(e["gancho"])}” <span style="color:{CINZA}">({_e(e["formato"])})</span></li>')
    for j in (ag.get("nas_buscas") or [])[:4]:
        conf = "confirmado nas manchetes" if j["manchetes"] else ("buscas de pré-jogo" if j["confianca"] == "alta" else "confira a data")
        linhas_jogo.append(
            f'<li style="margin:0 0 8px"><b>Pré-jogo · {_e(j["jogo"])}</b> <span style="color:{CINZA}">(em alta nas buscas do Google; {conf})</span>'
            f'<br>“{_e(j["gancho"])}” <span style="color:{CINZA}">({_e(j["formato"])})</span></li>')
    for j in (ag.get("na_midia") or [])[:3]:
        linhas_jogo.append(f'<li style="margin:0 0 8px"><b>Em pauta na mídia · {_e(j["jogo"])}</b>'
                           f' <span style="color:{CINZA}">({j["manchetes"]} manchetes)</span></li>')
    bloco_jogos = ""
    if linhas_jogo:
        bloco_jogos = (f'<tr><td style="padding:4px 0 14px"><h2 style="margin:0 0 8px;font:700 18px Arial,sans-serif;color:{TINTA}">'
                       f'Jogos que rendem conteúdo</h2><ul style="margin:0;padding-left:18px;font:14px/1.45 Arial,sans-serif;color:{TINTA}">'
                       f'{"".join(linhas_jogo)}</ul></td></tr>')
    buscas_txt = []
    for semente, lista in (dados.get("buscas_torcedor") or {}).items():
        if lista:
            buscas_txt.append(f"<b>{_e(semente)}</b>: " + ", ".join(_e(x) for x in lista[:3]))
    bloco_buscas = ""
    if buscas_txt:
        bloco_buscas = (f'<tr><td style="padding:0 0 14px;font:14px/1.5 Arial,sans-serif;color:{TINTA}">'
                        f'<h2 style="margin:0 0 6px;font:700 18px Arial,sans-serif">O torcedor está pesquisando</h2>'
                        f'{"<br>".join(buscas_txt)}</td></tr>')

    termos = ", ".join(_e(t) for t in dados.get("termos_futebol", [])[:8]) or "nenhum termo de futebol no topo hoje"
    link_painel = (f'<p style="margin:0 0 18px"><a href="{_e(painel_url)}" style="display:inline-block;background:{VERDE};'
                   f'color:#fff;text-decoration:none;font:700 14px Arial,sans-serif;padding:10px 16px;border-radius:6px">'
                   f'Abrir o painel completo</a></p>') if painel_url else ""

    corpo = f"""<!doctype html><html><body style="margin:0;background:{FUNDO}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{FUNDO}"><tr><td align="center" style="padding:20px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px">
<tr><td style="padding:0 0 16px">
 <p style="margin:0;font:700 12px Arial,sans-serif;color:{VERDE};letter-spacing:.08em;text-transform:uppercase">Radar Nações da Bola · {_e(data_br)}</p>
 <h1 style="margin:6px 0 8px;font:700 24px/1.25 Arial,sans-serif;color:{TINTA}">Grave primeiro sobre isto</h1>
 <p style="margin:0 0 12px;font:15px/1.5 Arial,sans-serif;color:{CINZA}">As {len(temas)} pautas com maior nota hoje, de 0 a 100. A nota soma buscas no Google, velocidade com que o assunto cresce, quantos veículos falam dele, views no YouTube nas últimas 48 h e o quanto combina com o canal.</p>
 {link_painel}
</td></tr>
{''.join(blocos)}
{bloco_jogos}
{bloco_buscas}
<tr><td style="padding:6px 0 0;font:13px/1.5 Arial,sans-serif;color:{CINZA}">
 <p style="margin:0 0 6px"><b>Em alta no Google agora (futebol):</b> {termos}</p>
 <p style="margin:0">Fontes consultadas: {_e(', '.join(f'{k}: {v}' for k, v in dados['status'].items()))}. Enviado automaticamente pelo radar.</p>
</td></tr>
</table></td></tr></table></body></html>"""

    texto = "\n\n".join(
        f"#{i} [{t['nota']:.0f}] {t['tema']}\nGancho: {t['sugestao']['gancho']}\nThumb: {t['sugestao']['titulo_thumb']}"
        for i, t in enumerate(temas, 1))
    return assunto, corpo, texto


def montar_email_raiox(rel: dict, painel_url: str | None) -> tuple[str, str, str]:
    """E-mail semanal com o desempenho do canal (YouTube Analytics)."""
    p = rel["periodo"]
    ini, fim = p["inicio"][8:10] + "/" + p["inicio"][5:7], p["fim"][8:10] + "/" + p["fim"][5:7]
    assunto = f"Raio-X do canal Nações da Bola: semana até {fim}"
    h2 = f'style="margin:18px 0 8px;font:700 18px Arial,sans-serif;color:{TINTA}"'
    txt = f'style="margin:0 0 6px;font:14px/1.5 Arial,sans-serif;color:{TINTA}"'
    cinza = f'style="color:{CINZA}"'

    def var(v):
        if v is None:
            return ""
        cor = VERDE if v >= 0 else "#B42318"
        return f' <span style="color:{cor}">({"+" if v >= 0 else ""}{v:.0f}% vs. semana anterior)</span>'

    r = rel["resumo_semana"]
    partes = [f'<p {txt}><b>Semana:</b> {_n(r["views"]["atual"])} views{var(r["views"]["variacao"])} · '
              f'{_n(r["minutos"]["atual"])} minutos assistidos{var(r["minutos"]["variacao"])} · '
              f'+{r["inscritos_ganhos"]["atual"]} / −{r["inscritos_perdidos"]["atual"]} inscritos</p>']
    if rel["recomendacoes"]:
        partes.append(f'<h2 {h2}>O que fazer nesta semana</h2><ul style="margin:0;padding-left:18px;font:14px/1.5 Arial,sans-serif;color:{TINTA}">'
                      + "".join(f"<li style='margin:0 0 6px'>{_e(x)}</li>" for x in rel["recomendacoes"]) + "</ul>")

    def tabela(titulo, cab, linhas):
        if not linhas:
            return ""
        th = "".join(f'<th align="left" style="padding:4px 8px 4px 0;font:600 12px Arial,sans-serif;color:{CINZA}">{c}</th>' for c in cab)
        tr = "".join("<tr>" + "".join(f'<td style="padding:4px 8px 4px 0;font:13px Arial,sans-serif;color:{TINTA};border-top:1px solid #DDE3DE">{c}</td>' for c in l) + "</tr>"
                     for l in linhas)
        return f'<h2 {h2}>{titulo}</h2><table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>{th}</tr>{tr}</table>'

    def ind(x):
        return f"{x:.1f}x".replace(".", ",") if x is not None else "—"

    partes.append(tabela("Formatos que rendem (últimas 4 semanas)", ["Formato", "% das views", "Inscritos", "Views em 7 dias (mediana)", "vs. canal"],
                         [[_e(f["formato"]), f'{f.get("pct_views", 0):.0f}%', f.get("inscritos", "—"), _n(f["mediana_v7"]), ind(f["indice"])]
                          for f in rel["formatos"]]))
    partes.append(tabela("Tipos de conteúdo", ["Tipo", "Vídeos", "Views em 7 dias", "vs. canal", "Inscritos"],
                         [[_e(t["nome"]), t["n_videos"], _n(t["mediana_v7"]), ind(t["indice"]), f'+{t["inscritos7"]}']
                          for t in rel.get("tipos", [])]))
    partes.append(tabela("Clubes que rendem", ["Clube", "Vídeos", "Views em 7 dias", "vs. canal"],
                         [[_e(c["nome"]), c["n_videos"], _n(c["mediana_v7"]), ind(c["indice"])] for c in rel.get("clubes", [])]))
    partes.append(tabela("Temas que rendem (categorias do radar)", ["Tema", "Vídeos", "Views em 7 dias", "vs. canal", "Peso no radar"],
                         [[_e(t["nome"]), t["n_videos"], _n(t["mediana_v7"]), ind(t["indice"]),
                           f'{rel["fatores_categoria"][t["nome"]]:.2f}x'.replace(".", ",") if t["nome"] in rel["fatores_categoria"] else "—"]
                          for t in rel["temas"]]))
    partes.append(tabela("Onde o público sai (vídeos longos e lives mais vistos)", ["Vídeo", "Fica após 30 s", "Metade sai em", "Maior queda"],
                         [[f'<a href="{_e(x["url"])}" style="color:{VERDE}">{_e(x["titulo"][:70])}</a> <span {cinza}>({x["duracao"]})</span>',
                           f'{x["fica_30s"]}%' if x.get("fica_30s") is not None else "—",
                           x["metade_sai_em"] or "não chega a sair metade",
                           f'{x["maior_queda"]["de"]}–{x["maior_queda"]["ate"]} (−{x["maior_queda"]["pontos"]} pts)' if x.get("maior_queda") else "—"]
                          for x in rel["retencao"]]))
    partes.append(tabela("De onde vem o público", ["Origem", "% das views"],
                         [[_e(t["origem"]), f'{t["pct"]:.0f}%'] for t in rel["trafego"]]))
    partes.append(tabela("Melhor dia para publicar", ["Dia", "Vídeos", "Views em 7 dias", "vs. canal"],
                         [[d["quando"], d["n_videos"], _n(d["mediana_v7"]), ind(d["indice"])] for d in rel["melhores_dias"]]))
    partes.append(tabela("Melhor horário para publicar", ["Horário", "Vídeos", "Views em 7 dias", "vs. canal"],
                         [[d["quando"], d["n_videos"], _n(d["mediana_v7"]), ind(d["indice"])] for d in rel["melhores_horarios"]]))
    partes.append(tabela("Vídeos que mais trouxeram inscritos", ["Vídeo", "Formato", "Inscritos"],
                         [[f'<a href="{_e(v["url"])}" style="color:{VERDE}">{_e(v["titulo"][:80])}</a>', v["formato"], f'+{v["inscritos"]}']
                          for v in rel["videos_inscritos"]]))
    link_painel = (f'<p style="margin:16px 0 0"><a href="{_e(painel_url)}#desempenho" style="display:inline-block;background:{VERDE};'
                   f'color:#fff;text-decoration:none;font:700 14px Arial,sans-serif;padding:10px 16px;border-radius:6px">'
                   f'Ver a aba Desempenho no painel</a></p>') if painel_url else ""
    corpo = f"""<!doctype html><html><body style="margin:0;background:{FUNDO}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{FUNDO}"><tr><td align="center" style="padding:20px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px"><tr><td style="background:#fff;border:1px solid #DDE3DE;border-radius:8px;padding:18px 20px">
 <p style="margin:0;font:700 12px Arial,sans-serif;color:{VERDE};letter-spacing:.08em;text-transform:uppercase">Raio-X semanal · {_e(rel["canal"]["nome"])}</p>
 <h1 style="margin:6px 0 8px;font:700 24px/1.25 Arial,sans-serif;color:{TINTA}">O que está rendendo no canal</h1>
 <p style="margin:0 0 12px;font:13px/1.5 Arial,sans-serif;color:{CINZA}">Números do YouTube Analytics de {ini} a {fim} (o YouTube fecha os dados com 2 a 3 dias de atraso).
 Para comparar vídeos de idades diferentes, usamos as views nos 7 primeiros dias de cada um ({rel["n_videos_v7"]} vídeos, mediana de {_n(rel["mediana_v7"])}).</p>
 {"".join(partes)}
 {link_painel}
 <p style="margin:16px 0 0;font:12px/1.5 Arial,sans-serif;color:{CINZA}">Acesso somente leitura. Os pesos por tema já foram ajustados no radar diário (entre 0,85x e 1,15x, mudando aos poucos a cada semana).</p>
</td></tr></table></td></tr></table></body></html>"""
    texto = "\n".join(["Raio-X semanal do canal", ""] + [f"- {x}" for x in rel["recomendacoes"]])
    return assunto, corpo, texto


def enviar(assunto: str, corpo_html: str, corpo_texto: str, *, host: str, porta: int,
           usuario: str, senha: str, para: list[str], remetente_nome: str = "Radar Nações da Bola") -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = f"{remetente_nome} <{usuario}>"
    msg["To"] = ", ".join(para)
    msg.attach(MIMEText(corpo_texto, "plain", "utf-8"))
    msg.attach(MIMEText(corpo_html, "html", "utf-8"))
    ctx = ssl.create_default_context()
    if porta == 465:
        with smtplib.SMTP_SSL(host, porta, context=ctx, timeout=30) as s:
            s.login(usuario, senha)
            s.sendmail(usuario, para, msg.as_string())
    else:
        with smtplib.SMTP(host, porta, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(usuario, senha)
            s.sendmail(usuario, para, msg.as_string())
    log.info("E-mail enviado para %d destinatário(s).", len(para))
