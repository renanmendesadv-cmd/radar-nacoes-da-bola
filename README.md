# Radar Nações da Bola

Todo dia às 08:30 (horário de Brasília, com horários reserva até 12:00 caso o GitHub atrase), o radar:

1. lê as buscas em alta no **Google Trends** e as notícias das últimas 24 h no **Google News**;
2. junta manchetes parecidas em um único tema e dá uma nota de 0 a 100 para cada um;
3. mede a **força no YouTube**: quantos vídeos saíram sobre cada pauta nas últimas 48 h, quantas views somam e quais são os 3 mais vistos (opcional, precisa de chave gratuita);
4. confere os últimos vídeos do canal e avisa quando um tema já foi coberto;
5. monta a agenda de jogos (ESPN; se ela bloquear, as buscas do Google, ex.: "palmeiras x ldu");
6. atualiza o **painel** (GitHub Pages) e manda um **e-mail** com as 5 melhores pautas.

O **Raio-X do canal** é atualizado **todo dia** na aba **Desempenho do canal** do painel; toda **segunda-feira** ele também vai por **e-mail** (YouTube Analytics, só leitura): formatos e temas que rendem,
onde o público sai dos vídeos, origens de tráfego, melhor dia e horário, vídeos que trouxeram inscritos. O Raio-X
**ajusta sozinho**, uma vez por semana (na segunda), o peso de cada tema na nota do radar.

**Alertas de tendência**: quando um assunto ligado ao canal explode no YouTube (vídeos com 3x ou mais views por hora
que a média do futebol e engajamento acima da média), o e-mail do dia abre com um 🔥 alerta dizendo o formato em alta
(Short, live ou vídeo longo) e sugerindo que o canal faça também. Fontes: os vídeos que o radar já busca para cada pauta
e a lista "Em alta" de Esportes do YouTube no Brasil (1 unidade da cota). Limites em `radar/config.py` (`ALERTA_*`).

**Monetização**: a aba Monetização do painel estima quanto o canal pode receber de anúncios nos próximos 30 dias
(views previstas por formato ÷ 1.000 × RPM), mostra os requisitos do Programa de Parcerias e deixa ajustar o RPM
com o valor real do YouTube Studio. É projeção, não valor garantido. Faixas de referência em `RPM_REFERENCIA`.
A mesma aba traz o **checklist do Programa de Parcerias**, com ✅ atingido, ⚠️ não atingido ou em risco, e 🔎 conferir no Studio.
Destaque para as **horas públicas dos últimos 12 meses**: calculadas vídeo a vídeo, sem Shorts, privados e apagados, com a
projeção de 30 dias. Se algum requisito medido estiver abaixo da meta, o e-mail diário avisa (no máximo uma vez por semana, ou
antes se a pendência mudar). Para canal já monetizado (`CANAL_MONETIZADO`), os requisitos de entrada funcionam como termômetro:
ficar abaixo não tira a monetização; inatividade, advertências e violação de políticas, sim.

**Guia de leitura** de uma página, para imprimir: `docs/guia.html` (link no painel).

Custo: zero. Chaves e senhas ficam só nos Secrets do GitHub.

## Como a nota é calculada

| Sinal | Peso | De onde vem |
| --- | --- | --- |
| Busca no Google | 24% | Volume do termo no Google Trends e posição da busca no autocompletar do Google |
| Aceleração | 24% | Quantas manchetes saíram nas últimas 6 h e quanto o tema cresceu em relação aos dias anteriores |
| Veículos falando | 16% | Quantos veículos diferentes publicaram sobre o tema |
| Aderência ao canal | 16% | Flamengo, Corinthians, São Paulo e Palmeiras valem o máximo; polêmica, VAR, mercado e técnico ganham bônus |
| Força no YouTube | 20% | Views somadas dos vídeos das últimas 48 h sobre o tema (1 milhão = máximo) e quantidade de vídeos |

- Sinal sem dado (sem chave do YouTube, ou pauta fora das 12 primeiras) sai da conta e os outros pesos se redistribuem.
  Sem o YouTube, a conta é exatamente a da versão 7 (30/30/20/20).
