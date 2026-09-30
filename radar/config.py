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

# Apelidos que também são nomes de estado, cidade ou palavra comum. Só contam como clube
# quando a manchete tem vocabulário de futebol (evita "Bahia" em notícia de eleição).
APELIDOS_AMBIGUOS = {"bahia", "fortaleza", "ceara", "santos", "galo", "colorado", "sao paulo",
                     "juventude", "mirassol", "athletico", "sport recife"}

# Outros esportes dos mesmos clubes (vôlei, basquete...): manchetes com estas palavras saem.
# Casam no início da palavra: "volei" pega "vôlei" e "voleibol".
OUTROS_ESPORTES = ["volei", "supervolei", "superliga", "basquete", "nbb", "nba", "futsal", "handebol",
                   "sesc rj", "beach tennis", "beach soccer", "futebol de areia", "futebol americano", "nfl ",
                   "e-sports", "esports", "natacao", "remo ", "ufc", "mma ", "ginastica", "atletismo",
                   "polo aquatico", "judo", "skate"]

# Palavras típicas de espanhol: manchetes nessa língua saem do radar (canal é em português).
MARCAS_ESPANHOL = ["el", "los", "del", "con", "y", "hoy", "recibe", "partido", "futbol", "las", "ante"]

# Competições nacionais (aderência média mesmo sem clube citado).
COMPETICOES_BR = ["brasileirao", "serie a", "serie b", "libertadores", "copa do brasil",
                  "sul-americana", "paulistao", "carioca"]

# Seleção e futebol internacional.
# Seleção Brasileira. "selecao" sozinho só conta se a manchete também citar "brasil"
# (evita "Cabo Verde x Ruanda pelas Eliminatórias" virar pauta da Seleção).
SELECAO = ["selecao brasileira", "canarinho", "amarelinha"]
INTERNACIONAL = [
    "copa do mundo", "eliminatorias", "data fifa",
    "champions", "premier league", "la liga", "real madrid", "barcelona", "manchester",
    "liverpool", "chelsea", "arsenal", "psg", "bayern", "juventus", "milan", "inter de milao",
    "neymar", "vinicius", "endrick", "messi", "cristiano", "mbappe", "haaland",
]

# Palavras que indicam futebol (filtro dos termos do Google Trends).
VOCAB_FUTEBOL = [
    "futebol", "gol ", "gols", "golaco", "jogo", "tecnico", "treinador", "rodada", "campeonato", "brasileirao",
    "libertadores", "sul-americana", "copa do brasil", "escalac", "elenco", "contratac",
    "reforc", "arbitr", "var ", "penalti", "cbf", "stjd", "torcida", "classific",
    "zagueiro", "atacante", "goleiro", "meia ", "estadio", "clube", "partida", "classico",
    "placar", "amistoso", "selecao", "elenco", "titular", "artilheiro", "torcedor",
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
    "Finanças e gestão": ["divida", "parcela", "pagamento", "salario", "acordo com a uniao", "receita federal",
                          "balanco", "penhora", "patrocin", "saf ", "orcamento", "fazenda nacional",
                          "profut", "credor", "calote", "faturamento"],
    "Lesão e desfalque": ["lesao", "machuc", "desfalque", "cirurgia", "departamento medico", "fora de"],
    "Seleção": ["selecao brasileira", "canarinho", "convocacao da selecao", "convocados"],
    "Jogo e resultado": ["vence ", "venceu", "empata", "empate", "perde", "derrota", "vitoria",
                         "goleia", "goleada", "classifica", "eliminad", "rodada", "placar", "virada"],
}

# Categorias com maior potencial de corte viral recebem bônus de aderência.
BONUS_VIRAL = {"Finanças e gestão": 0.15, "Polêmica e bastidor": 0.25, "Arbitragem e VAR": 0.2, "Mercado da bola": 0.15,
               "Técnico": 0.15}

# Pesos da nota final (somam 1.0). Espelham o documento de estratégia.
# Sinal ausente (ex.: YouTube sem chave, ou tema fora do lote consultado) sai da conta
# e os demais pesos são redistribuídos proporcionalmente (sem YouTube: 30/30/20/20).
PESOS = {"busca": 0.24, "aceleracao": 0.24, "midia": 0.16, "aderencia": 0.16, "youtube": 0.20}

TOP_EMAIL = 5      # pautas no e-mail
TOP_PAINEL = 15    # pautas no painel


# ---- Agenda de jogos -----------------------------------------------------------
# ESPN (gratuita). Desde 29/09/2026 site.api.espn.com responde 403 para o GitHub Actions;
# site.web.api.espn.com funcionou em 30/09. O radar tenta um pedido por host e, se todos
# bloquearem, usa as buscas do Google como plano B.
ESPN_IDS = {"Flamengo": 819, "Corinthians": 874, "São Paulo": 2026, "Palmeiras": 2029}
ESPN_LIGAS = ["bra.1", "conmebol.libertadores", "conmebol.sudamericana", "bra.copa_do_brazil"]
ESPN_HOSTS = ["site.api.espn.com", "site.web.api.espn.com"]
# Plano B: "palmeiras x" no autocompletar do Google revela o próximo adversário ("palmeiras x ldu").
SEMENTES_JOGO = {"Flamengo": "flamengo x", "Corinthians": "corinthians x", "São Paulo": "são paulo x",
                 "Palmeiras": "palmeiras x"}

