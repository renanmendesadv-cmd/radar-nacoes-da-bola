"""Agenda de jogos dos clubes do canal: pré-jogo (próximos dias) e pós-jogo (últimas horas).

Fontes, todas gratuitas e sem chave:
- ESPN (API pública do site): resultados e próximos jogos por clube e competição, com data.
  Desde 29/09/2026 responde 403 para servidores do GitHub Actions; se o primeiro pedido a um
  host for bloqueado, o radar desiste daquele host (não gasta 32 pedidos à toa).
- Buscas do Google (plano B): o autocompletar de "palmeiras x" mostra o adversário que o
  torcedor está pesquisando ("palmeiras x ldu"). Não traz data; as manchetes e as próprias
  sugestões ("onde assistir", "escalação" x "resultado", "2 x 1") dizem se é o próximo jogo.
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
from .score import norm, outro_esporte

log = logging.getLogger("radar")

ESPN = "https://{host}/apis/site/v2/sports/soccer/{liga}/teams/{tid}/schedule{extra}"
ESPN_HEADERS = {"Accept": "application/json", "Referer": "https://www.espn.com.br/", "Origin": "https://www.espn.com.br"}


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
    for host in C.ESPN_HOSTS:
        bloqueado = False
        for clube, tid in C.ESPN_IDS.items():
            for liga in C.ESPN_LIGAS:
                for extra in ("", "?fixture=true"):
                    info: dict = {}
                    txt = fetch(ESPN.format(host=host, liga=liga, tid=tid, extra=extra), tentativas=2, pausa=1.0,
                                headers=ESPN_HEADERS, info=info)
                    if info.get("status") in (401, 403, 429):
                        bloqueado = True
                        break
                    for ev in _parse_eventos(txt) if txt else []:
                        ev["clube"] = clube
                        todos[ev["id"]] = ev
                if bloqueado:
                    break
            if bloqueado:
                break
        if bloqueado and not todos:
            log.warning("ESPN bloqueou o acesso por %s (HTTP 403). Tentando o próximo host, se houver.", host)
            continue
        if todos:
            break
    log.info("Agenda ESPN: %d jogos lidos", len(todos))
    # Diagnóstico: próximo jogo que a ESPN conhece para cada clube.
    for clube in C.ESPN_IDS:
        prox = sorted(e["data"] or "" for e in todos.values() if e["clube"] == clube and e["estado"] == "pre")
        log.info("ESPN %s: %d jogos, %d futuros, próximo em %s", clube,
                 sum(1 for e in todos.values() if e["clube"] == clube), len(prox), prox[0] if prox else "-")
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


# ---------------------------------------------------------------- plano B: buscas do Google

SINAIS_FUTURO = ["onde assistir", "onde vai passar", "vai passar", "ao vivo", "horario", "que horas",
                 "escalacao", "escalacoes", "palpite", "ingresso", "transmissao", "provavel", "enfrenta",
                 "recebe", "visita", "encara", "duelo", "pre-jogo", "antes do jogo", "previa", "desfalque"]
SINAIS_PASSADO = ["resultado", "melhores momentos", "gols de", "venceu", "vence ", "empata", "empatou",
                  "perdeu", "perde ", "derrota", "goleou", "goleada", "atuacoes", "notas ", "pos-jogo",
                  "apos vitoria", "apos derrota", "apos empate"]
PLACAR = re.compile(r"(?<![a-z0-9])\d{1,2} ?x ?\d{1,2}(?![a-z0-9])")


def _conta(texto: str, sinais: list[str]) -> int:
    return sum(1 for k in sinais if re.search(r"(?<![a-z0-9])" + re.escape(k), texto))


def _nome_original(adv_norm: str, titulos: list[str], sugestao: str) -> str:
    """Grafia do adversário como aparece nas manchetes ("LDU", "Vélez"); senão, a da busca."""
    alvo = adv_norm.split()
    for t in titulos:
        palavras = [p.strip(".,:;!?()'\"“”") for p in t.split()]
        for i in range(len(palavras) - len(alvo) + 1):
            trecho = palavras[i:i + len(alvo)]
            if [norm(p) for p in trecho] == alvo:
                return " ".join(trecho)
    return sugestao.title()


def _adversario(sugestao: str, apelidos: list[str]) -> tuple[str, str] | None:
    """'palmeiras x ldu onde assistir' -> ('ldu', 'ldu') (normalizado, original)."""
    n = norm(sugestao)
    for a in sorted(apelidos, key=len, reverse=True):
        m = re.match(re.escape(a) + r" x (.+)$", n)
        if not m:
            continue
        palavras = []
        for p in m.group(1).split():
            if p in PARADAS or p in C.GENERICAS_BUSCA or p.isdigit() or p in {"quem", "ganhou", "resultado",
                                                                              "melhores", "momentos", "gols"}:
                break
            palavras.append(p)
        palavras = palavras[:3]
        if palavras and len(" ".join(palavras)) >= 3:
            return " ".join(palavras), sugestao
    return None


def jogos_das_buscas(sugestoes: dict[str, list[str]], titulos: list[str], por_clube: int = 2) -> list[dict]:
    """Próximos jogos dos clubes do canal a partir do autocompletar do Google.

    Ex.: "palmeiras x ldu quito" e "palmeiras x ldu onde assistir" -> Palmeiras x LDU (pré-jogo).
    Jogos que as buscas e as manchetes indicam como já disputados ("resultado", "2 x 1") saem."""
    titulos_n = [norm(t) for t in titulos]
    saida = []
    for clube, apelidos in C.CLUBES_FOCO.items():
        # Listas cujas sementes são deste clube ("palmeiras", "palmeiras x").
        listas = [v for k, v in sugestoes.items() if any(norm(k) == a or norm(k).startswith(a + " ") for a in apelidos)]
        jogos: dict[str, dict] = {}
        ordem = 0
        for lista in listas:
            for pos, sug in enumerate(lista):
                if outro_esporte(sug) or "feminin" in norm(sug) or "sub-" in norm(sug):
                    continue
                r = _adversario(sug, apelidos)
                if not r:
                    continue
                adv, _ = r
                if norm(clube) in adv or any(adv == a for a in apelidos):
                    continue
                # "ldu" e "ldu quito" são o mesmo jogo: fica a grafia mais completa.
                chave = next((k for k in jogos if k.startswith(adv) or adv.startswith(k)), adv)
                j = jogos.setdefault(chave, {"adv": adv, "sugestoes": [], "melhor_pos": pos, "ordem": ordem})
                ordem += 1
                if len(adv) > len(j["adv"]):
                    j["adv"] = adv
                j["sugestoes"].append(sug)
                j["melhor_pos"] = min(j["melhor_pos"], pos)
        for j in jogos.values():
            adv = j["adv"]
            texto_sug = " ".join(norm(s) for s in j["sugestoes"])
            futuro, passado = _conta(texto_sug, SINAIS_FUTURO), _conta(texto_sug, SINAIS_PASSADO)
            manchetes, exemplo = 0, None
            curto = adv.split()[0] if len(adv.split()[0]) >= 3 else adv  # "ldu quito" -> "ldu"
            for t, tn in zip(titulos, titulos_n):
                # Só conta manchete sobre o confronto ("Palmeiras x LDU", "contra a LDU"),
                # não lista de clubes ("oferecido a Santos, Botafogo, Flamengo e Vasco").
                if any(_confronto(tn, a, curto) for a in apelidos):
                    manchetes += 1
                    exemplo = exemplo or t
                    futuro += _conta(tn, SINAIS_FUTURO) > 0
                    passado += _conta(tn, SINAIS_PASSADO) > 0 or bool(PLACAR.search(tn))
            if passado > futuro:
                continue  # jogo já disputado
            if not futuro and not manchetes and j["melhor_pos"] >= 5:
                continue  # busca antiga ou genérica ("flamengo x botafogo" na 9ª posição)
            nome = _nome_original(adv, titulos, "")
            if not nome and curto != adv:  # manchete diz "LDU", busca diz "ldu quito" -> "LDU Quito"
                inicio = _nome_original(curto, titulos, "")
                nome = f"{inicio} {adv[len(curto):].strip().title()}" if inicio else ""
            nome = nome or adv.title()
            saida.append({
                "tipo": "pré-jogo", "fonte": "buscas do Google", "clube": clube,
                "jogo": f"{clube} x {nome}", "casa": clube, "fora": nome,
                "confianca": "alta" if futuro >= 1 else "média",
                "posicao_busca": j["melhor_pos"] + 1, "manchetes": manchetes, "exemplo": exemplo,
                "sugestoes": j["sugestoes"][:3], "_ordem": j["ordem"],
                "gancho": f"{clube} x {nome}: o detalhe que pode decidir esse jogo.",
                "titulo_thumb": "QUEM LEVA?",
                "formato": "Live de pré-jogo ou vídeo de escalação ideal (3 a 5 min)",
            })
    # Por clube: primeiro os confirmados pelas manchetes/sugestões, depois a posição na busca.
    saida.sort(key=lambda j: (j["clube"], j["confianca"] != "alta", -j["manchetes"], j["posicao_busca"], j["_ordem"]))
    final, cont = [], Counter()
    for j in saida:
        if cont[j["clube"]] < por_clube:
            cont[j["clube"]] += 1
            j.pop("_ordem")
            final.append(j)
    final.sort(key=lambda j: (j["confianca"] != "alta", -j["manchetes"], j["posicao_busca"]))
    return final


def _confronto(tn: str, clube: str, adv: str) -> bool:
    c, a = re.escape(clube), re.escape(adv)
    b0, b1 = r"(?<![a-z0-9])", r"(?![a-z0-9])"
    return bool(re.search(fr"{b0}{c}(?:-[a-z]{{2}})? ?x ?(?:o |a )?{a}{b1}|{b0}{a} ?x ?(?:o |a )?{c}{b1}", tn)
                or (_tem_palavra(tn, clube) and re.search(
                    fr"{b0}(?:contra|enfrenta|encara|recebe|visita|diante|pega) (?:o |a |do |da )?{a}{b1}", tn)))


def _tem_palavra(texto_norm: str, termo: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(termo) + r"(?![a-z0-9])", texto_norm) is not None


def mesmo_jogo(casa1: str, fora1: str, casa2: str, fora2: str) -> bool:
    a, b, c, f = norm(casa1), norm(fora1), norm(casa2), norm(fora2)
    if not all((a, b, c, f)):
        return False
    return ((a in c or c in a) and (b in f or f in b)) or ((a in f or f in a) and (b in c or c in b))


def unir_buscas(nas_buscas: list[dict], agenda: dict, eventos: list[dict] | None = None) -> list[dict]:
    """Tira das buscas os jogos que a ESPN já conhece (em qualquer data, inclusive os já disputados)
    e absorve os "em pauta na mídia" repetidos."""
    conhecidos = agenda["proximos"] + agenda["resultados"] + list(eventos or [])
    saida = [j for j in nas_buscas if not any(mesmo_jogo(j["casa"], j["fora"], e["casa"], e["fora"])
                                              for e in conhecidos)]
    restantes = []
    for m in agenda.get("na_midia", []):
        a, _, b = m["jogo"].partition(" x ")
        par = next((j for j in saida if mesmo_jogo(a, b, j["casa"], j["fora"])), None)
        if par:
            par["manchetes"] = max(par["manchetes"], m["manchetes"])
            par["exemplo"] = par["exemplo"] or m["exemplo"]
            par["confianca"] = "alta"
        else:
            restantes.append(m)
    agenda["na_midia"] = restantes
    return saida
