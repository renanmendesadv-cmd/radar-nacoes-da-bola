"""O que o torcedor está pesquisando: sugestões do buscador do Google (autocompletar).

Fonte gratuita e sem chave, mas não oficial. Não traz volume; a posição da sugestão
indica o quanto aquela busca é comum. Se a fonte falhar, o radar segue sem ela.
"""
from __future__ import annotations

import json
import logging
import time
from urllib.parse import quote_plus

from . import config as C
from .collect import fetch
from .score import norm

log = logging.getLogger("radar")

URL = "https://suggestqueries.google.com/complete/search?client=firefox&hl=pt-BR&gl=br&q={q}"

GENERICAS = C.GENERICAS_BUSCA


def sugestoes(termo: str) -> list[str]:
    txt = fetch(URL.format(q=quote_plus(termo)), tentativas=2, pausa=1.0)
    if not txt:
        return []
    try:
        dados = json.loads(txt)
        return [s for s in dados[1] if isinstance(s, str)][:10]
    except (ValueError, IndexError, TypeError):
        return []


def especificas(semente: str, lista: list[str]) -> list[str]:
    """Remove o próprio termo e palavras genéricas; fica o que é interesse específico."""
    base = set(norm(semente).split())
    saida = []
    for s in lista:
        resto = [p for p in norm(s).split() if p not in base and p not in GENERICAS and len(p) > 2]
        if resto:
            saida.append(s)
    return saida


def coletar(sementes: list[str]) -> dict[str, list[str]]:
    res = {}
    for s in sementes:
        res[s] = sugestoes(s)
        time.sleep(0.8)
    log.info("Buscas do torcedor: %d termos consultados, %d com resposta",
             len(res), sum(1 for v in res.values() if v))
    return res


COMUNS = {"brasileirao", "libertadores", "copa", "selecao", "brasil", "conmebol", "policia", "federal",
          "governo", "justica", "presidente", "tecnico", "diretoria", "torcida", "ingressos", "veja",
          "saiba", "entenda", "apos", "sobre", "contra", "final", "estadio", "clube", "time", "jogo",
          "uniao", "caixa", "serie", "sul-americana", "morumbis", "maracana", "allianz", "neo", "arena",
          "parque", "sede", "centro", "rio", "paulo", "quarta", "quinta", "sexta", "sabado", "domingo", "segunda", "terca", "janeiro", "fevereiro",
          "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"}


def nome_chave(titulos: list[str]) -> str | None:
    """Nome próprio que mais se repete nas manchetes de um tema (em geral, o jogador ou o assunto)."""
    clubes = {a for al in list(C.CLUBES_FOCO.values()) + list(C.CLUBES_BR.values()) for a in al}
    cont: dict[str, int] = {}
    original: dict[str, str] = {}
    for titulo in titulos:
        vistos = set()
        for palavra in titulo.replace(":", " ").replace(",", " ").replace(";", " ").split():
            limpa = palavra.strip("'\"!?.()“”‘’")
            n = norm(limpa)
            if (limpa[:1].isupper() and not limpa.isupper() and len(n) >= 4 and n not in clubes
                    and n not in GENERICAS and n not in COMUNS and n not in vistos):
                vistos.add(n)
                cont[n] = cont.get(n, 0) + 1
                original.setdefault(n, limpa)
    if not cont:
        return None
    melhor = max(cont, key=lambda k: (cont[k], len(k)))
    return original[melhor] if cont[melhor] >= 2 or len(titulos) == 1 else None
