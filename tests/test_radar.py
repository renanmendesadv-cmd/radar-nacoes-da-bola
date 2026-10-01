import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from radar import agenda, collect, score  # noqa: E402
from tests import make_fixtures  # noqa: E402

make_fixtures.gerar()
F = RAIZ / "tests" / "fixtures"
AGORA = make_fixtures.AGORA


def bruto():
    termos = collect.parse_trends((F / "trends.xml").read_text("utf-8"))
    noticias = []
    for f in (F / "news").glob("*.xml"):
        noticias += collect.parse_news(f.read_text("utf-8"), f.stem.replace("_", " "))
    videos = collect.parse_channel_feed((F / "channel.xml").read_text("utf-8"))
    return {"termos": termos, "noticias": noticias, "videos": videos}


def test_parsers():
    b = bruto()
    assert b["termos"][0]["trafego"] == 50_000
    assert b["termos"][0]["noticias"][0]["titulo"].startswith("Flamengo")
    assert all(" - Portal" not in n["titulo"] for n in b["noticias"])
    assert len(b["videos"]) == 2


def test_entidades_sem_falso_positivo():
    assert score.entidades("Vitória importante na rodada")["br"] == []
    assert score.entidades("Flamengo e Palmeiras empatam")["foco"] == ["Flamengo", "Palmeiras"]


def test_pontuacao_e_agrupamento():
    temas = score.pontuar(bruto(), {}, AGORA)
    nomes = [t["tema"] for t in temas]
    # Termo fora do futebol é descartado
    assert not any("Frente fria" in n for n in nomes)
    # As 4 manchetes da negociação do Flamengo viram um único tema
    fla = [t for t in temas if "Flamengo" in t["clubes"] and t["categoria"] == "Mercado da bola"]
    assert len(fla) == 1 and fla[0]["n_manchetes"] >= 4
    # Tema com busca no Google + clube foco fica no topo
    assert temas[0]["foco"] and temas[0]["trafego_google"] > 0
    # Tema já coberto pelo canal é sinalizado
    spfc = [t for t in temas if "São Paulo" in t["clubes"]]
    assert spfc and spfc[0]["ja_coberto"]
    for t in temas:
        assert 0 <= t["nota"] <= 100


def test_historico_reduz_aceleracao():
    b = bruto()
    t1 = score.pontuar(b, {}, AGORA)
    hist = {"2026-09-23": {t["assinatura"]: 20 for t in t1}}
    t2 = score.pontuar(b, hist, AGORA)
    a1 = {t["tema"]: t["sinais"]["aceleracao"] for t in t1}
    a2 = {t["tema"]: t["sinais"]["aceleracao"] for t in t2}
    assert all(a2[k] < a1[k] for k in a1)


def test_main_ponta_a_ponta(tmp_path):
    env = dict(os.environ, FIXTURES_DIR=str(F), AGORA=AGORA.isoformat(), DRY_RUN="1", OUT_DIR=str(tmp_path))
    r = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    dados = json.loads((tmp_path / "docs" / "data.json").read_text("utf-8"))
    assert dados["temas"] and dados["termos_futebol"]
    html = (tmp_path / "data" / "ultimo-email.html").read_text("utf-8")
    assert "Gancho" in html and "Grave primeiro" in html


def test_ruido_real_da_primeira_execucao():
    # Casos vistos na 1ª execução real (24/09/2026)
    assert not score.eh_futebol("Quaest: intenções de voto para o Senado na Bahia")
    assert score.entidades("Bahia vence o clássico e sobe na tabela")["br"] == ["Bahia"]
    assert score.espanhol("Con James a bordo, Nacional recibe a Millonarios")
    assert not score.espanhol("Flamengo recebe o Palmeiras no Maracanã")
    assert score.categoria("Golpe no governo") == "Notícia do dia"


def test_sem_efeito_corrente():
    base = [
        "Flamengo vence o Bahia no Maracanã",
        "Flamengo e Corinthians disputam final feminina",
        "Ingressos para final feminina entre Corinthians e Flamengo",
        "Corinthians atrasa parcelas de acordo com a União",
        "Palmeiras anuncia venda de ingressos para o clássico",
    ]
    noticias = [{"titulo": t, "fonte": f"F{i}", "url": "", "publicado": None, "busca": "x"}
                for i, t in enumerate(base)]
    grupos = score.agrupar(noticias)
    assert max(len(g["itens"]) for g in grupos) <= 2