# ---- Buscas do torcedor (autocompletar do Google) --------------------------------
BUSCAS_TORCEDOR = ["flamengo", "corinthians", "são paulo fc", "palmeiras", "seleção brasileira",
                   "brasileirão"]
# Sementes genéricas: aparecem no painel, mas não mexem na nota (evita "brasileirão série b"
# casar com qualquer pauta que cite a Série A/B).
SEMENTES_SO_PAINEL = {"seleção brasileira", "brasileirão"}
NOMES_POR_EXECUCAO = 8   # nomes tirados das pautas do dia para consultar

# Palavras que não indicam assunto nas sugestões de busca ("flamengo jogo hoje" é genérico).
GENERICAS_BUSCA = set("""
jogo jogos hoje joga vivo assistir onde horario escalacao tabela classificacao noticias noticia
ultimas agora resultado placar proximo proximos ingresso ingressos elenco site oficial loja camisa
hino simbolo historia titulos escudo wallpaper futemax multicanais globo sofascore ontem amanha
x e de do da das dos fc sub feminino masculino ao
""".split())


# ---- Força no YouTube (YouTube Data API v3, chave gratuita) ------------------------
# Cada busca custa 100 unidades da cota diária de 10.000. O radar gasta no máximo
# YT_BUSCAS_DIA buscas por dia (contando execuções manuais) e reaproveita o resultado
# de uma mesma consulta no mesmo dia.
YT_BUSCAS_DIA = 20
YT_BUSCAS_POR_EXECUCAO = 12   # pautas do topo consultadas por execução
YT_HORAS = 48                 # janela de publicação dos vídeos

# ---- Raio-X semanal do canal (YouTube Analytics, só leitura) -----------------------
RAIOX_DIA_SEMANA = 0          # 0 = segunda-feira
RAIOX_DIAS = 90               # janela de vídeos analisados
RAIOX_MAX_VIDEOS = 40         # vídeos com análise individual (views nos 7 primeiros dias)
# Ajuste automático: cada categoria recebe um fator entre estes limites conforme o desempenho
# dos vídeos do canal sobre ela (precisa de pelo menos RAIOX_MIN_VIDEOS_CATEGORIA vídeos).
FATOR_CATEGORIA_MIN, FATOR_CATEGORIA_MAX = 0.85, 1.15
RAIOX_MIN_VIDEOS_CATEGORIA = 3

# Tipos de conteúdo do próprio canal (Raio-X). A ordem importa: vale o primeiro que casar.
# "confronto" = título no formato "Time X Time" (transmissão); "multitemas" = vários assuntos
# separados por "/" (resenha). Os demais casam por palavra (sem acento, minúsculas).
TIPOS_CONTEUDO = [
    ("Sai pro Jogo (programa)", ["sai pro jogo"]),
    ("Perguntas do público", ["vc pergunta", "voce pergunta", "toca e recebe", "perguntas", "respondemos"]),
    ("Pré-jogo", ["pre-jogo", "pre jogo", "esquenta", "aquecimento"]),
    ("Pós-jogo", ["pos-jogo", "pos jogo"]),
    ("React", ["react", "reagindo", "reacao"]),
    ("Transmissão de jogo", ["confronto"]),
    ("Resenha multitemas", ["multitemas"]),
]
# Tipos ligados a jogo: sem palavra de categoria no título, contam como "Jogo e resultado"
# no ajuste de pesos do radar.
TIPOS_DE_JOGO = {"Transmissão de jogo", "Pré-jogo", "Pós-jogo", "Sai pro Jogo (programa)"}

# ---- Alertas de tendência no YouTube ----------------------------------------------
# Um assunto vira alerta quando, nas últimas 48 h, tem vídeos com views por hora bem acima
# da média do futebol no YouTube (linha de base dos últimos 14 dias) E engajamento
# (curtidas + comentários / views) pelo menos na média, com ligação ao canal.
ALERTA_FATOR_VELOCIDADE = 3.0   # views/hora >= 3x a média
ALERTA_FATOR_ENGAJAMENTO = 1.0  # engajamento >= a média
ALERTA_MIN_VIEWS = 20_000       # o vídeo mais forte do assunto precisa ter pelo menos isto
ALERTA_MAX_POR_DIA = 3
ALERTA_REPETIR_APOS_DIAS = 3    # o mesmo assunto não é avisado de novo antes disso

# ---- Estimativa de monetização (30 dias) --------------------------------------------
# RPM = quanto o canal recebe a cada 1.000 views (já descontada a parte do YouTube), em reais.
# São faixas de referência para canais brasileiros de futebol e variam muito com época do ano,
# anunciantes e país do público. Troque pelo RPM real do canal (YouTube Studio > Receita)
# no próprio painel, aba Monetização.
RPM_REFERENCIA = {             # (pessimista, provável, otimista)
    "Vídeos longos": (2.0, 4.0, 8.0),
    "Lives": (1.5, 3.0, 6.0),
    "Shorts": (0.05, 0.15, 0.35),
}
# Programa de Parcerias do YouTube (monetização por anúncios).
YPP_INSCRITOS, YPP_HORAS_12M, YPP_SHORTS_90D = 1_000, 4_000, 10_000_000

# O canal já está no Programa de Parcerias (informado pelo dono). Os requisitos de entrada
# (4.000 h / 10 mi de views em Shorts) não se aplicam a quem já foi aprovado.
CANAL_MONETIZADO = True
