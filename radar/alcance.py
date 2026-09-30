"""Impressões e taxa de cliques (CTR) das miniaturas: YouTube Reporting API, só leitura.

O YouTube só gera esses relatórios depois que existe uma "tarefa de relatório" para o canal.
Na primeira execução o radar cria essa tarefa (relatório channel_reach_basic_a1); o YouTube
entrega os 30 dias anteriores e, a partir daí, um arquivo por dia, em até 48 h. Cada arquivo
fica disponível só por 60 dias, então o radar baixa e guarda o resumo em data/alcance.json.

Precisa da API "YouTube Reporting API" ativada no projeto do Google Cloud. Usa a mesma
autorização do Raio-X (escopo yt-analytics.readonly); não precisa de novo login.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import requests

log = logging.getLogger("radar")

API = "https://youtubereporting.googleapis.com/v1"
TIPO = "channel_reach_basic_a1"
NOME_TAREFA = "Radar Nacoes da Bola - alcance"
DIAS_GUARDADOS = 120


class ErroAlcance(Exception):
    pass


def _pedir(metodo, url, token, **kw):
    try:
        r = metodo(url, headers={"Authorization": f"Bearer {token}"}, timeout=60, **kw)
    except requests.RequestException as e:
        raise ErroAlcance(f"falha de rede ({type(e).__name__})") from None
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = r.text[:160]
        if r.status_code == 403 and ("has not been used" in msg or "disabled" in msg):
            raise ErroAlcance("ative a \"YouTube Reporting API\" no projeto do Google Cloud (README, seção Raio-X)")
        raise ErroAlcance(f"HTTP {r.status_code}: {msg[:200]}")
    return r


def garantir_tarefa(token: str, get=requests.get, post=requests.post) -> tuple[str, bool]:
    """Devolve (id da tarefa, criada_agora)."""
    jobs = _pedir(get, f"{API}/jobs", token).json().get("jobs", [])
    for j in jobs:
        if j.get("reportTypeId") == TIPO:
            return j["id"], False
    j = _pedir(post, f"{API}/jobs", token, json={"reportTypeId": TIPO, "name": NOME_TAREFA}).json()
    log.info("Relatório de alcance ativado no YouTube (tarefa %s). Primeiros dados em até 48 h.", j.get("id"))
    return j["id"], True


def ler_csv(texto: str) -> dict[str, dict[str, list[float]]]:
    """CSV do relatório -> {data: {video_id: [impressões, cliques]}}.

    O relatório vem quebrado por país, aparelho, inscrito etc.; somamos tudo por vídeo e dia.
    CTR vem como fração (0,045) ou porcentagem (4,5); os dois casos são tratados."""
    linhas = list(csv.DictReader(io.StringIO(texto)))
    if not linhas:
        return {}
    ctrs = [float(l.get("video_thumbnail_impressions_ctr") or 0) for l in linhas]
    em_pct = any(c > 1 for c in ctrs)
    out: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for l, ctr in zip(linhas, ctrs):
        imp = float(l.get("video_thumbnail_impressions") or 0)
        if not imp:
            continue
        d = l.get("date", "")
        d = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d
        par = out[d][l.get("video_id", "")]
        par[0] += imp
        par[1] += imp * (ctr / 100 if em_pct else ctr)
    return {d: {v: [round(a), round(b, 2)] for v, (a, b) in vs.items()} for d, vs in out.items()}


def atualizar(token: str, caminho: Path, agora: datetime, get=requests.get, post=requests.post) -> dict:
    """Baixa os relatórios novos e devolve o histórico guardado."""
    try:
        hist = json.loads(caminho.read_text("utf-8")) if caminho.exists() else {}
    except ValueError:
        hist = {}
    hist.setdefault("dias", {})
    hist.setdefault("processados", [])
    job, nova = garantir_tarefa(token, get, post)
    hist["tarefa"] = job
    if nova:
        hist["ativado_em"] = agora.isoformat()
    pagina, novos = None, 0
    for _ in range(10):
        params = {"pageSize": 50}
        if pagina:
            params["pageToken"] = pagina
        res = _pedir(get, f"{API}/jobs/{job}/reports", token, params=params).json()
        for rep in res.get("reports", []):
            if rep["id"] in hist["processados"]:
                continue
            txt = _pedir(get, rep["downloadUrl"], token).text
            for d, vs in ler_csv(txt).items():
                hist["dias"].setdefault(d, {}).update(vs)
            hist["processados"].append(rep["id"])
            novos += 1
        pagina = res.get("nextPageToken")
        if not pagina:
            break
    limite = (agora.date() - timedelta(days=DIAS_GUARDADOS)).isoformat()
    hist["dias"] = {d: v for d, v in hist["dias"].items() if d >= limite}
    hist["processados"] = hist["processados"][-400:]
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), "utf-8")
    log.info("Alcance: %d relatório(s) novo(s); %d dias guardados.", novos, len(hist["dias"]))
    return hist


def resumo(hist: dict, videos: dict, fim: str, tipo_de, formato_de) -> dict:
    """Impressões e CTR dos últimos 28 dias até `fim`, por vídeo, formato e tipo de conteúdo."""
    ini = (datetime.fromisoformat(fim) - timedelta(days=27)).date().isoformat()
    por_video: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for d, vs in (hist.get("dias") or {}).items():
        if ini <= d <= fim:
            for vid, (imp, cli) in vs.items():
                por_video[vid][0] += imp
                por_video[vid][1] += cli
    if not por_video:
        return {"sem_dados": True, "ativado_em": hist.get("ativado_em")}
    imp_tot = sum(a for a, _ in por_video.values())
    cli_tot = sum(b for _, b in por_video.values())
    ctr_geral = 100 * cli_tot / imp_tot if imp_tot else 0

    def agrupa(chave):
        g = defaultdict(lambda: [0.0, 0.0, 0])
        for vid, (a, b) in por_video.items():
            v = videos.get(vid)
            if v:
                k = chave(v)
                g[k][0] += a; g[k][1] += b; g[k][2] += 1
        return sorted(({"nome": k, "impressoes": round(a), "ctr": round(100 * b / a, 1) if a else 0, "n_videos": n}
                       for k, (a, b, n) in g.items() if n >= 3 and a >= 1000), key=lambda r: -r["ctr"])
    lista = []
    for vid, (a, b) in por_video.items():
        v = videos.get(vid)
        if v and a >= 500:
            lista.append({"titulo": v["titulo"], "url": v.get("url", f"https://www.youtube.com/watch?v={vid}"),
                          "impressoes": round(a), "ctr": round(100 * b / a, 1), "formato": formato_de(v),
                          "pct_assistido": v.get("pct_assistido")})
    lista.sort(key=lambda x: -x["ctr"])
    return {"impressoes": round(imp_tot), "ctr": round(ctr_geral, 1), "por_formato": agrupa(formato_de),
            "por_tipo": agrupa(lambda v: tipo_de(v["titulo"])), "melhores": lista[:5],
            "piores": [x for x in lista[::-1] if x["impressoes"] >= 2000][:5], "n_videos": len(lista),
            "ativado_em": hist.get("ativado_em")}