def test_aderencia_rebaixa_tema_sem_ligacao():
    agora = AGORA
    ruido = {"termos": [{"termo": "costa rica x curacao", "trafego": 5000, "publicado": agora.isoformat(),
                         "noticias": [{"titulo": "Costa Rica x Curaçao: onde assistir ao vivo", "url": "", "fonte": "A"},
                                      {"titulo": "Costa Rica x Curaçao: escalações", "url": "", "fonte": "B"}]}],
             "noticias": [], "videos": []}
    b = bruto()
    b["termos"] += ruido["termos"]
    temas = score.pontuar(b, {}, agora)
    nomes = [t["tema"] for t in temas]
    costa = [i for i, n in enumerate(nomes) if "Costa Rica" in n]
    assert not costa or costa[0] >= 3  # some ou fica atrás dos temas dos clubes do canal


def test_financas_e_reality_show():
    assert score.categoria("Corinthians atrasa parcelas de acordo com a União") == "Finanças e gestão"
    assert not score.eh_futebol("Enquete A Fazenda: Ana x João")


def test_outros_esportes_e_termos():
    assert score.outro_esporte("GANHAR FLA-FLU É NORMAL! O Sesc RJ Flamengo venceu o Fluminense na Copa SuperVôlei")
    assert not score.outro_esporte("Flamengo vence o Fluminense no Maracanã")
    celeb = {"termo": "solange gomes", "noticias": [{"titulo": "Solange Gomes fala sobre reality"},
                                                   {"titulo": "Solange Gomes posta foto"}]}
    assert not score.termo_de_futebol(celeb)
    assert score.termo_de_futebol({"termo": "flamengo x palmeiras", "noticias": []})


def test_horario_reserva_nao_repete(tmp_path):
    base = dict(os.environ, FIXTURES_DIR=str(F), AGORA=AGORA.isoformat(), OUT_DIR=str(tmp_path),
                GITHUB_EVENT_NAME="schedule", EMAIL_TO="", SMTP_USER="", SMTP_PASS="")
    r1 = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=base, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    estado = json.loads((tmp_path / "data" / "estado.json").read_text("utf-8"))
    assert estado["ultima_agendada"] == "2026-09-24"
    r2 = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=base, capture_output=True, text=True)
    assert r2.returncode == 0 and "horário reserva" in r2.stderr
    manual = dict(base, GITHUB_EVENT_NAME="workflow_dispatch")
    r3 = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=manual, capture_output=True, text=True)
    assert r3.returncode == 0 and "temas pontuados" in r3.stderr


def test_selecao_so_brasil():
    assert not score.entidades("Cabo Verde x Ruanda: arbitragem polêmica nas Eliminatórias")["selecao"]
    assert score.entidades("Seleção Brasileira enfrenta a Austrália")["selecao"]
    assert score.entidades("Seleção de Ancelotti: Brasil treina no Rio")["selecao"]
    ent = {"foco": [], "br": [], "selecao": False, "comp_br": False, "intl": ["x"]}
    assert score.nota_aderencia(ent, "Arbitragem e VAR") <= 0.4


def test_agenda_e_buscas_ponta_a_ponta(tmp_path):
    env = dict(os.environ, FIXTURES_DIR=str(F), AGORA=AGORA.isoformat(), DRY_RUN="1", OUT_DIR=str(tmp_path))
    r = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    d = json.loads((tmp_path / "docs" / "data.json").read_text("utf-8"))
    ag = d["agenda"]
    assert [e["id"] for e in ag["resultados"]] == ["1"]            # vitória de ontem
    assert "venceu" in ag["resultados"][0]["gancho"]
    assert [e["id"] for e in ag["proximos"]] == ["2"]               # só o jogo dentro de 7 dias
    assert ag["proximos"][0]["liga"] == "Libertadores"
    assert ag["na_midia"] == []  # Palmeiras x Estudiantes já veio da ESPN: não repete
    assert agenda.jogos_na_midia(["Palmeiras x Estudiantes: onde assistir", "Palmeiras x Estudiantes: escalações"])
    spfc = next(t for t in d["temas"] if "São Paulo" in t["clubes"])
    assert spfc["sinais"]["busca"] > 0 and "lesão" in spfc["busca_torcedor"]
    assert d["buscas_torcedor"]["flamengo"] == ["flamengo meia europeu", "flamengo x bahia"]
    html = (tmp_path / "data" / "ultimo-email.html").read_text("utf-8")
    assert "Estudiantes" in html


