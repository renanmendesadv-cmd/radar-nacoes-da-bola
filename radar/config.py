"""Configuração editorial do Radar Nações da Bola.

Edite este arquivo para mudar clubes prioritários, buscas e pesos.
Nada aqui é secreto: e-mails e senhas ficam nos Secrets do GitHub.
"""

# Clubes em que o canal mais fala: recebem aderência máxima.
CLUBES_FOCO = {
    "Flamengo": ["flamengo", "mengao", "rubro-negro carioca"],
    "Corinthians": ["corinthians", "timao"],
    "São Paulo": ["sao paulo fc", "spfc", "tricolor paulista", "sao paulo"],
    "Palmeiras": ["palmeiras", "verdao"],
}

# Outros clubes brasileiros relevantes (aderência média).
CLUBES_BR = {
    "Santos": ["santos"], "Vasco": ["vasco"], "Fluminense": ["fluminense"],
    "Botafogo": ["botafogo"], "Grêmio": ["gremio"], "Internacional": ["colorado", "inter-rs", "internacional de porto alegre"],
    "Atlético-MG": ["atletico-mg", "atletico mineiro", "galo"], "Cruzeiro": ["cruzeiro"],
    "Bahia": ["bahia"], "Fortaleza": ["fortaleza"], "Bragantino": ["bragantino"],
    "Athletico-PR": ["athletico"], "Sport": ["sport recife"],
    # "vitoria" sozinho confundiria com "vitória" (resultado); por isso aliases específicos.
    "Vitória": ["ec vitoria", "vitoria-ba", "leao da barra"],
    "Mirassol": ["mirassol"], "Ceará": ["ceara"], "Juventude": ["juventude"],
}

# Competições nacionais (aderência média mesmo sem clube citado).
COMPETICOES_BR = ["brasileirao", "serie a", "serie b", "libertadores", "copa do brasil",
                  "sul-americana", "paulistao", "carioca"]

# Seleção e futebol internacional.
SELECAO = ["selecao brasileira", "selecao", "copa do mundo", "eliminatorias", "convocacao"]
INTERNACIONAL = [
    "champions", "premier league", "la liga", "real madrid", "barcelona", "manchester",
    "liverpool", "chelsea", "arsenal", "psg", "bayern", "juventus", "milan", "inter de milao",
    "neymar", "vinicius", "endrick", "messi", "cristiano", "mbappe", "haaland",
]

# Palavras que indicam futebol (filtro dos termos do Google Trends).
VOCAB_FUTEBOL = [
    "futebol", "gol", "jogo", "tecnico", "treinador", "rodada", "campeonato", "brasileirao",
    "libertadores", "sul-americana", "copa do brasil", "escalacao", "elenco", "contratacao",
    "reforco", "arbitragem", "var", "penalti", "cbf", "stjd", "torcida", "classificacao",
    "zagueiro", "atacante", "goleiro", "meia", "estadio", "clube", " x ", " vs ",
]

# Buscas no Google News (últimas 24 h). Cada uma vira uma consulta RSS.
BUSCAS_NEWS = [
    "Flamengo", "Corinthians", "São Paulo FC", "Palmeiras",
    "Brasileirão", "Libertadores", "Copa do Brasil", "Seleção Brasileira",
    "mercado da bola", "arbitragem VAR polêmica", "técnico demitido futebol",
    "Champions League", "brasileiros na Europa",
]

# Categorias editoriais: palavras-chave (sem acento) -> categoria.
CATEGORIAS = {
    "Mercado da bola": ["contrat", "reforco", "proposta", "negocia", "vendido",
                        "transfer", "emprestimo", "renova", "multa rescis", "sondado", "acerto"],
    "Técnico": ["tecnico", "treinador", "demit", "comissao tecnica", "novo tecnico", "cargo"],
    "Arbitragem e VAR": ["var ", "arbitr", "penalti", "expuls", "juiz", "impedimento", "anula"],
    "Polêmica e bastidor": ["polemic", "briga entre", "brigam", "bate-boca", "critica", "confusao", "protesto", "punicao",
                            "stjd", "denuncia", "racismo", "diretoria", "presidente", "eleicao",
                            "bastidor", "crise", "vaias"],
    "Lesão e desfalque": ["lesao", "machuc", "desfalque", "cirurgia", "departamento medico", "fora de"],
    "Seleção": ["selecao", "convoca", "eliminatorias", "copa do mundo"],
    "Jogo e resultado": ["vence ", "venceu", "empata", "empate", "perde", "derrota", "vitoria",
                         "goleia", "goleada", "classifica", "eliminad", "rodada", "placar", "virada"],
}

# Categorias com maior potencial de corte viral recebem bônus de aderência.
BONUS_VIRAL = {"Polêmica e bastidor": 0.25, "Arbitragem e VAR": 0.2, "Mercado da bola": 0.15,
               "Técnico": 0.15}

# Pesos da nota final (somam 1.0). Espelham o documento de estratégia.
PESOS = {"busca": 0.30, "aceleracao": 0.30, "midia": 0.20, "aderencia": 0.20}

TOP_EMAIL = 5      # pautas no e-mail
TOP_PAINEL = 15    # pautas no painel
