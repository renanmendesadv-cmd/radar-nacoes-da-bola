"""Aviso no celular pelo ntfy (https://ntfy.sh): app gratuito, sem cadastro, com som próprio.

Como funciona: o radar publica a mensagem num "tópico" (um nome que funciona como senha) e o
celular, inscrito no mesmo tópico pelo app ntfy, toca e mostra a notificação.

O nome do tópico fica só no Secret NTFY_TOPICO do GitHub: nunca no código, no log ou no painel,
porque quem souber o nome consegue ler os avisos. A mensagem só leva informação pública
(tema, números do YouTube e links de vídeos públicos).
"""
from __future__ import annotations

import logging

import requests

from . import config as C
from . import ganchos

log = logging.getLogger("radar")


def _mil(n: int | float | None) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".replace(".", ",").replace(",0", "") + " mi"
    if n >= 1000:
        return f"{round(n / 1000)} mil"
    return str(n)


def _decimal(x: float) -> str:
    return f"{x:.1f}".replace(".", ",").replace(",0", "")


def anexar_gancho(alertas: list[dict], temas: list[dict], dia: str) -> None:
    """Põe um gancho pronto em cada alerta: o da pauta, se o assunto for uma pauta do dia;
    senão, um gerado a partir do título do vídeo mais forte (pergunta aberta ou conflito)."""
    por_tema = {t["tema"]: t for t in temas}
    for a in alertas:
        pauta = por_tema.get(a["tema"])
        if pauta and (pauta.get("sugestao") or {}).get("gancho"):
            a["gancho"] = pauta["sugestao"]["gancho"]
            continue
        falso = {"tema": a["tema"], "manchetes": [{"titulo": a["tema"]}], "clubes": a.get("clubes") or [],
                 "categoria": None}
        try:
            ops = ganchos.opcoes(falso, dia, set())
        except Exception as e:  # noqa: BLE001 - sem gancho o alerta continua valendo
            log.warning("Gancho do alerta: %s", e)
            continue
        for tec in ("pergunta", "conflito", "contradicao", "dado"):
            if tec in ops and "[" not in ops[tec][1]:
                a["gancho"] = ops[tec][1]
                break


def urgente(a: dict) -> bool:
    return a.get("velocidade", 0) >= C.VIGIA_URGENTE_VELOCIDADE or (a.get("ganho_hora") or 0) >= C.VIGIA_URGENTE_GANHO


def mensagem(a: dict, painel: str | None) -> dict:
    """Conteúdo do aviso (formato JSON do ntfy, que aceita acentos e emojis sem problema)."""
    linhas = []
    if a.get("ganho_hora"):
        linhas.append(f"+{_mil(a['ganho_hora'])} views na última hora no vídeo mais forte.")
    linhas.append(f"{a['n_videos']} vídeo{'s' if a['n_videos'] != 1 else ''}, {_mil(a['views'])} views; "
                  f"{_decimal(a['velocidade'])}x a média de views por hora do futebol no YouTube.")
    linhas.append(f"Formato em alta: {a['formato_em_alta']}. {a['sugestao']}.")
    if a.get("gancho"):
        linhas.append(f"Gancho: “{a['gancho']}”")
    linhas.append("Confira os fatos antes de gravar.")
    tema = a["tema"] if len(a["tema"]) <= 80 else a["tema"][:77].rstrip() + "…"
    acoes = []
    top = (a.get("exemplos") or [{}])[0]
    if str(top.get("url", "")).startswith("https://"):
        acoes.append({"action": "view", "label": "Ver o vídeo", "url": top["url"]})
    if painel:
        acoes.append({"action": "view", "label": "Abrir o radar", "url": painel})
    msg = {
        "title": f"🔥 Bombando agora: {tema}",
        "message": "\n".join(linhas),
        "priority": 5 if urgente(a) else 4,  # 4 = alta (som e destaque); 5 = urgente
        "tags": ["fire"],
        "actions": acoes,
    }
    if painel:
        msg["click"] = painel
    return msg


def enviar(msg: dict, topico: str, servidor: str | None = None, post=None) -> bool:
    """Publica no ntfy. Nunca registra o nome do tópico no log."""
    post = post or requests.post
    servidor = (servidor or C.NTFY_SERVIDOR).rstrip("/")
    try:
        r = post(servidor, json={**msg, "topic": topico}, timeout=15)
    except requests.RequestException as e:
        log.error("ntfy: falha de rede (%s).", type(e).__name__)
        return False
    if r.status_code != 200:
        log.error("ntfy respondeu HTTP %s.", r.status_code)
        return False
    return True


def teste(topico: str, painel: str | None, servidor: str | None = None, post=None) -> bool:
    msg = {"title": "🔔 Teste do Radar Nações da Bola",
           "message": "Se você ouviu e está lendo isto, os avisos de assunto bombando estão funcionando.",
           "priority": 4, "tags": ["soccer"]}
    if painel:
        msg["click"] = painel
    return enviar(msg, topico, servidor, post)