# ---------------------------------------------------------------- versão 8

def _rodar(tmp_path, **extra):
    env = dict(os.environ, FIXTURES_DIR=str(F), AGORA=AGORA.isoformat(), DRY_RUN="1", OUT_DIR=str(tmp_path), **extra)
    if "YOUTUBE_API_KEY" not in extra:
        env.pop("YOUTUBE_API_KEY", None)
    r = subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=env, capture_output=True, text=True)
    return r, json.loads((tmp_path / "docs" / "data.json").read_text("utf-8")) if r.returncode in (0, 3) else None


def test_sementes_genericas_so_no_painel(tmp_path):
    r, d = _rodar(tmp_path)
    assert r.returncode == 0, r.stderr
    # "brasileirão protesto torcida" casaria com a pauta do protesto do Corinthians, mas a semente é só do painel.
    cor = next(t for t in d["temas"] if "Corinthians" in t["clubes"] and "rotest" in t["tema"])
    assert cor["busca_torcedor"] is None
    assert "brasileirão série b" in d["buscas_torcedor"]["brasileirão"]
    # Busca de outro esporte some do painel.
    assert d["buscas_torcedor"]["seleção brasileira"] == ["seleção brasileira convocação"]


def test_outros_esportes_nas_buscas():
    from radar import buscas
    assert buscas.especificas("seleção brasileira", ["seleção brasileira de voleibol masculino",
                                                     "seleção brasileira de futsal", "seleção brasileira convocação"]) \
        == ["seleção brasileira convocação"]
    assert score.outro_esporte("seleção brasileira de voleibol feminino")


def test_agenda_plano_b_pelas_buscas(tmp_path):
    r, d = _rodar(tmp_path)
    nb = d["agenda"]["nas_buscas"]
    jogos = [j["jogo"] for j in nb]
    assert "Corinthians x Rival" in jogos       # próximo jogo pelas buscas ("fc" é genérico)
    assert not any("Antigo" in j for j in jogos)                   # "resultado" = jogo já disputado
    assert not any("Estudiantes" in j for j in jogos)              # já veio da ESPN, não repete
    assert d["status"]["Agenda (buscas Google)"] == len(nb)
    sug = {"palmeiras": ["palmeiras x ldu quito", "palmeiras x ldu onde assistir", "palmeiras x santos resultado"]}
    j = agenda.jogos_das_buscas(sug, ["Palmeiras x LDU: onde assistir e escalações"])
    assert [x["jogo"] for x in j] == ["Palmeiras x LDU Quito"] and j[0]["confianca"] == "alta"


def test_espn_bloqueada_desiste_rapido(monkeypatch):
    chamadas = []

    def falso(url, **kw):
        chamadas.append(url)
        kw["info"]["status"] = 403
        return None
    monkeypatch.setattr(agenda, "fetch", falso)
    assert agenda.coletar_espn() == []
    assert len(chamadas) == 2  # um pedido por host, não 64


def test_youtube_sem_chave_nao_muda_nota(tmp_path):
    r, d = _rodar(tmp_path)
    assert d["status"]["YouTube (48 h)"] == "sem chave"
    assert all(t["sinais"]["youtube"] is None for t in d["temas"])
    # Sem YouTube, a conta equivale aos pesos antigos 30/30/20/20.
    s = {"busca": 0.5, "aceleracao": 0.8, "midia": 0.4, "aderencia": 1.0, "youtube": None}
    antigo = 100 * (0.3 * 0.5 + 0.3 * 0.8 + 0.2 * 0.4 + 0.2 * 1.0) * 1.0
    assert abs(score.nota_final(s, 1.0, False) - antigo) < 1e-9


