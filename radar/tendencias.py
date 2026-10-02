"""Alertas de tendência: assuntos ligados ao canal que estão explodindo no YouTube agora.

Fontes (sem gastar busca extra da cota):
- os vídeos das últimas 48 h que o radar já busca para cada pauta (Força no YouTube);
- a lista "Em alta" do YouTube, categoria Esportes, Brasil (1 unidade por execução).

Um assunto vira alerta quando:
1. o vídeo mais forte dele tem views por hora >= config.ALERTA_FATOR_VELOCIDADE x a média;
2. o engajamento (curtidas + comentários por view) está pelo menos na média;
3. tem ligação com o canal (clubes do canal, outros clubes brasileiros, Seleção, competições);
4. o canal ainda não cobriu e ele não foi avisado nos últimos dias.

A "média" é a linha de base do futebol no YouTube que o próprio radar mede: a mediana das
views por hora e do engajamento dos vídeos vistos nos últimos 14 dias.
"""
from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from . import config as C
from .score import entidades, eh_futebol, outro_esporte, tokens

log = logging.getLogger("radar")

SUGESTAO_FORMATO = {
    "Shorts": "Short de 30 a 60 s com a sua opinião ou reação (poste o mesmo vídeo como Reels no Instagram)",
    "Lives": "Live de debate ou react ao vivo, com o assunto no título",
    "Vídeos longos": "Vídeo de 8 a 12 min com análise e opinião forte logo no início",
}


def _horas(publicado: str | None, agora: datetime) -> float:
    try:
        d = datetime.fromisoformat((publicado or "").replace("Z", "+00:00"))
    except ValueError:
        return 48.0
    return max(1.0, (agora - d).total_seconds() / 3600)


def formato(v: dict) -> str:
    if v.get("live"):
        return "Lives"
    d = v.get("duracao_s") or 0
    return "Shorts" if (0 < d <= 180 or "#shorts" in v.get("titulo", "").lower()) else "Vídeos longos"


def metricas(v: dict, agora: datetime) -> dict:
    views = v.get("views") or 0
    inter = (v.get("likes") or 0) + (v.get("comentarios") or 0)
    tem_eng = v.get("likes") is not None or v.get("comentarios") is not None
    return {**v, "vph": views / _horas(v.get("publicado"), agora),
            "eng": (inter / views) if views and tem_eng else None, "formato": formato(v)}


def sinergia(texto: str) -> dict | None:
    """Ligação do assunto com o canal (None = sem ligação)."""
    if outro_esporte(texto) or not eh_futebol(texto):
        return None
    e = entidades(texto)
    if e["foco"] or e["selecao"] or e["br"] or e["comp_br"]:
        return e
    return None


def _mediana(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


BASE_MIN_VIDEOS = 20  # um dia só entra na linha de base com amostra suficiente


def atualizar_base(amostra: list[dict], agora: datetime, caminho: Path, gravar: bool = True) -> dict:
    """Guarda a mediana do dia e devolve a linha de base (mediana dos últimos 14 dias).

    A amostra vem só dos vídeos das pautas (futebol em geral). A lista "Em alta" fica de fora:
    ela já é o topo do YouTube e puxaria a média para cima, escondendo as tendências.
    gravar=False (vigia de hora em hora): só lê a linha de base, sem mexer no arquivo."""
    try:
        hist = json.loads(caminho.read_text("utf-8")) if caminho.exists() else {}
    except ValueError:
        hist = {}
    hoje = agora.date().isoformat()
    if gravar and len(amostra) >= BASE_MIN_VIDEOS:
        hist[hoje] = {"vph": _mediana([v["vph"] for v in amostra]), "eng": _mediana([v["eng"] for v in amostra]),
                      "n": len(amostra)}
    limite = (agora.date() - timedelta(days=14)).isoformat()
    hist = {d: x for d, x in hist.items() if d >= limite and x.get("n", 0) >= BASE_MIN_VIDEOS}
    if gravar:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(hist, ensure_ascii=False, indent=1), "utf-8")
    return {"vph": _mediana([x["vph"] for x in hist.values()]), "eng": _mediana([x["eng"] for x in hist.values()]),
            "dias": len(hist)}


def _dica_do_canal(desempenho: dict | None, fmt: str) -> str | None:
    """Liga o alerta ao que já funciona no canal (Raio-X)."""
    if not desempenho or desempenho.get("oculto"):
        return None
    fmts = {f["formato"]: f for f in desempenho.get("formatos", [])}
    tipos = [t for t in desempenho.get("tipos", []) if t.get("indice") and t["n_videos"] >= 3 and t["nome"] != "Outros"]
    if fmt == "Shorts" and (fmts.get("Shorts", {}).get("n_videos") or 0) < 3:
        return "Seu canal quase não tem Shorts: é uma chance de testar o formato com um assunto que já está bombando."
    if tipos:
        best = tipos[0]
        indice = f"{best['indice']:.1f}".replace(".", ",")
        return f"No seu canal, {best['nome']} rende {indice}x a média: puxe o assunto também na próxima live."
    return None