- **Ajuste pelo desempenho do canal**: cada categoria (Mercado da bola, Arbitragem e VAR...) recebe um fator entre 0,85x e 1,15x
  conforme as views dos vídeos do canal sobre ela nos 7 primeiros dias. O fator muda aos poucos (metade por semana) e só
  depois de pelo menos 3 vídeos na categoria. Fica salvo em `data/pesos-aprendidos.json`.
- Tema parecido com um vídeo recente do canal perde 15% da nota e recebe um aviso.

Para mudar clubes, buscas, pesos e limites, edite `radar/config.py`.

---

## Vigia do YouTube: aviso no celular e no painel (de hora em hora)

O workflow **Vigia do YouTube** (`.github/workflows/vigia.yml`, código em `radar/vigia.py`) confere o YouTube
de hora em hora, das 8h às 22h (Brasília). Quando um assunto ligado ao canal está bombando, ele avisa:

- **no celular**, pelo app gratuito **ntfy** (Android e iPhone), com som e botões "Ver o vídeo" e "Abrir o radar";
- **no painel**: faixa laranja presa no topo, contador na aba ("🔥 (1) Radar…"), ícone laranja e um toque curto
  (depois de ligar o botão **🔔 Som** uma vez). Com o painel aberto, a conferência é a cada 5 minutos.

Critérios: os mesmos dos alertas da manhã (3x a média de views por hora, engajamento na média, ligação com o canal)
e mais um: vídeo do assunto ganhando 20 mil views ou mais por hora. Os alertas da manhã também tocam no celular.
Limites: no máximo 3 avisos por dia somando manhã e vigia, o mesmo assunto não volta antes de 3 dias,
e silêncio das 23h às 7h. Custo na cota do YouTube: de 2 a 6 unidades por conferência (sem busca).

### Configurar o celular (uma vez, ~5 minutos)

1. Instale o app **ntfy** (Play Store ou App Store).
2. Invente um nome de canal difícil de adivinhar, só com letras, números e hífen, por exemplo
   `nacoes-radar-` seguido de 3 palavras aleatórias e um número. **Esse nome funciona como senha**:
   quem souber consegue ler os avisos. Não publique em lugar nenhum.
3. No app: botão **+** → digite o nome → **Subscribe** (servidor padrão, ntfy.sh).
4. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**,
   nome `NTFY_TOPICO`, valor = o mesmo nome do passo 2.
5. **Actions → Vigia do YouTube → Run workflow** (com "Só mandar uma notificação de teste" marcado).
   Em cerca de 1 minuto o celular toca com "🔔 Teste do Radar".

Dicas do app: no Android, em Configurações do ntfy, ligue **Entrega instantânea** para o aviso não atrasar
e escolha o som; no iPhone, permita notificações do ntfy. Sem o Secret, o vigia continua avisando só no painel.

## Ganchos: 5 técnicas

Cada pauta traz um gancho principal e mais até 4 alternativas, uma por técnica (`radar/ganchos.py`):

| Técnica | Como funciona | Exemplo |
|---|---|---|
| Dado | Abre com um número das manchetes ou medido pelo radar | "Corinthians aumenta déficit para R$ 278 milhões até julho. Guarda esse número…" |
| Conflito | Dois lados em choque | "O Flamengo sem Arrascaeta: o técnico vai ter que escolher entre improvisar ou mudar o time." |
| Contradição | Quebra o que todo mundo acha | "Parece só mais um desfalque. Não é: muda o jeito do time jogar." |
| Pergunta aberta | Dúvida que só o vídeo responde | "Quem merece a vaga de Raphinha na Seleção?" |
| Aposta | O apresentador crava um palpite | "Meu palpite para Palmeiras x Santos: [SEU PLACAR]. Deixa o seu nos comentários." |

- Os ganchos usam só fatos das manchetes do dia (número, protagonista, adversário) e o que o radar mediu (views no YouTube, buscas no Google).
  Opinião do apresentador fica [ENTRE COLCHETES] para ele completar.
- Contra a repetição: cada pauta do topo abre com uma técnica diferente, a ordem gira a cada dia, e a mesma frase não aparece duas vezes no mesmo dia.
- Frases específicas só aparecem quando a manchete confirma (por exemplo, "corte" só quando houve corte na Seleção).
- Os pré-jogos da agenda também variam entre as técnicas.

## Instalação (já feita)