def test_youtube_com_chave(tmp_path):
    r, d = _rodar(tmp_path, YOUTUBE_API_KEY="chave-de-teste")
    assert r.returncode == 0, r.stderr
    assert "chave-de-teste" not in r.stderr  # a chave nunca vai para o log
    fla = next(t for t in d["temas"] if "Flamengo" in t["clubes"] and t["categoria"] == "Mercado da bola")
    y = fla["youtube"]
    assert y["n_videos"] == 2 and y["views"] == 222000                # vídeo fora do assunto é descartado
    assert y["top"][0]["views"] == 180000 and fla["sinais"]["youtube"] > 0
    estado = json.loads((tmp_path / "data" / "estado.json").read_text("utf-8"))
    usadas = estado["youtube"]["buscas"]
    assert 0 < usadas <= 12
    # 2ª execução no mesmo dia: consultas repetidas vêm do cache, sem gastar cota.
    _rodar(tmp_path, YOUTUBE_API_KEY="chave-de-teste")
    estado = json.loads((tmp_path / "data" / "estado.json").read_text("utf-8"))
    assert estado["youtube"]["buscas"] == usadas


def test_youtube_limite_diario(tmp_path, monkeypatch):
    from radar import youtube, config as C
    temas = score.pontuar(bruto(), {}, AGORA)
    estado = {"youtube": {"dia": AGORA.astimezone(youtube.PACIFICO).date().isoformat(), "buscas": C.YT_BUSCAS_DIA}}
    youtube.enriquecer(temas, AGORA, "x", estado, tmp_path / "c.json", get=lambda *a, **k: 1 / 0)
    assert estado["youtube"]["buscas"] == C.YT_BUSCAS_DIA and all("youtube" not in t for t in temas)


def test_raiox_semanal(tmp_path):
    r, d = _rodar(tmp_path, RAIOX="1")
    assert r.returncode == 0, r.stderr
    rel = json.loads((tmp_path / "docs" / "desempenho.json").read_text("utf-8"))
    fmts = {f["formato"]: f for f in rel["formatos"]}
    assert set(fmts) == {"Shorts", "Vídeos longos", "Lives"}
    assert fmts["Shorts"]["indice"] > fmts["Lives"]["indice"]
    assert rel["temas"][0]["nome"] == "Arbitragem e VAR"
    f = rel["fatores_categoria"]
    assert f["Arbitragem e VAR"] > 1 > f["Jogo e resultado"]
    assert all(0.85 <= v <= 1.15 for v in f.values())
    assert rel["retencao"][0]["metade_sai_em"] and rel["retencao"][0]["maior_queda"]["de"] == "0:48"  # 10% a 20% de 8 min
    assert rel["retencao"][0]["fica_30s"] == 62
    assert rel["trafego"][0]["origem"] == "Feed de Shorts"
    assert rel["videos_inscritos"][0]["inscritos"] == 160
    assert rel["recomendacoes"]
    # Os fatores aprendidos já valem nas pautas do mesmo dia.
    assert d["fatores_categoria"] == f
    pesos = json.loads((tmp_path / "data" / "pesos-aprendidos.json").read_text("utf-8"))
    assert pesos["categorias"] == f
    html = (tmp_path / "data" / "ultimo-raiox.html").read_text("utf-8")
    assert "Onde o público sai" in html and "Formatos que rendem" in html


def test_raiox_sem_credenciais_nao_quebra(monkeypatch):
    from radar import main as M
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert M._raiox(AGORA, {}, None) == (None, None)


def test_raiox_token_revogado_avisa():
    from radar import analytics

    class R:
        status_code = 400

        def json(self):
            return {"error": "invalid_grant"}
    try:
        analytics.token_de_acesso("id", "segredo", "token", post=lambda *a, **k: R())
        assert False
    except analytics.ErroAnalytics as e:
        assert "YT_REFRESH_TOKEN" in str(e) and "segredo" not in str(e)


def test_fator_categoria_mexe_na_nota():
    b = bruto()
    t1 = score.pontuar(b, {}, AGORA)
    b["fatores_categoria"] = {"Mercado da bola": 1.15}
    t2 = score.pontuar(b, {}, AGORA)
    n1 = {t["tema"]: t["nota"] for t in t1}
    for t in t2:
        if t["categoria"] == "Mercado da bola":
            assert t["nota"] > n1[t["tema"]] or t["nota"] == 100
        else:
            assert t["nota"] == n1[t["tema"]]


