"""Ganchos de abertura com 5 técnicas: dado, conflito, contradição, pergunta aberta e aposta.

Os ganchos usam só fatos que estão nas manchetes do dia (números, nomes, adversário) e o que
o radar mediu (buscas no Google, views no YouTube). Nada é inventado: quando a frase precisa
de uma opinião do apresentador (o palpite de uma aposta), ela traz um espaço [ENTRE COLCHETES]
para ele completar.

Contra a repetição:
- cada pauta do dia começa por uma técnica diferente (a ordem gira a cada dia);
- cada técnica tem várias frases por tipo de assunto, escolhidas por sorteio fixo (tema + dia),
  e a mesma frase não aparece duas vezes no mesmo dia.
"""
from __future__ import annotations

import hashlib
import re

from . import config as C
from .buscas import nome_chave
from .score import entidades, norm

TECNICAS = ["dado", "conflito", "contradicao", "pergunta", "aposta"]
NOMES_TECNICA = {"dado": "Dado", "conflito": "Conflito", "contradicao": "Contradição",
                 "pergunta": "Pergunta aberta", "aposta": "Aposta"}

GRUPO = {"Lesão e desfalque": "lesao", "Mercado da bola": "mercado", "Técnico": "tecnico",
         "Arbitragem e VAR": "arbitragem", "Polêmica e bastidor": "polemica", "Finanças e gestão": "financas",
         "Seleção": "selecao", "Jogo e resultado": "jogo"}

# ---------------------------------------------------------------- fatos das manchetes

DINHEIRO = re.compile(r"R\$\s?\d[\d.,]*(?:\s?(?:milh(?:ão|ões|ao|oes)|bilh(?:ão|ões|ao|oes)|mil|mi|bi)\b)?", re.I)
PORCENTO = re.compile(r"\b\d+(?:[.,]\d+)?\s?%")
PLACAR = re.compile(r"\b\d{1,2}\s?x\s?\d{1,2}\b")
CONTAGEM = re.compile(r"\b(\d{1,3})\s+(jogos|gols|partidas|dias|semanas|meses|anos|vitórias|vitorias|derrotas|"
                      r"pontos|títulos|titulos|assistências|assistencias|desfalques|reforços|reforcos)\b", re.I)
EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️]")