1. **Secrets** (*Settings > Secrets and variables > Actions > New repository secret*):
   `EMAIL_TO` (destinatários, separados por vírgula), `SMTP_USER` (o Gmail que envia) e
   `SMTP_PASS` (senha de app de 16 letras, gerada em myaccount.google.com/apppasswords).
2. **Painel**: *Settings > Pages*, Source = *Deploy from a branch*, Branch = `main`, pasta `/docs`.
3. **Rodar agora**: *Actions > Radar diário > Run workflow*.

## Atualizar o radar

Desde a versão 8, o código fica só na pasta `radar/` e o `.github/workflows/radar.yml` apenas o executa (não traz mais o
código embutido). Qualquer mudança em `radar/`, `tests/` ou `docs/index.html` enviada para a `main` roda os testes e
atualiza o painel **sem mandar e-mail**. Se um teste falhar, o painel não é alterado. A versão em uso fica em `radar/VERSAO`.

---

## Força no YouTube: criar a chave (uma vez, ~5 minutos)

Quem faz: você (qualquer conta Google serve, não precisa ser a do canal).

1. Abra **console.cloud.google.com** e entre com sua conta Google. Aceite os termos se for o primeiro acesso.
2. No topo, clique no seletor de projeto > **Novo projeto**. Nome: `Radar Nacoes da Bola` > **Criar**. Confira que ele ficou
   selecionado no topo.
3. Menu ☰ > **APIs e serviços > Biblioteca**. Procure **YouTube Data API v3** > **Ativar**.
   Aproveite e ative também **YouTube Analytics API** (vai servir para o Raio-X).
4. Menu ☰ > **APIs e serviços > Credenciais > + Criar credenciais > Chave de API**. Copie a chave.
5. Ainda na tela da chave, clique em **Editar chave de API** (ou no nome dela):
   - *Restrições de aplicativo*: **Nenhuma** (os servidores do GitHub mudam de endereço a cada execução);
   - *Restrições de API*: **Restringir chave** > marque só **YouTube Data API v3** > **Salvar**.
   Assim, mesmo que a chave vaze, ela só serve para ler dados públicos do YouTube.
6. No GitHub: *Settings > Secrets and variables > Actions > New repository secret*, nome `YOUTUBE_API_KEY`, cole a chave.

**Cota gratuita**: 10.000 unidades por dia; cada busca custa 100. O radar usa no máximo **20 buscas por dia**
(2.000 unidades), contando execuções manuais, e reaproveita o resultado de uma mesma busca no mesmo dia. A cota zera à
meia-noite do Pacífico (4h ou 5h de Brasília). Se a cota acabar ou a chave falhar, as pautas saem normalmente, sem esse sinal.
Não é preciso cadastrar cartão de crédito.

---

## Raio-X do canal: autorização do dono do canal (uma vez, ~15 minutos)

O Raio-X lê as estatísticas privadas do canal (YouTube Analytics). Para isso o dono do canal (seu pai) autoriza, uma única
vez, um acesso **somente leitura**. O radar nunca consegue publicar, apagar, editar ou comentar nada: os únicos escopos
pedidos são `youtube.readonly` e `yt-analytics.readonly`.

### Parte A: você configura o app no Google Cloud (mesmo projeto da chave acima)

1. Em **console.cloud.google.com**, com o projeto `Radar Nacoes da Bola` selecionado, confira em
   *APIs e serviços > Biblioteca* que **YouTube Data API v3** e **YouTube Analytics API** estão **ativadas**.
2. Menu ☰ > **Google Auth Platform** (em algumas contas aparece como *APIs e serviços > Tela de permissão OAuth*) >
   **Começar**:
   - Nome do app: `Radar Nacoes da Bola`; e-mail de suporte: o seu;
   - Público: **Externo**;
   - Dados de contato: o seu e-mail > aceite a política > **Criar**.
3. **Acesso a dados** (*Data access*) > **Adicionar ou remover escopos** > marque:
   - `.../auth/youtube.readonly`
   - `.../auth/yt-analytics.readonly`
   (se não aparecerem na lista, cole os dois endereços completos no campo *Adicionar escopos manualmente*:
   `https://www.googleapis.com/auth/youtube.readonly` e `https://www.googleapis.com/auth/yt-analytics.readonly`)
   > **Atualizar** > **Salvar**.