def test_casos_reais_v8():
    # 29/09/2026: manchete com lista de clubes não confirma "Palmeiras x Vasco".
    sug = {"palmeiras x": ["palmeiras x ldu", "palmeiras x ldu onde assistir", "palmeiras x a", "palmeiras x b",
                           "palmeiras x c", "palmeiras x d", "palmeiras x e", "palmeiras x f", "palmeiras x g",
                           "palmeiras x vasco da gama"]}
    tit = ["Vencedor do prêmio Golden Boy foi oferecido a Santos, Botafogo, Flamengo, Palmeiras e Vasco"]
    jogos = [j["jogo"] for j in agenda.jogos_das_buscas(sug, tit)]
    assert "Palmeiras x Vasco" not in " ".join(jogos) and jogos[0].startswith("Palmeiras x Ldu")
    assert agenda._confronto("palmeiras x ldu onde assistir", "palmeiras", "ldu")
    assert agenda._confronto("flamengo enfrenta o estudiantes na libertadores", "flamengo", "estudiantes")
    # Jogo que a ESPN conhece (mesmo fora da janela de 7 dias) não repete.
    nb = [{"casa": "Palmeiras", "fora": "LDU", "manchetes": 0, "exemplo": None, "confianca": "média"}]
    ag = {"proximos": [], "resultados": [], "na_midia": []}
    assert agenda.unir_buscas(nb, ag, [{"casa": "LDU Quito", "fora": "Palmeiras"}]) == []
    # "Flamengo-PI" é outro clube.
    assert score.entidades("Flávio Araújo expõe atraso salarial do Flamengo-PI")["foco"] == []
    assert score.entidades("Atlético-MG vence o Flamengo")["foco"] == ["Flamengo"]
    assert score.entidades("Atlético-MG vence o Flamengo")["br"] == ["Atlético-MG"]


def test_tipos_de_conteudo_do_canal(tmp_path):
    from radar import analytics
    assert analytics.tipo_do_video("BOCA JUNIORS   X   SÃO PAULO - JOGO DE IDA") == "Transmissão de jogo"
    assert analytics.tipo_do_video("NORUEGA X PORTUGAL") == "Transmissão de jogo"
    assert analytics.tipo_do_video("SAI  PRO JOGO  # 215") == "Sai pro Jogo (programa)"
    assert analytics.tipo_do_video("FLU AFUNDA TIMÃO /VERDÃO PARA NAS MÃOS DE EX/TRICOLOR BATE INTER") == "Resenha multitemas"
    assert analytics.tipo_do_video("TOCA E  RECEBE - VC PERGUNTA  E NÓS RESPONDEMOS NA HORA") == "Perguntas do público"
    assert analytics.tipo_do_video("Flamengo vence e sobe na tabela") == "Outros"
    r, d = _rodar(tmp_path, RAIOX="1")
    rel = json.loads((tmp_path / "docs" / "desempenho.json").read_text("utf-8"))
    tipos = {t["nome"]: t for t in rel["tipos"]}
    assert tipos["Sai pro Jogo (programa)"]["n_videos"] == 3
    # Programa sem palavra de categoria conta como "Jogo e resultado" no ajuste de pesos.
    assert next(t for t in rel["temas"] if t["nome"] == "Jogo e resultado")["n_videos"] >= 6
    assert not any("mais rende: Outros" in x for x in rel["recomendacoes"])
    html = (tmp_path / "data" / "ultimo-raiox.html").read_text("utf-8")
    assert "Tipos de conteúdo" in html and "Clubes que rendem" in html


def test_videos_do_canal_pela_api():
    class R:
        def __init__(self, d, code=200):
            self._d, self.status_code = d, code

        def json(self):
            return self._d

    def get(url, params=None, **_):
        assert params["key"] == "k"
        if url.endswith("/channels"):
            assert params.get("forHandle") == "@canal"
            return R({"items": [{"id": "UCx", "contentDetails": {"relatedPlaylists": {"uploads": "UUx"}}}]})
        return R({"items": [{"snippet": {"title": "SAI PRO JOGO #219", "publishedAt": "2026-09-29T23:00:00Z",
                                         "resourceId": {"videoId": "abc"}}}]})
    videos, cid = collect.videos_pela_api("@canal", None, "k", get=get)
    assert cid == "UCx" and videos[0]["titulo"] == "SAI PRO JOGO #219" and videos[0]["url"].endswith("abc")
    assert collect.videos_pela_api("@canal", None, "k", get=lambda *a, **k: R({}, 403)) == ([], None)


