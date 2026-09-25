# Radar Nações da Bola

Todo dia às 08:30 (horário de Brasília), o radar:

1. lê as buscas em alta no **Google Trends** e as notícias das últimas 24 h no **Google News**;
2. junta manchetes parecidas em um único tema e dá uma nota de 0 a 100 para cada um;
3. confere os últimos vídeos do canal (RSS público do YouTube) e avisa quando um tema já foi coberto;
4. atualiza o **painel** (GitHub Pages) e manda um **e-mail** com as 5 melhores pautas, cada uma com gancho, texto de thumb e formato sugerido.

Custo: zero. Não precisa de chave de API. Roda no GitHub Actions.

## Como a nota é calculada

| Sinal | Peso | De onde vem |
| --- | --- | --- |
| Busca no Google | 30% | Volume do termo no Google Trends (Brasil) |
| Aceleração | 30% | Quantas manchetes saíram nas últimas 6 h e quanto o tema cresceu em relação aos dias anteriores |
| Veículos falando | 20% | Quantos veículos diferentes publicaram sobre o tema |
| Aderência ao canal | 20% | Flamengo, Corinthians, São Paulo e Palmeiras valem o máximo; polêmica, VAR, mercado e técnico ganham bônus |

Tema parecido com um vídeo recente do canal perde 15% da nota e recebe um aviso.
Para mudar clubes, buscas ou pesos, edite `radar/config.py`.

---

## Instalação

O arquivo `.github/workflows/radar.yml` carrega o projeto inteiro dentro dele. Na primeira execução ele
extrai o código, salva no repositório e liga o painel. Depois disso, o radar usa os arquivos do repositório:
edite `radar/config.py` à vontade.

1. **Criar o arquivo do radar**: no repositório, *Add file > Create new file*, nome
   `.github/workflows/radar.yml`, cole o conteúdo e confirme em *Commit changes*. A primeira execução começa sozinha.
2. **Secrets** (*Settings > Secrets and variables > Actions > New repository secret*):
   `EMAIL_TO` (destinatários, separados por vírgula), `SMTP_USER` (o Gmail que envia) e
   `SMTP_PASS` (senha de app de 16 letras, gerada em myaccount.google.com/apppasswords).
3. **Painel**: *Settings > Pages*, Source = *Deploy from a branch*, Branch = `main`, pasta `/docs`.
4. **Rodar de novo com e-mail**: *Actions > Radar diário > Run workflow*. Se preferir, espere: ele roda sozinho às 08:30.

Na primeira vez, o e-mail pode cair no Lixo eletrônico do Hotmail. Marque como "Não é lixo eletrônico".

## Problemas comuns

| Sintoma | O que fazer |
| --- | --- |
| Erro `Permission denied` / `403` no passo "Salvar painel" | Settings > Actions > General > Workflow permissions > **Read and write permissions** |
| Erro código 2 (falha no e-mail) | Confira `SMTP_USER` e `SMTP_PASS`. A senha tem que ser a **senha de app**, não a senha normal do Gmail |
| Erro código 1 (fontes fora do ar) | O Google recusou a coleta naquele horário. O painel anterior é mantido; o radar tenta de novo no dia seguinte, ou rode manualmente |
| "Canal (RSS YouTube): sem resposta" no painel | Em Settings > Secrets and variables > Actions > **Variables**, crie `CHANNEL_ID` com o ID do canal (começa com `UC`, aparece em youtube.com/account_advanced) |
| O radar parou depois de 2 meses | O GitHub desliga agendamentos de repositórios sem atividade. O próprio radar faz um commit por dia, o que normalmente evita isso; se acontecer, clique em "Enable workflow" na aba Actions |

## Testes

```bash
pip install -r requirements.txt pytest
python -m pytest -q tests
```

Os testes usam dados de demonstração (fictícios) gerados por `tests/make_fixtures.py` e não acessam a internet.
Para ver o e-mail sem enviar: `DRY_RUN=1 python -m radar.main` e abra `data/ultimo-email.html`.

## Próximos passos possíveis

- **API do YouTube** (gratuita): quando tiver a chave, dá para somar os vídeos de futebol em alta e as views dos concorrentes como mais um sinal.
- **Ganchos escritos por IA**: trocar os modelos de gancho por textos gerados pela API do Claude no tom do seu pai (custo baixo por dia, mas deixa de ser zero).
- **Reddit e Wikipédia**: mais dois sinais gratuitos de interesse súbito.

## Limites e cuidados

- O RSS do Google Trends e o do Google News são públicos, mas não são APIs oficiais com garantia. Se o Google mudar o formato, o radar registra o erro e mantém o painel anterior até o ajuste.
- O radar mostra só título, veículo e link das notícias, sem copiar o texto das matérias.
- As sugestões de gancho são pontos de partida. Confira os fatos na matéria original antes de gravar, principalmente em temas de polêmica e arbitragem.
