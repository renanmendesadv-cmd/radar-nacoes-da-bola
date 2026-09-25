"""Agrupa manchetes em temas, pontua cada tema e sugere o vídeo."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import config as C

STOP = set("""
a o e as os de da do das dos em no na nos nas um uma uns umas por para pra com sem sob sobre
que se ao aos ou mas mais menos ja nao sim foi ser sao esta estao era vai vao tem ter apos
ate como quando onde qual quais quem seu sua seus suas ele ela eles elas isso isto esse essa
este esta hoje ontem amanha diz dizem veja saiba entenda confira video fotos ao-vivo vivo
contra entre pelo pela pelos pelas numa num muito muita the and of to in for on at is
""".split())


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9\- ]+", " ", s).strip()


def tokens(s: str) -> set[str]:
    """Palavras relevantes reduzidas a um radical de 5 letras.

    Assim "negociação"/"negocia" e "europeu"/"Europa" contam como a mesma ideia,
    o que junta manchetes escritas de jeitos diferentes sobre o mesmo assunto.
    """
    return {t[:5] for t in norm(s).split() if len(t) >= 3 and t not in STOP and not t.isdigit()}


def _tem(texto_norm: str, termo: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(termo) + r"(?![a-z0-9])", texto_norm) is not None


def tem_vocab(t: str) -> bool:
    """Vocabulário de futebol (início de palavra).

    O padrão "A x B" sozinho não basta: reality shows e enquetes também usam.
    Jogos entram pelos nomes dos clubes, da Seleção ou das competições."""
    return any(re.search(r"(?<![a-z0-9])" + re.escape(v), t) for v in C.VOCAB_FUTEBOL)


def _clubes(t: str, tabela: dict, vocab: bool) -> list[str]:
    achados = []
    for clube, apelidos in tabela.items():
        for a in apelidos:
            if _tem(t, a) and (vocab or a not in C.APELIDOS_AMBIGUOS):
                achados.append(clube)
                break
    return achados


def outro_esporte(texto: str) -> bool:
    t = " " + norm(texto) + " "
    return any(re.search(r"(?<![a-z0-9])" + re.escape(k), t) for k in C.OUTROS_ESPORTES)


def termo_de_futebol(termo: dict) -> bool:
    """Termo do Trends só conta se ele mesmo, ou a maioria das notícias ligadas, for de futebol."""
    if outro_esporte(termo["termo"]):
        return False
    e = entidades(termo["termo"])
    if e["foco"] or e["br"] or e["selecao"] or e["comp_br"] or e["intl"] or e["vocab"]:
        return True
    nots = [n["titulo"] for n in termo["noticias"] if not espanhol(n["titulo"])]
    return bool(nots) and sum(eh_futebol(n) and not outro_esporte(n) for n in nots) * 2 > len(nots)


def espanhol(texto: str) -> bool:
    palavras = norm(texto).split()
    return sum(1 for p in palavras if p in C.MARCAS_ESPANHOL) >= 2


def entidades(texto: str) -> dict:
    t = " " + norm(texto) + " "
    vocab = tem_vocab(t)
    foco = _clubes(t, C.CLUBES_FOCO, vocab)
    br = _clubes(t, C.CLUBES_BR, vocab)
    sel = any(_tem(t, a) for a in C.SELECAO)
    intl = [a for a in C.INTERNACIONAL if _tem(t, a)]
    comp = any(_tem(t, a) for a in C.COMPETICOES_BR)
    return {"foco": foco, "br": br, "selecao": sel, "intl": intl, "comp_br": comp, "vocab": vocab}


def categoria(texto: str) -> str:
    t = " " + norm(texto) + " "
    # Palavra-chave precisa começar no início de uma palavra ("arbitr" casa "arbitragem",
    # mas "var " só casa a palavra VAR inteira, não "variação").
    contagem = {cat: sum(1 for k in chaves if re.search(r"(?<![a-z0-9])" + re.escape(k), t))
                for cat, chaves in C.CATEGORIAS.items()}
    melhor = max(contagem, key=contagem.get)
    return melhor if contagem[melhor] else "Notícia do dia"


def eh_futebol(texto: str) -> bool:
    e = entidades(texto)
    return bool(e["foco"] or e["br"] or e["selecao"] or e["intl"] or e["comp_br"] or e["vocab"])


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# ---------------------------------------------------------------- agrupamento

def agrupar(noticias: list[dict]) -> list[dict]:
    vistos, unicas = set(), []
    for n in noticias:
        chave = norm(n["titulo"])
        if chave and chave not in vistos:
            vistos.add(chave)
            n = dict(n, _tok=tokens(n["titulo"]), _ent=entidades(n["titulo"]))
            unicas.append(n)

    # Cada tema nasce de uma manchete-semente; as próximas só entram se forem parecidas com ela.
    # Comparar com a semente (e não com qualquer membro) evita o "efeito corrente", em que
    # dezenas de notícias diferentes acabam grudadas num tema só.
    grupos: list[dict] = []
    for n in unicas:
        melhor, melhor_sim = None, 0.0
        n_ent = set(n["_ent"]["foco"] + n["_ent"]["br"])
        for g in grupos:
            semente = g["itens"][0]
            sim = jaccard(n["_tok"], semente["_tok"])
            comuns = len(n["_tok"] & semente["_tok"])
            if (sim >= 0.34 or (n_ent & g["ents"] and comuns >= 3)) and sim > melhor_sim - 1e-9:
                if melhor is None or sim > melhor_sim:
                    melhor, melhor_sim = g, sim
        if melhor is None:
            melhor = {"itens": [], "ents": n_ent}
            grupos.append(melhor)
        melhor["itens"].append(n)
    return grupos


def _representante(itens: list[dict]) -> dict:
    def centralidade(n):
        return sum(len(n["_tok"] & m["_tok"]) for m in itens if m is not n)
    return max(itens, key=lambda n: (centralidade(n), -len(n["titulo"])))


def entidades_do_tema(itens: list[dict], termos: list[str]) -> dict:
    """Clubes/contexto citados em pelo menos 1/3 das manchetes do tema."""
    n = len(itens)
    minimo = max(1, math.ceil(n / 3))
    cont_foco, cont_br = Counter(), Counter()
    sel = comp = intl = 0
    for i in itens:
        e = i["_ent"]
        cont_foco.update(e["foco"]); cont_br.update(e["br"])
        sel += e["selecao"]; comp += e["comp_br"]; intl += bool(e["intl"])
    for t in termos:
        e = entidades(t)
        cont_foco.update(e["foco"]); cont_br.update(e["br"])
    return {
        "foco": [c for c, q in cont_foco.most_common() if q >= minimo],
        "br": [c for c, q in cont_br.most_common() if q >= minimo],
        "selecao": sel >= minimo, "comp_br": comp >= minimo, "intl": ["x"] if intl >= minimo else [],
    }


def categoria_do_tema(itens: list[dict]) -> str:
    votos = Counter(categoria(i["titulo"]) for i in itens)
    votos.pop("Notícia do dia", None)
    return votos.most_common(1)[0][0] if votos else "Notícia do dia"


def assinatura(tok_counter: Counter) -> list[str]:
    return [t for t, _ in tok_counter.most_common(4)]


# ---------------------------------------------------------------- notas

def nota_busca(trafego: int) -> float:
    return min(1.0, math.log10(trafego) / 6) if trafego > 1 else 0.0


def nota_midia(n_fontes: int) -> float:
    return min(1.0, math.log1p(n_fontes) / math.log1p(10))


def nota_aderencia(ent: dict, cat: str) -> float:
    if ent["foco"]:
        base = 1.0
    elif ent["selecao"]:
        base = 0.7
    elif ent["br"] or ent["comp_br"]:
        base = 0.6
    elif ent["intl"]:
        base = 0.5
    else:
        base = 0.3
    return min(1.0, base + C.BONUS_VIRAL.get(cat, 0.0))


def nota_aceleracao(itens: list[dict], assin: list[str], historico: dict, agora: datetime) -> float:
    datas = [datetime.fromisoformat(i["publicado"]) for i in itens if i.get("publicado")]
    recentes = sum(1 for d in datas if agora - d <= timedelta(hours=6))
    razao = recentes / len(datas) if datas else 0.5
    # Crescimento em relação aos dias anteriores (histórico salvo pelo próprio radar).
    anterior = 0
    for dia, temas in historico.items():
        if dia == agora.date().isoformat():
            continue
        for sig, qtd in temas.items():
            if len(set(sig.split("|")) & set(assin)) >= 2:
                anterior = max(anterior, qtd)
    n = len(itens)
    crescimento = n / (n + anterior)  # tema novo -> 1.0; estável -> 0.5; caindo -> < 0.5
    # Volume recente conta junto com a proporção: 2 manchetes novas não podem valer
    # mais do que 12 manchetes, 6 delas nas últimas horas.
    volume_recente = min(1.0, math.log1p(recentes) / math.log1p(6))
    return 0.35 * razao + 0.35 * volume_recente + 0.30 * crescimento


# ---------------------------------------------------------------- sugestões

def sugestao(cat: str, ent: dict, rep_titulo: str) -> dict:
    clube = (ent["foco"] or ent["br"] or [None])[0]
    if clube:
        o_alvo, no_alvo, para_alvo = f"o {clube}", f"no {clube}", f"para o {clube}"
    elif ent["selecao"]:
        o_alvo, no_alvo, para_alvo = "a Seleção", "na Seleção", "para a Seleção"
    else:
        o_alvo, no_alvo, para_alvo = "o futebol brasileiro", "no futebol", "para o time"
    CL = (clube or ("SELEÇÃO" if ent["selecao"] else "FUTEBOL")).upper()
    modelos = {
        "Mercado da bola": ("React rápido (1 a 3 min)",
                            f"Essa negociação pode mudar {o_alvo}, ou virar o erro do ano.",
                            f"{CL}: VALE O INVESTIMENTO?"),
        "Técnico": ("Opinião forte (60 a 90 s)",
                    f"O problema {no_alvo} não é só o técnico, e eu explico por quê.",
                    f"{CL}: A CULPA É DE QUEM?"),
        "Arbitragem e VAR": ("Corte de debate (30 a 60 s)",
                             "Foi ou não foi? Olha esse lance antes de responder.",
                             "FOI PÊNALTI?"),
        "Polêmica e bastidor": ("Explicador de bastidor (2 a 4 min)",
                                f"O que ninguém está contando sobre essa crise {no_alvo}.",
                                f"{CL}: O QUE ESTÁ POR TRÁS"),
        "Finanças e gestão": ("Explicador de bastidor (2 a 4 min)",
                              f"O buraco {no_alvo} é maior do que parece. Eu explico em 2 minutos.",
                              f"{CL}: A CONTA CHEGOU"),
        "Lesão e desfalque": ("React rápido (1 a 2 min)",
                              f"Esse desfalque muda tudo {para_alvo} nos próximos jogos.",
                              f"{CL} SEM ELE: E AGORA?"),
        "Seleção": ("Lista ou ranking (3 a 5 min)",
                    "Se eu fosse o técnico da Seleção, a lista seria outra.",
                    "A MINHA SELEÇÃO"),
        "Jogo e resultado": ("Corte da live com a reação (30 a 90 s)",
                             f"Esse resultado diz mais sobre {o_alvo} do que o placar mostra.",
                             f"{CL}: O QUE O JOGO REVELOU"),
    }
    formato, gancho, titulo = modelos.get(cat, (
        "Enquete e provocação (30 s)",
        "Todo mundo está falando disso. E você, concorda?",
        f"{CL}: E AGORA?"))
    return {"formato": formato, "gancho": gancho, "titulo_thumb": titulo,
            "pergunta_enquete": f"Qual sua opinião: {rep_titulo[:90]}?"}


# ---------------------------------------------------------------- pipeline

def pontuar(bruto: dict, historico: dict, agora: datetime | None = None) -> list[dict]:
    agora = agora or datetime.now(timezone.utc)
    termos = [t for t in bruto["termos"] if termo_de_futebol(t)]
    for t in termos:
        t["noticias"] = [n for n in t["noticias"] if not espanhol(n["titulo"]) and not outro_esporte(n["titulo"])]
    noticias = [n for n in bruto["noticias"]
                if not espanhol(n["titulo"]) and not outro_esporte(n["titulo"])
                and eh_futebol(n["titulo"] + " " + n["busca"])]
    videos_tok = [(v, tokens(v["titulo"]), entidades(v["titulo"])) for v in bruto["videos"]]

    grupos = agrupar(noticias)

    # Cada termo do Trends vai para o tema que MELHOR combina com ele (só um),
    # para que um termo genérico como "flamengo" não infle todas as notícias do clube.
    for g in grupos:
        g["trafego"], g["termos"] = 0, []
        g["_texto"] = " ".join(norm(i["titulo"]) for i in g["itens"])
        g["_toks"] = set().union(*(i["_tok"] for i in g["itens"]))
    usados = set()
    for idx, t in enumerate(termos):
        tt = tokens(t["termo"])
        tn = set().union(*(tokens(n["titulo"]) for n in t["noticias"])) if t["noticias"] else set()
        melhor, melhor_sim = None, 0.0
        for g in grupos:
            contem = bool(norm(t["termo"])) and _tem(g["_texto"], norm(t["termo"]))
            sim = jaccard(tn, g["_toks"]) + (0.3 if contem or (tt and tt <= g["_toks"]) else 0)
            if sim > melhor_sim:
                melhor, melhor_sim = g, sim
        if melhor is not None and melhor_sim >= 0.3:
            melhor["trafego"] += t["trafego"]
            melhor["termos"].append(t["termo"])
            usados.add(idx)
    for idx, t in enumerate(termos):
        if idx in usados:
            continue
        itens = [dict(titulo=n["titulo"], fonte=n["fonte"], url=n["url"], publicado=t["publicado"],
                      busca="Google Trends", _tok=tokens(n["titulo"]), _ent=entidades(n["titulo"]))
                 for n in t["noticias"]] or [dict(titulo=t["termo"], fonte="Google Trends",
                                                 url="https://trends.google.com/trending?geo=BR",
                                                 publicado=t["publicado"], busca="Google Trends",
                                                 _tok=tokens(t["termo"]), _ent=entidades(t["termo"]))]
        grupos.append({"itens": itens, "ents": set(), "trafego": t["trafego"], "termos": [t["termo"]]})

    temas = []
    for g in grupos:
        itens = g["itens"]
        rep = _representante(itens)
        ent = entidades_do_tema(itens, g["termos"])
        cat = categoria_do_tema(itens)
        cont = Counter(t for i in itens for t in i["_tok"])
        assin = assinatura(cont)
        fontes = {i["fonte"] for i in itens if i.get("fonte")}

        sinais = {
            "busca": nota_busca(g["trafego"]),
            "aceleracao": nota_aceleracao(itens, assin, historico, agora),
            "midia": nota_midia(len(fontes)),
            "aderencia": nota_aderencia(ent, cat),
        }
        # A aderência também multiplica a nota: um assunto quente sem ligação com o canal
        # (jogo de outro país, notícia fora do futebol brasileiro) não deve liderar a pauta.
        nota = 100 * sum(C.PESOS[k] * v for k, v in sinais.items()) * (0.55 + 0.45 * sinais["aderencia"])

        coberto = None
        for v, vt, ve in videos_tok:
            comum_ent = set(ve["foco"] + ve["br"]) & set(ent["foco"] + ent["br"])
            if jaccard(vt, set(assin)) >= 0.3 or (comum_ent and len(vt & set(assin)) >= 2):
                coberto = {"titulo": v["titulo"], "url": v["url"]}
                nota *= 0.85
                break

        temas.append({
            "tema": rep["titulo"],
            "categoria": cat,
            "clubes": ent["foco"] + ent["br"],
            "foco": bool(ent["foco"]),
            "nota": round(nota, 1),
            "sinais": {k: round(v * 100) for k, v in sinais.items()},
            "trafego_google": g["trafego"],
            "termos_trends": g["termos"],
            "n_fontes": len(fontes),
            "n_manchetes": len(itens),
            "assinatura": "|".join(assin),
            "ja_coberto": coberto,
            "sugestao": sugestao(cat, ent, rep["titulo"]),
            "manchetes": [{"titulo": i["titulo"], "fonte": i.get("fonte", ""), "url": i.get("url", "")}
                          for i in sorted(itens, key=lambda i: i.get("publicado") or "", reverse=True)[:5]],
        })

    # Temas com uma única manchete e sem busca no Google são ruído na maioria das vezes.
    temas = [t for t in temas if t["n_manchetes"] >= 2 or t["trafego_google"] > 0]
    temas.sort(key=lambda t: t["nota"], reverse=True)
    return temas


def atualizar_historico(historico: dict, temas: list[dict], agora: datetime, dias: int = 7) -> dict:
    hoje = agora.date().isoformat()
    historico = {d: v for d, v in historico.items()
                 if (agora.date() - datetime.fromisoformat(d).date()).days < dias}
    historico[hoje] = {t["assinatura"]: t["n_manchetes"] for t in temas if t["assinatura"]}
    return historico
