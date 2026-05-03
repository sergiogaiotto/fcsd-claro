# FALE COM **SEUS DADOS**

**Transforme perguntas em respostas.** Plataforma de analise de dados com linguagem natural, visualizacao interativa, modelagem preditiva, inferencia causal e Deep Agent autonomo que converte portugues em SQL.

Desenvolvido por [Sergio Gaiotto](https://www.falagaiotto.com.br) — Especialista, pesquisador e educador em dados e inteligencia artificial aplicada.

---

## Sumário

   [Visão Geral](#visão-geral)

1. [Arquitetura Geral](#1-arquitetura-geral)
2. [Stack Tecnológico](#2-stack-tecnológico)
3. [Variáveis de Ambiente](#3-variáveis-de-ambiente)
4. [Modelo de Dados Interno](#4-modelo-de-dados-interno)
5. [Deep Agent — Motor de Linguagem Natural para SQL](#5-deep-agent--motor-de-linguagem-natural-para-sql)
6. [Sistema de Skills — Progressive Disclosure](#6-sistema-de-skills--progressive-disclosure)
7. [Skill Router — Auto-detecção sem LLM](#7-skill-router--auto-detecção-sem-llm)
8. [Wizard "Criar SKILL" — Geração com IA](#8-wizard-criar-skill--geração-com-ia)
9. [DataMarts — Governança de Acesso a Tabelas](#9-datamarts--governança-de-acesso-a-tabelas)
10. [Tipos de Análise — System Prompts Configuráveis](#10-tipos-de-análise--system-prompts-configuráveis)
11. [Perguntas Salvas com SQL Reutilizável](#11-perguntas-salvas-com-sql-reutilizável)
12. [Explorar — PyGWalker + AI Ask Bar](#12-explorar--pygwalker--ai-ask-bar)
13. [Gráficos — Chart.js com Recomendação por IA](#13-gráficos--chartjs-com-recomendação-por-ia)
14. [Análise Avançada — Predição e Inferência Causal](#14-análise-avançada--predição-e-inferência-causal)
15. [Galeria de Análises](#15-galeria-de-análises)
16. [Autenticação e Controle de Acesso](#16-autenticação-e-controle-de-acesso)
17. [API Externa (v1)](#17-api-externa-v1)
18. [Observabilidade — Langfuse](#18-observabilidade--langfuse)
19. [Segurança SQL](#19-segurança-sql)
20. [Import/Export de Dados e Entidades](#20-importexport-de-dados-e-entidades)
21. [Referência Completa de Endpoints](#21-referência-completa-de-endpoints)
22. [Estrutura de Arquivos](#22-estrutura-de-arquivos)
23. [Row-Level Security por Login](#23-row-level-security-por-login)
---

## Visão Geral

Fale Com Seus Dados e uma aplicação open-source que elimina a barreira técnica entre pessoas e seus dados. O sistema combina um **Deep Agent** com planejamento autonomo, exploração de schema e escrita de queries via skills progressivas, um motor de **análise estatística descritiva, preditiva e causal** com modelos de machine learning, e **visualização interativa** com PyGWalker e Chart.js — tudo acessível via interface web em português brasileiro, protegido por autenticação com controle de acesso por perfil e segmentação por DataMart.

A plataforma integra quatro pilares analíticos: estatistica descritiva para entender a distribuição e estrutura dos dados, modelagem preditiva para estimar valores e classificar observacoes, inferência causal para identificar relações de causa e efeito entre variáveis, e redução de dimensionalidade para simplificar datasets complexos preservando informação relevante.

---

## Funcionalidades

### Autenticação e Controle de Acesso

Toda a aplicação e protegida por autenticação obrigatória. O acesso exige login e senha, com sessões gerenciadas via cookie httponly com TTL de 24 horas.

**Primeiro acesso** — quando o banco de dados nao possui nenhum usuário cadastrado, a tela de login detecta essa condicao e informa que as credenciais digitadas criarão automaticamente uma conta **Root** com acesso total. Nao há seed, migration manual ou setup externo — basta iniciar o servidor e fazer o primeiro login.

**Três perfis de acesso:**

**Root** — acesso total e irrestrito. Visualiza todas as tabelas, DataMarts, skills e funcionalidades independente de atribuição. Pode criar, editar e excluir qualquer recurso, incluindo outros usuários Root. Criado automaticamente no primeiro acesso.

**Administrador** — acesso administrativo dentro do escopo dos DataMarts atribuidos. Pode criar, editar e excluir usuarios (exceto Root), gerenciar tabelas, skills, DataMarts e tipos de analise. Visualiza apenas tabelas dos DataMarts atribuidos ao seu cadastro.

**Usuário Comum** — acesso as funcionalidades de consulta, visualização, análise, exportação, galeria e perguntas salvas. Não vê a aba "Usuarios" nem o botão de exclusao de tabelas. Visualiza apenas tabelas dos DataMarts atribuidos ao seu cadastro.

Cada usuário possui login, senha (PBKDF2-SHA256 + salt), tipo, nome de exibição, descrição do perfil e lista de DataMarts atribuidos.

### DataMarts

DataMart e o mecanismo de segmentação e controle de acesso a dados. Cada DataMart agrupa um conjunto de tabelas do banco de dados, e cada usuário tem acesso apenas as tabelas pertencentes aos DataMarts atribuidos ao seu cadastro.

**Fundamento** — em cenários corporativos, diferentes áreas (financeiro, marketing, operacoes) precisam acessar conjuntos distintos de dados. O conceito de DataMart origina-se da arquitetura de data warehousing, onde cada mart representa uma visão especializada de um subconjunto do repositório central. O Fale Com Seus Dados aplica esse conceito como filtro lógico — sem duplicação física de dados, cada usuário acessa apenas o escopo autorizado. Isso garante governança, conformidade com LGPD e isolamento entre áreas de negócio.

**Funcionamento:**

Um DataMart "default" e criado automaticamente na inicialização. No upload de Excel, o usuário escolhe em qual DataMart as tabelas serão criadas — via combobox com DataMarts existentes ou digitando o nome de um novo. As tabelas importadas são automaticamente associadas ao DataMart selecionado.

No cadastro de usuário, o administrador atribui um ou mais DataMarts via checkbox. O usuário Root ignora essa restrição — visualiza tudo.

Na tela de consulta, checkboxes dos DataMarts atribuidos permitem selecionar quais DataMarts considerar na consulta. O Deep Agent recebe apenas o schema das tabelas acessíveis — tabelas fora do escopo nao aparecem sequer no contexto do LLM, impedindo vazamento de informacao.

**Tabelas internas:**

`datamarts` — cadastro de DataMarts com nome e descrição.

`datamart_tables` — associação N:N entre DataMarts e tabelas do banco (datamart_id, table_name).

`user_datamarts` — associação N:N entre usuários e DataMarts (user_id, datamart_id).

### Gerenciamento de Usuários

Aba dedicada na interface (visível apenas para Root e Administradores) com tabela CRUD completa. Permite criar novos usuarios com definição de tipo, perfil e DataMarts, editar dados existentes, alterar senhas e excluir contas. Proteção de integridade: ninguém pode excluir a si mesmo, e usuários Root nao podem ser excluídos.

**Importação via Excel** — botão "Importar" na aba Usuários. O arquivo Excel deve conter colunas `login`, `display_name` e `profile_description`. Todos os usuários importados recebem senha padrão `...`, tipo `admin` e são atribuídos ao DataMart "default". O administrador ajusta permissões individualmente apos a importação.

**Exportação para Excel** — botão "Exportar" na aba Usuários. Gera planilha com login, tipo, nome, descrição, status, DataMarts atribuídos e data de criação.

### Consulta em Linguagem Natural

O núcleo da aplicação. O usuário digita uma pergunta em português e o Deep Agent autonomamente explora o banco de dados, identifica tabelas e colunas relevantes, gera SQL otimizado, executa e retorna resultados formatados com insights.

Suporta contexto conversacional — perguntas de acompanhamento mantém a referência da conversa anterior, permitindo aprofundamento iterativo sem necessidade de repetir o contexto.

O limite de registros retornados e configurável via dropdown na interface (20, 50, 100, 500, 1000 ou Todos). A lógica de LIMIT e aplicada após a geração do SQL pelo agente, garantindo que o usuário controla o volume independente do que o LLM decide.

**Filtragem por DataMart** — antes de cada consulta, o usuário pode selecionar quais DataMarts considerar via checkboxes na interface. O sistema resolve os DataMarts selecionados em uma lista de tabelas acessiveis e injeta essa restrição no contexto do agente. O agente recebe instrução explícita de não acessar tabelas fora da lista.

**Formato de resposta** — o agente nunca reproduz dados da query no texto. A resposta textual contém apenas resumo analítico, insights e propostas de analise. Os dados aparecem automaticamente na tabela HTML formatada pelo frontend, com detecção automatica de colunas numéricas, alinhamento a direita, formatação pt-BR com separador de milhar e tratamento de nulos.

**Propostas de análise** — ao final de cada resposta, o agente inclui 3 a 5 sugestões de aprofundamento específicas aos dados retornados. Cada proposta e um link clicável que, ao ser acionado, preenche o campo de consulta e executa automaticamente — transformando a análise em fluxo interativo e dirigido por dados.

### Perguntas Salvas

Funcionalidade que permite ao usuario salvar, reutilizar e gerenciar perguntas frequentes. Cada pergunta e armazenada por usuário, com rótulo opcional para facilitar identificação.

**Fundamento** — em cenários de análise recorrente, os mesmos indicadores e cortes de dados são consultados repetidamente (fechamento mensal, KPIs semanais, relatórios periódicos). O mecanismo de perguntas salvas elimina a necessidade de redigitar consultas complexas, reduz erros de digitação e padroniza a linguagem de acesso aos dados entre membros de uma equipe.

**Combobox na tela de consulta** — abaixo do seletor de tipo de análise, um dropdown lista todas as perguntas salvas do usuário. Ao selecionar, a pergunta e posicionada no campo de entrada e o envio e disparado automaticamente. O combobox exibe o rótulo seguido do texto da pergunta, truncado em 100 caracteres, com tooltip mostrando o texto completo.

**Botao "Salvar Pergunta"** — disponível na barra de ações apos cada resultado de consulta. Ao clicar, o sistema solicita um rotulo opcional via prompt nativo. A pergunta e associada ao usuário logado. Perguntas duplicadas (mesmo texto e mesmo usuario) são detectadas no backend e informadas sem gerar erro.

**Aba "Perguntas"** — tab dedicada na interface principal com tabela completa mostrando rótulo, texto da pergunta, usuário, data de criação e botão de exclusão. Administradores visualizam perguntas de todos os usuários; usuários comuns veem apenas as próprias. Clicar na pergunta navega para a aba de consulta e executa automaticamente.

**Exportacao e importacao** — botões "Exportar" e "Importar" na aba Perguntas. A exportação gera arquivo `.xlsx` com colunas label, question, user e created_at. A importação aceita Excel com colunas `question` (ou `pergunta`) e `label` (ou `rotulo`/`rótulo`). Perguntas duplicadas são ignoradas silenciosamente durante importação. A importação sempre associa ao usuário logado.

**Tabela interna:**

`saved_questions` — id, user_id (FK com CASCADE), question, label, created_at.

### Upload de Excel e Gestao de Tabelas

Arquivos `.xlsx` sao importados diretamente pela interface. Cada aba da planilha e convertida em uma tabela SQLite — se a tabela já existe, os dados são adicionados (append).

**Associacao a DataMart** — no momento do upload, o usuário seleciona um DataMart existente via combobox ou digita o nome de um novo DataMart. Todas as tabelas criadas pelo upload são automaticamente associadas ao DataMart escolhido.

Administradores podem **excluir tabelas** diretamente pela aba Tabelas. O botão de exclusão aparece no hover de cada tabela e exige dupla confirmação antes de executar o `DROP TABLE`. Tabelas internas do sistema sao protegidas contra exclusão. A exclusao tambem remove a associação da tabela em todos os DataMarts.

### Custom Skills

Skills expandem a capacidade do agente ao responder consultas. Cada skill ativa e injetada no contexto do Deep Agent como conhecimento especializado — regras de interpretação, métricas específicas, formatos de resposta.

**Fundamento** — o conceito de skills implementa o padrao de Progressive Disclosure do framework Deep Agents. Em vez de carregar todo o conhecimento no contexto do LLM (limitado em tokens), o sistema injeta apenas o conhecimento relevante para cada consulta. Isso otimiza o uso de contexto e permite especializacao ilimitada sem degradar a qualidade das respostas base.

**Exemplos de uso:** análise financeira (DRE, balanco, indicadores), segmentacao RFM, analise de churn, KPI dashboards especializados, regras de negócio por vertical.

**Selecao por consulta** — álem das skills globalmente ativas, o usuário pode selecionar skills especificas para a próxima consulta via pop-up skill picker na barra de ações. Skills selecionadas sao injetadas no contexto do agente apenas para aquela consulta.

**Importacao via Excel** — botão "Importar" na aba Skills. O arquivo deve conter colunas `name`, `description` e `content`. Skills importadas ficam ativas por padrão.

**Exportacao para Excel** — botão "Exportar" na aba Skills. Gera planilha com nome, descrição, conteúdo, status, autor e data.

### System Prompts e Tipos de Analise

O sistema permite criar, editar e excluir tipos de analise customizados. Cada tipo define um system prompt proprio com guardrails de entrada e saída, controlando o comportamento do agente. Isso permite que uma mesma instalação atenda diferentes contextos — análise financeira, marketing, operações — cada um com instruções e restrições específicas.

**Fundamento** — guardrails implementam o conceito de alinhamento por design. O guardrail de entrada restringe quais perguntas o agente aceita (evitando consultas destrutivas ou fora do escopo), enquanto o guardrail de saída define formato, idioma e nível de detalhe da resposta. Juntos, garantem que o agente opera dentro de limites previsíveis e auditáveis.

### Grafico Interativo (Chart.js)

Após qualquer consulta, o botao "Gráfico" abre um submenu com 9 opções de visualização: Auto (LLM), Barras, Linhas, Dispersao, Área, Pizza, Rosca, Radar e Polar. O sistema analisa o dataset e indica quais tipos são adequados para a combinação de colunas disponível.

O gráfico abre em nova aba com controles interativos:

**Tipo** — troca o tipo de gráfico em tempo real sem recarregar.

**Eixo X** — seleciona qualquer coluna do dataset como eixo horizontal.

**Eixo Y** — seleciona qualquer coluna como métrica.

**Agregacao** — Soma, Média, Contagem ou Nenhuma. Quando ativa, os dados são agrupados pelo campo X.

**Limite** — restringe a quantidade de itens exibidos (20, 50, 100, Todos).

**Ordem** — Ascendente ou Descendente pelo valor do campo X. Usa `localeCompare` com `numeric:true` para ordenação natural de datas, números textuais e strings.

Quando o modo "Auto (LLM)" e selecionado, o sistema envia amostra dos dados ao LLM que recomenda tipo de gráfico, campos X e Y e agregação. O resultado pré-configura os dropdowns — o usuário pode ajustar a partir dai. Se o LLM falhar, um fallback automático seleciona a primeira coluna categórica como X e a primeira numérica como Y.

Toda a agregação e renderização acontecem client-side em JavaScript. Os dados brutos são transmitidos como JSON e o Chart.js reconstrói o gráfico a cada alteração nos controles.

### Visualização Interativa (Explorar)

Após qualquer consulta, o botão "Explorar" abre o **PyGWalker** em nova aba — um ambiente drag-and-drop para criação de visualizações. O usuário arrasta colunas para eixos, aplica filtros, muda tipos de gráfico, tudo sem código. O estado completo (HTML + localStorage) e preservado para salvar na galeria.

A abertura via form POST direto (não `fetch` + `document.write`) garante que o PyGWalker carrega seus CDNs sem restrição de Content Security Policy.

### Galeria de Analises

Visualizações podem ser salvas na galeria com titulo e descrição. Cada item recebe um token único de compartilhamento, permitindo acesso via URL pública sem autenticação. A galeria preserva o estado completo do PyGWalker, incluindo filtros e configurações visuais aplicadas.

### Avaliação Período a Período

Funcionalidade especializada para comparação temporal de métricas. Disponível como botão "Avaliar" na barra de acoes após uma consulta.

**Fundamento** — a análise de variação periódica (period-over-period) e uma técnica fundamental em business intelligence. Medir a variação absoluta e percentual entre períodos consecutivos revela tendências, sazonalidade e pontos de inflexão que não são visíveis em valores absolutos isolados.

**Funcionamento** — o usuário seleciona a granularidade (mês a mês ou ano a ano), a coluna de data/período e a métrica numérica. O sistema formula uma pergunta estruturada que o Deep Agent executa, retornando para cada período: valor atual, valor anterior, variação absoluta e variação percentual, com destaque automático para os períodos de maior crescimento e maior queda.

### Análise Avançada — Estatística Descritiva

O modulo de análise avançada gera automaticamente um dashboard estatístico completo a partir dos dados da consulta. A aba descritiva inclui:

**Tendência Central** — média, mediana, moda para cada coluna numérica. A média captura o valor esperado, mas e sensível a outliers; a mediana representa o ponto central da distribuição e e robusta a valores extremos; a moda identifica o valor mais frequente, relevante para distribuições multimodais.

**Dispersão** — desvio padrão, variância, amplitude (max - min), coeficiente de variação. O desvio padrão mede a dispersão típica dos dados em relação a média na mesma unidade de medida; a variância e seu quadrado, útil em cálculos intermediários, mas de interpretação menos direta; o coeficiente de variação (CV = desvio/média) permite comparar dispersão entre variáveis com escalas diferentes — um CV acima de 30% geralmente indica alta heterogeneidade.

**Posicao** — quartis (Q1, Q2, Q3), amplitude interquartil (IQR), percentis 5, 10, 90, 95. Os quartis dividem a distribuicao em quatro partes iguais; o IQR (Q3 - Q1) captura os 50% centrais dos dados e e a base para deteccao de outliers pelo metodo de Tukey (valores abaixo de Q1 - 1.5×IQR ou acima de Q3 + 1.5×IQR). Assimetria (skewness) indica a direcao da cauda da distribuicao; curtose (kurtosis) mede o peso das caudas — valores altos indicam maior probabilidade de valores extremos.

**Histogramas** — distribuicao de frequencia para cada coluna numerica com bins automaticos via Chart.js. O numero de bins e calculado como min(20, max(5, n/5)), equilibrando resolucao e legibilidade.

**Matriz de Correlacao** — correlacao de Pearson entre ate 12 colunas numericas, renderizada como heatmap interativo com escala de cor (verde = correlacao positiva, vermelho = negativa), tooltips com nomes completos e valores exatos. O coeficiente de Pearson mede a forca e direcao da relacao linear entre duas variaveis, variando de -1 (relacao inversa perfeita) a +1 (relacao direta perfeita). Valores proximos de zero indicam ausencia de relacao linear — mas nao necessariamente ausencia de relacao nao-linear.

**Diagramas de Dispersao** — scatter plots automaticos para os primeiros 4 pares de colunas numericas, com amostragem de ate 200 pontos. Permitem identificar visualmente padroes, clusters, outliers e a forma da relacao entre variaveis.

**Tabelas de Frequencia** — contagem e percentual para colunas categoricas (ate 30 categorias), com graficos de barras ou doughnut associados. Barras sao usadas para mais de 6 categorias; doughnut para 6 ou menos.

### Analise Avancada — Modelagem Preditiva

Cinco motores de modelagem disponiveis, todos com label encoding automatico para variaveis categoricas:

**Regressao Linear** — preve valores numericos continuos a partir de uma ou mais variaveis independentes. O modelo ajusta uma funcao linear Y = b0 + b1×X1 + b2×X2 + ... que minimiza a soma dos quadrados dos residuos (metodo dos minimos quadrados ordinarios, OLS).

Metricas de ajuste global: R² (proporcao da variancia explicada pelo modelo, de 0 a 1), R² Ajustado (corrigido pelo numero de preditores — penaliza overfitting com variaveis irrelevantes), Erro Padrao da Regressao (dispersao tipica dos residuos). Metricas de erro preditivo: MAE (erro absoluto medio), MSE (erro quadratico medio), RMSE (raiz do MSE, na unidade original), MAPE (erro percentual medio), Variancia Explicada.

Tabela ANOVA completa com estatistica F e significancia global do modelo. Metricas de informacao AIC, AICc e BIC para comparacao entre modelos — valores menores indicam melhor equilibrio entre ajuste e parcimonia. Durbin-Watson para autocorrelacao serial dos residuos (valores proximos de 2 indicam ausencia). VIF (Variance Inflation Factor) para deteccao de multicolinearidade — VIF acima de 5 indica correlacao problematica entre preditores; acima de 10 e severo.

Grafico de dispersao Real vs Previsto com linha de referencia perfeita. Saida de residuos com destaque de outliers (residuo padronizado |z| > 2).

**Regressao Logistica** — classifica observacoes em categorias, sem restricao de quantidade de classes. O modelo estima a probabilidade de pertencimento a cada classe via funcao logistica (sigmoid para binario, softmax para multiclasse). Solver `lbfgs` com fallback para `saga` + StandardScaler quando a convergencia falha.

Significance Testing com Log-Likelihood Ratio Test: compara a verossimilhanca do modelo completo (LL1) contra o modelo nulo (LL0, apenas intercepto). A estatistica Chi-Quadrado = 2×(LL1 - LL0) testa se o conjunto de preditores melhora significativamente a classificacao. Pseudo R-Squared em tres variantes: McFadden (1 - LL1/LL0, mais conservador), Cox & Snell (penalizado pelo tamanho amostral, nunca atinge 1) e Nagelkerke (normalizado de Cox & Snell para variar de 0 a 1). AIC e BIC para selecao de modelo.

Tabela de coeficientes com Wald (quadrado da razao coeficiente/erro padrao), p-valor, Exp(B) ou Odds Ratio (multiplicador da chance — acima de 1 aumenta a probabilidade, abaixo de 1 diminui) e intervalos de confianca a 95% para Exp(B). Classification Table com percentual de acerto por classe e acuracia global. Curva ROC para classificacao binaria com AUC e estatistica KS (maxima separacao entre distribuicoes de positivos e negativos).

**Clusterizacao K-Means** — agrupamento nao supervisionado sem variavel alvo. O algoritmo particiona os dados em K grupos minimizando a distancia euclidiana intra-cluster (inertia). Os dados sao padronizados via StandardScaler antes da clusterizacao para evitar que variaveis com maior escala dominem a distancia.

Selecao automatica de K via Silhouette Score (mede quao similar cada ponto e ao seu cluster vs o cluster mais proximo — varia de -1 a +1, valores altos indicam clusters bem separados) ou definicao manual (2-20). Metricas adicionais: Calinski-Harabasz (razao variancia inter/intra-cluster — maior e melhor), Davies-Bouldin (media da similaridade entre clusters — menor e melhor).

Grafico do Metodo do Cotovelo com curvas duais (inertia e silhouette), com justificativa automatica da selecao do K. Matriz de distancia euclidiana entre centroides renderizada como heatmap. Perfis de cluster com medias por variavel para interpretacao dos agrupamentos. Scatter plot dos dois primeiros atributos com cores por cluster.

**PCA (Analise de Componentes Principais)** — reducao de dimensionalidade nao supervisionada. PCA transforma um conjunto de variaveis possivelmente correlacionadas em um conjunto menor de variaveis nao correlacionadas (componentes principais) que capturam a maxima variancia dos dados originais.

**Fundamento matematico** — PCA calcula os autovetores (direcoes de maxima variancia) e autovalores (magnitude da variancia em cada direcao) da matriz de covariancia dos dados padronizados. Cada componente principal e uma combinacao linear das variaveis originais. O primeiro componente captura a maior variancia possivel; o segundo captura a maior variancia restante ortogonal ao primeiro, e assim por diante.

**Aplicacoes** — reducao de dimensionalidade para visualizacao (projetar dados multidimensionais em 2D/3D), pre-processamento para modelos de machine learning (remover multicolinearidade), deteccao de padroes latentes (fatores nao observaveis que explicam a estrutura dos dados), compressao de informacao (representar dados complexos com menos variaveis sem perda significativa).

Tabela de eigenvalues com variancia explicada individual e acumulada por componente. Selecao automatica de componentes pelo criterio de 80% da variancia acumulada. Criterio de Kaiser (reter componentes com eigenvalue > 1 — indicando que explicam mais variancia que uma unica variavel original padronizada).

Scree Plot dual (barras de variancia individual + linha de acumulada) para identificacao visual do "cotovelo". Matriz de Loadings (componentes × features) renderizada como heatmap — loadings altos indicam quais variaveis originais mais contribuem para cada componente. Top Contributors por componente com barras direcionais (positivo/negativo).

Biplot — projecao das observacoes no espaco PC1 × PC2 com vetores das variaveis originais sobrepostos. A direcao do vetor indica como a variavel se alinha com os componentes; o comprimento indica a contribuicao; o angulo entre vetores indica correlacao (angulo pequeno = correlacao positiva, 90° = independentes, 180° = correlacao negativa).

**AutoML** — torneio automatico de multiplos modelos. Quando AutoGluon esta instalado, utiliza seu motor de ensemble com presets de qualidade configuraveis. Caso contrario, executa torneio scikit-learn com 9-10 algoritmos candidatos (Ridge, Lasso, ElasticNet, Random Forest, Gradient Boosting, Extra Trees, Decision Tree, KNN, SVM, MLP) via validacao cruzada 5-fold.

Detecta automaticamente o tipo de tarefa (regressao para alvos numericos com mais de 10 valores unicos, classificacao binaria ou multiclasse para os demais). Leaderboard rankeado por metrica primaria (R² para regressao, AUC-ROC para classificacao). Feature importance do melhor modelo. Re-fit do vencedor em dados completos para metricas finais.

### Analise Avancada — Inferencia Causal

Cinco metodos para identificacao de relacoes causais entre variaveis, acessiveis na aba "Inferencia Causal" da analise avancada.

**Fundamento** — correlacao nao implica causalidade. A analise preditiva identifica padroes de associacao, mas nao distingue se X causa Y, se Y causa X, ou se uma terceira variavel Z causa ambos. A inferencia causal aplica tecnicas estatisticas especificas para estimar efeitos causais a partir de dados observacionais (nao experimentais), aproximando-se da logica de ensaios controlados randomizados.

**Grafo Causal (DAG)** — constroi o esqueleto de um Grafo Aciclico Direcionado via correlacoes parciais e teste Fisher-z. A correlacao parcial mede a associacao entre duas variaveis controlando (removendo) o efeito de todas as demais. Se a correlacao parcial entre A e B e significativa apos controlar C, D, E..., isso sugere uma ligacao direta no grafo. Implementacao baseada na etapa 0 do algoritmo PC (Peter-Clark).

Saidas: heatmap de correlacoes parciais, lista de arestas significativas com p-valor, manto de Markov (vizinhos diretos) e grau de centralidade por variavel. O nivel de significancia α e configuravel (0.01, 0.05, 0.10).

**Propensity Score Matching (PSM)** — estima o Efeito Medio do Tratamento nos Tratados (ATT) equilibrando grupos via Regressao Logistica + matching 1:1 por vizinho mais proximo. O propensity score e a probabilidade estimada de receber o tratamento dado um conjunto de covariaveis. Ao parear cada unidade tratada com a unidade controle mais proxima em termos de propensity score, o metodo simula a randomizacao de um experimento.

Saidas: ATT com intervalo de confianca e p-valor (teste t pareado), tabela de balanco de covariaveis com Standardized Mean Difference antes e apos matching (SMD < 0.10 indica balanceamento adequado), distribuicao dos propensity scores por grupo.

**Analise de Mediacao** — decomposicao de Baron-Kenny com Teste de Sobel e intervalo de confianca Bootstrap. A mediacao investiga se o efeito de X sobre Y ocorre indiretamente atraves de uma variavel intermediaria M (mediador). O efeito total (c) e decomposto em efeito direto (c', caminho X→Y controlando M) e efeito indireto (a×b, produto do caminho X→M pelo caminho M→Y|X).

O Teste de Sobel avalia a significancia estatistica do efeito indireto. Como sua distribuicao pode ser nao-normal, o IC Bootstrap 95% (500 ou 1000 reamostragens) fornece inferencia mais robusta — se o intervalo nao contem zero, o efeito indireto e significativo. A proporcao mediada (indireto/total) indica quanto do efeito de X sobre Y transita pelo mediador.

Saidas: diagrama de caminhos com coeficientes, tabela de estimativas com erro padrao e p-valor, distribuicao bootstrap do efeito indireto com heatmap de significancia.

**Controle Sintetico** — estima o contrafactual de uma unidade tratada combinando unidades doadoras de forma otima no pre-tratamento. O metodo constroi uma versao "sintetica" da unidade tratada como media ponderada de unidades nao tratadas, onde os pesos sao otimizados para minimizar a diferenca entre a unidade real e a sintetica no periodo pre-intervencao.

**Fundamento** — desenvolvido por Abadie e Gardeazabal (2003) e Abadie, Diamond e Hainmueller (2010), o controle sintetico e a tecnica padrao para avaliacao de impacto de intervencoes em estudos de caso unico (uma cidade, uma empresa, um pais). A qualidade e medida pelo RMSE pre-tratamento — quanto menor, melhor o contrafactual sintetico aproxima a realidade observada antes da intervencao.

Saidas: serie temporal real vs sintetica, gap (diferenca) periodo a periodo, ATT medio pos-intervencao, pesos dos doadores rankeados.

**Variavel Instrumental (2SLS)** — Two-Stage Least Squares para estimacao do LATE (Local Average Treatment Effect) quando o tratamento e endogeno (correlacionado com o erro). O instrumento Z deve satisfazer duas condicoes: relevancia (Z afeta o tratamento D) e exclusao (Z afeta o resultado Y apenas atraves de D).

1ª Etapa: regride D sobre Z (e controles) para obter D-chapeu (predito). A estatistica F da 1ª etapa mede a forca do instrumento — F ≥ 10 e considerado forte (Staiger-Stock rule). 2ª Etapa: regride Y sobre D-chapeu (e controles) para obter o LATE, que representa o efeito causal do tratamento para a subpopulacao de "compliantes" (afetados pelo instrumento).

Teste de Hausman compara OLS (potencialmente viesado por endogeneidade) com 2SLS. Se p < 0.10, ha evidencia de endogeneidade e o OLS e inconsistente — o 2SLS deve ser preferido.

Saidas: F da 1ª etapa com classificacao de forca, LATE com IC 95%, comparacao LATE vs OLS, forma reduzida (Z→Y), Hausman chi² e conclusao sobre endogeneidade.

### Tabela de Coeficientes — Inferencia Estatistica

Para regressao linear e logistica, o sistema calcula e exibe uma tabela completa de inferencia para cada variavel (incluindo intercepto), com colunas: Coeff (B), S.E. (erro padrao), Wald/t (estatistica de teste), p-valor, Exp(B), Inferior e Superior (IC 95%), e VIF (apenas regressao linear). Variaveis significativas (p < 0.05) sao destacadas com indicador visual. Tooltips interativos explicam cada coluna contextualizado ao tipo de modelo.

A tabela utiliza pseudo-inversa de Moore-Penrose (pinv) como fallback para matrizes singulares ou quase-singulares, garantindo que todas as variaveis aparecem mesmo em condicoes de multicolinearidade severa.

### Recomendacao de Variaveis

Logo abaixo da tabela de coeficientes, o sistema gera automaticamente uma recomendacao baseada na significancia estatistica. Lista as variaveis significativas ordenadas por p-valor (mais relevantes primeiro), com direcao do efeito e Exp(B). Identifica variaveis nao significativas e sugere remocao para simplificacao do modelo, seguindo o principio da parcimonia (Navalha de Occam aplicada a modelagem estatistica).

### Exportacao e Email

Qualquer resultado de consulta pode ser exportado para `.xlsx` com um clique. O sistema tambem gera arquivos `.eml` para envio via Outlook local — ao clicar em "Enviar Email", o sistema monta um arquivo `.eml` com destinatario, assunto, corpo HTML e anexo Excel embutido. O header `X-Unsent: 1` faz com que o Outlook abra o arquivo como rascunho pronto para envio, sem necessidade de configuracao de servidor ou credenciais.

### API Externa

Endpoint REST (`/api/v1/query`) para integracao com sistemas externos. Autenticacao via header `X-API-Key` com hash SHA256 + salt (independente da autenticacao por sessao). Chaves sao geradas e gerenciadas pela interface administrativa. Permite que aplicacoes terceiras consultem os dados usando a mesma infraestrutura de linguagem natural.

### Historico de Consultas

Todas as consultas sao registradas automaticamente com pergunta original, SQL gerado, resumo dos resultados e tipo de analise utilizado. Acessivel via interface para revisao e auditoria.



---

## 1. Arquitetura Geral

```
┌─────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (SPA)                             │
│        default.html — Tailwind CSS, Chart.js, SheetJS, fetch()      │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Query    │  │  Explorar│  │  Skills  │  │ DataMarts│  ...        │
│  │ (NL→SQL) │  │ PyGWalker│  │  Editor  │  │  Admin   │             │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘             │
│        │             │             │             │                  │
└────────┼─────────────┼─────────────┼─────────────┼──────────────────┘
         │             │             │             │
     REST API (FastAPI)  /api/*
         │             │             │             │
┌────────┼─────────────┼─────────────┼─────────────┼──────────────────┐
│  ┌─────▼────┐  ┌─────▼────┐  ┌─────▼────┐  ┌─────▼────┐             │
│  │  agent   │  │   viz    │  │ database │  │ security │             │
│  │ _service │  │ _service │  │  .py     │  │  .py     │             │
│  └─────┬────┘  └──────────┘  └─────┬────┘  └──────────┘             │
│        │                           │                                │
│  ┌─────▼───────────────────────────▼────┐                           │
│  │            SQLite Database           │                           │
│  │  (dados do usuário + metadados)      │                           │
│  └──────────────────────────────────────┘                           │
│                                                                     │
│  ┌──────────────────────────────────────┐                           │
│  │   LangGraph StateGraph (Deep Agent)  │                           │
│  │  agent_node ←→ ToolNode (SQL tools)  │                           │
│  │       ↕ OpenAI GPT-4.1               │                           │
│  └──────────────────────────────────────┘                           │
│                                                                     │
│  ┌──────────────────────────────────────┐                           │
│  │   Langfuse (observabilidade)         │  ← opcional               │
│  └──────────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

O ciclo fundamental: **Pergunta (NL) → Deep Agent (LangGraph) → SQL → SQLite → Dados → Explicação + Visualização**.

O Deep Agent opera como um grafo cíclico de dois nós (`agent` ↔ `tools`). O nó `agent` raciocina com o LLM e emite tool calls. O nó `tools` executa as ferramentas SQL e devolve resultados ao `agent`. O ciclo repete até o agente emitir uma mensagem final sem tool calls.

---

## 2. Stack Tecnológico

| Camada | Tecnologia | Função |
|---|---|---|
| **Runtime** | Python 3.11+ | Linguagem principal |
| **Framework Web** | FastAPI | API REST assíncrona, validação Pydantic |
| **LLM** | OpenAI GPT-4.1 (configurável) | Geração de SQL, análise, explicações |
| **Orquestração** | LangGraph (StateGraph) | Grafo de agente com ciclo agent↔tools |
| **SQL Toolkit** | langchain-community SQLDatabaseToolkit | Ferramentas `sql_db_query`, `sql_db_schema`, `sql_db_list_tables` |
| **Banco de Dados** | SQLite | Armazenamento unificado (dados + metadados) |
| **ORM/Engine** | SQLAlchemy (engine only) | Conexão para toolkit; metadados via sqlite3 raw |
| **Exploração Visual** | PyGWalker | Drag-and-drop no Explorar (Tableau-like) |
| **Gráficos** | Chart.js | Renderização interativa no browser |
| **Parsing Excel** | openpyxl, pandas | Upload e importação de dados |
| **Parsing Client** | SheetJS (cdnjs) | Anexar arquivo no Explorar (client-side) |
| **Observabilidade** | Langfuse | Tracing de LLM, custos, latência |
| **Frontend** | HTML + Tailwind CSS + vanilla JS | SPA single-file |
| **Configuração** | pydantic-settings + .env | Variáveis de ambiente tipadas |
| **YAML** | PyYAML (transitiva via langchain) | Parser de frontmatter em SKILL.md |

---

## 3. Variáveis de Ambiente

Todas as variáveis são configuradas via arquivo `.env` na raiz do projeto. O `pydantic-settings` carrega e valida automaticamente.

| Variável | Tipo | Default | Descrição |
|---|---|---|---|
| `OPENAI_API_KEY` | `str` | `""` | Chave da API OpenAI. Obrigatória para o Deep Agent, AI Ask Bar e Gerador de Skills |
| `OPENAI_MODEL` | `str` | `gpt-4.1` | Modelo OpenAI utilizado em todas as chamadas LLM. Aceita qualquer modelo compatível com a API |
| `DATABASE_URL` | `str` | `sqlite:///data/quick_insights.db` | Connection string SQLAlchemy. Usado pelo toolkit SQL |
| `API_SALT` | `str` | `default-salt` | Salt para hashing de API keys |
| `API_SECRET_KEY` | `str` | `default-secret` | Chave secreta para geração de API keys |
| `SESSION_SECRET` | `str` | `qi-session-secret-change-me` | Segredo para tokens de sessão |
| `COOKIE_SECURE` | `bool` | `false` | `true` para cookies HTTPS-only (produção) |
| `LANGFUSE_SECRET_KEY` | `str` | `""` | Secret key Langfuse (vazio = desabilitado) |
| `LANGFUSE_PUBLIC_KEY` | `str` | `""` | Public key Langfuse |
| `LANGFUSE_HOST` | `str` | `https://cloud.langfuse.com` | Endpoint Langfuse (self-hosted ou cloud) |
| `HOST` | `str` | `0.0.0.0` | Endereço de bind do servidor |
| `PORT` | `int` | `8000` | Porta do servidor |

### Paths implícitos (derivados de `BASE_DIR`)

| Path | Valor | Descrição |
|---|---|---|
| `project_dir` | raiz do projeto | Diretório base |
| `upload_dir` | `{BASE_DIR}/uploads/` | Destino dos uploads Excel |
| `templates_dir` | `{BASE_DIR}/app/templates/` | Templates HTML (Jinja2) |
| `static_dir` | `{BASE_DIR}/app/static/` | Arquivos estáticos |
| `agents_md` | `{BASE_DIR}/AGENTS.md` | Identidade e instruções globais do agente |
| `skills_dir` | `{BASE_DIR}/skills/` | Skills de filesystem (`skills/{name}/SKILL.md`) |
| `db_path` | `{BASE_DIR}/data/quick_insights.db` | Caminho físico do banco SQLite |

---

## 4. Modelo de Dados Interno

O SQLite armazena **dados do usuário** (tabelas importadas via Excel) e **metadados** (configurações, skills, histórico). As tabelas internas são protegidas e invisíveis para o agente.

### Tabelas internas (protegidas)

```
INTERNAL_TABLES = {
    "analysis_types", "api_keys", "query_history", "analysis_gallery",
    "users", "sessions", "custom_skills", "sqlite_sequence",
    "datamarts", "datamart_tables", "user_datamarts", "saved_questions",
}
```

### Schema das tabelas internas

#### `users`
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | `INTEGER PK` | Identificador único |
| `login` | `TEXT UNIQUE NOCASE` | Login do usuário (case-insensitive) |
| `password_hash` | `TEXT` | Hash bcrypt da senha |
| `user_type` | `TEXT` | `root`, `superuser`, `admin` ou `user` |
| `display_name` | `TEXT` | Nome de exibição |
| `profile_description` | `TEXT` | Descrição do perfil |
| `is_active` | `INTEGER` | 1 = ativo, 0 = desabilitado |
| `created_at` | `TIMESTAMP` | Data de criação |
| `updated_at` | `TIMESTAMP` | Data da última atualização |

#### `sessions`
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | `INTEGER PK` | Identificador |
| `token` | `TEXT UNIQUE` | Token opaco da sessão |
| `user_id` | `INTEGER FK` | Referência ao usuário |
| `expires_at` | `TIMESTAMP` | Expiração (24h por padrão) |

#### `custom_skills`
| Coluna | Tipo | Default | Descrição |
|---|---|---|---|
| `id` | `INTEGER PK` | — | Identificador |
| `name` | `TEXT UNIQUE` | — | Nome slug da skill (`analise-financeira`) |
| `description` | `TEXT` | `''` | Descrição curta (1 linha) |
| `content` | `TEXT` | `''` | Conteúdo SKILL.md completo (com ou sem YAML frontmatter) |
| `triggers` | `TEXT` | `'[]'` | JSON array de palavras-chave para auto-detecção |
| `trust_level` | `INTEGER` | `1` | Nível de confiança (1-3). Preparado para governança |
| `priority` | `INTEGER` | `10` | Prioridade no roteamento — maior = preferido em caso de empate |
| `is_active` | `INTEGER` | `1` | 1 = habilitada, 0 = desabilitada |
| `created_by` | `TEXT` | `''` | Login do criador |
| `created_at` | `TIMESTAMP` | agora | Data de criação |
| `updated_at` | `TIMESTAMP` | agora | Última atualização |

#### `analysis_types`
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | `INTEGER PK` | Identificador |
| `name` | `TEXT UNIQUE` | Nome do tipo de análise |
| `system_prompt` | `TEXT` | System prompt injetado no agente |
| `guardrails_input` | `TEXT` | Restrições de entrada (validação antes do LLM) |
| `guardrails_output` | `TEXT` | Restrições de saída (formatação pós-LLM) |

#### `api_keys`
| Coluna | Tipo | Descrição |
|---|---|---|
| `key_hash` | `TEXT UNIQUE` | Hash SHA-256 + salt da API key |
| `label` | `TEXT` | Rótulo descritivo |
| `is_active` | `INTEGER` | 1 = ativa |

#### `query_history`
| Coluna | Tipo | Descrição |
|---|---|---|
| `question` | `TEXT` | Pergunta em linguagem natural |
| `sql_generated` | `TEXT` | SQL gerado pelo agente |
| `result_summary` | `TEXT` | Resumo da resposta (primeiros 500 chars) |
| `analysis_type_id` | `INTEGER FK` | Tipo de análise usado |

#### `analysis_gallery`
| Coluna | Tipo | Descrição |
|---|---|---|
| `title` | `TEXT` | Título da análise salva |
| `description` | `TEXT` | Descrição |
| `query_data` | `TEXT` | JSON com `{columns, rows}` |
| `chart_config` | `TEXT` | JSON com localStorage do PyGWalker |
| `page_html` | `TEXT` | HTML completo da página capturada |
| `share_token` | `TEXT UNIQUE` | Token de 12 chars para compartilhamento público |

#### `datamarts`
| Coluna | Tipo | Descrição |
|---|---|---|
| `name` | `TEXT UNIQUE NOCASE` | Nome do DataMart (`default` é protegido contra exclusão) |
| `description` | `TEXT` | Descrição |

#### `datamart_tables`
| Coluna | Tipo | Descrição |
|---|---|---|
| `datamart_id` | `INTEGER FK` | Referência ao DataMart |
| `table_name` | `TEXT` | Nome da tabela associada |
| **UNIQUE** | `(datamart_id, table_name)` | Impede duplicação |

#### `user_datamarts`
| Coluna | Tipo | Descrição |
|---|---|---|
| `user_id` | `INTEGER FK` | Referência ao usuário |
| `datamart_id` | `INTEGER FK` | Referência ao DataMart |
| **UNIQUE** | `(user_id, datamart_id)` | Impede duplicação |

#### `saved_questions`
| Coluna | Tipo | Descrição |
|---|---|---|
| `user_id` | `INTEGER FK` | Dono da pergunta |
| `question` | `TEXT` | Texto da pergunta |
| `label` | `TEXT` | Rótulo opcional |
| `sql_generated` | `TEXT` | SQL gerado (sem LIMIT) — para reuso direto |

### Migração automática

O `init_metadata_tables()` executa `ALTER TABLE ... ADD COLUMN` para colunas ausentes em bancos existentes. As migrações são aditivas e idempotentes — o sistema detecta a ausência da coluna via `SELECT` e adiciona se necessário.

---

## 5. Deep Agent — Motor de Linguagem Natural para SQL

### Conceito

O Deep Agent é um grafo LangGraph (`StateGraph`) com dois nós e um ciclo condicional:

```
START → agent ←→ tools → END
```

O nó `agent` recebe o estado, compõe um system prompt massivo com todas as instruções (identidade, skills, schema, guardrails), e invoca o LLM com tool binding. Se o LLM retorna tool calls, o fluxo vai para `tools`. Caso contrário, termina.

### `AgentState` (TypedDict)

| Campo | Tipo | Descrição |
|---|---|---|
| `messages` | `list` (Annotated com `add_messages`) | Histórico completo de mensagens — LangGraph acumula automaticamente |
| `sql_query` | `str` | SQL gerado (preenchido durante execução) |
| `query_result` | `dict` | Resultado da execução |
| `analysis_type_id` | `int \| None` | Tipo de análise selecionado |
| `skill_ids` | `list[int] \| None` | IDs das skills ativadas (manual ou auto) |
| `accessible_tables` | `list[str] \| None` | Tabelas acessíveis (filtro DataMart) |

### Composição do System Prompt

O `agent_node` monta o system prompt concatenando, nesta ordem:

1. **Analysis Type system_prompt** — instrução base configurável por tipo de análise
2. **AGENTS.md** — identidade e instruções globais do agente (arquivo na raiz)
3. **Skills Summary** — resumo das skills de filesystem (`skills/{name}/SKILL.md`)
4. **Query Writing Skill** — instruções para geração de SQL (`skills/query-writing/SKILL.md`)
5. **Schema Exploration Skill** — instruções para exploração de schema
6. **Skills Level 1** — metadata de TODAS as skills ativas (~30 tokens cada)
7. **Skills Level 2** — corpo completo das skills ativadas (selecionadas ou auto-detectadas)
8. **Table Restriction** — restrição de tabelas por DataMart (quando aplicável)
9. **Database Schema** — descrição textual de todas as tabelas acessíveis com colunas e tipos
10. **Guardrails de Entrada** — validações pré-LLM
11. **Guardrails de Saída** — formatação pós-LLM

### SQL Tools (via SQLDatabaseToolkit)

O toolkit LangChain fornece automaticamente as ferramentas:

| Ferramenta | Função |
|---|---|
| `sql_db_query` | Executa SQL e retorna resultados |
| `sql_db_schema` | Retorna DDL de tabelas específicas |
| `sql_db_list_tables` | Lista tabelas disponíveis |

O LLM decide quais ferramentas usar e em que ordem. O ciclo agent↔tools permite múltiplas iterações: o agente pode explorar o schema, executar uma query, verificar resultados e refinar.

### `run_query()` — Orquestrador principal

Parâmetros:

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `question` | `str` | Pergunta em linguagem natural |
| `analysis_type_id` | `int \| None` | Tipo de análise para carregar system prompt específico |
| `context` | `str \| None` | Contexto de conversa anterior (multi-turn) |
| `result_limit` | `int \| None` | Limite de registros (default 20, 0 = ilimitado) |
| `user_login` | `str` | Login do usuário (para tracing Langfuse) |
| `skill_ids` | `list[int] \| None` | Skills manualmente selecionadas |
| `accessible_tables` | `list[str] \| None` | Tabelas filtradas por DataMart |
| `saved_sql` | `str \| None` | SQL salvo para execução direta (pula o agente) |

Fluxo interno:

1. **Fast path**: se `saved_sql` é fornecido e não vazio, aplica LIMIT e executa direto. Se falhar (schema mudou), cai no fluxo normal.
2. **Skill Router**: se nenhuma skill foi selecionada manualmente, `_skill_router(question)` tenta auto-detectar skills relevantes por keywords.
3. **Invocação do agente**: monta mensagens (contexto + pergunta), invoca o grafo LangGraph.
4. **Extração de resultados**: percorre mensagens finais para extrair o último SQL executado e a resposta do agente.
5. **Execução SQL**: o SQL extraído é re-executado com `LIMIT` aplicado via `_apply_limit()`.
6. **Persistência**: grava em `query_history`.
7. **Retorno**: `{question, sql_generated, explanation, data, auto_skill_ids}`.

### `_apply_limit(sql, limit)` — Gestão de LIMIT

Regex `r'\s*\bLIMIT\s+\d+\b'` aplicada ao SQL:

- Se `limit` é None ou ≤ 0: remove qualquer LIMIT existente.
- Se LIMIT já existe: substitui pelo valor desejado.
- Se não existe: adiciona `LIMIT {limit}` ao final.

### Singleton

O agente é instanciado uma vez (`_agent`) e reutilizado. `reset_agent()` força reconstrução — chamado automaticamente quando novas tabelas são importadas.

---

## 6. Sistema de Skills — Progressive Disclosure

Baseado no paper **"Agent Skills for Large Language Models"** (Xu & Yan, arXiv:2602.12430v3, 2026).

### Conceito

Skills são blocos de conhecimento procedural que ampliam a capacidade do agente para domínios específicos. O desafio é: injetar muitas skills no contexto degrada a performance (distração, confusão, saturação de contexto). A solução é **progressive disclosure** — carregar apenas o necessário, quando necessário.

### Dois níveis de carregamento

#### Level 1 — Metadata (sempre carregado)

A função `_get_skills_level1_context()` gera um "índice" de TODAS as skills ativas: nome + descrição + até 5 triggers. Custo: ~30 tokens por skill. Sempre presente no system prompt.

Exemplo de output Level 1:
```
## Skills Disponíveis (Level 1 — metadata)
- **analise-financeira**: Análise de DRE e balanço patrimonial [triggers: financeiro, DRE, balanço, receita, EBITDA]
- **vendas-pipeline**: Análise de funil de vendas [triggers: vendas, pipeline, conversão, lead]
```

O agente "sabe que existe" sem consumir contexto com instruções completas.

#### Level 2 — Instruções procedurais (sob demanda)

A função `_get_custom_skills_context(skill_ids)` carrega o corpo completo apenas das skills ativadas. O YAML frontmatter é parseado e removido — só as instruções entram no contexto.

Ativação por:
- **Seleção manual**: usuário clica no Skill Picker antes de perguntar.
- **Auto-detecção**: Skill Router identifica skills relevantes por keywords.

### Formato SKILL.md

```yaml
---
name: analise-financeira
description: Análise de DRE e balanço patrimonial
triggers: [financeiro, DRE, balanço, receita, despesa, EBITDA]
trust_level: 1
priority: 10
---
## Quando Usar
...instruções procedurais...

## Métricas e Indicadores
...KPIs com fórmulas SQL...

## Padrões de Query
...exemplos SQL para SQLite...
```

### YAML Frontmatter — Metadados

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `name` | `string` | Sim | Slug kebab-case identificador da skill |
| `description` | `string` | Sim | Descrição curta (1 linha) — usada no Level 1 |
| `triggers` | `list[string]` | Não | Palavras-chave para auto-detecção. Se ausente, extraídas automaticamente |
| `trust_level` | `int` (1-3) | Não | Nível de confiança. 1 = padrão. Preparado para governança futura |
| `priority` | `int` | Não | Prioridade no roteamento (default 10). Desempate quando múltiplas skills ativam |

### Resolução de Triggers — Cascata

A função `_resolve_skill_triggers()` segue uma cascata de 3 níveis:

1. **Explícitos** — fornecidos via API/formulário (campo "Triggers" no editor).
2. **Frontmatter** — extraídos do YAML dentro do campo `content`.
3. **Auto-extraídos** — gerados por `_auto_extract_triggers(name, description)`: extrai palavras ≥ 4 caracteres, filtra stopwords em português, retorna até 15 palavras.

### Stopwords pt-BR

O sistema filtra stopwords comuns do português para evitar triggers inúteis:

```
"para", "como", "mais", "sobre", "todos", "entre", "quando", "cada",
"esse", "esta", "este", "isso", "isto", "aqui", "então", ...
```

### Parser de Frontmatter

`_parse_skill_frontmatter(content)` usa regex `r'^---\s*\n(.*?)\n---\s*\n?(.*)` com `re.DOTALL` para separar o bloco YAML do corpo. O YAML é parseado com `yaml.safe_load()`. Se PyYAML não estiver disponível ou o frontmatter for malformado, o fallback retorna o conteúdo inteiro como body.

### Skills de Filesystem vs Custom Skills

| Tipo | Armazenamento | Carregamento | Gestão |
|---|---|---|---|
| **Filesystem** | `skills/{name}/SKILL.md` | Sempre no system prompt (summary) | Edição manual de arquivos |
| **Custom** (banco) | Tabela `custom_skills` | Level 1 (metadata) + Level 2 (sob demanda) | Editor na UI, CRUD completo |

As skills de filesystem (`query-writing`, `schema-exploration`) são instruções fundamentais carregadas integralmente. As custom skills são dinâmicas e seguem progressive disclosure.

---

## 7. Skill Router — Auto-detecção sem LLM

### Conceito

Quando o usuário não seleciona skills manualmente, o Skill Router analisa a pergunta contra os triggers de todas as skills ativas usando scoring por keywords. Custo: zero tokens LLM. Tempo: <1ms.

### Algoritmo `_skill_router(question)`

1. **Tokenização**: extrai palavras ≥ 3 chars da pergunta (`re.findall(r'\b\w{3,}\b', question_lower)`).
2. **Scoring por trigger**: para cada trigger de cada skill ativa:
   - **Phrase match** (trigger multi-word está contido na pergunta): **3 pontos**
   - **Word match** (trigger é uma das palavras exatas da pergunta): **2 pontos**
   - **Substring match** (trigger ≥ 4 chars é substring de alguma palavra): **1 ponto**
3. **Ordenação**: score descendente, depois priority descendente.
4. **Corte**: retorna no máximo **3 skill IDs**.

O limite de 3 é um **phase transition safeguard** referenciado no paper (Li, 2026): acima de 3 skills simultâneas, a qualidade degrada por sobrecarga de contexto.

### Exemplo

Pergunta: "Qual a margem bruta por produto no último trimestre?"

| Skill | Triggers | Score |
|---|---|---|
| analise-financeira | `[financeiro, DRE, balanço, receita, margem, EBITDA]` | margem=2 → **2** |
| vendas-pipeline | `[vendas, pipeline, conversão, lead, produto]` | produto=2 → **2** |
| marketing-digital | `[campanha, lead, CAC, ROI]` | 0 → **descartada** |

Resultado: skills `analise-financeira` e `vendas-pipeline` auto-ativadas.

### Indicador no Frontend

Quando o Skill Router ativa skills, a resposta inclui `auto_skill_ids`. O frontend exibe um badge roxo:

> **Skills auto-detectadas: 2 skill(s) ativada(s) via Skill Router**

---

## 8. Wizard "Criar SKILL" — Geração com IA

### Conceito

O wizard guia o usuário por 3 passos para criar uma skill completa sem escrever Markdown manualmente. A IA (OpenAI) gera o SKILL.md a partir de um sumário estruturado.

### Fluxo do Wizard

**Step 1 — Contexto**:
- **Domínio**: dropdown com opções pré-definidas (Financeiro, Vendas, Marketing, RH, Operações, Produto, Saúde, Educação) ou "Outro" com campo livre.
- **Objetivo**: textarea obrigatória (min 10 chars). Descreve em linguagem natural o que a skill deve ensinar ao agente.

**Step 2 — Detalhes** (todos opcionais):
- **Métricas/KPIs**: separados por vírgula (ex: "receita líquida, margem bruta, EBITDA").
- **Contexto dos dados**: tabelas, colunas, períodos conhecidos.
- **Regras de negócio**: restrições, filtros obrigatórios, formatação.
- **Formato de resposta**: Auto, Detalhado, Conciso, Executivo ou Técnico.

**Step 3 — Gerar**:
- **Resumo visual**: todas as informações consolidadas para revisão.
- **Botão "Gerar SKILL.md com IA"**: envia ao endpoint `POST /api/skills/generate`.
- O resultado preenche automaticamente os 4 campos do editor (nome, descrição, triggers, conteúdo).
- O modal fecha e o editor fica visível para revisão e ajuste antes de salvar.

### Prompt de Geração

O sistema envia ao LLM um prompt estruturado (`_SKILL_GEN_PROMPT`) que instrui a geração de:

1. YAML frontmatter completo (name, description, triggers 5-10 palavras, trust_level, priority)
2. Seção "Quando Usar" — condições de ativação
3. Seção "Métricas e Indicadores" — KPIs com fórmulas SQL
4. Seção "Padrões de Query" — exemplos SQL para SQLite
5. Seção "Regras de Negócio" — restrições e formatação
6. Seção "Formato de Resposta" — estrutura da resposta ao usuário
7. Seção "Propostas de Análise" — 5 perguntas exemplo

Regras de geração enforçadas: SQL compatível com SQLite, português do Brasil, tabelas genéricas, conteúdo diretamente utilizável.

### Endpoint `POST /api/skills/generate`

| Campo do body | Tipo | Descrição |
|---|---|---|
| `domain` | `string` | Domínio de negócio |
| `objective` | `string` | Objetivo da skill (obrigatório, min 10 chars) |
| `metrics` | `string` | KPIs relevantes |
| `data_context` | `string` | Contexto dos dados |
| `rules` | `string` | Regras de negócio |
| `format` | `string` | `auto \| detailed \| concise \| executive \| technical` |

Retorno: `{name, description, triggers[], content}` ou `{error}`.

O `temperature=0.3` produz output determinístico com alguma variação criativa. O resultado é parseado via `_parse_skill_frontmatter()` para extrair metadados.

---

## 9. DataMarts — Governança de Acesso a Tabelas

### Conceito

DataMarts são agrupamentos lógicos de tabelas que controlam visibilidade. Um usuário só consulta as tabelas dos DataMarts aos quais está atribuído. O DataMart `default` existe sempre e não pode ser excluído.

### Hierarquia

```
DataMart (ex: "Financeiro")
  ├── tabela_receitas
  ├── tabela_despesas
  └── tabela_centros_custo

Usuário "analista.financeiro"
  └── DataMarts atribuídos: [Financeiro]
      → Vê apenas: receitas, despesas, centros_custo
```

### Restrição de Acesso no Agente

Quando `accessible_tables` é não-nulo, o system prompt inclui:

```
## RESTRIÇÃO DE ACESSO
Você só pode consultar as seguintes tabelas: receitas, despesas, centros_custo
NÃO tente acessar tabelas fora desta lista.
```

A restrição é semântica (no system prompt) + factual (o `get_table_schema_text()` filtra as tabelas visíveis).

### Exceção Root

Usuários `root` vêem todas as tabelas e todos os DataMarts. Quando um root seleciona DataMarts específicos, apenas essas tabelas ficam acessíveis na query.

### Upload com DataMart

`POST /api/upload?datamart_name=Financeiro` — o Excel é importado e cada sheet é automaticamente associada ao DataMart especificado.

---

## 10. Tipos de Análise — System Prompts Configuráveis

### Conceito

Cada tipo de análise é um perfil de comportamento do agente, definido por 3 campos de texto livre que moldam a geração de SQL e a narrativa da resposta.

### Campos

| Campo | Função | Exemplo |
|---|---|---|
| `system_prompt` | Instrução principal do agente — personalidade, estilo, idioma | "Você é um controller financeiro. Sempre calcule variação percentual entre períodos." |
| `guardrails_input` | Validação antes do LLM — restrições sobre o que pode ser consultado | "Apenas tabelas do domínio financeiro. Proibido consultar dados de RH." |
| `guardrails_output` | Formatação pós-LLM — como a resposta deve ser estruturada | "Formate valores em R$ com 2 casas decimais. Inclua gráfico de evolução mensal." |

### Default

Se nenhum tipo é selecionado, o agente usa o prompt padrão:

> "Você é um analista de dados especialista. Responda em português do Brasil. Gere SQL ANSI compatível com SQLite. Explique os resultados de forma clara."

---

## 11. Perguntas Salvas com SQL Reutilizável

### Conceito

Perguntas frequentes podem ser salvas. O diferencial: o SQL gerado na primeira execução é armazenado (sem LIMIT) e reutilizado nas execuções seguintes, eliminando chamadas ao LLM.

### Fluxo

1. Usuário faz uma pergunta → agente gera SQL → frontend captura em `lastSqlGenerated`.
2. Usuário clica "Salvar" → `POST /api/saved-questions` com `{question, label, sql_generated}`.
3. `_strip_sql_limit(sql)` remove `LIMIT N` do final via regex `r'\s+LIMIT\s+\d+\s*;?\s*$'` antes de salvar.
4. Ao reusar: `POST /api/query` com `saved_sql` → `run_query()` executa direto sem LLM.
5. Se o SQL salvo falhar (schema mudou), o sistema cai automaticamente no fluxo normal com agente.

### Deduplicação

Se o usuário salva uma pergunta que já existe (mesmo texto), o SQL é **atualizado** ao invés de criar duplicata. Assim, o SQL evolui conforme o usuário refaz a mesma pergunta.

### Indicador ⚡

No combobox de perguntas salvas e na tab Perguntas, um ícone ⚡ indica perguntas com SQL salvo, que executam sem custo de LLM.

---

## 12. Explorar — PyGWalker + AI Ask Bar

### PyGWalker (Drag-and-Drop)

O endpoint `POST /api/explore` recebe `{columns, rows}` e gera uma página HTML completa com PyGWalker embarcado. O PyGWalker transforma dados tabulares em uma interface estilo Tableau, com drag-and-drop de campos para eixos, filtros, e tipos de gráfico.

### AI Ask Bar (OpenAI)

Acima do PyGWalker, uma barra de input permite perguntas em linguagem natural como "Mostrar vendas por região em barras". O fluxo:

1. Frontend envia `POST /api/explore/ask` com `{prompt, json_data}`.
2. `ask_visualization_ai(data, prompt)` na `viz_service.py`:
   - Constrói schema do dataset: tipo de cada coluna, valores únicos, amostra de 3 linhas.
   - Envia prompt ao OpenAI com `temperature=0`.
   - Retorna JSON: `{chart_type, x, y, color, agg, explanation}`.
3. Frontend renderiza Chart.js inline com a configuração sugerida.

### Parâmetros de retorno da AI Ask

| Campo | Tipo | Valores | Descrição |
|---|---|---|---|
| `chart_type` | `string` | `bar`, `line`, `scatter`, `area`, `pie`, `doughnut`, `radar`, `polarArea` | Tipo de gráfico recomendado |
| `x` | `string` | nome de coluna | Eixo X |
| `y` | `string` | nome de coluna | Eixo Y (métrica) |
| `color` | `string` | nome de coluna ou `""` | Campo para agrupamento (gera múltiplos datasets) |
| `agg` | `string` | `sum`, `mean`, `count`, `min`, `max`, `none` | Agregação a aplicar |
| `explanation` | `string` | texto em português | Explicação do que o gráfico mostra |

### Anexar Arquivo

Botão "Anexar Arquivo" abre modal com:
- Drop zone para arrastar arquivo (.xlsx ou .csv).
- Seletor de modo: **Substituir** (apaga dados atuais) ou **Append** (merge).
- Parsing client-side via SheetJS para Excel, `FileReader` + split para CSV.
- Submissão via `POST /api/explore/open` com dados mesclados.

---

## 13. Gráficos — Chart.js com Recomendação por IA

### Recomendação automática

O endpoint `POST /api/chart` usa um prompt LLM (`_SPEC_PROMPT`) que analisa colunas, tipos e amostra dos dados para recomendar o melhor tipo de gráfico.

Regras de decisão do prompt:
- 1 dimensão + 1 métrica → `bar`
- Dimensão temporal + métrica → `line`
- 2 métricas → `scatter`
- Apenas métricas → `bar` com primeira coluna como eixo

### Gráfico tipado

`POST /api/chart/typed` permite selecionar o tipo manualmente:

Tipos suportados: `auto`, `bar`, `line`, `scatter`, `area`, `pie`, `doughnut`, `radar`, `polarArea`.

### Opções de campo

`POST /api/chart/options` analisa os dados e retorna as opções de campo X, Y e agregação disponíveis para a UI interativa de seleção.

---

## 14. Análise Avançada — Predição e Inferência Causal

### Modelos Preditivos (`POST /api/analytics/predict`)

| `model_type` | Algoritmo | Target | Descrição |
|---|---|---|---|
| `linear` | Regressão Linear | Numérico | Predição de valores contínuos |
| `logistic` | Regressão Logística | Categórico (binário) | Classificação binária |
| `clustering` | K-Means | Não requerido | Segmentação não-supervisionada |
| `automl` | Seleção automática | Numérico ou categórico | Testa múltiplos modelos e retorna o melhor |
| `pca` | Análise de Componentes Principais | Não requerido | Redução de dimensionalidade |

Parâmetros do `PredictionRequest`:
- `query_data`: `{columns, rows}` — dados de entrada.
- `target`: coluna alvo (Y). Vazio para clustering/PCA.
- `features`: lista de colunas features (X). Mínimo 1.
- `model_type`: tipo do modelo.
- `n_clusters`: quantidade de clusters para K-Means (0 = automático via silhouette score).

### Inferência Causal (`POST /api/analytics/causal`)

| `method` | Técnica | Descrição |
|---|---|---|
| `dag` | Grafo Acíclico Dirigido | Descobre relações causais entre variáveis usando testes de independência condicional |
| `psm` | Propensity Score Matching | Estima efeito de tratamento comparando grupos similares |
| `mediation` | Análise de Mediação | Decompõe efeito total em direto e indireto (via mediador) |
| `synthetic_control` | Controle Sintético | Estima contrafactual ponderando unidades de controle |
| `iv` | Variáveis Instrumentais (2SLS) | Estima causalidade usando instrumento exógeno |

Parâmetros do `CausalRequest.config` por método:

**DAG**: `{variables: [...], alpha: 0.05}` — lista de variáveis e nível de significância.

**PSM**: `{treatment: col, outcome: col, covariates: [...]}` — tratamento binário, resultado, covariáveis.

**Mediation**: `{exposure: col, mediator: col, outcome: col, n_bootstrap: 500}` — exposição, mediador, resultado, número de reamostragens.

**Synthetic Control**: `{unit_col, time_col, outcome_col, treated_unit, treatment_time}` — coluna de unidade, tempo, resultado, unidade tratada, momento do tratamento.

**IV**: `{instrument: col, treatment: col, outcome: col, covariates: [...]}` — instrumento, tratamento, resultado, covariáveis.

---

## 15. Galeria de Análises

### Conceito

Análises podem ser salvas na galeria para consulta posterior e compartilhamento externo via URL pública.

### Fluxo

1. `POST /api/gallery` salva título, descrição, dados (`query_data`), config do PyGWalker (`local_storage`), HTML da página e gera `share_token` (UUID hex 12 chars).
2. `GET /api/gallery/{token}/view` renderiza a análise. Se `page_html` existe, restaura o localStorage do PyGWalker via script injetado no `<head>`.
3. Se não há HTML salvo, gera visualização via `generate_gallery_view_html()` com Chart.js.

---

## 16. Autenticação e Controle de Acesso

### Hierarquia de Permissões

| Tipo | Pode | Não pode |
|---|---|---|
| `root` | Tudo. Vê todas as tabelas e DataMarts. Cria/edita root users | — |
| `superuser` | Gestão de usuários, skills, DataMarts | Criar users root |
| `admin` | CRUD de skills, analysis types, DataMarts, importação | Criar users root |
| `user` | Consultar, explorar, salvar perguntas | Administração |

### Sessão

- Login: `POST /api/auth/login` — valida bcrypt, cria token de sessão, seta cookie `qi_session` (HttpOnly, SameSite=Lax).
- TTL: 24h (`max_age=86400`).
- Logout: `POST /api/auth/logout` — destrói sessão e deleta cookie.
- Verificação: `GET /api/auth/check` — retorna estado de autenticação.
- Perfil: `GET /api/auth/me` — retorna dados do usuário, DataMarts e flag `is_root`.

### Dependencies FastAPI

```python
get_current_user   # Valida sessão, retorna user ou 401
require_admin      # Exige user_type in (root, superuser, admin)
require_root       # Exige user_type = root
```

---

## 17. API Externa (v1)

### Endpoint

`POST /api/v1/query`

### Autenticação

Header `X-API-Key` com chave gerada via UI (admin). A chave é hashada com SHA-256 + salt e armazenada em `api_keys`.

### Body

```json
{
  "question": "Qual o total de vendas por região?",
  "analysis_type_id": 1
}
```

### Resposta

```json
{
  "question": "...",
  "sql_generated": "SELECT ...",
  "explanation": "...",
  "data": {"columns": [...], "rows": [...], "row_count": N}
}
```

### Tracing

Queries via API key são logadas no Langfuse como `api-key:{primeiros 8 chars}`.

---

## 18. Observabilidade — Langfuse

### Integração

Se `LANGFUSE_SECRET_KEY` e `LANGFUSE_PUBLIC_KEY` estão configurados, cada invocação do agente gera traces no Langfuse via `langfuse.langchain.CallbackHandler`.

### Metadata enviado

| Campo | Valor |
|---|---|
| `langfuse_user_id` | Login do usuário ou `"anonymous"` |
| `langfuse_session_id` | `qi-{login}` |
| `langfuse_tags` | `["user:{login}"]` |
| `source` | `"quick-insights"` |

### O que rastrear

- Tokens consumidos por query.
- Latência do agente (total e por iteração).
- Tool calls realizadas (quais ferramentas SQL, quantas iterações).
- Custo estimado por modelo.
- Queries por usuário/período.

---

## 19. Segurança SQL

### Validação `_validate_select_only_sql(sql)`

1. Rejeita consultas vazias.
2. Rejeita múltiplas instruções (`;` no meio do SQL).
3. Aceita apenas `SELECT`, `WITH` e `PRAGMA`.
4. Proíbe tokens destrutivos: `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, `REPLACE`, `TRUNCATE`, `ATTACH`, `DETACH`.
5. Tokenização com `re.findall(r"[A-Z_]+", upper)` para detecção precisa.

### Proteção de nomes

- `_is_safe_identifier(name)`: regex `r"[A-Za-z_][A-Za-z0-9_]*"` — rejeita injeção via nomes de tabela.
- `_safe_table_name(name)`: mesma validação, lança HTTP 400 se inválido.

### Tabelas internas

O conjunto `INTERNAL_TABLES` é filtrado de todas as listagens e do schema enviado ao agente. O agente nunca "vê" tabelas de metadados.

---

## 20. Import/Export de Dados e Entidades

### Upload de Dados (Excel)

`POST /api/upload` — recebe `.xlsx` ou `.xls` (max 10MB). Cada sheet se torna uma tabela SQLite. Tabelas são associadas ao DataMart especificado via query param `datamart_name`. O agente é resetado automaticamente para reconhecer as novas tabelas.

### Export de Resultados

`POST /api/export/excel` — converte `{columns, rows}` em arquivo `.xlsx` para download.

### Email

`POST /api/email` — gera arquivo `.eml` com HTML body e anexo Excel opcional. O usuário abre no cliente de email local.

### Skills (Export/Import)

- `GET /api/skills/export/excel` — exporta todas as skills como `.xlsx` com colunas: name, description, content, is_active, created_by, created_at.
- `POST /api/skills/import` — importa skills de `.xlsx`. Cria novas, reporta erros de duplicação.

### Usuários (Export/Import)

- `GET /api/users/export/excel` — exporta todos os usuários como `.xlsx`.
- `POST /api/users/import` — importa de `.xlsx`. Cria com senha padrão `minhasenha01`, tipo `admin`, DataMart `default`.

### Perguntas Salvas (Export/Import)

- `GET /api/saved-questions/export` — exporta como `.xlsx` com colunas: label, question, sql_generated, user, created_at. Admin vê todas; user vê apenas suas.
- `POST /api/saved-questions/import` — importa de `.xlsx`. Aceita colunas `question`/`pergunta`, `label`/`rótulo`, `sql_generated`/`sql`. Deduplicação por texto da pergunta.

---

## 21. Referência Completa de Endpoints

### Autenticação (público)

| Método | Path | Descrição |
|---|---|---|
| `POST` | `/api/auth/login` | Login com credenciais |
| `POST` | `/api/auth/logout` | Logout |
| `GET` | `/api/auth/me` | Perfil do usuário autenticado |
| `GET` | `/api/auth/check` | Verificação de estado de autenticação |

### Consulta (Deep Agent)

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `POST` | `/api/query` | Sessão | Query em linguagem natural (ou SQL salvo) |
| `POST` | `/api/v1/query` | API Key | Query via API externa |

### Tabelas

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `GET` | `/api/tables` | Sessão | Lista tabelas (filtrada por DataMart) |
| `GET` | `/api/tables/{name}/preview` | — | Preview com LIMIT |
| `DELETE` | `/api/tables/{name}` | Admin | Exclui tabela de dados |
| `POST` | `/api/upload` | Admin | Upload de Excel para importação |

### DataMarts

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `GET` | `/api/datamarts` | Sessão | Lista todos os DataMarts |
| `POST` | `/api/datamarts` | Admin | Cria DataMart |
| `PUT` | `/api/datamarts/{id}` | Admin | Atualiza nome/descrição |
| `DELETE` | `/api/datamarts/{id}` | Admin | Exclui DataMart (exceto `default`) |
| `POST` | `/api/datamarts/{id}/tables` | Admin | Associa tabela ao DataMart |
| `DELETE` | `/api/datamarts/{id}/tables/{name}` | Admin | Remove associação |
| `GET` | `/api/datamarts/user` | Sessão | DataMarts do usuário atual |

### Tipos de Análise

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `GET` | `/api/analysis-types` | — | Lista tipos |
| `GET` | `/api/analysis-types/{id}` | — | Detalhe de um tipo |
| `POST` | `/api/analysis-types` | Admin | Cria tipo |
| `PUT` | `/api/analysis-types/{id}` | Admin | Atualiza tipo |
| `DELETE` | `/api/analysis-types/{id}` | Admin | Exclui tipo |

### Skills

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `GET` | `/api/skills` | — | Lista todas as skills |
| `GET` | `/api/skills/active` | — | Lista skills ativas |
| `GET` | `/api/skills/{id}` | — | Detalhe de uma skill |
| `POST` | `/api/skills` | Admin | Cria skill |
| `PUT` | `/api/skills/{id}` | Admin | Atualiza skill |
| `PUT` | `/api/skills/{id}/toggle` | Admin | Ativa/desativa skill |
| `DELETE` | `/api/skills/{id}` | Admin | Exclui skill |
| `POST` | `/api/skills/generate` | Admin | Gera SKILL.md com IA (wizard) |
| `GET` | `/api/skills/export/excel` | Admin | Exporta skills como Excel |
| `POST` | `/api/skills/import` | Admin | Importa skills de Excel |

### Explorar e Gráficos

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `POST` | `/api/explore` | — | Gera página PyGWalker |
| `POST` | `/api/explore/open` | — | Abre PyGWalker com dados (form) |
| `POST` | `/api/explore/ask` | Sessão | AI Ask Bar — NL → config de gráfico |
| `POST` | `/api/chart` | — | Gráfico auto (Chart.js com recomendação LLM) |
| `POST` | `/api/chart/open` | — | Gráfico com tipo selecionado (form) |
| `POST` | `/api/chart/typed` | — | Gráfico tipado (JSON body) |
| `POST` | `/api/chart/options` | — | Opções de campo para UI |

### Análise Avançada

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `POST` | `/api/analytics` | — | Gera página de análise avançada |
| `POST` | `/api/analytics/open` | — | Abre análise com dados (form) |
| `POST` | `/api/analytics/predict` | — | Executa modelo preditivo |
| `POST` | `/api/analytics/causal` | — | Executa inferência causal |

### Galeria

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `GET` | `/api/gallery` | — | Lista análises salvas |
| `POST` | `/api/gallery` | Sessão | Salva análise na galeria |
| `DELETE` | `/api/gallery/{id}` | Admin | Exclui item da galeria |
| `GET` | `/api/gallery/{token}/view` | Público | Visualiza análise compartilhada |

### Histórico

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `GET` | `/api/history?limit=N` | — | Últimas N queries (max 100) |

### Perguntas Salvas

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `GET` | `/api/saved-questions` | Sessão | Perguntas do usuário |
| `POST` | `/api/saved-questions` | Sessão | Salva pergunta com SQL |
| `PUT` | `/api/saved-questions/{id}` | Sessão | Atualiza rótulo |
| `DELETE` | `/api/saved-questions/{id}` | Sessão | Exclui pergunta |
| `GET` | `/api/saved-questions/all` | Sessão | Todas (admin) ou do usuário |
| `GET` | `/api/saved-questions/export` | Sessão | Exporta como Excel |
| `POST` | `/api/saved-questions/import` | Sessão | Importa de Excel |

### Usuários (Admin)

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `GET` | `/api/users` | Admin | Lista usuários |
| `POST` | `/api/users` | Admin | Cria usuário |
| `PUT` | `/api/users/{id}` | Admin | Atualiza usuário |
| `DELETE` | `/api/users/{id}` | Admin | Exclui usuário |
| `PUT` | `/api/users/{id}/password` | Admin | Altera senha |
| `GET` | `/api/users/export/excel` | Admin | Exporta usuários |
| `POST` | `/api/users/import` | Admin | Importa usuários |

### API Keys (Admin)

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `POST` | `/api/keys` | Admin | Cria API key |
| `GET` | `/api/keys` | Admin | Lista API keys |

### Email e Export

| Método | Path | Auth | Descrição |
|---|---|---|---|
| `POST` | `/api/email` | — | Gera arquivo .eml |
| `POST` | `/api/export/excel` | — | Exporta dados como Excel |

---

## 22. Estrutura de Arquivos

```
quick-insights/
├── .env                          # Variáveis de ambiente
├── AGENTS.md                     # Identidade e instruções globais do agente
├── README.md                     # Este documento
├── data/
│   └── quick_insights.db         # Banco SQLite (dados + metadados)
├── uploads/                      # Excel uploads temporários
├── skills/                       # Skills de filesystem
│   ├── query-writing/
│   │   └── SKILL.md              # Instruções para geração de SQL
│   └── schema-exploration/
│       └── SKILL.md              # Instruções para exploração de schema
├── app/
│   ├── core/
│   │   ├── config.py             # Settings (pydantic-settings + .env)
│   │   ├── database.py           # SQLite: init, CRUD, schema, skills, DataMarts
│   │   └── security.py           # Auth: bcrypt, sessions, API keys
│   ├── models/
│   │   └── schemas.py            # Pydantic models para validação de request/response
│   ├── services/
│   │   ├── agent_service.py      # Deep Agent: LangGraph, skills, run_query
│   │   ├── viz_service.py        # PyGWalker, Chart.js, AI Ask
│   │   ├── analytics_service.py  # Predição (sklearn) e Inferência Causal
│   │   ├── excel_service.py      # Importação de Excel → SQLite
│   │   └── email_service.py      # Geração de .eml
│   ├── api/
│   │   └── routes.py             # Todos os endpoints FastAPI
│   └── templates/
│       └── default.html          # Frontend SPA (Tailwind + vanilla JS)
└── main.py                       # Entrypoint (uvicorn)
```
## 23. Row-Level Security por Login
 
Mecanismo automático de segurança em nível de registro que garante isolamento de dados entre usuários dentro de uma mesma tabela.
 
**Fundamento** — em cenários onde múltiplos usuários compartilham uma mesma tabela (por exemplo, metas de vendas por vendedor, tarefas por colaborador, carteira de clientes por gerente), a segmentação por DataMart (que opera no nível de tabela) não é suficiente. O Row-Level Security (RLS) resolve esse problema operando no nível de registro: cada linha da tabela é filtrada pela identidade do usuário autenticado, garantindo que nenhum usuário acesse dados de outro.
 
**Detecção automática** — o sistema escaneia automaticamente as tabelas acessíveis ao usuário (filtradas por DataMart) buscando a presença de uma coluna chamada `login` (case-insensitive). A detecção ocorre a cada consulta, sem cache, garantindo que novas tabelas importadas com coluna `login` sejam protegidas imediatamente.
 
**Injeção no Deep Agent** — quando tabelas com coluna `login` são detectadas, uma diretiva de segurança é injetada no system prompt do agente com prioridade máxima:
 
```
## FILTRO OBRIGATÓRIO POR USUÁRIO — ROW-LEVEL SECURITY
As seguintes tabelas possuem a coluna "login": "metas_vendas", "tarefas"
REGRA INVIOLÁVEL: Sempre que consultar qualquer uma dessas tabelas,
você DEVE obrigatoriamente incluir o filtro:
  WHERE "login" = 'joao.silva'
Se a query já tiver cláusula WHERE, use:
  AND "login" = 'joao.silva'
Aplica-se a SELECT direto, JOINs, subqueries, CTEs e qualquer
forma de acesso a essas tabelas.
NUNCA omita este filtro — é uma regra de segurança obrigatória.
NUNCA mostre dados de outros usuários.
```
 
**Proteção de SQL salvo** — quando um usuário executa uma pergunta salva (fast path com SQL reutilizado), o sistema verifica se o SQL armazenado já contém o filtro de login do usuário autenticado. Se o filtro não estiver presente (SQL salvo antes da implementação do RLS, ou SQL salvo por outro usuário), o fast path é desabilitado e a consulta é forçada a passar pelo agente, que aplica a diretiva normalmente. Nas execuções subsequentes, o SQL gerado pelo agente (com o filtro) será salvo, restaurando o fast path.
 
**Escopo de aplicação:**
 
| Cenário | Filtro aplicado? |
|---|---|
| Usuário `user` consulta tabela COM coluna `login` | Sim — `WHERE "login" = '{user_login}'` |
| Usuário `admin` consulta tabela COM coluna `login` | Sim — `WHERE "login" = '{user_login}'` |
| Usuário `root` consulta tabela COM coluna `login` | Não — vê todos os registros |
| Qualquer usuário consulta tabela SEM coluna `login` | Não — sem filtro (tabela não tem RLS) |
| API externa (`/api/v1/query` com API key) | Não — sem sessão de usuário |
| SQL salvo com filtro já presente | Fast path mantido — sem custo de LLM |
| SQL salvo sem filtro de login | Forçado pelo agente — filtro injetado via system prompt |
 
**Exemplo prático:**
 
Tabela `metas_vendas` com colunas: `login`, `regiao`, `meta`, `realizado`, `periodo`.
 
Usuário `joao.silva` pergunta: "Qual meu percentual de atingimento por região?"
 
O agente gera:
```sql
SELECT regiao,
       SUM(realizado) AS total_realizado,
       SUM(meta) AS total_meta,
       ROUND(SUM(realizado) * 100.0 / SUM(meta), 1) AS pct_atingimento
FROM metas_vendas
WHERE "login" = 'joao.silva'
GROUP BY regiao
ORDER BY pct_atingimento DESC
```
 
O filtro `WHERE "login" = 'joao.silva'` é adicionado obrigatoriamente pelo agente, mesmo que o usuário não mencione "meus dados" — a diretiva no system prompt garante a aplicação automática.
 
**Implementação técnica:**
 
Função `get_tables_with_login_column(table_names)` em `database.py`:
- Recebe a lista de tabelas acessíveis (já filtrada por DataMart) ou `None` (todas as tabelas de usuário)
- Executa `PRAGMA table_info` em cada tabela candidata
- Retorna lista de nomes de tabelas que possuem coluna com `col[1].lower() == "login"`
- Exclui tabelas internas (`INTERNAL_TABLES`)
- Custo: zero tokens LLM, execução em <1ms
 
Campos adicionados ao `AgentState`:
- `login_filter_user: str` — login do usuário autenticado (vazio se root ou sem filtro)
- `login_filter_tables: list[str]` — tabelas com coluna `login` detectadas
 
Parâmetro adicionado ao `run_query()`:
- `apply_login_filter: bool = True` — `False` para root, `True` para todos os demais
 
**Segurança do mecanismo:**
 
O filtro opera em duas camadas complementares:
 
1. **Camada semântica (system prompt)** — o agente recebe instrução explícita e prioritária para sempre incluir `WHERE "login" = '{login}'`. A linguagem da diretiva usa termos como "INVIOLÁVEL", "NUNCA omita" e "regra de segurança obrigatória" para maximizar a adesão do LLM.
 
2. **Camada de invalidação (saved SQL)** — SQLs salvos que não contêm o login do usuário são rejeitados no fast path, forçando regeneração pelo agente com a diretiva ativa. Isso garante que SQLs legados (anteriores à implementação do RLS) ou SQLs salvos por outros usuários não vazem dados.

3. Configurar Row-Level Security
 
Nenhuma configuração é necessária. Basta importar uma planilha com coluna `login` contendo os logins dos usuários. O RLS é ativado automaticamente.
 
Exemplo de planilha:
 
| login | regiao | meta | realizado |
|---|---|---|---|
| joao.silva | Sul | 100000 | 85000 |
| joao.silva | Sudeste | 150000 | 162000 |
| maria.santos | Norte | 80000 | 72000 |
| maria.santos | Nordeste | 120000 | 118000 |
 
Quando `joao.silva` consulta: vê apenas as 2 primeiras linhas.
Quando `maria.santos` consulta: vê apenas as 2 últimas linhas.
Quando `root` consulta: vê todas as 4 linhas.

**Limitação conhecida** — o filtro depende do comportamento do LLM seguindo a diretiva no system prompt. Embora a linguagem da diretiva seja projetada para maximizar conformidade, não há validação programática pós-geração que verifique se o SQL gerado contém efetivamente a cláusula `WHERE "login" = ...`. Em cenários de altíssima sensibilidade, recomenda-se implementar validação adicional no `execute_readonly_sql()` para queries que tocam tabelas com coluna `login`.

```

---

## Stack Tecnologica

| Camada | Tecnologia | Funcao |
|---|---|---|
| Backend | Python 3.11 + FastAPI + Uvicorn | API REST assincrona |
| Deep Agent | deepagents + LangGraph + LangChain + OpenAI | Planejamento e execucao autonoma |
| SQL Toolkit | langchain-community SQLDatabaseToolkit + SQLAlchemy | Interacao com banco de dados |
| Machine Learning | scikit-learn + SciPy + NumPy + Pandas | Modelos preditivos, PCA e estatisticas |
| Inferencia Causal | SciPy (optimize, stats) + NumPy | PSM, Mediacao, Controle Sintetico, IV/2SLS |
| Banco de Dados | SQLite | Armazenamento local zero-config |
| Visualizacao | PyGWalker + Chart.js | Exploracao interativa + graficos |
| Frontend | HTML + Tailwind CSS + JavaScript | SPA com dark theme |
| Email | Python email (stdlib) + .eml | Outlook local via download |
| Autenticacao | PBKDF2-SHA256 + salt + sessoes httponly | Login, perfis, controle de acesso |
| API Keys | SHA256 + salt | Autenticacao REST externa |

---

## Endpoints da API

### Autenticacao

| Metodo | Rota | Acesso | Descricao |
|---|---|---|---|
| `POST` | `/api/auth/login` | Publico | Autenticar e criar sessao |
| `POST` | `/api/auth/logout` | Autenticado | Encerrar sessao |
| `GET` | `/api/auth/me` | Autenticado | Dados do usuario logado + DataMarts |
| `GET` | `/api/auth/check` | Publico | Verificar sessao + existencia de usuarios |

### Gerenciamento de Usuarios

| Metodo | Rota | Acesso | Descricao |
|---|---|---|---|
| `GET` | `/api/users` | Admin | Listar todos os usuarios (com DataMarts) |
| `POST` | `/api/users` | Admin | Criar novo usuario (com DataMarts) |
| `PUT` | `/api/users/{id}` | Admin | Atualizar dados do usuario (com DataMarts) |
| `PUT` | `/api/users/{id}/password` | Admin | Alterar senha |
| `DELETE` | `/api/users/{id}` | Admin | Excluir usuario |
| `GET` | `/api/users/export` | Admin | Exportar usuarios para Excel |
| `POST` | `/api/users/import` | Admin | Importar usuarios via Excel |

### DataMarts

| Metodo | Rota | Acesso | Descricao |
|---|---|---|---|
| `GET` | `/api/datamarts` | Autenticado | Listar todos os DataMarts |
| `POST` | `/api/datamarts` | Admin | Criar DataMart |
| `PUT` | `/api/datamarts/{id}` | Admin | Atualizar DataMart |
| `DELETE` | `/api/datamarts/{id}` | Admin | Excluir DataMart (exceto default) |
| `POST` | `/api/datamarts/{id}/tables` | Admin | Associar tabela ao DataMart |
| `DELETE` | `/api/datamarts/{id}/tables/{name}` | Admin | Remover tabela do DataMart |
| `GET` | `/api/datamarts/user` | Autenticado | DataMarts do usuario logado |

### Consulta e Dados

| Metodo | Rota | Acesso | Descricao |
|---|---|---|---|
| `GET` | `/` | Autenticado | Interface web (SPA) |
| `GET` | `/login` | Publico | Tela de login |
| `GET` | `/api/tables` | Autenticado | Listar tabelas (filtradas por DataMart) |
| `GET` | `/api/tables/{name}/preview` | Autenticado | Preview de uma tabela (ate 100 linhas) |
| `DELETE` | `/api/tables/{name}` | Admin | Excluir tabela (DROP TABLE) |
| `POST` | `/api/upload` | Admin | Upload de arquivo Excel (com DataMart) |
| `POST` | `/api/query` | Autenticado | Consulta em linguagem natural (com DataMarts) |
| `GET` | `/api/history` | Autenticado | Historico de consultas |

### Perguntas Salvas

| Metodo | Rota | Acesso | Descricao |
|---|---|---|---|
| `GET` | `/api/saved-questions` | Autenticado | Listar perguntas do usuario (combobox) |
| `GET` | `/api/saved-questions/all` | Autenticado | Listar com dados do usuario (tab Perguntas) |
| `GET` | `/api/saved-questions/export` | Autenticado | Exportar para Excel |
| `POST` | `/api/saved-questions` | Autenticado | Salvar nova pergunta |
| `POST` | `/api/saved-questions/import` | Autenticado | Importar via Excel |
| `PUT` | `/api/saved-questions/{id}` | Autenticado | Atualizar rotulo |
| `DELETE` | `/api/saved-questions/{id}` | Autenticado | Excluir (apenas proprias) |

### Analise e Visualizacao

| Metodo | Rota | Acesso | Descricao |
|---|---|---|---|
| `POST` | `/api/explore` | Autenticado | Gerar pagina PyGWalker (JSON body) |
| `POST` | `/api/explore/open` | Autenticado | Gerar pagina PyGWalker (form POST, nova aba) |
| `POST` | `/api/chart` | Autenticado | Gerar grafico Chart.js via LLM (JSON body) |
| `POST` | `/api/chart/open` | Autenticado | Gerar grafico Chart.js (form POST, nova aba) |
| `POST` | `/api/chart/typed` | Autenticado | Grafico com tipo selecionado |
| `POST` | `/api/chart/options` | Autenticado | Opcoes de grafico para os dados |
| `POST` | `/api/analytics` | Autenticado | Dashboard estatistico descritivo |
| `POST` | `/api/analytics/open` | Autenticado | Dashboard estatistico (form POST, nova aba) |
| `POST` | `/api/analytics/predict` | Autenticado | Modelo preditivo (linear/logistic/clustering/pca/automl) |
| `POST` | `/api/analytics/causal` | Autenticado | Inferencia causal (dag/psm/mediation/synthetic_control/iv) |

### Custom Skills

| Metodo | Rota | Acesso | Descricao |
|---|---|---|---|
| `GET` | `/api/skills` | Autenticado | Listar todas as skills |
| `GET` | `/api/skills/active` | Autenticado | Listar skills ativas |
| `POST` | `/api/skills` | Admin | Criar nova skill |
| `GET` | `/api/skills/{id}` | Autenticado | Obter skill especifica |
| `PUT` | `/api/skills/{id}` | Admin | Atualizar skill |
| `PUT` | `/api/skills/{id}/toggle` | Admin | Ativar/desativar skill |
| `DELETE` | `/api/skills/{id}` | Admin | Excluir skill |
| `GET` | `/api/skills/export/excel` | Admin | Exportar skills para Excel |
| `POST` | `/api/skills/import` | Admin | Importar skills via Excel |

### Galeria e Exportacao

| Metodo | Rota | Acesso | Descricao |
|---|---|---|---|
| `GET` | `/api/gallery` | Autenticado | Listar itens da galeria |
| `POST` | `/api/gallery` | Autenticado | Salvar visualizacao na galeria |
| `DELETE` | `/api/gallery/{id}` | Admin | Excluir item da galeria |
| `GET` | `/api/gallery/{token}/view` | Publico | Visualizar item publico via token |
| `POST` | `/api/export/excel` | Autenticado | Exportar dados para .xlsx |
| `POST` | `/api/email` | Autenticado | Gerar .eml para Outlook local |

### Configuracao e API Externa

| Metodo | Rota | Acesso | Descricao |
|---|---|---|---|
| `GET` | `/api/analysis-types` | Autenticado | Listar tipos de analise |
| `GET` | `/api/analysis-types/{id}` | Autenticado | Obter tipo de analise especifico |
| `POST` | `/api/analysis-types` | Admin | Criar tipo de analise |
| `PUT` | `/api/analysis-types/{id}` | Admin | Atualizar tipo de analise |
| `DELETE` | `/api/analysis-types/{id}` | Admin | Excluir tipo de analise |
| `POST` | `/api/keys` | Admin | Gerar nova API key |
| `GET` | `/api/keys` | Admin | Listar API keys |
| `POST` | `/api/v1/query` | API Key | Endpoint externo (autenticado via X-API-Key) |

---

## Autenticacao — Detalhamento Tecnico

### Middleware HTTP

Todas as requisicoes passam pelo middleware `auth_middleware` em `main.py`. Rotas publicas (login, auth/check, auth/login, static, gallery view, API v1) sao liberadas. Demais rotas exigem cookie de sessao valido — requisicoes de pagina redirecionam para `/login`, requisicoes de API retornam HTTP 401.

### Content Security Policy

O middleware `security_headers_middleware` aplica CSP restritivo na interface principal, permitindo CDNs especificos (Tailwind, marked.js, Google Fonts). Paginas autonomas (Explorar, Grafico, Analise Avancada, Galeria) sao excluidas do CSP para que PyGWalker e Chart.js carreguem seus proprios recursos externos livremente.

### Sessoes

Token gerado via `secrets.token_urlsafe(48)`. Armazenado na tabela `sessions` com `user_id` e `expires_at`. Cookie `qi_session` com flags `httponly`, `samesite=lax`, `max_age=86400` (24h). Sessoes expiradas sao limpas automaticamente a cada novo login.

### Primeiro Acesso

A funcao `authenticate_user()` verifica se a tabela `users` tem 0 registros. Se sim, cria o usuario com as credenciais fornecidas como `root` com display_name "Root" e descricao automatica. Todos os DataMarts existentes sao atribuidos ao Root.

### Hierarquia de Permissoes

| Acao | Root | Admin | User |
|---|---|---|---|
| Acesso a todas as tabelas | Sim | Apenas DataMarts atribuidos | Apenas DataMarts atribuidos |
| Gerenciar usuarios | Sim (incluindo outros Root) | Sim (exceto Root) | Nao |
| Criar/excluir DataMarts | Sim | Sim | Nao |
| Upload de Excel | Sim | Sim | Nao |
| Excluir tabelas | Sim | Sim | Nao |
| Gerenciar skills | Sim | Sim | Nao |
| Consultar dados | Sim (sem filtro) | Sim (filtrado) | Sim (filtrado) |
| Salvar/excluir perguntas | Sim (proprias) | Sim (proprias) | Sim (proprias) |
| Ver perguntas de outros | Sim | Sim | Nao |
| Exportar/importar usuarios | Sim | Sim | Nao |
| Exportar/importar skills | Sim | Sim | Nao |
| Exportar/importar perguntas | Sim (todas) | Sim (todas) | Sim (proprias) |

---

## Deep Agent

### Progressive Disclosure

O agente segue o padrao Deep Agents de carregamento progressivo para otimizar o uso de contexto:

**AGENTS.md** (sempre carregado) — identidade do agente, regras de seguranca (read-only, sem DDL/DML), formato de resposta (nunca reproduzir dados no texto), idioma (portugues brasileiro), guidelines de SQL.

**skills/** (carregados sob demanda):

`query-writing/SKILL.md` — workflow para escrita de SQL: queries simples (single-table) ate complexas (multi-table JOINs, subqueries, agregacoes). Inclui padroes de validacao, tratamento de erros e reformulacao automatica.

`schema-exploration/SKILL.md` — workflow para descoberta de estrutura: listar tabelas, examinar colunas, tipos, relacionamentos, conteudo amostral. Usado antes de queries complexas para entender o contexto.

**Custom Skills** (carregadas do banco) — skills criadas via interface sao injetadas no contexto do agente quando ativas ou selecionadas por consulta.

### Filtragem de Tabelas por DataMart

Quando o usuario nao e Root, o agente recebe uma secao `RESTRICAO DE ACESSO` no system prompt listando explicitamente quais tabelas pode consultar. O `get_table_schema_text()` recebe a lista de tabelas acessiveis e retorna apenas o schema dessas tabelas. O agente nao tem conhecimento de tabelas fora do escopo.

### Tools do Agente

| Tool | Descricao |
|---|---|
| `sql_db_list_tables` | Listar todas as tabelas disponiveis |
| `sql_db_schema` | Schema detalhado de uma tabela especifica |
| `sql_db_query` | Executar SQL read-only no banco |
| `sql_db_query_checker` | Validar sintaxe SQL antes da execucao |

### Seguranca do Agente

O agente opera em modo **read-only estrito**. Comandos DDL/DML (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `REPLACE`, `TRUNCATE`) sao bloqueados em duas camadas: nas instrucoes do AGENTS.md e na funcao `execute_readonly_sql()` que faz parsing de tokens antes da execucao.

---

## Schema do Banco de Dados

O SQLite armazena tanto os dados do usuario (tabelas criadas via upload de Excel) quanto as tabelas internas de metadados:

**`users`** — contas de usuario com login, password_hash (PBKDF2-SHA256+salt), user_type (root/superuser/admin/user), display_name, profile_description, is_active e timestamps.

**`sessions`** — sessoes ativas com token, user_id e expires_at. Sessoes expiradas sao removidas automaticamente.

**`datamarts`** — DataMarts com nome unico e descricao. O DataMart "default" e criado automaticamente.

**`datamart_tables`** — associacao entre DataMarts e tabelas (datamart_id, table_name). Unique constraint impede duplicidade.

**`user_datamarts`** — associacao entre usuarios e DataMarts (user_id, datamart_id). Unique constraint impede duplicidade.

**`custom_skills`** — skills customizadas com nome, descricao, conteudo Markdown, status ativo/inativo e autor.

**`saved_questions`** — perguntas salvas por usuario com question, label opcional e created_at. FK com CASCADE para users. Deteccao de duplicatas por (user_id, question).

**`analysis_types`** — tipos de analise customizados com system prompt, guardrails de entrada e saida.

**`api_keys`** — chaves de API com hash SHA256, label e status ativo/inativo.

**`query_history`** — registro de todas as consultas com pergunta, SQL gerado, resumo e tipo de analise.

**`analysis_gallery`** — visualizacoes salvas com dados, config do grafico, HTML completo do PyGWalker e token de compartilhamento.

Tabelas internas sao automaticamente excluidas das listagens e consultas do agente.

---

## Setup

### 1. Clone e crie o ambiente virtual

```bash
git clone <repo-url> quick-insights
cd quick-insights
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / Mac
```

### 2. Instale as dependencias

```bash
pip install -r requirements.txt
```

### 3. Configure o `.env`

```env
OPENAI_API_KEY=sk-sua-chave-aqui
OPENAI_MODEL=gpt-4.1
SESSION_SECRET=minha-chave-secreta-de-sessao
```

### 4. Execute

```bash
python run.py
```

Acesse **http://localhost:8000** — sera redirecionado para a tela de login. No primeiro acesso, as credenciais informadas criam automaticamente a conta Root com acesso total.

### 5. Deploy no Render

Para deploy no Render, configure a variavel de ambiente `PYTHON_VERSION=3.11.11` no dashboard do servico (Environment → Environment Variables). Isso evita incompatibilidades entre LangChain/Pydantic V1 e Python 3.14 que o Render pode selecionar por padrao.

---

## Variaveis de Ambiente

| Variavel | Obrigatoria | Padrao | Descricao |
|---|---|---|---|
| `OPENAI_API_KEY` | Sim | — | Chave da API OpenAI |
| `OPENAI_MODEL` | Nao | `gpt-4.1` | Modelo LLM utilizado pelo agente |
| `DATABASE_URL` | Nao | `sqlite:///data/quick_insights.db` | Connection string do banco |
| `API_SALT` | Nao | `default-salt` | Salt para hash SHA256 (API keys) |
| `API_SECRET_KEY` | Nao | `default-secret` | Chave secreta da aplicacao |
| `SESSION_SECRET` | Nao | `qi-session-secret-change-me` | Secret para gestao de sessoes |
| `COOKIE_SECURE` | Nao | `false` | `true` para HTTPS |
| `PYTHON_VERSION` | Nao | — | Versao do Python no Render (recomendado: `3.11.11`) |
| `LANGCHAIN_TRACING_V2` | Nao | `false` | Ativar tracing LangSmith |
| `LANGCHAIN_API_KEY` | Nao | — | Chave da API LangSmith |
| `LANGCHAIN_PROJECT` | Nao | `quick-insights` | Nome do projeto no LangSmith |
| `HOST` | Nao | `0.0.0.0` | Host do servidor |
| `PORT` | Nao | `8000` | Porta do servidor |

---

## Dependencias Principais

```
deepagents>=0.3.5          # Framework de agentes autonomos
langgraph>=1.0.6           # Orquestracao de grafos de execucao
langchain>=1.2.3           # Toolkit de LLM
langchain-openai>=0.3.0    # Integracao OpenAI
langchain-community>=0.3.0 # SQL Database Toolkit
fastapi>=0.115.0           # Framework web assincrono
sqlalchemy>=2.0.0          # ORM e toolkit SQL
pandas>=2.2.0              # Manipulacao de dados
scikit-learn>=1.4.0        # Modelos de machine learning e PCA
scipy>=1.12.0              # Estatisticas, otimizacao e distancias
pygwalker>=0.5.0           # Visualizacao interativa
openpyxl>=3.1.0            # Leitura/escrita de Excel
rich>=13.0.0               # CLI formatting
langfuse>=2.0.0            # Observabilidade
```

---

## Licenca

Apache 2.0

---

<p align="center">
  <strong>FALE COM</strong><span style="color:#ff6347">SEUS DADOS</span><br>
  <a href="https://www.claro.com.br">Dados & AI</a>
</p>