def test_raiox_diario_sem_email_nem_ajuste(tmp_path):
    # 24/09/2026 é quinta: painel atualizado, sem e-mail do Raio-X e sem mexer nos pesos.
    r, d = _rodar(tmp_path)
    assert r.returncode == 0, r.stderr
    rel = json.loads((tmp_path / "docs" / "desempenho.json").read_text("utf-8"))
    assert rel["tipos"] and all(v == 1.0 for v in rel["fatores_categoria"].values())
    assert not (tmp_path / "data" / "pesos-aprendidos.json").exists()
    assert not (tmp_path / "data" / "ultimo-raiox.html").exists()
    assert "ultimo_raiox" not in json.loads((tmp_path / "data" / "estado.json").read_text("utf-8"))


def _video(i, views, horas, likes, dur=600, titulo=None, live=False):
    from datetime import timedelta
    return {"id": f"v{i}", "titulo": titulo or f"Vídeo {i}", "canal": f"Canal {i}", "canal_id": f"UC{i}", "views": views,
            "likes": likes, "comentarios": likes // 10, "duracao_s": dur, "live": live, "descricao": "",
            "publicado": (AGORA - timedelta(hours=horas)).isoformat(), "url": f"https://www.youtube.com/watch?v=v{i}"}


def test_alertas_de_tendencia(tmp_path):
    from radar import tendencias
    comum = [{"tema": f"Pauta comum {k}", "clubes": ["Palmeiras"], "ja_coberto": None, "sinais": {"aderencia": 100},
              "manchetes": [], "youtube": {"amostra": [_video(100 + 10 * k + j, 2000, 40, 60) for j in range(8)]}}
             for k in range(3)]
    quente = {"tema": "Arrascaeta sofre fratura e desfalca o Flamengo", "clubes": ["Flamengo"], "ja_coberto": None,
              "sinais": {"aderencia": 100}, "manchetes": [{"titulo": "Arrascaeta sofre fratura e desfalca o Flamengo"}],
              "youtube": {"amostra": [_video(1, 300000, 5, 18000, dur=45), _video(2, 80000, 6, 4000, dur=50),
                                      _video(3, 30000, 10, 900)]}}
    em_alta = [_video(50, 400000, 8, 30000, dur=40, titulo="Seleção Brasileira: Ancelotti convoca novo atacante"),
               _video(51, 900000, 6, 50000, dur=40, titulo="NBA: lance incrível do Lakers no basquete")]
    estado = {}
    alertas = tendencias.detectar([quente] + comum, em_alta, AGORA, tmp_path / "base.json", estado)
    temas = [a["tema"] for a in alertas]
    assert temas[0].startswith("Arrascaeta") or temas[1].startswith("Arrascaeta")
    assert any("Seleção Brasileira" in t for t in temas)
    assert not any("NBA" in t for t in temas) and not any("Pauta comum" in t for t in temas)
    a = next(a for a in alertas if a["tema"].startswith("Arrascaeta"))
    assert a["formato_em_alta"] == "Shorts" and "Reels" in a["sugestao"] and a["velocidade"] >= 3
    # No dia seguinte, o mesmo assunto não é avisado de novo.
    assert tendencias.detectar([quente] + comum, em_alta, AGORA, tmp_path / "base.json", estado) == []


def test_monetizacao_estimada(tmp_path):
    r, d = _rodar(tmp_path, RAIOX="1")
    m = json.loads((tmp_path / "docs" / "desempenho.json").read_text("utf-8"))["monetizacao"]
    e = m["estimativa_rs"]
    assert 0 < e["pessimista"] < e["provavel"] < e["otimista"]
    assert m["tendencia_pct"] > 0 and m["views_28d"] == sum(3000 + 20 * i for i in range(28))
    assert set(m["previsao_views_30d"]) == {"Vídeos longos", "Lives", "Shorts"}
    el = m["elegibilidade"]
    assert el["horas_12m"] == 2400 and el["cumpre"] is True  # horas públicas; o canal já é monetizado
    html = (tmp_path / "data" / "ultimo-raiox.html").read_text("utf-8")
    assert "Estimativa de monetização" in html


def test_linha_de_base_exige_amostra(tmp_path):
    from radar import tendencias
    poucos = [{"tema": "X", "clubes": ["Flamengo"], "ja_coberto": None, "sinais": {"aderencia": 100}, "manchetes": [],
               "youtube": {"amostra": [_video(1, 300000, 5, 18000)]}}]
    # Com 1 vídeo não há linha de base, e a lista "Em alta" não entra nela.
    em_alta = [_video(9, 900000, 2, 50000, titulo="Flamengo vence clássico com golaço") for _ in range(30)]
    assert tendencias.detectar(poucos, em_alta, AGORA, tmp_path / "b.json", {}) == []
    assert json.loads((tmp_path / "b.json").read_text("utf-8")) == {}


