"""Spanish, keys 550-1098."""
DATA = r"""
550|Buscar novelas ligeras por título
551|Leer
552|A la estantería
553|La clasificación de edad del sitio supera tu modo de edad.
554|Oculto por tu filtro de etiquetas.
555|No hay capítulos.
556|Añadido a la estantería.
557|No hay fuentes para los idiomas elegidos.
558|ocultos por el modo de edad: {n}
559|Descargar para leer sin conexión (EPUB)
560|Descargando capítulos: {done} de {total}
561|El libro está descargado y en la estantería.
562|Omitir
563|Atrás
564|Siguiente
565|Hecho
566|Paso {n} de {total}
567|Mostrar el tutorial
568|¡Bienvenido a AniHUB!
569|Un recorrido breve: iluminaré los botones principales y explicaré qué hacen. Continúa con «Siguiente» o la tecla →; puedes salir en cualquier momento (Esc).
570|Arte
571|La sección de imágenes: búsqueda en sitios web, tu biblioteca y suscripciones. La barra de la izquierda cambia de sección.
572|Pestañas de la sección
573|<b>Sitios</b> — búsqueda en internet, <b>Biblioteca</b> — lo que guardaste en el disco, <b>Suscripciones</b> — sigue obras nuevas por etiqueta o artista.
574|Elige un sitio
575|Danbooru, Gelbooru, Pixiv, Pinterest y más. Algunos sitios tienen sus propios ajustes y claves: Ajustes, bloque «Credenciales».
576|Búsqueda por etiquetas
577|Escribe etiquetas separadas por espacios; <b>-etiqueta</b> excluye. En el visor cada etiqueta tiene un botón «+» (añadir a la búsqueda) y «−» (excluir).
578|Guardar
579|Selecciona imágenes en la lista y pulsa «Guardar»: se conservan el archivo, las etiquetas y el autor, y se omiten los duplicados.
580|Suscribirse
581|Sigue la búsqueda actual: las obras nuevas se cuentan en la pestaña Suscripciones y pueden guardarse automáticamente.
582|Manga
583|Catálogos, biblioteca y lector de manga (mediante Suwayomi). Filtros por género, inicio de sesión en las fuentes, seguimiento de capítulos.
584|Generación
585|Una interfaz para Stable Diffusion Forge: generación, cola, historial, CivitAI. La ruta de Forge se indica en Ajustes.
586|Anime
587|El calendario de temporada y tu lista (AniList), ver episodios y música.
588|Ver anime
589|La pestaña Ver muestra anime de sitios web y de tu disco. El botón «Extensiones» añade fuentes en muchos idiomas desde repositorios, como Aniyomi.
590|Novelas ligeras
591|Un lector de libros EPUB, FB2 y TXT de tu ordenador — y en línea.
592|Estantería y En línea
593|La estantería guarda tus libros; la pestaña En línea busca en sitios web (RanobeLib, por ejemplo). Cualquier libro en línea puede descargarse para leerlo sin conexión.
594|Modo de edad
595|12+, 16+ o 18+: el modo decide qué contenido se ve en todas partes. Sus etiquetas no se pueden editar; tus propias etiquetas ocultas van en el campo de abajo.
596|En línea / sin conexión
597|El botón de abajo detiene todas las peticiones a internet — útil en la carretera. La barra de estado también muestra descargas, actualizaciones y el estado de los servicios.
598|¡Eso es todo!
599|Consejo: <b>Ctrl+K</b> abre la paleta de comandos — un salto rápido a cualquier sección o acción. Repite el recorrido en Ajustes («Mostrar el tutorial»).
600|¿Cerrar AniHUB por completo o mantenerlo en la bandeja?
601|En la bandeja la aplicación mantiene las descargas, las suscripciones y la búsqueda de capítulos nuevos de manga.
602|Minimizar a la bandeja
603|Cerrar por completo
604|Cancelar
605|Recordar mi elección
606|Al cerrar la ventana
607|Preguntar
608|Minimizar a la bandeja
609|Cerrar por completo
610|Biblioteca
611|Radio
612|Buscar y descargar
613|Añadir emisora
614|Quitar
615|Nombre
616|Dirección del stream o de la lista de reproducción
617|mía
618|Elige una emisora (doble clic)
619|Detenido
620|Anison.FM es una radio de anime. Tus propias emisoras: la dirección de un stream (mp3/aac) o una lista .pls / .m3u.
621|Error: {msg}
622|no hay dirección de stream en la lista
623|el stream no se abre
624|Anime: buscar openings y endings (vacío: novedades)
625|Anime
626|Tema
627|Artista
628|Escuchar
629|Detener
630|Descargar a la biblioteca
631|Más
632|Temas encontrados: {n}
633|Reproduciendo: {title}
634|Descargando: {n}…
635|Temas descargados: {n}
636|Personalizado
637|Fondo
638|Paneles
639|Texto
640|Acento
641|Restablecer
642|Desplazamiento suave con la rueda del ratón
643|Generación de imágenes (Stable Diffusion)
644|La sección Generación funciona con Stable Diffusion Forge y necesita una tarjeta gráfica NVIDIA. Comprobando tu equipo:
645|Tu equipo es adecuado. ¿Qué hacemos con Forge?
646|Tu equipo es adecuado, con limitaciones:
647|Tu equipo no es adecuado para Stable Diffusion Forge, así que la sección Generación y todas las funciones relacionadas se ocultarán. Puedes volver a comprobarlo más tarde en Ajustes.
648|Descargar Forge (unos 1,8 GB) en la carpeta:
649|Forge ya está descargado — elige su carpeta:
650|Decidir más tarde (la sección se queda, indica la ruta en Ajustes)
651|En esta carpeta no hay Forge (no se encontró webui\webui.bat). Elige la carpeta del paquete de Forge o su subcarpeta webui.
652|Las tarjetas RTX 50 necesitan un PyTorch reciente: puede que el paquete descargable no las admita. Con una RTX 50 es mejor indicar un Forge que ya tengas configurado.
653|Tarjeta gráfica: {d} ({gb} GB de memoria de vídeo)
654|Memoria: {gb} GB
655|Espacio libre en disco: {gb} GB
656|No se encontró ninguna tarjeta gráfica NVIDIA (se requiere CUDA)
657|Menos de 4 GB de memoria de vídeo
658|4–6 GB de memoria de vídeo: solo modelos ligeros y tamaños pequeños
659|Menos de 8 GB de memoria
660|Menos de 16 GB de memoria: espera ralentizaciones
661|Menos de 15 GB libres: elige otra unidad para Forge
662|Generación de imágenes
663|Comprobar el equipo de nuevo
664|Descargar Forge…
665|La sección Generación está activada.
666|La sección Generación está desactivada: este equipo no es adecuado para Stable Diffusion Forge.
667|Reinicia AniHUB para que el cambio surta efecto.
668|Instalando Stable Diffusion Forge
669|Descargando Forge (unos 1,8 GB) y descomprimiéndolo en:\n{dest}
670|Buscando la última versión…
671|Descargados {done} de {total} MB
672|Descomprimiendo (unos minutos)…
673|Hecho. Forge está instalado: {path}
674|Error: {msg}
675|Cerrar
676|No se puede mostrar {name}. Abre la página en un navegador: {url}
677|Artista
678|Copyright
679|Personajes
680|Etiquetas
681|Meta
682|Buscar esta etiqueta
683|Añadir a la búsqueda
684|Excluir de la búsqueda
685|Copiar
686|Idioma
687|Tema
688|Seguir el sistema
689|Claro
690|Oscuro
691|Carpeta de la biblioteca
692|Clasificaciones de contenido mostradas
693|Proxy (http://host:puerto o socks5://host:puerto)
694|Intervalo mín. entre peticiones a la API (ms)
695|Máx. de descargas en paralelo
696|Credenciales de los sitios
697|Guardar
698|Ajustes guardados. El cambio de idioma se aplica al reiniciar.
699|Abrir carpeta
700|General
701|Sensible
702|Dudoso
703|Explícito
704|Asistente de AniHUB
705|Bienvenido
706|Elige el idioma de la interfaz y el tema.
707|Carpeta de la biblioteca
708|¿Dónde debe guardar AniHUB tu biblioteca? Elige una carpeta en una unidad con suficiente espacio libre.
709|Espacio libre: {gb:.1f} GB
710|No se puede escribir en la carpeta.
711|Comprobación del sistema
712|Requisitos de los módulos opcionales (puedes continuar en cualquier caso).
713|Hecho
714|Todo está listo. Pulsa Finalizar para iniciar AniHUB.
715|Examinar...
716|Java encontrado: {d}
717|Java no encontrado. Hace falta para leer manga (Suwayomi). Instala Java 17+; la instalación automática llegará más adelante.
718|GPU: {d}
719|No se detectó ninguna GPU NVIDIA. Stable Diffusion la necesita.
720|GPU: {d}. Menos de 6 GB de VRAM: la generación puede estar limitada.
721|Espacio libre en disco: {gb:.1f} GB
722|Solo hay {gb:.1f} GB libres. Una biblioteca necesita mucho más.
723|Mostrar AniHUB
724|Salir
725|AniHUB sigue funcionando en la bandeja.
726|Generar
727|Generaciones guardadas
728|Iniciar Forge
729|Detener Forge
730|Carpeta de Forge...
731|Registro de Forge
732|Prompt
733|Prompt negativo
734|Checkpoint
735|Sampler
736|Scheduler
737|Pasos
738|Tamaño
739|Semilla (-1 = aleatoria)
740|Número de lotes
741|Tamaño del lote
742|Preparando (cargando el modelo)...
743|Generar
744|Detener
745|Deteniendo...
746|Borrar resultados
747|Clasificación
748|Hecho: {n} imagen(es). Los archivos se guardan en la carpeta sd de la biblioteca.
749|Inicia Forge para generar (el botón de arriba).
750|detenido
751|iniciando...
752|en ejecución
753|en ejecución (externo)
754|se bloqueó
755|Forge se inició fuera de AniHUB, así que AniHUB no lo detendrá.
756|Forge se cerró inesperadamente. Abre el registro.
757|Carpeta de Forge (con webui.bat)
758|Puerto de la API
759|Solo API, sin interfaz web (--nowebui)
760|Argumentos de inicio adicionales
761|Detener Forge tras inactividad, minutos (0 = nunca)
762|Leyendo
763|Completado
764|En pausa
765|Abandonado
766|Planeo leer
767|Biblioteca
768|Explorar
769|Extensiones
770|Novedades
771|Iniciar el servicio de manga
772|Detener
773|Iniciar con AniHUB (para avisos de capítulos nuevos)
774|Inicia el servicio de manga (botón de arriba) para usar esta sección.
775|La lectura de manga usa el motor Suwayomi, que ejecuta extensiones de Tachiyomi. AniHUB lo descargará (unos 340 MB, incluye su propio Java; no hay que instalar nada más).
776|Descargar e instalar Suwayomi
777|Cancelar
778|Buscando la última versión...
779|Descargando: {done:.0f} / {total:.0f} MB
780|Verificando...
781|Descomprimiendo...
782|Hecho
783|Filtrar la biblioteca por título
784|Buscar capítulos nuevos
785|Consultando capítulos nuevos a las fuentes...
786|Todos
787|Títulos en la biblioteca: {n}
788|Populares
789|Últimos
790|Buscar títulos en esta fuente
791|Aún no hay fuentes: instala una extensión en la pestaña Extensiones.
792|Actualizar desde la fuente
793|Empezar a leer
794|Continuar leyendo
795|Capítulo
796|Grupo
797|Fecha
798|Título
799|Marcar como leído
800|Marcar como no leído
801|Descargar para leer sin conexión
802|Eliminar descarga
803|★ En la biblioteca
804|☆ Añadir a la biblioteca
805|(sin categoría)
806|Capítulos: {n}, sin leer: {unread}
807|En cola de descarga...
808|Descargando: {n} en cola, actual {p}%
809|Capítulos: {n}
810|Capítulos nuevos: {n} ({titles})
811|Buscar extensiones
812|Solo instaladas
813|Instalar desde archivo...
814|Nombre
815|Idioma
816|Versión
817|Estado
818|Desinstalar
819|Repositorios:
820|URL del índice del repositorio de extensiones
821|Añadir
822|Quitar
823|Todos los idiomas
824|Trabajando con el catálogo...
825|Procesando: {name}...
826|instalada
827|actualización disponible
828|(obsoleta)
829|Mostradas: {n} de {total}. Las extensiones 18+ aparecen cuando la clasificación Explícito está activada en Ajustes.
830|Windows mantiene bloqueado este archivo de extensión mientras el servicio está en marcha. Detén el servicio de manga, inícialo de nuevo y reintenta.
831|Consejo: prefiere la versión .jar de una extensión; el motor rechaza algunos .apk.
832|Página simple
833|Página doble
834|Webtoon
835|De derecha a izquierda
836|Este capítulo no tiene páginas
837|Puerto del servicio de manga
838|Buscar capítulos nuevos cada (minutos)
839|Fecha de adición
840|Tamaño de archivo
841|Clasificación de contenido
842|Nombre
843|Mis estrellas
844|Puntuación del sitio
845|Autor
846|Ascendente / descendente
847|Todos
848|Favoritos
849|Categorías
850|Colecciones
851|Etiquetas inteligentes
852|Papelera
853|predeterminada
854|Nueva categoría...
855|Nueva colección...
856|Renombrar...
857|Eliminar
858|Hacer predeterminada (los elementos nuevos irán aquí)
859|Quitar la predeterminada
860|Subir
861|Bajar
862|Nombre:
863|Este nombre ya está en uso.
864|¿Eliminar esta categoría? Los elementos se quedan en la biblioteca.
865|¿Eliminar esta colección? Los elementos se quedan en la biblioteca.
866|Vaciar la papelera
867|Cualquier estrella
868|Importar...
869|Herramientas
870|Acciones
871|Mostrados: {shown} de {total}
872|Seleccionados: {n}
873|los elementos se eliminan definitivamente tras {days} días
874|Selecciona primero elementos
875|Restaurar
876|Eliminar definitivamente
877|¿Eliminar definitivamente {n} elemento(s)? No se puede deshacer.
878|Editar etiquetas...
879|Ejecutar el etiquetador automático
880|Etiquetar automáticamente todos los elementos sin etiquetas
881|Etiquetando automáticamente {n} elemento(s)...
882|Etiquetados automáticamente: {n}
883|Añadir a la colección
884|Quitar de esta colección
885|Añadir a la categoría
886|Quitar de esta categoría
887|Clasificación de contenido
888|Mi valoración
889|Sin valoración
890|♥ Añadir a favoritos
891|Quitar de favoritos
892|Enviar a img2img
893|Mostrar en la carpeta
894|Mover a la papelera
895|¿Mover {n} elemento(s) a la papelera? Puedes restaurarlos desde allí.
896|Sí
897|Sí, siempre
898|No
899|Etiquetas ({n} elemento(s))
900|Escribe una etiqueta para añadir (aparecen sugerencias)
901|Añadir
902|Desmarca una etiqueta para quitarla.
903|Marcada: en todos los elementos seleccionados. Parcialmente marcada: en algunos. Marca para añadir a todos, desmarca para quitar de todos.
904|Gestor de etiquetas
905|Jerarquía
906|Etiquetas inteligentes
907|Filtrar etiquetas
908|Etiqueta
909|Elementos
910|Etiqueta padre
911|Establecer padre
912|Quitar padre
913|Renombrar / fusionar...
914|Nuevo nombre (una etiqueta existente se fusionará):
915|Eliminar etiqueta
916|¿Eliminar la etiqueta {name} de toda la biblioteca?
917|Una etiqueta padre también encuentra todo lo etiquetado con sus hijas (buscar 'vocaloid' encuentra 'hatsune_miku').
918|Etiquetas en la jerarquía: {n}
919|Nombre de la etiqueta inteligente
920|Añadir una etiqueta al grupo
921|Quitar seleccionadas
922|Nueva
923|Guardar
924|Eliminar
925|Dale un nombre a la etiqueta inteligente y al menos una etiqueta.
926|Una etiqueta inteligente es una carpeta de etiquetas: buscar '@nombre' encuentra elementos con CUALQUIERA de ellas (incluidas las hijas). También puedes pulsarla en la barra lateral.
927|Importar imágenes locales
928|Añadir carpeta...
929|Añadir archivos...
930|Limpiar
931|(categoría predeterminada)
932|Etiquetar con el etiquetador automático (también define la clasificación)
933|El etiquetador automático está desactivado o su modelo no está descargado: consulta Ajustes.
934|Clasificación:
935|Categoría:
936|Importar
937|Cancelar
938|Los archivos se copian a la biblioteca; los duplicados exactos se omiten y las imágenes similares se marcan.
939|Importados: {saved}, duplicados omitidos: {duplicate}, fallidos: {failed}, posiblemente similares: {similar}, cancelados: {cancelled}
940|Buscar imágenes similares
941|Archivo
942|Tamaño
943|Dimensiones
944|Clasificación
945|Escaneando...
946|Marcar todas menos la mayor de cada grupo
947|Mover las marcadas a la papelera
948|Grupos de imágenes visualmente similares (copias redimensionadas o recomprimidas). El archivo más grande aparece primero.
949|Grupo {n} ({k} imágenes)
950|Grupos encontrados: {n}
951|No se encontraron imágenes similares.
952|Movidas a la papelera: {n}
953|posibles duplicados: {n}
954|Guardar y avisar
955|Omitir
956|Desactivado
957|Imágenes visualmente similares al guardar
958|Vaciar la papelera tras (días, 0 = nunca)
959|Preguntar antes de mover a la papelera
960|Biblioteca
961|Etiquetador automático (WD14)
962|Etiquetar automáticamente las imágenes importadas y las publicaciones sin etiquetas
963|Modelo
964|Descargar modelo
965|instalado
966|no descargado (~{mb} MB, se ejecuta en la CPU)
967|Confianza de etiquetas
968|Confianza de personajes
969|Imagen de origen (img2img)
970|Elegir...
971|Quitar
972|Intensidad de denoising
973|Generar (img2img)
974|Imagen cargada como origen de img2img. Inicia Forge si no está en marcha y pulsa Generar.
975|Cola
976|Historial
977|Guardar preajuste...
978|Eliminar
979|(preajuste)
980|Preajuste aplicado: {name}
981|Estilos
982|Guardar el prompt como estilo...
983|Eliminar estilo
984|Cargar desde imagen...
985|Esta imagen no tiene parámetros de generación.
986|Parámetros cargados desde {name}
987|(auto)
988|mantener los de Forge
989|Clip skip
990|Hires fix
991|igual que los pasos
992|Ampliar por
993|Upscaler
994|Pasos de hires
995|Denoising de hires
996|Variación de semilla
997|Semilla de variación
998|Intensidad de variación
999|Añadir a la cola
1000|Cuántas copias poner en cola (cada una con semilla aleatoria)
1001|En cola: {n}
1002|Escribe primero un prompt.
1003|Ampliar
1004|Ampliando {n} imagen(es)...
1005|Ampliadas: {n}. Los archivos están en la carpeta sd.
1006|Peso:
1007|Insertar en el prompt
1008|Disponibles: {n}
1009|Estado
1010|Parámetros
1011|Backend
1012|Imágenes
1013|Iniciar la cola
1014|Pausar tras la actual
1015|Cancelar la actual
1016|Duplicar
1017|Quitar
1018|Limpiar terminadas
1019|en espera
1020|en ejecución
1021|hecha
1022|fallida
1023|cancelada
1024|No hay ningún backend de Forge en marcha: inicia uno y pulsa Iniciar la cola de nuevo.
1025|Programación
1026|Ejecutar la cola a las
1027|todos los días
1028|una vez
1029|Iniciar Forge automáticamente si no está en marcha
1030|Detener el Forge que inició AniHUB cuando termine la cola
1031|Solo si el PC estuvo inactivo durante (minutos, 0 = ignorar)
1032|Próxima ejecución: {when}
1033|La programación está desactivada.
1034|Se inició la ejecución programada.
1035|Llegó la hora programada, pero la cola está vacía.
1036|Backends
1037|GPU predeterminada
1038|Buscar prompts y semillas
1039|Cargar parámetros
1040|Guardar como preajuste...
1041|Repetir (cola)
1042|Quitar del historial
1043|Borrar el historial
1044|¿Borrar todo el historial? Los archivos de imagen no se eliminan.
1045|Mostrados: {shown} de {total}
1046|Preajuste guardado: {name}
1047|En cola: {n}
1048|Pega un enlace de modelo de CivitAI
1049|Abrir
1050|Buscar en CivitAI
1051|Checkpoints
1052|LoRA
1053|Embeddings
1054|VAE
1055|Más descargados
1056|Mejor valorados
1057|Más recientes
1058|Cualquier modelo base
1059|Incluir 18+
1060|Activa la clasificación Explícito en Ajustes para buscar modelos 18+.
1061|Más resultados
1062|Versión
1063|Archivo
1064|Descargar a Forge
1065|Abrir en CivitAI
1066|Encontrados: {n}
1067|Eso no es un enlace de modelo de CivitAI.
1068|Palabras de activación: {words}
1069|Indica primero la carpeta de Forge (Ajustes).
1070|Descargando {name} en {folder}...
1071|Instalado: {path}
1072|Descarga cancelada.
1073|Generación
1074|Backends adicionales: el mismo Forge en otro puerto, fijado a una GPU (reinicia AniHUB para aplicarlo).
1075|Activo
1076|Nombre
1077|Puerto
1078|GPU
1079|Añadir backend
1080|Quitar seleccionado
1081|Clave de API de CivitAI
1082|opcional: necesaria para algunos archivos
1083|Desde imagen
1084|Los resultados aparecerán aquí
1085|Escribe un prompt, inicia Forge y pulsa Generar. Cada imagen se guarda en el disco; elige las que quieras conservar.
1086|El servicio de manga está detenido
1087|Aquí no hay nada todavía
1088|Guarda imágenes desde la pestaña Sitios o importa una carpeta: aparecerán aquí.
1089|Encuentra algo que mirar
1090|Elige una fuente, escribe etiquetas y pulsa Buscar. Usa -etiqueta para excluir.
1091|Apariencia
1092|Almacenamiento y contenido
1093|Red
1094|Atrás
1095|Siguiente
1096|Finalizar
1097|Cancelar
1098|La biblioteca no está disponible
1360|Instalar sd-scripts…
1361|Instalando sd-scripts
1362|Descargando sd-scripts, creando su propio entorno de Python e instalando PyTorch con sus dependencias (varios GB, puede tardar) en:\n{dest}
1363|Comprobando espacio libre y Python…
1364|Descargado {done} de {total} MB
1365|Descomprimiendo…
1366|Creando su entorno de Python…
1367|Actualizando pip…
1368|Instalando PyTorch (varios GB, puede tardar)…
1369|Instalando el resto de dependencias de sd-scripts…
1370|Configurando Accelerate…
1371|Listo. sd-scripts está instalado: {path}
1383|Publicar en CivitAI.red…
1384|Publicando «{name}»
1385|CivitAI no tiene API para subir un modelo, solo su propio sitio. Aquí se prepara todo (imágenes de muestra, descripción, modelos base detectados) y se copia/abre lo necesario; la subida real son unos clics en su página de carga.
1386|Añadir imágenes de muestra…
1387|Detectando el modelo…
1388|Modelo no detectado (esta imagen no tiene esos metadatos)
1389|Descripción
1390|Copiar descripción y abrir CivitAI.red
1391|Abrir la carpeta de las imágenes
1392|Descripción copiada, CivitAI.red está abierto: arrastra las imágenes y pega la descripción allí.
1393|Subir a rule34.xxx…
1394|Preparando «{name}» para rule34.xxx
1395|rule34.xxx no tiene API para subir una imagen, solo su propio sitio. El autoetiquetador rellena etiquetas iniciales, que puedes añadir o quitar abajo; luego las etiquetas se copian y se abre la carpeta de la imagen, así que la subida real son unos clics en su página de carga.
1396|Etiquetas
1397|Detectando etiquetas…
1398|Clasificación sugerida: {rating}
1399|Copiar etiquetas y abrir rule34.xxx
1400|Abrir la carpeta de la imagen
1401|Etiquetas copiadas, rule34.xxx está abierto: elige el archivo allí y pega las etiquetas.
1402|Volumen
1403|Pausar
1404|Reanudar descarga
1405|en pausa
1406|Pausar
1407|Reanudar
1408|Reanudar descarga
1409|Descarga en pausa: haz clic en Reanudar para continuar.
1410|Pausar
1411|Reanudar
1412|Descarga en pausa. Haz clic en Reanudar para continuar.
1413|Pausar
1414|Reanudar
1415|Entrenamiento en pausa: el proceso está congelado, no se pierde nada.
1416|Pausar
1417|Reanudar
1418|En pausa. Haz clic en Reanudar para continuar.
1419|Pausar
1420|Reanudar
1421|Complementos
1422|Corregir caras automáticamente (ADetailer)
1423|Instalar ADetailer…
1424|Instalando {name}
1425|Descargando en {dest}
1426|Instalado. Reinicia Forge para cargarlo.
1427|ADetailer instalado — reinicia Forge para empezar a usarlo.
1428|Listas de comodines
1429|Escribe __nombre__ en cualquier parte del prompt para elegir una entrada al azar de la lista llamada «nombre» en cada generación — una elección distinta por imagen, incluso dentro del mismo lote.
1430|Nueva lista
1431|Eliminar lista
1432|Nombre de la lista (se usa como __nombre__)
1433|Entradas (una por línea)
1434|kimono\ntraje de baño\nuniforme escolar
1435|Control de pose (OpenPose)
1436|Elegir foto de referencia…
1437|Quitar
1438|Intensidad
1439|No se encontró ningún modelo OpenPose en la carpeta de modelos ControlNet de Forge — descarga uno allí para usar el control de pose.
1440|Dividir en zonas (Forge Couple)
1441|Instalar Forge Couple…
1442|De izquierda a derecha
1443|De arriba a abajo
1444|Cada línea del prompt de arriba se convierte en su propia zona — escribe una línea por zona en vez de un prompt largo.
1445|Listas de comodines…
1446|Usa __nombre__ en el prompt para elegir una etiqueta al azar de una lista
1447|Animar (AnimateDiff)
1448|Instalar AnimateDiff…
1449|Convierte esta generación en un GIF corto en lugar de una imagen fija — funciona con un prompt nuevo o con un arte existente enviado a img2img.
1450|No se encontró ningún modelo de módulo de movimiento en la carpeta propia de AnimateDiff — descarga uno allí para animar.
1451|Fotogramas
1452|FPS
1472|VTube
1473|Iniciar ComfyUI
1474|Detener ComfyUI
1475|Registro de ComfyUI
1476|Abrir imagen…
1477|Suelta aquí una imagen de anime de frente, o abre una — funciona mejor si el pelo no cubre la cara y el fondo es liso
1478|Resolución
1479|Pasos
1480|Dividir ojos / orejas / manos en izquierda-derecha
1481|Mejor división del pelo delantero/trasero (LaMa)
1482|Modo de poca VRAM (tarjetas de 10–12 GB; más lento)
1483|Dividir en capas
1484|Cancelar
1485|ComfyUI-See-through no está instalado en este ComfyUI (su carpeta custom_nodes).
1486|Dividiendo en capas… esto puede tardar desde unos minutos hasta decenas de minutos
1487|{m} min {s} s transcurridos
1488|Listo: {n} capas
1489|Cancelado.
1490|Capas
1491|Guardar PSD como…
1492|Guardado en {name}
1493|Mostrar en la carpeta
1494|Abre primero una imagen.
1495|Carpeta de ComfyUI
1496|Puerto de ComfyUI
1497|Enviar a VTube
1498|Notificaciones
1499|Borrar
1500|Aún no hay notificaciones
1501|Atajos de teclado
1502|Atajos de teclado
1503|Restablecer
1504|Paleta de comandos
1505|Notificaciones
1506|Deshacer
1507|Rehacer
1508|Ir a Arte
1509|Ir a Manga
1510|Ir a Novelas ligeras
1511|Ir a Generación
1512|Ir a Anime
1513|Ir a Configuración
1514|Deshecho: {label}
1515|Rehecho: {label}
1516|Discord Rich Presence
1517|Mostrar actividad en Discord
1518|ID de aplicación
1519|de discord.com/developers/applications
1520|Explorando: {section}
1521|Generando con Stable Diffusion
1522|generación
1523|generaciones de Stable Diffusion
1524|Por modelo
1525|Copiar imagen
1526|Guardar como…
1527|Copiar ruta del archivo
1528|Abrir carpeta contenedora
1529|Nueva sección…
1530|Renombrar sección
1531|Eliminar sección
1532|Examinar…
1533|Carpetas
1534|Generaciones
1535|Salida de VTube
1536|Biblioteca de música
1537|Carpetas
1538|Carpetas del equipo
1539|Añadir carpeta…
1540|Nombre
1541|Quitar de la lista
1542|Añadir a la biblioteca
1543|Añadidos: {saved}, duplicados: {dup}, fallidos: {failed}
1544|Ninguna carpeta abierta
1545|Añade una carpeta a la izquierda, o abre una para ver sus imágenes aquí -- no se copia nada.
1546|Descargar ComfyUI…
1547|Instalando ComfyUI
1548|Descargando ComfyUI (aprox. 1,9 GB) y descomprimiendo en:\n{dest}
1549|Listo. ComfyUI está instalado: {path}
1550|Personaje {n} — {name}
1551|Personajes:
1552|Una etiqueta pulsada en el catálogo se añade a este personaje
1553|Editar…
1554|Sección
1555|Nombre
1556|Pertenece a un personaje (una instancia por personaje activo)
1557|Editar…
1558|Categoría
1559|Nombre
1560|Permitir varias etiquetas a la vez
1561|Guardar todas las etiquetas en un archivo…
1562|Cargar etiquetas desde un archivo…
1563|Guardado: {n} etiquetas → {path}
1564|Cargado: {nodes} categorías, {tags} etiquetas, {images} imágenes
1565|Redibujar todas las imágenes aquí (Forge)
1566|Aquí no hay nada que redibujar
"""