4. **Público** (*Audience*) > em *Status de publicação*, clique em **Publicar app** > **Confirmar**. O status deve ficar
   **Em produção**.
   > **Importante**: em modo *Teste* o Google invalida a autorização a cada **7 dias** e o Raio-X para de funcionar.
   > Em produção ela não expira. O Google pode oferecer "enviar para verificação": **não é necessário** para um app que só
   > vocês usam (o único efeito é um aviso de "app não verificado" no login, explicado abaixo).
5. **Clientes** (*Clients*) > **+ Criar cliente**:
   - Tipo de aplicativo: **Aplicativo da Web**; nome: `Radar`;
   - *URIs de redirecionamento autorizados* > **+ Adicionar URI**: `https://developers.google.com/oauthplayground`
   - **Criar**. Copie o **ID do cliente** e a **Chave secreta do cliente** (baixe o JSON: a chave secreta pode não ser mostrada de novo).
6. No GitHub, crie os Secrets `YT_CLIENT_ID` e `YT_CLIENT_SECRET` com esses dois valores.

### Parte B: seu pai faz o login (no computador dele, ou no seu com a conta dele)

1. Abra **https://developers.google.com/oauthplayground**.
2. Clique na **engrenagem ⚙** (canto superior direito) > marque **Use your own OAuth credentials** > cole o
   *OAuth Client ID* e o *OAuth Client secret* da Parte A > feche a janelinha.
   (Sem isso o Playground usa as credenciais dele e apaga o acesso em 24 horas.)
3. À esquerda, em *Step 1*, no campo **Input your own scopes**, cole exatamente:
   ```
   https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly
   ```
   > **Authorize APIs**.
4. Entre com a **conta Google dona do canal**. Se o canal estiver numa *conta de marca*, o Google pergunta qual conta/canal
   usar: escolha o **canal Nações da Bola**.
5. Vai aparecer **"O Google não verificou este app"**. É esperado (o app é de vocês). Clique em **Avançado** >
   **Acessar Radar Nacoes da Bola (não seguro)**. Confira que as permissões são só de **ver** (visualizar a conta do YouTube e
   os relatórios do YouTube Analytics), marque as duas e clique em **Continuar**.
6. De volta ao Playground, em *Step 2*, clique em **Exchange authorization code for tokens**.
   Copie o valor de **Refresh token** (começa com `1//`).
7. No GitHub, crie o Secret `YT_REFRESH_TOKEN` com esse valor. Feche a aba do Playground. Não mande o token por chat ou e-mail.
8. Teste: *Actions > Radar diário > Run workflow* > marque **Gerar também o Raio-X do canal agora** > **Run workflow**.
   Em ~3 minutos chega o e-mail do Raio-X e a aba *Desempenho do canal* do painel é preenchida.

**Para revogar a qualquer momento**: seu pai abre **myaccount.google.com/connections** (Terceiros com acesso), escolhe
*Radar Nacoes da Bola* > **Excluir todas as conexões**. O radar diário continua; só o Raio-X para.

**Se o Raio-X parar** (erro código 3 no Actions, com "invalid_grant" no log): a autorização foi revogada, o app voltou para
*Teste* ou ficou 6 meses sem uso. Repita a Parte B e atualize o Secret `YT_REFRESH_TOKEN`.

### Impressões e cliques das miniaturas (uma vez, 1 minuto)

