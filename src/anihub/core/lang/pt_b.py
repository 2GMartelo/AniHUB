"""Portuguese (Brazil), keys 550-1098."""
DATA = r"""
550|Pesquisar light novels por título
551|Ler
552|Para a estante
553|A classificação etária do site é maior que o seu modo de idade.
554|Oculto pelo seu filtro de tags.
555|Sem capítulos.
556|Adicionado à estante.
557|Não há fontes para os idiomas escolhidos.
558|ocultos pelo modo de idade: {n}
559|Baixar para ler offline (EPUB)
560|Baixando capítulos: {done} de {total}
561|O livro foi baixado e está na estante.
562|Pular
563|Voltar
564|Avançar
565|Concluir
566|Passo {n} de {total}
567|Mostrar o tutorial
568|Bem-vindo ao AniHUB!
569|Um tour rápido: vou destacar os botões principais e explicar o que fazem. Continue com «Avançar» ou a tecla →; saia quando quiser (Esc).
570|Arte
571|A seção de imagens: pesquisa em sites, sua biblioteca e assinaturas. A barra à esquerda troca de seção.
572|Abas da seção
573|<b>Sites</b> — pesquisa na internet, <b>Biblioteca</b> — o que você salvou no disco, <b>Assinaturas</b> — acompanhe obras novas por tag ou artista.
574|Escolha um site
575|Danbooru, Gelbooru, Pixiv, Pinterest e outros. Alguns sites têm configurações e chaves próprias: Configurações, bloco «Credenciais».
576|Pesquisa por tags
577|Digite tags separadas por espaços; <b>-tag</b> exclui. No visualizador, cada tag tem um botão «+» (adicionar à pesquisa) e «−» (excluir).
578|Salvar
579|Selecione imagens no feed e clique em «Salvar»: o arquivo, as tags e o autor são mantidos e os duplicados são ignorados.
580|Assinar
581|Acompanhe a pesquisa atual: as obras novas são contadas na aba Assinaturas e podem ser salvas automaticamente.
582|Mangá
583|Catálogos, biblioteca e leitor de mangá (via Suwayomi). Filtros por gênero, login nas fontes, acompanhamento de capítulos.
584|Geração
585|Um front-end para o Stable Diffusion Forge: geração, fila, histórico, CivitAI. O caminho do Forge é definido nas Configurações.
586|Anime
587|O calendário de temporada e a sua lista (AniList), assistir episódios e música.
588|Assistir anime
589|A aba Assistir mostra animes de sites e do seu disco. O botão «Extensões» adiciona fontes em vários idiomas de repositórios, como no Aniyomi.
590|Light novels
591|Um leitor de livros EPUB, FB2 e TXT do seu computador — e online.
592|Estante e Online
593|A Estante guarda seus livros; a aba Online pesquisa em sites (RanobeLib, por exemplo). Qualquer livro online pode ser baixado para ler offline.
594|Modo de idade
595|12+, 16+ ou 18+: o modo decide que conteúdo aparece em todo lugar. Suas tags não podem ser editadas; as suas próprias tags ocultas vão no campo abaixo.
596|Online / offline
597|O botão de baixo interrompe todas as requisições à internet — útil na estrada. A barra de status também mostra downloads, atualizações e o estado dos serviços.
598|É só isso!
599|Dica: <b>Ctrl+K</b> abre a paleta de comandos — um salto rápido para qualquer seção ou ação. Repita o tour nas Configurações («Mostrar o tutorial»).
600|Fechar o AniHUB completamente ou mantê-lo na bandeja?
601|Na bandeja o aplicativo mantém downloads, assinaturas e verificações de capítulos novos de mangá em andamento.
602|Minimizar para a bandeja
603|Fechar completamente
604|Cancelar
605|Lembrar minha escolha
606|Ao fechar a janela
607|Perguntar
608|Minimizar para a bandeja
609|Fechar completamente
610|Biblioteca
611|Rádio
612|Pesquisar e baixar
613|Adicionar estação
614|Remover
615|Nome
616|Endereço do stream ou da playlist
617|minha
618|Escolha uma estação (clique duplo)
619|Parado
620|A Anison.FM é uma rádio de anime. Suas próprias estações: o endereço de um stream (mp3/aac) ou uma playlist .pls / .m3u.
621|Erro: {msg}
622|não há endereço de stream na playlist
623|o stream não abre
624|Anime: achar aberturas e encerramentos (vazio: novidades)
625|Anime
626|Tema
627|Artista
628|Ouvir
629|Parar
630|Baixar para a biblioteca
631|Mais
632|Temas encontrados: {n}
633|Tocando: {title}
634|Baixando: {n}…
635|Temas baixados: {n}
636|Personalizado
637|Fundo
638|Painéis
639|Texto
640|Destaque
641|Redefinir
642|Rolagem suave com a roda do mouse
643|Geração de imagens (Stable Diffusion)
644|A seção Geração usa o Stable Diffusion Forge e precisa de uma placa de vídeo NVIDIA. Verificando o seu computador:
645|Seu computador é adequado. O que fazer com o Forge?
646|Seu computador é adequado, com limitações:
647|Seu computador não é adequado para o Stable Diffusion Forge, então a seção Geração e todas as funções ligadas a ela serão ocultadas. Você pode verificar de novo depois nas Configurações.
648|Baixar o Forge (cerca de 1,8 GB) para a pasta:
649|O Forge já foi baixado — escolha a pasta dele:
650|Decidir depois (a seção continua, defina o caminho nas Configurações)
651|Não há Forge nesta pasta (webui\webui.bat não encontrado). Escolha a pasta do pacote do Forge ou a subpasta webui dele.
652|Placas RTX 50 precisam de um PyTorch recente: o pacote para download pode não suportá-las. Com uma RTX 50, é melhor indicar um Forge que você já configurou.
653|Placa de vídeo: {d} ({gb} GB de memória de vídeo)
654|Memória: {gb} GB
655|Espaço livre em disco: {gb} GB
656|Nenhuma placa de vídeo NVIDIA encontrada (CUDA é necessário)
657|Menos de 4 GB de memória de vídeo
658|4–6 GB de memória de vídeo: apenas modelos leves e tamanhos pequenos
659|Menos de 8 GB de memória
660|Menos de 16 GB de memória: espere lentidão
661|Menos de 15 GB livres: escolha outra unidade para o Forge
662|Geração de imagens
663|Verificar o computador de novo
664|Baixar o Forge…
665|A seção Geração está ativada.
666|A seção Geração está desativada: este computador não é adequado para o Stable Diffusion Forge.
667|Reinicie o AniHUB para a mudança ter efeito.
668|Instalando o Stable Diffusion Forge
669|Baixando o Forge (cerca de 1,8 GB) e descompactando em:\n{dest}
670|Procurando a versão mais recente…
671|Baixados {done} de {total} MB
672|Descompactando (alguns minutos)…
673|Pronto. O Forge foi instalado: {path}
674|Falha: {msg}
675|Fechar
676|Não é possível exibir {name}. Abra a página em um navegador: {url}
677|Artista
678|Copyright
679|Personagens
680|Tags
681|Meta
682|Pesquisar esta tag
683|Adicionar à pesquisa
684|Excluir da pesquisa
685|Copiar
686|Idioma
687|Tema
688|Seguir o sistema
689|Claro
690|Escuro
691|Pasta da biblioteca
692|Classificações de conteúdo exibidas
693|Proxy (http://host:porta ou socks5://host:porta)
694|Intervalo mín. entre requisições à API (ms)
695|Máx. de downloads em paralelo
696|Credenciais dos sites
697|Salvar
698|Configurações salvas. A mudança de idioma vale após reiniciar.
699|Abrir pasta
700|Geral
701|Sensível
702|Questionável
703|Explícito
704|Configuração do AniHUB
705|Bem-vindo
706|Escolha o idioma da interface e o tema.
707|Pasta da biblioteca
708|Onde o AniHUB deve guardar a sua biblioteca? Escolha uma pasta em um disco com bastante espaço livre.
709|Espaço livre: {gb:.1f} GB
710|Não é possível gravar na pasta.
711|Verificação do sistema
712|Requisitos dos módulos opcionais (você pode continuar de qualquer forma).
713|Concluído
714|Tudo pronto. Clique em Concluir para iniciar o AniHUB.
715|Procurar...
716|Java encontrado: {d}
717|Java não encontrado. Ele é necessário para ler mangá (Suwayomi). Instale o Java 17+; a instalação automática virá depois.
718|GPU: {d}
719|GPU NVIDIA não detectada. O Stable Diffusion precisa de uma.
720|GPU: {d}. Menos de 6 GB de VRAM: a geração pode ser limitada.
721|Espaço livre em disco: {gb:.1f} GB
722|Só há {gb:.1f} GB livres. Uma biblioteca precisa de muito mais.
723|Mostrar o AniHUB
724|Sair
725|O AniHUB continua em execução na bandeja.
726|Gerar
727|Gerações salvas
728|Iniciar o Forge
729|Parar o Forge
730|Pasta do Forge...
731|Log do Forge
732|Prompt
733|Prompt negativo
734|Checkpoint
735|Sampler
736|Scheduler
737|Passos
738|Tamanho
739|Seed (-1 = aleatória)
740|Número de lotes
741|Tamanho do lote
742|Preparando (carregando o modelo)...
743|Gerar
744|Parar
745|Parando...
746|Limpar resultados
747|Classificação
748|Concluído: {n} imagem(ns). Os arquivos ficam na pasta sd da biblioteca.
749|Inicie o Forge para gerar (o botão acima).
750|parado
751|iniciando...
752|em execução
753|em execução (externo)
754|travou
755|O Forge foi iniciado fora do AniHUB, então o AniHUB não vai pará-lo.
756|O Forge encerrou inesperadamente. Abra o log.
757|Pasta do Forge (com webui.bat)
758|Porta da API
759|Só API, sem a interface web (--nowebui)
760|Argumentos de inicialização extras
761|Parar o Forge após inatividade, minutos (0 = nunca)
762|Lendo
763|Concluído
764|Em espera
765|Abandonado
766|Pretendo ler
767|Biblioteca
768|Explorar
769|Extensões
770|Novidades
771|Iniciar o serviço de mangá
772|Parar
773|Iniciar com o AniHUB (para avisos de capítulos novos)
774|Inicie o serviço de mangá (botão acima) para usar esta seção.
775|A leitura de mangá usa o mecanismo Suwayomi, que executa extensões do Tachiyomi. O AniHUB vai baixá-lo (cerca de 340 MB, inclui o próprio Java; não é preciso instalar mais nada).
776|Baixar e instalar o Suwayomi
777|Cancelar
778|Procurando a versão mais recente...
779|Baixando: {done:.0f} / {total:.0f} MB
780|Verificando...
781|Descompactando...
782|Concluído
783|Filtrar a biblioteca por título
784|Verificar capítulos novos
785|Consultando as fontes sobre capítulos novos...
786|Todos
787|Títulos na biblioteca: {n}
788|Populares
789|Recentes
790|Pesquisar títulos nesta fonte
791|Ainda não há fontes: instale uma extensão na aba Extensões.
792|Atualizar da fonte
793|Começar a ler
794|Continuar lendo
795|Capítulo
796|Grupo
797|Data
798|Título
799|Marcar como lido
800|Marcar como não lido
801|Baixar para ler offline
802|Excluir download
803|★ Na biblioteca
804|☆ Adicionar à biblioteca
805|(sem categoria)
806|Capítulos: {n}, não lidos: {unread}
807|Na fila de download...
808|Baixando: {n} na fila, atual {p}%
809|Capítulos: {n}
810|Capítulos novos: {n} ({titles})
811|Pesquisar extensões
812|Somente instaladas
813|Instalar de um arquivo...
814|Nome
815|Idioma
816|Versão
817|Status
818|Desinstalar
819|Repositórios:
820|URL do índice do repositório de extensões
821|Adicionar
822|Remover
823|Todos os idiomas
824|Trabalhando com o catálogo...
825|Processando: {name}...
826|instalada
827|atualização disponível
828|(obsoleta)
829|Exibidas: {n} de {total}. As extensões 18+ aparecem quando a classificação Explícito está ativada nas Configurações.
830|O Windows mantém este arquivo de extensão bloqueado enquanto o serviço está em execução. Pare o serviço de mangá, inicie de novo e tente outra vez.
831|Dica: prefira a versão .jar de uma extensão; alguns .apk são rejeitados pelo mecanismo.
832|Página única
833|Página dupla
834|Webtoon
835|Da direita para a esquerda
836|Este capítulo não tem páginas
837|Porta do serviço de mangá
838|Verificar capítulos novos a cada (minutos)
839|Data de adição
840|Tamanho do arquivo
841|Classificação de conteúdo
842|Nome
843|Minhas estrelas
844|Nota do site
845|Autor
846|Crescente / decrescente
847|Todos
848|Favoritos
849|Categorias
850|Coleções
851|Tags inteligentes
852|Lixeira
853|padrão
854|Nova categoria...
855|Nova coleção...
856|Renomear...
857|Excluir
858|Tornar padrão (os itens novos vão para cá)
859|Remover o padrão
860|Subir
861|Descer
862|Nome:
863|Este nome já está em uso.
864|Excluir esta categoria? Os itens permanecem na biblioteca.
865|Excluir esta coleção? Os itens permanecem na biblioteca.
866|Esvaziar a lixeira
867|Qualquer estrela
868|Importar...
869|Ferramentas
870|Ações
871|Exibidos: {shown} de {total}
872|Selecionados: {n}
873|os itens são excluídos definitivamente após {days} dias
874|Selecione itens primeiro
875|Restaurar
876|Excluir definitivamente
877|Excluir definitivamente {n} item(ns)? Isto não pode ser desfeito.
878|Editar tags...
879|Executar o marcador automático
880|Marcar automaticamente todos os itens sem tags
881|Marcando automaticamente {n} item(ns)...
882|Marcados automaticamente: {n}
883|Adicionar à coleção
884|Remover desta coleção
885|Adicionar à categoria
886|Remover desta categoria
887|Classificação de conteúdo
888|Minha avaliação
889|Sem avaliação
890|♥ Adicionar aos favoritos
891|Remover dos favoritos
892|Enviar para img2img
893|Mostrar na pasta
894|Mover para a lixeira
895|Mover {n} item(ns) para a lixeira? Você pode restaurá-los de lá.
896|Sim
897|Sim, sempre
898|Não
899|Tags ({n} item(ns))
900|Digite uma tag para adicionar (aparecem sugestões)
901|Adicionar
902|Desmarque uma tag para removê-la.
903|Marcada: em todos os itens selecionados. Parcialmente marcada: em alguns. Marque para adicionar a todos, desmarque para remover de todos.
904|Gerenciador de tags
905|Hierarquia
906|Tags inteligentes
907|Filtrar tags
908|Tag
909|Itens
910|Tag pai
911|Definir pai
912|Remover pai
913|Renomear / mesclar...
914|Novo nome (uma tag existente será mesclada):
915|Excluir tag
916|Excluir a tag {name} de toda a biblioteca?
917|Uma tag pai também encontra tudo que tem as suas filhas (pesquisar 'vocaloid' acha 'hatsune_miku').
918|Tags na hierarquia: {n}
919|Nome da tag inteligente
920|Adicionar uma tag ao grupo
921|Remover selecionadas
922|Nova
923|Salvar
924|Excluir
925|Dê um nome à tag inteligente e pelo menos uma tag.
926|Uma tag inteligente é uma pasta de tags: pesquisar '@nome' acha itens com QUALQUER uma delas (filhas incluídas). Você também pode clicar nela na barra lateral.
927|Importar imagens locais
928|Adicionar pasta...
929|Adicionar arquivos...
930|Limpar
931|(categoria padrão)
932|Marcar com o marcador automático (também define a classificação)
933|O marcador automático está desligado ou o modelo não foi baixado: veja as Configurações.
934|Classificação:
935|Categoria:
936|Importar
937|Cancelar
938|Os arquivos são copiados para a biblioteca; duplicados exatos são ignorados e imagens semelhantes são sinalizadas.
939|Importados: {saved}, duplicados ignorados: {duplicate}, com falha: {failed}, possivelmente semelhantes: {similar}, cancelados: {cancelled}
940|Achar imagens semelhantes
941|Arquivo
942|Tamanho
943|Dimensões
944|Classificação
945|Escaneando...
946|Marcar todas menos a maior de cada grupo
947|Mover as marcadas para a lixeira
948|Grupos de imagens visualmente semelhantes (cópias redimensionadas ou recomprimidas). O maior arquivo aparece primeiro.
949|Grupo {n} ({k} imagens)
950|Grupos encontrados: {n}
951|Nenhuma imagem semelhante encontrada.
952|Movidas para a lixeira: {n}
953|possíveis duplicados: {n}
954|Salvar e avisar
955|Pular
956|Desligado
957|Imagens visualmente semelhantes ao salvar
958|Esvaziar a lixeira após (dias, 0 = nunca)
959|Perguntar antes de mover para a lixeira
960|Biblioteca
961|Marcador automático (WD14)
962|Marcar automaticamente as imagens importadas e posts sem tags
963|Modelo
964|Baixar modelo
965|instalado
966|não baixado (~{mb} MB, roda na CPU)
967|Confiança das tags
968|Confiança dos personagens
969|Imagem de origem (img2img)
970|Escolher...
971|Limpar
972|Intensidade do denoising
973|Gerar (img2img)
974|Imagem carregada como origem do img2img. Inicie o Forge se não estiver rodando e clique em Gerar.
975|Fila
976|Histórico
977|Salvar predefinição...
978|Excluir
979|(predefinição)
980|Predefinição aplicada: {name}
981|Estilos
982|Salvar o prompt como estilo...
983|Excluir estilo
984|Carregar de imagem...
985|Esta imagem não tem parâmetros de geração.
986|Parâmetros carregados de {name}
987|(auto)
988|manter os do Forge
989|Clip skip
990|Hires fix
991|igual aos passos
992|Ampliar em
993|Upscaler
994|Passos do hires
995|Denoising do hires
996|Variação de seed
997|Seed da variação
998|Intensidade da variação
999|Adicionar à fila
1000|Quantas cópias colocar na fila (cada uma com seed aleatória)
1001|Na fila: {n}
1002|Escreva um prompt primeiro.
1003|Ampliar
1004|Ampliando {n} imagem(ns)...
1005|Ampliadas: {n}. Os arquivos estão na pasta sd.
1006|Peso:
1007|Inserir no prompt
1008|Disponíveis: {n}
1009|Status
1010|Parâmetros
1011|Backend
1012|Imagens
1013|Iniciar a fila
1014|Pausar após a atual
1015|Cancelar a atual
1016|Duplicar
1017|Remover
1018|Limpar concluídas
1019|aguardando
1020|em execução
1021|concluída
1022|com falha
1023|cancelada
1024|Nenhum backend do Forge em execução: inicie um e clique em Iniciar a fila de novo.
1025|Agendamento
1026|Executar a fila às
1027|todos os dias
1028|uma vez
1029|Iniciar o Forge automaticamente se não estiver rodando
1030|Parar o Forge que o AniHUB iniciou quando a fila terminar
1031|Somente se o PC ficou ocioso por (minutos, 0 = ignorar)
1032|Próxima execução: {when}
1033|O agendamento está desligado.
1034|A execução agendada começou.
1035|O horário agendado chegou, mas a fila está vazia.
1036|Backends
1037|GPU padrão
1038|Pesquisar prompts e seeds
1039|Carregar parâmetros
1040|Salvar como predefinição...
1041|Repetir (fila)
1042|Remover do histórico
1043|Limpar o histórico
1044|Limpar todo o histórico? Os arquivos de imagem não são excluídos.
1045|Exibidos: {shown} de {total}
1046|Predefinição salva: {name}
1047|Na fila: {n}
1048|Cole um link de modelo do CivitAI
1049|Abrir
1050|Pesquisar no CivitAI
1051|Checkpoints
1052|LoRA
1053|Embeddings
1054|VAE
1055|Mais baixados
1056|Mais bem avaliados
1057|Mais recentes
1058|Qualquer modelo base
1059|Incluir 18+
1060|Ative a classificação Explícito nas Configurações para pesquisar modelos 18+.
1061|Mais resultados
1062|Versão
1063|Arquivo
1064|Baixar para o Forge
1065|Abrir no CivitAI
1066|Encontrados: {n}
1067|Isso não é um link de modelo do CivitAI.
1068|Palavras-gatilho: {words}
1069|Defina primeiro a pasta do Forge (Configurações).
1070|Baixando {name} para {folder}...
1071|Instalado: {path}
1072|Download cancelado.
1073|Geração
1074|Backends extras: o mesmo Forge em outra porta, fixado em uma GPU (reinicie o AniHUB para aplicar).
1075|Ativo
1076|Nome
1077|Porta
1078|GPU
1079|Adicionar backend
1080|Remover selecionado
1081|Chave de API do CivitAI
1082|opcional: necessária para alguns arquivos
1083|De imagem
1084|Os resultados vão aparecer aqui
1085|Escreva um prompt, inicie o Forge e clique em Gerar. Cada imagem é salva em disco; escolha as que quer manter.
1086|O serviço de mangá está parado
1087|Nada aqui ainda
1088|Salve imagens pela aba Sites ou importe uma pasta: elas vão aparecer aqui.
1089|Encontre algo para ver
1090|Escolha uma fonte, digite tags e clique em Pesquisar. Use -tag para excluir.
1091|Aparência
1092|Armazenamento e conteúdo
1093|Rede
1094|Voltar
1095|Avançar
1096|Concluir
1097|Cancelar
1098|A biblioteca não está disponível
"""
