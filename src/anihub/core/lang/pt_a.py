"""Portuguese (Brazil), keys 0-549."""
DATA = r"""
0|Arte
1|Mangá
2|Geração
3|Anime
4|Novels
5|Configurações
6|Navegar pelos sites
7|Biblioteca
8|Esta seção será implementada em uma etapa posterior.
9|Tags separadas por espaços, -tag para excluir
10|Pesquisar
11|Fonte
12|Salvar na biblioteca
13|Abrir
14|Fechar
15|Carregando...
16|Não há mais resultados
17|Erro: {msg}
18|Salvos: {saved}, duplicados: {dup}, com falha: {failed}
19|Carregados: {n}
20|Itens na biblioteca: {n}
21|Mouse: setas laterais ou roda para avançar · botões abaixo · teclas: ←/→ Espaço P F T L M S Esc
22|Anterior (←)
23|Próximo (→)
24|Apresentação (P)
25|Favorito (L)
26|Avaliação
27|Sem avaliação
28|Salvar na biblioteca (S)
29|Tags (T)
30|Tela cheia (F)
31|Fechar (Esc)
32|Reproduzir / pausar
33|Som (M)
34|Capítulo anterior ([)
35|Próximo capítulo (])
36|Página anterior
37|Próxima página
38|Esquerda
39|Direita
40|Tela cheia (F)
41|Fechar (Esc)
42|Filtros
43|Pesquise por gêneros, tags, status e mais
44|Login na fonte
45|Entrar / alterar as configurações desta fonte
46|Somente não lidos
47|Qualquer gênero
48|Qualquer status
49|Desconhecido
50|Em andamento
51|Concluído
52|Licenciado
53|Publicação encerrada
54|Cancelado
55|Em hiato
56|Encontrar um gênero ou tag
57|Redefinir
58|Aplicar filtros
59|Esta fonte não tem filtros: use a pesquisa por título.
60|Crescente
61|Clique: incluir → excluir → desligado
62|Configurações: {name}
63|Esta fonte não tem configurações.
64|Salvo.
65|As fontes que exigem conta pedem aqui o login e a senha. As alterações são salvas na hora e usadas pela fonte na próxima requisição. Sites que fazem login por uma página web ou verificação do Cloudflare não são suportados pelo backend.
66|Regras automáticas
67|Nova
68|Excluir
69|As regras são executadas de cima para baixo
70|Nome da regra
71|Nova regra
72|Quando um item…
73|…faça isto
74|Tem todas as tags
75|Tem alguma das tags
76|Não tem nenhuma de
77|tag tag ... (uma tag pai também inclui as filhas)
78|tag tag ...
79|tag tag ...
80|Autor
81|nomes de artistas
82|Fonte
84|Classificação
85|Seção
86|Arte
87|Gerações
88|Adicionar à coleção
89|Adicionar à categoria
90|Adicionar tags
91|tag tag ...
92|Definir classificação de conteúdo
93|Definir minha avaliação
94|Marcar como favorito
96|sem alteração
97|Salvar regra
98|Aplicar à biblioteca inteira
99|Aplicar regras automaticamente aos itens novos
100|Uma regra precisa de pelo menos uma condição e uma ação. As regras são executadas na ordem da lista em cada item novo (salvo de um site, importado, gerado) e depois da marcação automática.
101|Adicione pelo menos uma condição e uma ação.
102|Regra salva.
103|Preencha as condições e ações e salve.
104|Excluir a regra «{name}»?
105|Executar todas as regras ativas em todos os itens da biblioteca?
106|Concluído: {n} correspondências em {rules} regras.
107|Comparar
108|Comparar as duas (antes / depois)...
109|Antes
110|Depois
111|Lado a lado
112|Trocar
113|Arraste o divisor ou use ←/→ · Espaço: lado a lado · X: trocar
114|Online
115|Offline
116|Modo offline: nada vai para a internet
117|Modo offline: sites, catálogo de mangá, CivitAI e downloads estão desligados. Sua biblioteca, capítulos salvos e geração local continuam funcionando. O Forge aplica a configuração na próxima inicialização.
118|Máscara de inpaint
119|Máscara (inpaint)…
120|Editar máscara…
121|Remover máscara
122|Pincel
123|Borracha (E)
124|Desfazer
125|Limpar
126|Inverter
127|Usar máscara
128|Pinte o que deve ser redesenhado. O botão esquerdo pinta, o direito faz o contrário, a roda muda o tamanho do pincel e Ctrl+Z desfaz.
129|Desfoque da máscara
130|Conteúdo mascarado
131|Original
132|Preenchimento
133|Ruído latente
134|Latente vazio
135|Somente a área mascarada (resolução total)
136|Máscara definida: só a área pintada será redesenhada.
137|Grade X/Y…
138|Compare como um ou dois parâmetros mudam a imagem
139|Grade X/Y
140|Eixo X
141|Eixo Y
142|— (uma linha)
143|Escolher…
144|valores: 20, 30, 40 ou um intervalo início:fim:passo (20:40:10)
145|primeiro valor = texto a procurar no prompt, os demais o substituem: cat, dog, fox
146|Passos
147|CFG
148|Sampler
149|Scheduler
150|Seed
151|Denoising (img2img)
152|Clip skip
153|Checkpoint
154|Procurar/substituir no prompt
155|{x} × {y} = {n} imagens
156|{n} imagens é demais (limite {max})
157|Gerar a grade
158|O Forge está ocupado com outra coisa.
159|Gerando…
160|A tabela aparece aqui.
161|Nada foi gerado.
162|Concluído: {n} imagens.
163|Parado: {n} de {total} imagens.
164|Salvar como…
165|Para a biblioteca
166|Salvo na biblioteca.
167|Já está na biblioteca.
168|Espere a execução terminar ou clique em Parar.
169|Todas as imagens usam o formulário Gerar atual e a mesma seed; só os parâmetros escolhidos mudam. As células também ficam no histórico de geração.
170|Temporada
171|Minha lista
172|Assistir
173|Assistindo
174|Planejado
175|Concluído
176|Em espera
177|Abandonado
178|Reassistindo
179|Inverno
180|Primavera
181|Verão
182|Outono
183|TV
184|TV curto
185|Filme
186|Especial
187|OVA
188|ONA
189|Música
190|Em exibição
191|Finalizado
192|Ainda não exibido
193|Cancelado
194|Em hiato
195|d
196|h
197|min
198|O episódio {ep} está no ar agora
199|Episódio {ep} em {span}
200|{n} episódios
201|Sem descrição.
202|Esta temporada
203|Pesquise qualquer anime pelo título
204|Resultados da pesquisa
205|Abrir
206|Adicionar à lista
207|«{title}»: {status}
208|Status
209|Episódios assistidos
210|Nota
211|Salvar
212|Adicionar à lista
213|Remover da lista
214|Salvo.
215|Removido.
216|Remover {n} item(ns) da sua lista?
217|Mais um episódio assistido
218|Definir status
219|Sem nota
220|Todos
221|Títulos na lista: {n}
222|Sincronizar com o AniList
223|Entre primeiro no AniList (botão Conta).
224|Sincronizando…
225|Sincronizado: enviados {sent}, recebidos {got}.
226|Título
227|Episódios
228|Nota
229|Status
230|Próximo episódio
231|Conta do AniList
232|AniList: sem login
233|Conectado como {name}.
234|Abrir as configurações de desenvolvedor do AniList
235|Copiar a URL de redirecionamento
236|Client ID numérico do seu cliente de API
237|Abrir a página de autorização
238|Token de acesso
239|cole o token exibido depois de aprovar
240|Entrar
241|Sair
242|Digite primeiro o Client ID numérico (passo 2).
243|A lista funciona sem conta. Para espelhá-la no AniList:\n1. Abra as configurações de desenvolvedor e crie um cliente; como URL de redirecionamento use {redirect}\n2. Cole abaixo o ID numérico do cliente e abra a página de autorização.\n3. Aprove o acesso, copie o token exibido na página e cole aqui.\nO token é guardado apenas neste computador.
244|Assistir episódios em breve
245|As fontes para assistir episódios vão aparecer aqui. O calendário de temporada e a sua lista já funcionam.
246|Rastreadores
247|Rastreando…
248|Rastreamento: {title}
249|MyAnimeList, AniList, Shikimori, Kitsu e mais: depois de vincular um título, os capítulos que você lê são enviados ao rastreador.
250|{name}: conectado.
251|{name}: sem login.
252|O token expirou: entre de novo.
253|Abrir a página de login
254|cole o endereço em que o navegador terminou
255|1. Abra a página de login e aprove o acesso.\n2. O navegador pode mostrar um erro ou pedir para abrir um aplicativo: tudo bem. Copie o endereço completo dessa página (ou o token/código exibido) e cole abaixo.
256|Entrar
257|Sair
258|usuário ou e-mail
259|senha
260|Conectado.
261|O rastreador não aceitou.
262|Desconectado.
263|Status
264|Capítulos lidos
265|Nota
266|Desvincular
267|Excluir também a entrada em {name}? (Sim = excluir lá também, Não = apenas desvincular aqui)
268|Vincular a esta entrada
269|Encontrados: {n}
270|{n} cap.
271|Você não está conectado a nenhum rastreador: use o botão «Rastreadores».
272|Light novels
273|Adicionar livros…
274|Adicionar uma pasta…
275|Pesquisar por título ou autor
276|Somente não terminados
277|Livros
278|Sua estante está vazia
279|Adicione livros EPUB, FB2 ou TXT: o progresso de leitura, o tamanho da fonte e o tema são lembrados.
280|Livros: {n}
281|{n} capítulos
282|Nenhum arquivo EPUB / FB2 / TXT encontrado.
283|Adicionados: {saved}, já existiam: {duplicate}, com falha: {failed}.
284|Marcar como lido
285|Marcar como não lido
286|Excluir «{title}» da estante? A cópia na biblioteca também é removida.
287|Conteúdo (T)
288|Texto menor (−)
289|Texto maior (+)
290|Tema: como o aplicativo
291|Tema: escuro
292|Tema: claro
293|Tema: sépia
294|{n} / {total} · {pct}%
295|Arquivos locais
296|Voltar 10 s (←)
297|Avançar 10 s (→)
298|Abrir em um player externo
299|Esta fonte não tem stream para o episódio.
300|stream
301|Episódio {n}
302|Este stream precisa de cabeçalhos de requisição especiais: use o botão do player externo (defina anime.external_player no config.json, por exemplo mpv).
303|Não foi possível reproduzir: {msg}
304|Pesquisar na fonte (vazio = tudo / populares)
305|Abrir a pasta de animes
306|Qual título do AniList é este?
307|Este
308|Vincular ao AniList…
309|Alterar vínculo…
310|Desvincular
311|Abrir o site
312|№
313|Título
314|Estado
315|Assistir
316|Marcar como assistido
317|Marcar como não assistido
318|Escolha um título
319|Clique duas vezes em um título para ver os episódios. Arquivos locais: coloque uma pasta por série (com os episódios dentro) na pasta de animes. Mais sites e idiomas: botão Extensões.
320|Ainda não há séries: clique em «Abrir a pasta de animes» e coloque lá uma pasta por série.
321|Episódios: {n}
322|Nenhum episódio encontrado.
323|Vinculado ao AniList: {title}. Os episódios assistidos atualizam sua lista.
324|Não vinculado ao AniList: os episódios assistidos não atualizarão sua lista.
325|assistido
326|continuar de {t}
327|Vinculado.
328|Atualização disponível
329|O AniHUB {new} está disponível (você tem {old}).
330|Baixar e instalar
331|Reinstalar esta versão
332|Instalar esta versão mais antiga
333|Depois
334|Ignorar esta versão
335|Abrir no GitHub
336|instalada
337|pré-lançamento
338|Sem descrição.
339|Esta versão não tem instalador.
340|Baixando o instalador…
341|Iniciando o instalador; o AniHUB será fechado.
342|Cancelado.
343|Todas as versões…
344|Versões: {n}
345|Atualização {v} disponível
346|Sobre e atualizações
347|AniHUB versão {v}
348|Verificar atualizações automaticamente (uma vez por dia)
349|Verificar atualizações
350|Você tem a versão mais recente.
351|Abrir a pasta de logs
352|Downloads
353|Na fila de download: {n} (veja Downloads na barra de status).
354|Post
355|Status
356|Detalhes
357|na fila
358|baixando
359|salvo
360|já está na biblioteca
361|com falha
362|cancelado
363|Pausar
364|Retomar
365|Cancelar selecionados
366|Cancelar todos
367|Tentar de novo os que falharam
368|Limpar concluídos
369|Ao mesmo tempo:
370|Limite de velocidade:
371|ilimitado
372|MB/s
373|Ativos: {active} (baixando {running}) · salvos {done} · duplicados {dup} · com falha {failed}
374|Downloads: {n}
375|Downloads
376|imagens semelhantes já presentes: {n}
377|salvos {n}
378|duplicados {n}
379|com falha {n}
380|cancelados {n}
381|nada
382|Downloads concluídos: {details}.
383|Baixados {n}: {details}.
384|Backups
385|Fazer backup do banco de dados da biblioteca automaticamente
386|Incluir as configurações (config.json) nos backups
387|A cada (dias)
388|Manter os últimos
389|Fazer backup agora
390|Restaurar de um backup…
391|Cancelar a restauração
392|Abrir a pasta de backups
393|Há uma restauração agendada: ela é aplicada na próxima inicialização do AniHUB.
394|Último backup: {when} (backups: {n})
395|Ainda não há backups.
396|Criado: {name}
397|O backup está íntegro ({n} itens). Reinicie o AniHUB para aplicá-lo; o banco de dados atual fica ao lado como cópia.
398|O banco de dados da biblioteca foi restaurado de um backup.
399|Limite do cache (miniaturas, vídeos)
400|Verificação de integridade da biblioteca
401|Procura registros cujo arquivo sumiu, arquivos na pasta arts que a biblioteca não conhece e (opcionalmente) arquivos que mudaram desde que foram salvos. Nada é excluído sem perguntar.
402|Verificar também o conteúdo dos arquivos (lento)
403|Verificar
404|Remover registros sem arquivos
405|Otimizar o banco de dados
406|Abrir a pasta arts
407|Problema
408|Arquivo
409|o arquivo está faltando
410|o conteúdo mudou
411|não está na biblioteca
412|Banco de dados: OK
413|Problema no banco de dados: {msg}
414|verificados: {n}
415|nenhum problema encontrado
416|faltando: {missing}, alterados: {damaged}, arquivos desconhecidos: {orphans}
417|Remover {n} registros cujos arquivos não existem mais? Suas tags e vínculos com coleções também são removidos.
418|Registros removidos: {n}.
419|O banco de dados foi otimizado.
420|Relatar um problema…
421|Relatar um problema
422|Ocorreu um erro: relate-o
423|Este texto é o que seria compartilhado: versão, sistema, o último erro e o log recente. Chaves, tokens, senhas e seu nome de usuário são removidos automaticamente; leia antes de postar. O AniHUB em si não envia nada.
424|O que você fez, o que esperava e o que aconteceu?
425|Incluir o log recente
426|O relatório:
427|Copiar
428|Copiar e abrir o GitHub Issues
429|Copiado para a área de transferência.
430|A página do issue está aberta; o relatório está na área de transferência.
431|Relatório de problema
432|Ir a uma seção, executar uma ação, achar uma tag, livro ou série…
433|↑ ↓ escolher · Enter executar · Esc fechar
434|seção
435|ação
436|biblioteca
437|livro
438|lista de animes
439|Verificar atualizações
440|Fazer backup da biblioteca agora
441|Abrir downloads
442|Alternar o modo offline
443|Alternar tema escuro / claro
444|Pesquisar na biblioteca: {q}
445|Assinaturas
446|Assinar
447|Seguir
448|Nome da assinatura
449|Digite primeiro uma pesquisa: a assinatura a acompanha.
450|Seguindo «{name}»: os posts novos serão contados.
451|Sem assinaturas
452|Em Sites, digite uma pesquisa (uma tag ou um artista) e clique em «Seguir»: os posts novos aparecem aqui.
453|Verificar agora
454|Verificar todas
455|Salvar novos
456|Marcar como visto
457|Excluir
458|Excluir a assinatura «{name}»?
459|Ativada
460|Salvar posts novos automaticamente
461|nunca
462|{source}: {query}  ·  última verificação: {when}
463|Posts novos: {n}
464|Marcado como visto.
465|Modo offline: sem verificações.
466|Esta fonte não está mais disponível.
467|Posts novos: {fresh}, salvos automaticamente: {saved}
468|Estatísticas
469|itens na biblioteca
470|em disco
471|favoritos
472|avaliados por você
473|tags
474|coleções
475|livros lidos / na estante
476|episódios assistidos
477|assinaturas
478|na lixeira
479|Adicionados por mês
480|Por fonte
481|Por classificação de conteúdo
482|Tags mais usadas
483|Artistas mais salvos
484|Exportar / compartilhar
485|Pacote AniHUB (.zip, com tags)…
486|Galeria HTML (.zip)…
487|Exportar a coleção…
488|Importar um pacote…
489|Pacote AniHUB
490|Exportados {n} para {path}
491|Pacote «{name}»: adicionados {saved}, já existiam {dup}, com falha {failed}.
492|Música
493|Pesquisar faixas ou álbuns
494|Abrir a pasta de música
495|Reescanear
496|№
497|Faixa
498|Ainda não há música
499|Coloque uma pasta por título (um álbum de OST) na pasta de música: <biblioteca>/music/<Título>/faixas (mp3, flac, ogg…).
500|Nada tocando
501|Arquivos soltos
502|{n} faixas
503|na sua lista: {title}
504|Aleatório
505|Repetir
506|Modo de idade e filtro de tags
507|Modo de idade
508|12+ — somente conteúdo seguro
509|16+ — seios permitidos, o restante do conteúdo 18+ fica oculto
510|18+ — sem restrições embutidas
511|Ocultas pelo modo (não editável)
512|O modo 18+ não oculta nada por si só.
513|Minhas tags ocultas
514|Separadas por espaços ou vírgulas. Um * no final oculta todas as tags que começam assim: guro*
515|Mudar para 18+? Conteúdo adulto será exibido sem restrições embutidas. Você precisa ter 18 anos ou mais.
516|Modo de idade
517|Escolha um modo. Suas tags restritas mudam com o modo; você pode adicionar suas próprias tags ocultas depois nas Configurações.
518|12+ — oculta tudo relacionado a conteúdo 16+ e 18+
519|16+ — seios permitidos, o restante do conteúdo 18+ é filtrado
520|18+ — sem restrições embutidas
521|Sem login, o Pixiv mostra apenas obras para todas as idades. Para R-18: entre no pixiv.net no navegador, pressione F12 → Application → Cookies → pixiv.net, copie o valor de PHPSESSID e cole aqui (requer o modo 18+). O cookie fica só neste computador e é enviado apenas ao pixiv.net.
522|palavras de busca · user:nome · board:nome/quadro · um link de perfil ou quadro
523|Janela translúcida (Mica)
524|O material do Windows 11: a janela deixa o papel de parede e as cores da área de trabalho transparecerem. Requer Windows 11 22H2 ou mais recente.
525|Extensões
526|Extensões: fontes de repositórios
527|Repositórios
528|Adicionar repositório
529|Remover
530|Endereço do index.json do repositório:
531|Um repositório é um index.json que lista extensões (como no Aniyomi). Adicione apenas os que você confia.
532|Nome
533|Idioma
534|Versão
535|Status
536|Instalar
537|Atualizar
538|Remover
539|Configurações
540|Atualizar catálogo
541|instalada
542|Extensões disponíveis: {n}
543|Pronto: {name}
544|Instalar «{name}»?\n\nUma extensão é um programa Python e roda com as suas permissões. Repositório: {repo}
545|Extensões são código de terceiros. Instale apenas de repositórios em que você confia. O arquivo é verificado com a soma de verificação do repositório.
546|Idiomas
547|Todos os idiomas
548|Estante
549|Online
"""