No projeto `Radar Nacoes da Bola` do Google Cloud, abra a biblioteca de APIs, procure **YouTube Reporting API** e clique em
**Ativar** (https://console.cloud.google.com/apis/library/youtubereporting.googleapis.com?project=radar-nacoes-da-bola).
Não precisa de novo login. Na execução seguinte o radar ativa o relatório `channel_reach_basic_a1` no canal; o YouTube entrega os
30 dias anteriores e depois um arquivo por dia, em até 48 h. Cada arquivo só fica disponível por 60 dias, por isso o radar guarda o
resumo em `data/alcance.json`.

### Receita real (opcional, novo login do dono do canal)

Troca o RPM de referência pelo RPM real e mostra receita por vídeo e por formato, **só no e-mail** (o painel é público).
1. Google Cloud > **Google Auth Platform > Acesso a dados > Adicionar ou remover escopos**: adicione
   `https://www.googleapis.com/auth/yt-analytics-monetary.readonly` > Atualizar > **Salvar**.
2. Repita a Parte B do Raio-X com os **três** escopos:
   ```
   https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/yt-analytics-monetary.readonly
   ```
3. Substitua o Secret `YT_REFRESH_TOKEN` pelo novo token (o antigo deixa de ser necessário).

Sem esse passo, tudo funciona com o RPM de referência.

### Privacidade do Raio-X

O **perfil do público** (idade, gênero, países) e a **receita real** vão só no e-mail, nunca no painel.
Este repositório é **público**, e o painel também. Com o Raio-X ligado, `docs/desempenho.json` publica números que o YouTube
só mostra ao dono do canal (retenção, origens de tráfego, inscritos por vídeo). Não há dado pessoal de espectadores, mas um
concorrente poderia ver a estratégia do canal. Para mandar o Raio-X só por e-mail: *Settings > Secrets and variables > Actions >
Variables > New repository variable*, nome `RAIOX_PAINEL`, valor `0`. A partir da segunda seguinte a aba mostra apenas um aviso.
(Os números detalhados também deixam de ser gravados no repositório; o arquivo antigo pode ser apagado à mão.)

---

## Problemas comuns

| Sintoma | O que fazer |
| --- | --- |
| Erro `Permission denied` / `403` no passo "Salvar painel" | Settings > Actions > General > Workflow permissions > **Read and write permissions** |
| Erro código 1 (fontes fora do ar) | O Google recusou a coleta naquele horário. O painel anterior é mantido; rode manualmente mais tarde |
| Erro código 2 (falha no e-mail) | Confira `SMTP_USER` e `SMTP_PASS`. A senha tem que ser a **senha de app**, não a senha normal do Gmail |
| Erro código 3 (falha no Raio-X) | As pautas do dia saíram. Veja a mensagem no log; se for "invalid_grant", refaça a Parte B do Raio-X |
| "Agenda (ESPN): sem resposta" | Desde 29/09/2026 o endereço principal da ESPN (`site.api.espn.com`) recusa os servidores do GitHub (HTTP 403). O radar tenta então `site.web.api.espn.com`, que funcionou em 30/09. Se os dois bloquearem, os jogos vêm das buscas do Google ("em alta nas buscas", sem data): confira data e horário antes de gravar |
| "YouTube (48 h): sem chave" | Crie o Secret `YOUTUBE_API_KEY` (seção Força no YouTube) |
| "YouTube (48 h): cota esgotada" | A cota diária acabou (execuções manuais demais). Volta sozinha no dia seguinte |
| "Vídeos do canal: sem resposta" | Com a chave `YOUTUBE_API_KEY` o radar lê os vídeos pela API oficial; sem ela, pelo RSS público, que às vezes falha. Se persistir, em Settings > Secrets and variables > Actions > **Variables**, crie `CHANNEL_ID` com o ID do canal (começa com `UC`, aparece em youtube.com/account_advanced) |
| O radar parou depois de 2 meses | O GitHub desliga agendamentos de repositórios sem atividade. O próprio radar faz um commit por dia, o que normalmente evita isso; se acontecer, clique em "Enable workflow" na aba Actions |

## Testes

```bash
pip install -r requirements.txt pytest
python -m pytest -q tests
```

Os testes usam dados de demonstração (fictícios) gerados por `tests/make_fixtures.py` e não acessam a internet.
Para ver os e-mails sem enviar: `DRY_RUN=1 python -m radar.main` e abra `data/ultimo-email.html`
(com `RAIOX=1`, também `data/ultimo-raiox.html`).

## Limites e cuidados

- O RSS do Google Trends, o do Google News e o autocompletar do Google são públicos, mas não são APIs oficiais com garantia.
  Se o Google mudar o formato, o radar registra o erro e segue com as outras fontes.
- Os jogos vindos das buscas do Google não têm data nem mando de campo: "Palmeiras x LDU" pode ser jogo fora de casa.
- O Raio-X compara vídeos pelas views nos 7 primeiros dias; com poucos vídeos numa categoria (menos de 3), o peso dela não muda.
  Shorts são identificados pela duração (até 3 min), o que pode confundir um vídeo horizontal curto com um Short.
- O radar mostra só título, veículo e link das notícias e dos vídeos, sem copiar conteúdo.
- As sugestões de gancho são pontos de partida. Confira os fatos na matéria original antes de gravar, principalmente em temas de polêmica e arbitragem.
