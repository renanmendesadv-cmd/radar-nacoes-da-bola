"""Força no YouTube: o que já está rendendo views sobre cada pauta (YouTube Data API v3).

Precisa da chave YOUTUBE_API_KEY (gratuita, Secret do GitHub). Sem a chave, o radar segue
normalmente e o sinal "Força no YouTube" fica de fora da nota (os outros pesos se redistribuem).

Cota: a API dá 10.000 unidades por dia (zera à meia-noite do horário do Pacífico).
Cada busca (search.list) custa 100 e a leitura das views (videos.list) custa 1.
O radar faz no máximo config.YT_BUSCAS_DIA buscas por dia, contando execuções manuais,
e guarda o resultado de cada consulta do dia em data/youtube-cache.json.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import config as C
from .buscas import nome_chave
from .score import STOP, entidades, norm, nota_youtube, outro_esporte, recalcular, tokens

log = logging.getLogger("radar")

API = "https://www.googleapis.com/youtube/v3"
PACIFICO = ZoneInfo("America/Los_Angeles")  # a cota do Google vira neste fuso


class CotaEsgotada(Exception):
    pass


def _get(get, recurso: str, params: dict, chave: str) -> dict:
    """GET na API. Nunca registra a URL (ela leva a chave)."""
    try:
        r = get(f"{API}/{recurso}", params={**params, "key": chave}, timeout=20)
    except requests.RequestException as e:
        raise RuntimeError(f"falha de rede no YouTube ({type(e).__name__})") from None
    if r.status_code == 200:
        return r.json()
    try:
        erro = r.json().get("error", {})
        motivo = (erro.get("errors") or [{}])[0].get("reason", "") or erro.get("status", "")
        msg = erro.get("message", "")
    except ValueError:
        motivo, msg = "", r.text[:200]
    if r.status_code == 403 and motivo in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
        raise CotaEsgotada(motivo)
    raise RuntimeError(f"YouTube respondeu HTTP {r.status_code} {motivo}: {msg[:160]}")


# Palavras que não ajudam a busca no YouTube (verbos e termos vagos de manchete).
VAGAS = set("""
volta voltar pode deve passar fazer tenta calcula anuncia aumentar dispara previsto prevista pronta pronto
quase acima abaixo mais menos novo nova segue seguem ganha perde sobe cai vira fica ficar pede quer
milhoes milhao bilhao reais valor valores ano anos semana mes dias vez vezes time elenco clube jogo
""".split())


def consulta_do_tema(tema: dict) -> str:
    """Texto de busca: clube + nome próprio mais citado + até 2 palavras que mais se repetem.

    Ex.: "Corinthians déficit dívida", "Flamengo Arrascaeta cirurgia"."""
    from .buscas import COMUNS
    titulos = [m["titulo"] for m in tema.get("manchetes", [])] or [tema["tema"]]
    clubes_tab = {**C.CLUBES_FOCO, **C.CLUBES_BR}
    apelidos = {a for al in clubes_tab.values() for a in al} | {norm(k) for k in clubes_tab} | {"inter"}
    partes: list[str] = []
    if tema.get("clubes"):
        partes.append(tema["clubes"][0])
    elif entidades(tema["tema"])["selecao"]:
        partes.append("Seleção Brasileira")

    def serve(palavra: str) -> bool:
        n = norm(palavra)
        return (len(n) >= 4 and not n.isdigit() and n not in STOP and n not in C.GENERICAS_BUSCA
                and n not in COMUNS and n not in VAGAS and not any(a in n for a in apelidos))

    nome = nome_chave(titulos)
    if nome and serve(nome):
        partes.append(nome)
    toks_titulos = [tokens(t) for t in titulos]
    candidatas = []
    for palavra in re.split(r"[\s,:;!?()\"“”'‘’—–]+", tema["tema"]):
        palavra = palavra.strip(".-")
        if not serve(palavra):
            continue
        n = norm(palavra)
        peso = sum(1 for tt in toks_titulos if n[:5] in tt) + (0.5 if palavra[:1].isupper() else 0)
        candidatas.append((peso, len(n), palavra))
    candidatas.sort(key=lambda c: (-c[0], -c[1]))
    extras = 0
    for _, _, p in candidatas:
        if extras >= 2:
            break
        if not any(norm(p) in norm(x) or norm(x) in norm(p) for x in partes):
            partes.append(p)
            extras += 1
    return " ".join(partes)


def _relevante(video: dict, consulta: str, clube: str | None) -> bool:
    """Evita vídeo fora do assunto: título/descrição precisam ter alguma palavra da consulta
    além do nome do clube (ou o clube, quando a consulta só tem ele)."""
    texto = video["titulo"] + " " + video.get("descricao", "")
    if outro_esporte(video["titulo"]):
        return False
    tv = tokens(texto)
    base = tokens(clube or "")
    resto = tokens(consulta) - base
    return bool((resto & tv) if resto else (base & tv))


def buscar(consulta: str, agora: datetime, chave: str, get=requests.get, clube: str | None = None,
           canal_id: str | None = None) -> dict:
    desde = (agora - timedelta(hours=C.YT_HORAS)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = _get(get, "search", {"part": "snippet", "q": consulta, "type": "video", "order": "viewCount",
                               "publishedAfter": desde, "maxResults": 25, "regionCode": "BR",
                               "relevanceLanguage": "pt", "safeSearch": "none"}, chave)
    ids = [i["id"]["videoId"] for i in res.get("items", []) if i.get("id", {}).get("videoId")]
    videos = []
    if ids:
        det = _get(get, "videos", {"part": "snippet,statistics", "id": ",".join(ids)}, chave)
        for v in det.get("items", []):
            sn, st = v.get("snippet", {}), v.get("statistics", {})
            videos.append({
                "id": v["id"], "titulo": sn.get("title", ""), "descricao": sn.get("description", "")[:300],
                "canal": sn.get("channelTitle", ""), "canal_id": sn.get("channelId", ""),
                "publicado": sn.get("publishedAt"), "views": int(st.get("viewCount", 0) or 0),
                "url": f"https://www.youtube.com/watch?v={v['id']}",
            })
    videos = [v for v in videos if _relevante(v, consulta, clube)]
    videos.sort(key=lambda v: v["views"], reverse=True)
    total = sum(v["views"] for v in videos)
    return {
        "consulta": consulta,
        "n_videos": len(videos),
        "mais_de": bool(res.get("nextPageToken")) and len(ids) >= 25,
        "views": total,
        "top": [{k: v[k] for k in ("titulo", "canal", "views", "url", "publicado")}
                | {"do_canal": bool(canal_id) and v["canal_id"] == canal_id} for v in videos[:3]],
    }


def enriquecer(temas: list[dict], agora: datetime, chave: str | None, estado: dict, cache_path: Path,
               fatores: dict | None = None, canal_id: str | None = None, get=requests.get) -> str:
    """Soma o sinal "Força no YouTube" às pautas do topo. Devolve o texto de status do painel."""
    if not chave:
        log.info("YOUTUBE_API_KEY ausente: sinal do YouTube desligado nesta execução.")
        return "sem chave"
    dia = agora.astimezone(PACIFICO).date().isoformat()
    uso = estado.get("youtube") or {}
    if uso.get("dia") != dia:
        uso = {"dia": dia, "buscas": 0}
    try:
        cache = json.loads(cache_path.read_text("utf-8")) if cache_path.exists() else {}
    except ValueError:
        cache = {}
    cache = {k: v for k, v in cache.items() if v.get("dia") == dia}

    lote = temas[: C.YT_BUSCAS_POR_EXECUCAO]
    feitos = 0
    erro = None
    for t in lote:
        q = consulta_do_tema(t)
        if not q:
            continue
        chave_cache = norm(q)
        if chave_cache in cache:
            r = cache[chave_cache]["resultado"]
        else:
            if uso["buscas"] >= C.YT_BUSCAS_DIA:
                log.info("Limite diário de %d buscas no YouTube atingido; demais pautas sem o sinal.", C.YT_BUSCAS_DIA)
                break
            try:
                r = buscar(q, agora, chave, get=get, clube=(t.get("clubes") or [None])[0], canal_id=canal_id)
            except CotaEsgotada:
                erro = "cota esgotada"
                log.warning("Cota diária da API do YouTube esgotada; o sinal volta amanhã.")
                break
            except RuntimeError as e:
                erro = "erro"
                log.warning("YouTube: %s", e)
                break
            uso["buscas"] += 1
            cache[chave_cache] = {"dia": dia, "resultado": r}
        t["youtube"] = r
        t["sinais"]["youtube"] = round(nota_youtube(r["views"], r["n_videos"]) * 100)
        recalcular(t, fatores)
        feitos += 1
    estado["youtube"] = uso
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), "utf-8")
    temas.sort(key=lambda t: t["nota"], reverse=True)
    log.info("YouTube: %d pautas com o sinal; %d/%d buscas usadas hoje.", feitos, uso["buscas"], C.YT_BUSCAS_DIA)
    return erro or feitos
