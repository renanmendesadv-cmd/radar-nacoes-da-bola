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
   {coberto}
  </td></tr>
 </table>
</td></tr>""")

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
 <p style="margin:0 0 12px;font:15px/1.5 Arial,sans-serif;color:{CINZA}">As {len(temas)} pautas com maior nota hoje, de 0 a 100. A nota soma buscas no Google, velocidade com que o assunto cresce, quantos veículos falam dele e o quanto combina com o canal.</p>
 {link_painel}
</td></tr>
{''.join(blocos)}
<tr><td style="padding:6px 0 0;font:13px/1.5 Arial,sans-serif;color:{CINZA}">
 <p style="margin:0 0 6px"><b>Em alta no Google agora (futebol):</b> {termos}</p>
 <p style="margin:0">Fontes consultadas: {_e(', '.join(f'{k}: {v}' for k, v in dados['status'].items()))}. Enviado automaticamente pelo radar.</p>
</td></tr>
</table></td></tr></table></body></html>"""

    texto = "\n\n".join(
        f"#{i} [{t['nota']:.0f}] {t['tema']}\nGancho: {t['sugestao']['gancho']}\nThumb: {t['sugestao']['titulo_thumb']}"
        for i, t in enumerate(temas, 1))
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