def _limpa(texto: str) -> str:
    t = EMOJI.sub("", texto or "")
    t = re.sub(r"^\s*(ao vivo|urgente|ultima hora|última hora|vídeo|video)\s*[:\-|]\s*", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -|:")
    letras = [c for c in t if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) / len(letras) > 0.7:  # manchete toda em maiúsculas
        t = t.lower()
        t = t[:1].upper() + t[1:]
    return t


CONECTIVOS = {"que", "onde", "quando", "e", "mas", "porque", "pois", "enquanto", "se", "como", "após", "apos"}


def _clausula(titulo: str, ini: int, fim: int, max_palavras: int = 14) -> str:
    """Trecho da manchete em volta do número, cortado em pontuação e sem perder o número."""
    t = titulo
    esq = max(t.rfind(s, 0, ini) for s in (":", ";", "|", " - ", "?", "!", "."))
    dir_ = [p for p in (t.find(s, fim) for s in (";", "|", " - ", "?", "!", ",")) if p != -1]
    a, b = (esq + 1 if esq >= 0 else 0), (min(dir_) if dir_ else len(t))
    trecho = t[a:b].strip(" ,:;-")
    if len(trecho.split()) > max_palavras:
        virgula = t.rfind(",", a, ini)
        if virgula != -1:
            a = virgula + 1
        antes, depois = t[a:fim].split(), t[fim:b].split()
        antes = antes[-max_palavras:]
        trecho = " ".join(antes + depois[:max(0, max_palavras - len(antes))]).strip(" ,:;-")
    return trecho


def extrair_dado(titulos: list[str]) -> dict | None:
    """O número mais forte das manchetes, com o trecho em volta. Prioridade: R$ > % > contagem > placar.

    "limpo" diz se o trecho funciona sozinho como frase (não começa com "que", "e", "mas"...).
    """
    for padrao, peso in ((DINHEIRO, 4), (PORCENTO, 3), (CONTAGEM, 2), (PLACAR, 1)):
        for titulo in titulos:
            t = _limpa(titulo)
            for m in padrao.finditer(t):
                # "Rodada 19", "Sub-17", "Cartola 2026" e anos não são dados de pauta
                antes = t[max(0, m.start() - 8):m.start()].lower()
                if re.fullmatch(r"20\d\d", m.group(0)) or "sub" in antes or "rodada" in t[m.start():m.end() + 8].lower():
                    continue
                trecho = _clausula(t, m.start(), m.end())
                if len(trecho.split()) >= 3:
                    primeira = norm(trecho.split()[0])
                    return {"numero": m.group(0).strip(), "trecho": trecho, "peso": peso,
                            "limpo": primeira not in CONECTIVOS and trecho[:1].isupper()}
    return None


# Frases de rodapé que não fazem parte do fato ("; veja comparação", "Entenda").
JA_JOGOU = re.compile(r"\b(vence|venceu|goleia|goleou|empata|empatou|perde|perdeu|bate|derrota|"
                      r"classificad[oa]s?|eliminad[oa]s?|elimina|avança|avanca)\b", re.I)
RABOS = re.compile(r"[;:,.\-–|]\s*(veja|entenda|saiba|confira|assista|ouça|leia)\b.*$|\s+(entenda|veja)\s*$", re.I)


def extrair_fato(titulos: list[str], alvo_chaves: list[str], referencia: str = "") -> str | None:
    """A manchete mais curta e direta que cita o assunto, para abrir o gancho com o fato.

    Entre as que citam o clube/protagonista, vence a que mais se parece com o título do tema.
    """
    ref = {w for w in norm(referencia).split() if len(w) >= 4}
    candidatos = []
    for titulo in titulos:
        t = RABOS.sub("", _limpa(titulo)).strip(" ,;:-|")
        t = re.sub(r"^\s*\w+(?: \w+)?!\s+", "", t)  # "Classificados! Flamengo vence..."
        rotulo = re.match(r"^([^:|]{1,25})[:|]\s+", t)
        if rotulo and len(rotulo.group(1).split()) <= 3:  # "Feminino: ...", "Exclusivo | ..."
            t = t[rotulo.end():]
        for sep in (" | ", ": ", "; ", " - "):
            if sep not in t:
                continue
            pedaco = t.split(sep)[0].strip()
            if len(pedaco.split()) >= 5:
                t = pedaco
                break
        t = t.rstrip(" .!")
        if t.endswith("?") or not 5 <= len(t.split()) <= 16:
            continue
        cita = any(norm(k) in norm(t) for k in alvo_chaves if k)
        parecida = len(ref & {w for w in norm(t).split() if len(w) >= 4})
        candidatos.append((not cita, -parecida, len(t.split()), t))
    if not candidatos:
        return None
    return min(candidatos)[-1]


def _adversario(titulos: list[str], clube: str | None) -> str | None:
    for titulo in titulos:
        e = entidades(titulo)
        outros = [c for c in e["foco"] + e["br"] if c != clube]
        m = re.search(r"([A-ZÀ-Ú][\wÀ-ú\-]+(?: [A-ZÀ-Ú][\wÀ-ú\-]+)?) x ([A-ZÀ-Ú][\wÀ-ú\-]+(?: [A-ZÀ-Ú][\wÀ-ú\-]+)?)", titulo)
        if m and clube:
            a, b = m.group(1), m.group(2)
            if norm(clube) in norm(a):
                return b
            if norm(clube) in norm(b):
                return a
        if outros:
            return outros[0]
    return None


# ---------------------------------------------------------------- frases

def _artigos(clube: str | None, selecao: bool) -> dict:
    if clube:
        return {"alvo": clube, "o_alvo": f"o {clube}", "do_alvo": f"do {clube}", "no_alvo": f"no {clube}",
                "para_alvo": f"para o {clube}", "ALVO": clube.upper()}
    if selecao:
        return {"alvo": "Seleção", "o_alvo": "a Seleção", "do_alvo": "da Seleção", "no_alvo": "na Seleção",
                "para_alvo": "para a Seleção", "ALVO": "SELEÇÃO"}
    return {"do_alvo": "do futebol brasileiro", "no_alvo": "no futebol brasileiro", "para_alvo": "para o seu time"}


# Campos: {fato} = a manchete mais direta do tema; {nome} = protagonista (jogador/técnico);
# {adv} = adversário; {dado}/{num} = número da manchete; {views}, {busca}, {trafego} = o que o radar mediu.
# Maiúscula no nome do campo ({Fato}, {O_alvo}) = valor com inicial maiúscula.
# Uma frase só entra se todos os campos dela existirem. Uma tupla (frase, regex) só entra se a regex
# aparecer nas manchetes: assim "corte" só aparece quando houve corte, "cirurgia" quando houve cirurgia.
FRASES = {
    "dado": {
        "_com_dado": ["{Dado}. Guarda esse número, porque ele muda a conversa sobre {o_alvo}.",
                      "{Dado}. Parece só um número, mas ele vai pesar nos próximos meses {do_alvo}.",
                      "{Dado}. Quase ninguém fez a conta do que isso significa {para_alvo}."],
        "_num": ["{Num}. Esse é o número da semana {no_alvo}, e eu vou te mostrar por quê.",
                 "{Num}. Grava esse número: ele explica boa parte do que está acontecendo {no_alvo}."],
        "_youtube": ["{Views} em dois dias só sobre esse assunto. Eu vou direto no ponto que ficou de fora.",
                     "{Views} em 48 horas. Todo mundo falou disso; quase ninguém explicou o principal."],
        "_busca": ["O torcedor está digitando “{busca}” no Google agora. A resposta não é tão simples.",
                   "“{busca}”: é isso que o torcedor está pesquisando hoje. Eu vou responder sem enrolação."],
        "_google": ["Mais de {trafego} buscas no Google hoje. O motivo vai além da manchete."],
    },
    "conflito": {
        "resultado": ["{Fato}. Quem venceu comemora; quem perdeu tem uma conta para acertar.",
                      "{Fato}. Dentro de campo acabou. Fora dele, a discussão está só começando."],
        "lesao": ["{O_alvo} sem {nome}: o técnico vai ter que escolher entre improvisar ou mudar o time.",
                  "De um lado, {o_alvo} precisando de resultado. Do outro, o departamento médico pedindo calma com {nome}.",
                  "{Fato}. Agora o técnico tem que escolher: improvisar ou mudar o time inteiro."],
        "mercado": ["{O_alvo} quer, mas do outro lado alguém está segurando. Essa queda de braço vai ter um perdedor.",
                    "{Fato}. Torcida empolgada de um lado, diretoria fazendo conta do outro.",
                    "{Fato}. Nessa negociação, alguém vai sair perdendo."],
        "tecnico": ["Diretoria de um lado, elenco do outro, e no meio um técnico que precisa de resultado já.",
                    "{Fato}. O técnico {do_alvo} está contra o relógio: cada jogo agora é uma prova."],
        "arbitragem": ["{O_alvo} contra a arbitragem: alguém está errado nesse lance, e eu vou mostrar quem.",
                       "{Fato}. Juiz de um lado, {o_alvo} do outro: a imagem vai mostrar quem tem razão."],
        "polemica": [("{Fato}. Diretoria de um lado, torcida do outro, e quem perde é sempre o time.", r"pol[êe]mic|briga|crise|confus|cr[íi]tic|protest|racis|puni|den[úu]nci|amea[çc]|vaia|cobran"),
                     ("{Fato}. Tem gente {no_alvo} puxando para lados opostos, e essa conta chega no campo.", r"pol[êe]mic|briga|crise|confus|cr[íi]tic|protest|racis|puni|den[úu]nci|amea[çc]|vaia|cobran")],
        "financas": ["{Fato}. Dinheiro de um lado, time do outro: alguma coisa vai ter que ceder.",
                     "{Fato}. Nessa conta, tem quem ganha e tem quem paga, e não é a mesma pessoa."],
        "selecao": [("Sem {nome}, a briga por uma vaga na Seleção esquentou. Quem entra?", r"cortad|corte|fora|desfalc"),
                    ("Clube de um lado, Seleção do outro: quem paga a conta pela lesão de {nome}?", r"les[ãa]o|edema|fratura|cortad"),
                    "{Fato}. Clube e Seleção puxando para lados diferentes: quem tem razão?"],
        "jogo": ["{Alvo} x {Adv}: um precisa vencer, o outro não pode perder.",
                 "{Alvo} contra {Adv} vale mais do que três pontos, e os dois sabem disso."],
        "geral": ["{Fato}. Tem gente ganhando e gente perdendo com isso, e eu vou dizer quem.",
                  "{Fato}. Por trás disso, tem dois lados que não querem a mesma coisa.",
                  "{Fato}. Nem todo mundo {no_alvo} vai gostar disso, e eu vou explicar por quê."],
    },
    "contradicao": {
        "resultado": ["{Fato}. O placar diz uma coisa. O jogo, visto de perto, diz outra.",
                      "{Fato}. Todo mundo vai olhar o resultado; eu vou mostrar o que ele esconde."],
        "_com_dado": ["Todo clube fala em {palavra}. {Dado}. Esse número conta outra história.",
                      "{Num}. No discurso, {palavra}. Na prática, essa conta não fecha."],
        "lesao": ["Todo mundo diz que sem {nome} {o_alvo} afunda. Eu não tenho tanta certeza, e vou te mostrar por quê.",
                  "{Fato}. Parece só mais um desfalque. Não é: muda o jeito do time jogar.",
                  "{Fato}. Todo mundo está olhando para quem sai. O problema está em quem entra."],
        "mercado": ["{Fato}. Parece um grande negócio. Olhando de perto, não é bem assim.",
                    "Todo mundo está comemorando essa negociação {do_alvo}. Eu vejo um risco que ninguém está comentando."],
        "tecnico": ["Todo mundo culpa o técnico. Eu acho que o problema {do_alvo} está em outro lugar.",
                    "{Fato}. O técnico parece garantido no cargo. Os bastidores dizem outra coisa."],
        "arbitragem": ["Todo mundo viu o mesmo lance e cada um enxergou uma coisa. A regra é mais clara do que parece.",
                       "{Fato}. Muita gente está reclamando da arbitragem, mas a regra pode estar do outro lado."],
        "polemica": [("{Fato}. Era para ser uma decisão simples. Virou a maior confusão da semana.", r"pol[êe]mic|briga|crise|confus|cr[íi]tic|protest|racis|puni|den[úu]nci|amea[çc]|vaia|cobran"),
                     ("Dizem que está tudo em paz {no_alvo}. O que acontece nos bastidores mostra o contrário.", r"pol[êe]mic|briga|crise|confus|cr[íi]tic|protest|racis|puni|den[úu]nci|amea[çc]|vaia|cobran")],
        "financas": ["{Fato}. Parece só uma questão de dinheiro. Não é: isso chega no campo.",
                     "{Fato}. A manchete conta uma parte. A outra parte está nos números."],
        "selecao": [("{Fato}. Parece um corte sem importância, mas pode mudar a próxima convocação inteira.", r"cortad|corte"),
                    ("{Fato}. Era para ser só mais um compromisso da Seleção. Virou dor de cabeça.", r"amistoso|les[ãa]o|cortad|desfalc"),
                    "{Fato}. Todo mundo está olhando para um lado; o que importa para a Seleção está do outro."],
        "jogo": ["{Alvo} x {Adv} parece um jogo com dono. É exatamente aí que mora o perigo.",
                 "{Fato}. Parece que está tudo resolvido. No futebol, quase nunca está."],
        "geral": ["{Fato}. Todo mundo leu a manchete; quase ninguém leu o que está por trás.",
                  "{Fato}. A leitura óbvia é uma. A que importa é outra.",
                  "{Fato}. Parece notícia pequena. Não é.",
                  "{Fato}. Todo mundo vai falar do óbvio; eu vou falar do que ninguém percebeu."],
    },
    "pergunta": {
        "resultado": ["{Fato}. O que esse resultado muda daqui para frente?",
                      "{Fato}. Foi mérito de quem venceu ou erro de quem perdeu?"],
        "lesao": ["Sem {nome}, quem segura {o_alvo} nos próximos jogos?",
                  "Quanto vale {nome} para {o_alvo}? A resposta está nos números.",
                  "{Fato}. Quem entra no lugar, e o time aguenta?",
                  "{Fato}. O elenco {do_alvo} tem reposição à altura?"],
        "mercado": ["{Fato}. Se isso sair, quem perde espaço no elenco?",
                    "Esse negócio vale a pena para {o_alvo}? Pensa bem antes de responder."],
        "tecnico": ["Quanto tempo o técnico ainda tem {no_alvo}?",
                    "Se o técnico {do_alvo} cair amanhã, quem você colocaria no lugar?"],
        "arbitragem": ["Se fosse a favor do seu time, você estaria reclamando desse lance?",
                       "{Fato}. Foi ou não foi? Responde nos comentários antes de ver a minha análise."],
        "polemica": [("{Fato}. Quem ganha com essa confusão? Pensa bem antes de responder.", r"pol[êe]mic|briga|crise|confus|cr[íi]tic|protest|racis|puni|den[úu]nci|amea[çc]|vaia|cobran"),
                     "Até onde essa história {do_alvo} vai chegar?"],
        "financas": [("{Fato}. De onde vai sair esse dinheiro?", r"R\$|milh|d[íi]vida|d[ée]ficit|pagament|indeniza"),
                     "{Fato}. Quem paga essa conta no fim: a diretoria ou o torcedor?"],
        "selecao": [("Quem merece a vaga de {nome} na Seleção?", r"cortad|corte|fora|desfalc"),
                    "Se você fosse o técnico da Seleção, quem chamaria agora?"],
        "jogo": ["O que {o_alvo} precisa fazer para vencer esse jogo?",
                 "{Alvo} x {Adv}: qual é o detalhe que vai decidir?"],
        "geral": ["{Fato}. E agora: o que muda {para_alvo}?",
                  "{Fato}. Isso é bom ou ruim {para_alvo}? Responde antes de ver a minha análise.",
                  "{Fato}. A pergunta que ninguém está fazendo: quem sai ganhando com isso?",
                  "{Fato}. Foi certo ou errado? Comenta antes de ver o vídeo inteiro."],
    },
    "aposta": {
        "resultado": ["{Fato}. Minha aposta: depois desse jogo, [SEU PALPITE]. Me cobra depois.",
                      "{Fato}. Eu aposto que esse resultado vai pesar lá na frente. Você concorda?"],
        "lesao": ["Minha aposta: {o_alvo} vai sentir a falta de {nome} já no próximo jogo. Comenta a sua e me cobra depois.",
                  "Eu aposto que [SEU PALPITE: QUEM ENTRA] vai ganhar a vaga de {nome}. Você concorda?",
                  "{Fato}. Meu palpite de quanto tempo esse desfalque vai durar: [SEU PALPITE]. Qual é o seu?"],
        "mercado": ["Eu aposto: esse negócio [SAI / NÃO SAI] até o fim do mês. Se eu errar, pode me cobrar nos comentários.",
                    "Minha aposta é que essa novela {do_alvo} termina [SEU PALPITE]. Guarda esse vídeo."],
        "tecnico": ["Minha aposta: essa história do técnico {do_alvo} termina [SEU PALPITE]. Volta aqui e me cobra.",
                    "Eu aposto que [SEU PALPITE] até a próxima rodada. Qual é a sua?"],
        "arbitragem": ["Aposto que ninguém vai ser punido por esse lance. Você aposta em quê?",
                       "Minha aposta: esse lance ainda vai ser assunto a semana inteira. Comenta o seu palpite."],
        "polemica": [("Minha aposta: essa confusão {do_alvo} ainda vai ter mais um capítulo esta semana. Guarda esse vídeo.", r"pol[êe]mic|briga|crise|confus|cr[íi]tic|protest|racis|puni|den[úu]nci|amea[çc]|vaia|cobran"),
                     "{Fato}. Eu aposto que [SEU PALPITE]. Se eu acertar, você me deve um like."],
        "financas": ["{Fato}. Minha aposta: [SEU PALPITE]. Volta aqui daqui a um mês e me cobra.",
                     "Eu aposto que essa conta chega no elenco {do_alvo} ainda nesta temporada. Você aposta em quê?"],
        "selecao": ["Minha aposta para a vaga de {nome}: [SEU PALPITE]. Qual é a sua?",
                    "Eu aposto que a próxima lista da Seleção vai ter [SEU PALPITE]. Me cobra depois."],
        "jogo": ["Meu palpite para {Alvo} x {Adv}: [SEU PLACAR]. Deixa o seu nos comentários.",
                 "Eu aposto que {o_alvo} [VENCE / EMPATA / PERDE], e explico por quê. Qual é o seu placar?"],
        "geral": ["{Fato}. Minha aposta: [SEU PALPITE]. Me cobra daqui a uma semana.",
                  "{Fato}. Eu aposto que essa história ainda ganha capítulo novo esta semana. Guarda esse vídeo.",
                  "{Fato}. Aposto que pouca gente entendeu o tamanho disso. Me cobra no fim da temporada.",
                  "{Fato}. Eu já tenho meu palpite de como isso termina: [SEU PALPITE]. E você?"],
    },
}

# Palavras que confirmam o tipo de assunto nas manchetes. Sem elas, o gancho usa as frases gerais
# (que partem do fato), para não falar de "negociação" numa notícia que é resultado de jogo.
CONFIRMA_GRUPO = {
    "lesao": r"les[ãa]o|lesionad|desfalc|machuc|cirurgi|fratur|edema|dores|\bdor\b|departamento m[ée]dico|recupera|vetad",
    "mercado": r"contrata[çcrd]|negocia|proposta|renov|transfer|empr[ée]st|sond|refor[çc]o|multa|janela|\bvenda d[eo]",
    "tecnico": r"t[ée]cnico|treinador|demiss|demit|comando|cargo",
    "arbitragem": r"[áa]rbitr|juiz|\bvar\b|p[êe]nalti|impedimento|expuls|cart[ãa]o",
    "financas": r"R\$|milh|d[íi]vida|d[ée]ficit|receita|or[çc]amento|balan[çc]o|patroc|bets?\b|saf\b|indeniza|pagament",
}

# Palavra do discurso de clube, para a contradição com o número da manchete.
PALAVRA = {"financas": "equilíbrio", "mercado": "planejamento", "tecnico": "projeto", "polemica": "união"}

# Texto da thumb por técnica: a primeira opção que tiver os campos vence.
THUMB = {
    "dado": {"_com_dado": ["{NUM}"], "_num": ["{NUM}"], "_youtube": ["TODO MUNDO VIU"],
             "_busca": ["VOCÊ PESQUISOU"], "_google": ["TODO MUNDO BUSCOU"]},
    "conflito": {"jogo": ["{ALVO} x {ADV}"], "resultado": ["{ALVO} x {ADV}"], "lesao": ["SEM {NOME}?"], "selecao": ["SEM {NOME}?"],
                 "_adv": ["{ALVO} x {ADV}"], "geral": ["QUEM TEM RAZÃO?"]},
    "contradicao": ["NÃO É BEM ASSIM"],
    "pergunta": ["E AGORA, {ALVO}?", "E AGORA?"],
    "aposta": ["MEU PALPITE"],
}


def _preencher(frase: str, campos: dict) -> str | None:
    def troca(m):
        k = m.group(1)
        v = campos.get(k)
        if v is None:
            v = campos.get(k[0].lower() + k[1:])
        if v is None or v == "":
            raise KeyError(k)
        v = str(v)
        return v[:1].upper() + v[1:] if k[0].isupper() else v
    try:
        texto = re.sub(r"\{(\w+)\}", troca, frase)
    except KeyError:
        return None
    return texto[:1].upper() + texto[1:]


def _sorteio(*partes) -> int:
    return int(hashlib.sha1("|".join(map(str, partes)).encode()).hexdigest()[:8], 16)


def _views(n: int) -> str:
    if n >= 1_000_000:
        m = f"{n / 1_000_000:.1f}".replace(".", ",").replace(",0", "")
        return f"{m} {'milhão' if n < 2_000_000 else 'milhões'} de visualizações"
    if n >= 1000:
        return f"{round(n / 1000):,} mil visualizações".replace(",", ".")
    return f"{n} visualizações"


# Países e palavras que aparecem com maiúscula nas manchetes mas não são o protagonista.
NAO_NOMES = {"uruguai", "argentina", "india", "portugal", "espanha", "franca", "italia", "inglaterra", "alemanha",
             "colombia", "chile", "paraguai", "peru", "equador", "bolivia", "venezuela", "japao", "eua", "mexico",
             "cartola", "premier", "league", "champions", "europa", "mundial", "fifa", "cbf", "stf", "governo"}


BUSCA_GENERICA = {"brasileiro", "brasileirao", "serie", "campeonato", "futebol", "jogo", "jogos", "hoje", "onde",
                  "assistir", "vivo", "noticias", "tabela", "classificacao", "resultado", "horario"}


def _busca_relevante(busca: str, titulos: list[str], clubes: set[str]) -> bool:
    """A busca do torcedor só entra se tiver uma palavra do assunto além do nome do clube."""
    texto = norm(" ".join(titulos))
    for palavra in norm(busca).split():
        if (len(palavra) >= 4 and palavra not in clubes and palavra not in C.GENERICAS_BUSCA
                and palavra not in BUSCA_GENERICA and palavra in texto):
            return True
    return False


def campos_do_tema(tema: dict) -> dict:
    titulos = [m["titulo"] for m in tema.get("manchetes", [])] + [tema["tema"]]
    clube = (tema.get("clubes") or [None])[0]
    selecao = tema.get("categoria") == "Seleção" or entidades(" ".join(titulos))["selecao"]
    campos = _artigos(clube, selecao and not clube)
    grupo = GRUPO.get(tema.get("categoria"), "geral")
    confirma = CONFIRMA_GRUPO.get(grupo)
    if confirma and not re.search(confirma, " ".join(titulos), re.I):
        grupo = "geral"  # a categoria veio da pontuação; as frases específicas exigem a palavra na manchete
    if grupo == "jogo" and any(PLACAR.search(x) or JA_JOGOU.search(x) for x in titulos):
        grupo = "resultado"  # jogo que já aconteceu: nada de "parece que está tudo resolvido"
    clubes_n = {norm(a) for al in list(C.CLUBES_FOCO.values()) + list(C.CLUBES_BR.values()) for a in al}
    nome = nome_chave(titulos)
    if nome and norm(nome) not in clubes_n | NAO_NOMES | {"selecao", "brasil"}:
        campos["nome"] = nome
        campos["NOME"] = nome.upper()
    adv = _adversario(titulos, clube)
    if adv and clube and norm(adv) != norm(clube):
        campos["adv"] = adv
        campos["ADV"] = adv.upper()
    fato = extrair_fato(titulos, [clube, campos.get("nome"), "Seleção"], tema["tema"])
    if fato:
        campos["fato"] = fato
    dado = extrair_dado(titulos)
    if dado:
        campos.update({"num": dado["numero"], "NUM": dado["numero"].upper(), "_peso": dado["peso"]})
        if dado["limpo"]:
            campos["dado"] = dado["trecho"]
    if grupo in PALAVRA:
        campos["palavra"] = PALAVRA[grupo]
    y = tema.get("youtube") or {}
    if y.get("n_videos", 0) >= 3 and y.get("views", 0) >= 10_000:
        campos["views"] = _views(y["views"])
    if tema.get("busca_torcedor") and _busca_relevante(tema["busca_torcedor"], titulos, clubes_n):
        campos["busca"] = tema["busca_torcedor"]
    if (tema.get("trafego_google") or 0) >= 10_000:
        campos["trafego"] = f"{tema['trafego_google']:,}".replace(",", ".")
    campos["_grupo"] = grupo
    campos["_texto"] = " ".join(titulos)
    return campos


def _candidatas(lista, campos: dict) -> list[tuple[str, str]]:
    saida = []
    for item in lista:
        frase, exige = (item if isinstance(item, tuple) else (item, None))
        if exige and not re.search(exige, campos["_texto"], re.I):
            continue
        texto = _preencher(frase, campos)
        if texto:
            saida.append((frase, texto))
    return saida


def _fontes_dado(campos: dict) -> list[str]:
    fontes = []
    if "dado" in campos and campos.get("_peso", 0) >= 2:
        fontes.append("_com_dado")
    if "num" in campos:
        fontes.append("_num")
    return fontes + ["_youtube", "_busca", "_google"]


def opcoes(tema: dict, dia: str, usadas: set[str], campos: dict | None = None) -> dict[str, tuple[str, str, str | None]]:
    """Um gancho por técnica: {técnica: (frase-modelo, texto, thumb)}.

    Preferência: frase do tipo de assunto ainda não usada no dia > frase geral não usada > repetida.
    """
    campos = campos or campos_do_tema(tema)
    grupo = campos["_grupo"]
    saida = {}
    for tec in TECNICAS:
        thumb_tec = None
        if tec == "dado":
            camadas = []
            for fonte in _fontes_dado(campos):
                prontas = _candidatas(FRASES["dado"][fonte], campos)
                if prontas:
                    camadas, thumb_tec = [prontas], THUMB["dado"][fonte]
                    break
        else:
            especificas = FRASES[tec].get(grupo, []) if grupo != "geral" else []
            if tec == "contradicao" and campos.get("_peso", 0) >= 3 and "palavra" in campos:
                especificas = FRASES[tec]["_com_dado"] + especificas
            camadas = [_candidatas(especificas, campos), _candidatas(FRASES[tec]["geral"], campos)]
            thumb_tec = THUMB[tec]
            if isinstance(thumb_tec, dict):  # conflito: depende do assunto
                thumb_tec = thumb_tec.get(grupo, []) + thumb_tec["geral"]
        livres = [c for camada in camadas for c in camada if c[0] not in usadas]
        todas = [c for camada in camadas for c in camada]
        # Frases do tipo de assunto primeiro: só cai para as gerais quando as específicas acabaram.
        if livres:
            primeira_camada = next(cam for cam in camadas if any(c[0] not in usadas for c in cam))
            pool = [c for c in primeira_camada if c[0] not in usadas]
        elif todas:
            pool = todas
        else:
            continue
        # Mesmo texto já usado hoje (ex.: a mesma busca em dois temas parecidos) vai para o fim da fila.
        pool = [c for c in pool if c[1] not in usadas] or pool
        f, texto = pool[_sorteio(tema["tema"], dia, tec) % len(pool)]
        if tec == "conflito" and "adv" in campos and campos["adv"] in texto:
            thumb_tec = ["{ALVO} x {ADV}"]
        tb = next((t for t in (_preencher(x, campos) for x in thumb_tec) if t), None) if thumb_tec else None
        saida[tec] = (f, texto, tb)
    return saida


def _escolher_principais(lista_ops: list[dict], ordens: list[list[str]]) -> list[str | None]:
    """Técnica de abertura de cada pauta: a da vez na rotação, sem repetir enquanto houver outra livre.

    Quando uma pauta não tem material para nenhuma técnica livre, tenta trocar com uma pauta anterior
    que tenha (um passo de "caminho de aumento", suficiente para 5 técnicas).
    """
    principais: list[str | None] = []
    for i, ops in enumerate(lista_ops):
        if not ops:
            principais.append(None)
            continue
        usadas = set(p for p in principais if p)
        livres = [tec for tec in ordens[i] if tec in ops and tec not in usadas]
        if livres:
            principais.append(livres[0])
            continue
        escolha = None
        if len(usadas) < len(TECNICAS):
            for j, pj in enumerate(principais):
                if pj and pj in ops:
                    alternativa = next((tec for tec in ordens[j] if tec in lista_ops[j] and tec not in usadas), None)
                    if alternativa:
                        principais[j], escolha = alternativa, pj
                        break
        if escolha is None:  # todas já usadas: a menos repetida, na ordem da rotação
            escolha = min((tec for tec in ordens[i] if tec in ops), key=lambda tec: principais.count(tec))
        principais.append(escolha)
    return principais


def aplicar(temas: list[dict], dia: str) -> None:
    """Troca o gancho de cada pauta pelos ganchos por técnica, girando a técnica principal."""
    usadas: set[str] = set()
    inicio = _sorteio(dia) % len(TECNICAS)
    lista_ops, ordens = [], []
    for i, t in enumerate(temas):
        ops = opcoes(t, dia, usadas)
        usadas.update(f for f, _, _ in ops.values())
        usadas.update(tx for _, tx, _ in ops.values())
        lista_ops.append(ops)
        ordens.append(TECNICAS[(inicio + i) % 5:] + TECNICAS[:(inicio + i) % 5])
    for t, ops, ordem, principal in zip(temas, lista_ops, ordens, _escolher_principais(lista_ops, ordens)):
        if not principal:
            continue
        s = t["sugestao"]
        s["gancho"] = ops[principal][1]
        s["tecnica"] = NOMES_TECNICA[principal]
        s["ganchos"] = [{"tecnica": NOMES_TECNICA[tec], "texto": ops[tec][1], "thumb": ops[tec][2]}
                        for tec in [principal] + [x for x in ordem if x != principal] if tec in ops]
        if ops[principal][2]:
            s["titulo_thumb"] = ops[principal][2]


def gancho_jogo(casa: str, fora: str, dia: str, i: int) -> tuple[str, str, str]:
    """Gancho de pré-jogo variado: (gancho, thumb, técnica)."""
    opcoes_j = [
        (f"{casa} x {fora}: qual é o detalhe que vai decidir esse jogo?", "QUEM LEVA?", "pergunta"),
        (f"Meu palpite para {casa} x {fora}: [SEU PLACAR]. Deixa o seu nos comentários.", "MEU PALPITE", "aposta"),
        (f"{casa} x {fora}: um precisa vencer, o outro não pode perder.", f"{casa} x {fora}".upper(), "conflito"),
        (f"{casa} x {fora} parece um jogo com dono. É exatamente aí que mora o perigo.", "ZEBRA À VISTA?", "contradicao"),
        (f"Se você fosse o técnico em {casa} x {fora}, quem escalaria?", "SUA ESCALAÇÃO", "pergunta"),
    ]
    g, tb, tec = opcoes_j[(_sorteio(dia) + i) % len(opcoes_j)]
    return g, tb, NOMES_TECNICA[tec]