def test_alcance_publico_e_receita(tmp_path):
    r, d = _rodar(tmp_path, RAIOX="1")
    assert r.returncode == 0, r.stderr
    rel = json.loads((tmp_path / "docs" / "desempenho.json").read_text("utf-8"))
    a = rel["alcance"]
    assert a["impressoes"] == 80000 and 3 < a["ctr"] < 4
    assert a["por_tipo"][0]["ctr"] > a["por_tipo"][-1]["ctr"]
    assert any("Taxa de cliques" in x for x in rel["recomendacoes"])
    # Dados privados não vão para o painel público.
    assert "publico" not in rel and "receita_real" not in rel["monetizacao"]
    assert rel["monetizacao"]["tem_receita_real"] is True and rel["monetizacao"]["elegibilidade"]["monetizado"] is True
    html = (tmp_path / "data" / "ultimo-raiox.html").read_text("utf-8")
    assert "Perfil do público" in html and "25–34" in html and "Receita real" in html
    assert "Miniaturas: impressões e cliques" in html


def test_ler_csv_do_alcance():
    from radar import alcance
    cab = "date,channel_id,video_id,country_code,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
    fracao = alcance.ler_csv(cab + "20260915,UC1,v1,BR,1000,0.05\n20260915,UC1,v1,PT,1000,0.03\n")
    assert fracao == {"2026-09-15": {"v1": [2000, 80.0]}}
    pct = alcance.ler_csv(cab + "20260915,UC1,v1,BR,1000,5.0\n")
    assert pct == {"2026-09-15": {"v1": [1000, 50.0]}}


def test_requisitos_do_programa_de_parcerias(tmp_path):
    r, d = _rodar(tmp_path, RAIOX="1")
    rel = json.loads((tmp_path / "docs" / "desempenho.json").read_text("utf-8"))
    req = rel["requisitos"]
    it = {i["id"]: i for i in req["itens"]}
    # 2.400 h públicas: privados e Shorts ficam fora da conta.
    assert it["horas_12m"]["atual"] == 2400 and it["horas_12m"]["status"] == "abaixo" and "Faltam 1.600 h" in it["horas_12m"]["acao"]
    assert req["horas"]["projecao_30d"] == 2400 and len(req["horas"]["por_mes"]) >= 12
    assert it["inscritos"]["status"] == "ok" and it["atividade"]["status"] == "ok"
    assert it["advertencias"]["status"] == "conferir"
    assert req["pendencias"] == ["Horas assistidas públicas (12 meses)"] and it["nivel_inicial"]["status"] == "abaixo"
    assert "não tiram a monetização" in req["nota"]
    # E-mail diário sinaliza; no dia seguinte (mesma pendência) não repete; semanal sempre mostra.
    diario = (tmp_path / "data" / "ultimo-email.html").read_text("utf-8")
    assert "Monetização: requisito abaixo da meta" in diario
    assert "Requisitos do Programa de Parcerias" in (tmp_path / "data" / "ultimo-raiox.html").read_text("utf-8")
    env = dict(os.environ, FIXTURES_DIR=str(F), AGORA="2026-09-25T11:00:00+00:00", DRY_RUN="1", OUT_DIR=str(tmp_path))
    env.pop("YOUTUBE_API_KEY", None)
    subprocess.run([sys.executable, "-m", "radar.main"], cwd=RAIZ, env=env, capture_output=True, text=True)
    assert "Monetização: requisito abaixo da meta" not in (tmp_path / "data" / "ultimo-email.html").read_text("utf-8")


def _tema(tema, categoria, clubes, manchetes, **extra):
    return dict({"tema": tema, "categoria": categoria, "clubes": clubes,
                 "manchetes": [{"titulo": m} for m in manchetes], "sugestao": {"gancho": "x", "titulo_thumb": "x"}}, **extra)