def detectar(temas: list[dict], em_alta: list[dict], agora: datetime, base_path: Path, estado: dict,
             desempenho: dict | None = None, canal_id: str | None = None, *, gravar_base: bool = True,
             avisados_extra: dict | None = None, limite: int | None = None) -> list[dict]:
    """Assuntos bombando. avisados_extra: vídeos já avisados por outra rotina (vigia x radar da manhã),
    para não repetir. limite: quantos alertas no máximo (padrão: ALERTA_MAX_POR_DIA)."""
    # 1. Amostra do dia: vídeos das pautas + "Em alta" de Esportes com ligação ao futebol.
    grupos = []
    for t in temas:
        y = t.get("youtube") or {}
        vs = [metricas(v, agora) for v in y.get("amostra", []) if v.get("publicado")]
        if vs:
            grupos.append({"tema": t["tema"], "clubes": t.get("clubes", []), "ja_coberto": t.get("ja_coberto"),
                           "sinergia": t.get("sinais", {}).get("aderencia", 0) >= 60, "videos": vs,
                           "toks": set().union(*(tokens(m["titulo"]) for m in t.get("manchetes", [])[:5]) or [set()])})
    alta = [dict(metricas(v, agora), fonte="em_alta") for v in em_alta if _horas(v.get("publicado"), agora) <= 72]
    alta = [v for v in alta if sinergia(v["titulo"] + " " + v.get("descricao", "")[:120])]
    for v in alta:
        # Vídeo em alta sobre uma pauta do dia entra no grupo dela; senão vira um assunto próprio.
        vt = tokens(v["titulo"])
        par = next((g for g in grupos if len(vt & g["toks"]) >= 3), None)
        if par:
            if v["id"] not in {x["id"] for x in par["videos"]}:
                par["videos"].append(v)
        else:
            e = sinergia(v["titulo"] + " " + v.get("descricao", "")[:120])
            grupos.append({"tema": v["titulo"], "clubes": e["foco"] + e["br"], "ja_coberto": None, "sinergia": True,
                           "videos": [v], "toks": vt, "so_em_alta": True})
    amostra = [v for g in grupos if not g.get("so_em_alta") for v in g["videos"] if v.get("fonte") != "em_alta"]
    base = atualizar_base(amostra, agora, base_path, gravar=gravar_base)
    if not base["vph"]:
        log.info("Tendências: linha de base ainda em formação (%d vídeos hoje; mínimo %d).", len(amostra), BASE_MIN_VIDEOS)
        return []

    # 2. Assuntos acima da média.
    avisados = {k: d for k, d in (estado.get("alertas") or {}).items()
                if d >= (agora.date() - timedelta(days=C.ALERTA_REPETIR_APOS_DIAS)).isoformat()}
    ja_avisados = set(avisados) | set(avisados_extra or {})
    alertas = []
    for g in grupos:
        if not g["sinergia"] or g["ja_coberto"]:
            continue
        vs = [v for v in g["videos"] if not (canal_id and v.get("canal_id") == canal_id)]
        if not vs:
            continue
        top = max(vs, key=lambda v: v["vph"])
        views = sum(v["views"] for v in vs)
        inter = sum((v.get("likes") or 0) + (v.get("comentarios") or 0) for v in vs if v["eng"] is not None)
        base_views = sum(v["views"] for v in vs if v["eng"] is not None)
        eng = inter / base_views if base_views else None
        f_vel = top["vph"] / base["vph"]
        f_eng = (eng / base["eng"]) if (eng is not None and base["eng"]) else None
        # ganho_hora: views ganhas por hora desde a conferência anterior (só no vigia).
        ganho = max((v.get("ganho_hora") or 0) for v in vs)
        if top["views"] < C.ALERTA_MIN_VIEWS or (f_vel < C.ALERTA_FATOR_VELOCIDADE and ganho < C.VIGIA_GANHO_HORA):
            continue
        if f_eng is None or f_eng < C.ALERTA_FATOR_ENGAJAMENTO:
            continue
        chave = top["id"]
        if chave in ja_avisados or any(v["id"] in ja_avisados for v in vs):
            continue
        peso = {}
        for v in vs:
            peso[v["formato"]] = peso.get(v["formato"], 0) + v["vph"]
        fmt = max(peso, key=peso.get)
        alertas.append({
            "id": chave, "tema": g["tema"], "clubes": g["clubes"], "origem": "Em alta no YouTube (Esportes)" if g.get("so_em_alta") else "Pauta do radar",
            "formato_em_alta": fmt, "sugestao": SUGESTAO_FORMATO[fmt], "dica_do_canal": _dica_do_canal(desempenho, fmt),
            "n_videos": len(vs), "views": views, "velocidade": round(f_vel, 1), "engajamento": round(f_eng, 1),
            "engajamento_pct": round(100 * eng, 1), "ganho_hora": round(ganho) if ganho else None,
            "exemplos": [{"titulo": v["titulo"], "canal": v["canal"], "views": v["views"], "url": v["url"],
                          "formato": v["formato"], "views_hora": round(v["vph"])}
                         for v in sorted(vs, key=lambda v: -v["vph"])[:3]],
            "_ordem": (f_vel + 3 * ganho / C.VIGIA_GANHO_HORA) * min(f_eng, 3), "_ids": [v["id"] for v in vs],
        })
    alertas.sort(key=lambda a: -a["_ordem"])
    alertas = alertas[: C.ALERTA_MAX_POR_DIA if limite is None else max(0, limite)]
    hoje = agora.date().isoformat()
    for a in alertas:
        for i in a.pop("_ids"):
            avisados[i] = hoje
        a.pop("_ordem")
    estado["alertas"] = avisados
    log.info("Tendências: base %s views/h, engajamento %s; %d alertas.", round(base["vph"] or 0),
             round(100 * (base["eng"] or 0), 1), len(alertas))
    return alertas
