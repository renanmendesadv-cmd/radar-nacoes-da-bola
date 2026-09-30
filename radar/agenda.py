"""Agenda de jogos dos clubes do canal: pré-jogo (próximos dias) e pós-jogo (últimas horas).

Fontes, ambas gratuitas e sem chave:
- ESPN (API pública do site): resultados e próximos jogos por clube e competição.
  O Brasileirão costuma estar em dia; copas podem vir incompletas.
- As próprias manchetes do dia: jogos citados como "Clube x Adversário" em várias
  matérias ("onde assistir", "escalação"...) entram como "jogo em pauta na mídia".
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta

from . import config as C
from .collect import fetch
from .score import norm

log = logging.getLogger("radar")

ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/teams/{tid}/schedule{extra}"


def _parse_eventos(txt: str) -> list[dict]:
    try:
        dados = json.loads(txt)
    except ValueError:
        return []
    eventos = []
    for ev in dados.get("events", []) or []:
        comp = (ev.get("competitions") or [{}])[0]
        times = comp.get("competitors") or []
        casa = next((t for t in times if t.get("homeAway") == "home"), times[0] if times else {})
        fora = next((t for t in times if t.get("homeAway") == "away"), times[1] if len(times) > 1 else {})

        def placar(t):
            s = t.get("score")
            if isinstance(s, dict):
                s = s.get("displayValue") or s.get("value")
            try:
                return int(float(s))
            except (TypeError, ValueError):
                return None

        status = (comp.get("status") or ev.get("status") or {}).get("type", {})
        eventos.append({
            "id": str(ev.get("id")),
            "data": ev.get("date"),
            "liga": (ev.get("league") or {}).get("name") or (ev.get("season") or {}).get("displayName", ""),
            "casa": (casa.get("team") or {}).get("displayName", ""),
            "fora": (fora.get("team") or {}).get("displayName", ""),
            "placar_casa": placar(casa),
            "placar_fora": placar(fora),
            "estado": status.get("state", ""),
        })
    return eventos


def coletar_espn() -> list[dict]:
    todos: dict[str, dict] = {}
    for clube, tid in C.ESPN_IDS.items():
        for liga in C.ESPN_LIGAS:
            for extra in ("", "?fixture=true"):
                txt = fetch(ESPN.format(liga=liga, tid=tid, extra=extra), tentativas=2, pausa=1.0)
                for ev in _parse_eventos(txt) if txt else []:
                    ev["clube"] = clube
                    todos[ev["id"]] = ev
    log.info("Agenda ESPN: %d jogos lidos", len(todos))
    return list(todos.values())


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _gancho_pos(ev: dict) -> tuple[str, str]:
    clube = ev["clube"]
    eh_casa = norm(clube) in norm(ev["casa"])
    gc, gf = ev["placar_casa"], ev["placar_fora"]
    if gc is None or gf is None:
        return (f"O que o jogo do {clube} revelou.", f"{clube.upper()}: O QUE FICOU")
    meus, deles = (gc, gf) if eh_casa else (gf, gc)
    adv = ev["fora"] if eh_casa else ev["casa"]
    if meus > deles:
        return (f"O {clube} venceu o {adv}, mas tem um detalhe que ninguém comentou.",
                f"{clube.upper()} VENCEU. E AGORA?")
    if meus < deles:
        return (f"O que deu errado para o {clube} contra o {adv}? Eu explico em 1 minuto.",
                f"O QUE DEU ERRADO?")
    return (f"Empate com o {adv}: foi bom ou foi ruim para o {clube}?", "EMPATE: BOM OU RUIM?")


LIGAS_PT = {"brazilian serie a": "Brasileirão", "brasileiro serie a": "Brasileirão",
            "conmebol libertadores": "Libertadores", "conmebol sudamericana": "Sul-Americana",
            "copa do brazil": "Copa do Brasil", "copa do brasil": "Copa do Brasil"}


def _liga_pt(nome: str) -> str:
    n = norm(nome)
    for k, v in LIGAS_PT.items():
        if k in n:
            return v
    return nome


def montar_agenda(eventos: list[dict], agora: datetime, dias: int = 7) -> dict:
    pre, pos = [], []
    for ev in eventos:
        ev = dict(ev, liga=_liga_pt(ev.get("liga", "")))
        d = _dt(ev["data"])
        if not d:
            continue
        if ev["estado"] == "post" and timedelta(0) <= agora - d <= timedelta(hours=40):
            gancho, thumb = _gancho_pos(ev)
            pos.append(dict(ev, tipo="pós-jogo", gancho=gancho, titulo_thumb=thumb,
                            formato="Corte da reação na live + análise (60 a 90 s)"))
        elif ev["estado"] == "pre" and timedelta(0) <= d - agora <= timedelta(days=dias):
            horas = (d - agora).total_seconds() / 3600
            ev = dict(ev, tipo="pré-jogo", em_horas=round(horas))
            ev["gancho"] = f"{ev['casa']} x {ev['fora']}: o detalhe que pode decidir esse jogo."
            ev["titulo_thumb"] = "QUEM LEVA?"
            ev["formato"] = ("Live de pré-jogo ou vídeo de escalação ideal (3 a 5 min)" if horas <= 48
                             else "Enquete: qual o seu palpite? (30 s)")
            pre.append(ev)
    pre.sort(key=lambda e: e["data"])
    pos.sort(key=lambda e: e["data"], reverse=True)
    return {"proximos": pre[:8], "resultados": pos[:6]}


def sem_repetir(na_midia: list[dict], agenda: dict) -> list[dict]:
    """Tira da lista "em pauta na mídia" os jogos que a ESPN já trouxe com data e placar."""
    conhecidos = [(norm(e["casa"]), norm(e["fora"])) for e in agenda["proximos"] + agenda["resultados"]]
    saida = []
    for j in na_midia:
        a, _, b = norm(j["jogo"]).partition(" x ")
        if any((a in c or c in a) and (b in f or f in b) or (a in f or f in a) and (b in c or c in b)
               for c, f in conhecidos):
            continue
        saida.append(j)
    return saida


PADRAO_JOGO = re.compile(r"([a-z0-9\-]+(?: [a-z0-9\-]+){0,2}) x ([a-z0-9\-]+(?: [a-z0-9\-]+){0,2})")
PARADAS = {"onde", "assistir", "ao", "vivo", "hoje", "horario", "escalacoes", "escalacao", "palpite",
           "palpites", "pelo", "pela", "no", "na", "em", "de", "do", "da", "e", "o", "a", "veja",
           "saiba", "como", "quando", "transmissao", "prova", "odds", "sub-20", "sub-17", "feminino"}


def _limpa_lado(s: str, do_fim: bool) -> str:
    palavras = s.split()
    if do_fim:  # lado esquerdo: fica com as últimas palavras antes do "x"
        while palavras and palavras[0] in PARADAS:
            palavras.pop(0)
        # corta tudo antes de uma palavra de parada
        for i in range(len(palavras) - 1, -1, -1):
            if palavras[i] in PARADAS:
                palavras = palavras[i + 1:]
                break
    else:
        for i, p in enumerate(palavras):
            if p in PARADAS:
                palavras = palavras[:i]
                break
    return " ".join(palavras)


def jogos_na_midia(titulos: list[str], minimo: int = 2) -> list[dict]:
    """Jogos dos clubes do canal citados como "A x B" em pelo menos `minimo` manchetes."""
    apelidos = {a: c for c, al in C.CLUBES_FOCO.items() for a in al}
    cont, exemplo = Counter(), {}
    for t in titulos:
        n = norm(t)
        if "sub-" in n or "feminin" in n:
            continue
        for a, b in PADRAO_JOGO.findall(n):
            a, b = _limpa_lado(a, True), _limpa_lado(b, False)
            if not a or not b:
                continue
            clube = next((apelidos[x] for x in apelidos if a.endswith(x) or b.startswith(x)), None)
            if not clube:
                continue
            chave = f"{a} x {b}"
            cont[chave] += 1
            exemplo.setdefault(chave, (clube, t))
    saida = []
    for chave, q in cont.most_common(6):
        if q < minimo:
            break
        clube, t = exemplo[chave]
        saida.append({"jogo": chave.title().replace(" X ", " x "), "clube": clube, "manchetes": q, "exemplo": t})
    return saida