def test_ganchos_extraem_dado_das_manchetes():
    from radar import ganchos
    d = ganchos.extrair_dado(["Corinthians aumenta déficit para R$ 278 milhões até julho, 258% a mais"])
    assert d["numero"] == "R$ 278 milhões" and d["peso"] == 4 and d["limpo"]
    assert d["trecho"].startswith("Corinthians aumenta déficit")
    # Ano, rodada e Sub-17 não são dado de pauta; trecho longo não perde o número.
    assert ganchos.extrair_dado(["Ao vivo: Corinthians x Atlético-GO | Rodada 19 | Campeonato Brasileiro sub-17"]) is None
    d = ganchos.extrair_dado(["Arrascaeta sofre quinta lesão com o Uruguai, que já o fez desfalcar o Flamengo por 118 dias"])
    assert d["numero"] == "118 dias" and "118 dias" in d["trecho"] and not d["limpo"]


def test_ganchos_cinco_tecnicas_sem_repetir():
    from radar import ganchos
    temas = [
        _tema("Arrascaeta sofre fratura no punho e preocupa o Flamengo", "Lesão e desfalque", ["Flamengo"],
              ["Arrascaeta sofre fratura no punho e vai passar por cirurgia", "Flamengo perde mais em jogos sem Arrascaeta; veja comparação"],
              youtube={"n_videos": 12, "views": 501_000}),
        _tema("Corinthians aumenta déficit", "Finanças e gestão", ["Corinthians"],
              ["Corinthians aumenta déficit para R$ 278 milhões até julho, 258% a mais"]),
        _tema("Raphinha é cortado da Seleção", "Seleção", [],
              ["Raphinha é cortado da Seleção Brasileira para amistoso", "Raphinha tem edema na coxa e é cortado da Seleção"]),
        _tema("Palmeiras x Santos", "Jogo e resultado", ["Palmeiras"], ["Palmeiras x Santos: onde assistir e escalações"]),
        _tema("Flamengo entra em ação no STF contra fim das bets", "Finanças e gestão", ["Flamengo"],
              ["Flamengo se manifesta sobre ação no STF contra fim das bets"]),
    ]
    ganchos.aplicar(temas, "2026-10-01")
    principais = [t["sugestao"]["tecnica"] for t in temas]
    assert len(set(principais)) == 5  # cada pauta abre com uma técnica diferente
    textos = [g["texto"] for t in temas for g in t["sugestao"]["ganchos"]]
    assert len(textos) == len(set(textos))  # nenhum gancho repetido no dia
    assert all("{" not in tx and "}" not in tx for tx in textos)
    fin = {g["tecnica"]: g["texto"] for g in temas[1]["sugestao"]["ganchos"]}
    assert fin["Dado"].startswith("Corinthians aumenta déficit para R$ 278 milhões")
    sel = " ".join(g["texto"] for g in temas[2]["sugestao"]["ganchos"])
    assert "a Seleção" in sel or "da Seleção" in sel or "na Seleção" in sel
    assert "o Seleção" not in sel and "do Seleção" not in sel
    jogo = {g["tecnica"]: g["texto"] for g in temas[3]["sugestao"]["ganchos"]}
    assert "Palmeiras x Santos" in jogo["Conflito"] or "Palmeiras contra Santos" in jogo["Conflito"]
    assert "[" in jogo["Aposta"]  # palpite fica para o apresentador completar, nada inventado
    # A rotação muda de um dia para o outro: em uma semana, as aberturas não são sempre iguais.
    semana = set()
    for dia in range(2, 9):
        outro = [dict(t, sugestao={"gancho": "x", "titulo_thumb": "x"}) for t in temas]
        ganchos.aplicar(outro, f"2026-10-0{dia}")
        semana.add(tuple(t["sugestao"]["tecnica"] for t in outro))
    assert len(semana) > 1


def test_ganchos_nao_usam_busca_sem_ligacao():
    from radar import ganchos
    t = _tema("Bidu lida com dores no púbis e pode desfalcar o Corinthians", "Lesão e desfalque", ["Corinthians"],
              ["Bidu lida com dores no púbis e pode desfalcar o Corinthians"], busca_torcedor="corinthians x estudiantes")
    assert "busca" not in ganchos.campos_do_tema(t)
    g, thumb, tec = ganchos.gancho_jogo("Flamengo", "Vasco", "2026-10-01", 0)
    assert "Flamengo" in g and thumb and tec in ganchos.NOMES_TECNICA.values()
    assert len({ganchos.gancho_jogo("Flamengo", "Vasco", "2026-10-01", i)[0] for i in range(5)}) == 5
