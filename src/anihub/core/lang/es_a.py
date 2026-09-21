"""Spanish, keys 0-549."""
DATA = r"""
0|Arte
1|Manga
2|Generación
3|Anime
4|Novelas
5|Ajustes
6|Explorar sitios
7|Biblioteca
8|Esta sección se implementará en una etapa posterior.
9|Etiquetas separadas por espacios, -etiqueta para excluir
10|Buscar
11|Fuente
12|Guardar en la biblioteca
13|Abrir
14|Cerrar
15|Cargando...
16|No hay más resultados
17|Error: {msg}
18|Guardados: {saved}, duplicados: {dup}, fallidos: {failed}
19|Cargados: {n}
20|Elementos en la biblioteca: {n}
21|Ratón: flechas laterales o rueda para pasar · botones abajo · teclas: ←/→ Espacio P F T L M S Esc
22|Anterior (←)
23|Siguiente (→)
24|Presentación (P)
25|Favorito (L)
26|Valoración
27|Sin valoración
28|Guardar en la biblioteca (S)
29|Etiquetas (T)
30|Pantalla completa (F)
31|Cerrar (Esc)
32|Reproducir / pausar
33|Sonido (M)
34|Capítulo anterior ([)
35|Capítulo siguiente (])
36|Página anterior
37|Página siguiente
38|Izquierda
39|Derecha
40|Pantalla completa (F)
41|Cerrar (Esc)
42|Filtros
43|Buscar por géneros, etiquetas, estado y más
44|Iniciar sesión en la fuente
45|Iniciar sesión / cambiar los ajustes de esta fuente
46|Solo no leídos
47|Cualquier género
48|Cualquier estado
49|Desconocido
50|En publicación
51|Completado
52|Con licencia
53|Publicación finalizada
54|Cancelado
55|En pausa
56|Buscar un género o etiqueta
57|Restablecer
58|Aplicar filtros
59|Esta fuente no tiene filtros: usa la búsqueda por título.
60|Ascendente
61|Clic: incluir → excluir → desactivar
62|Ajustes: {name}
63|Esta fuente no tiene ajustes.
64|Guardado.
65|Las fuentes que requieren una cuenta piden aquí el usuario y la contraseña. Los cambios se guardan al instante y la fuente los usa en la siguiente petición. El motor no admite sitios que inician sesión mediante una página web o una comprobación de Cloudflare.
66|Reglas automáticas
67|Nueva
68|Eliminar
69|Las reglas se ejecutan de arriba abajo
70|Nombre de la regla
71|Nueva regla
72|Cuando un elemento…
73|…haz esto
74|Tiene todas las etiquetas
75|Tiene alguna etiqueta
76|No tiene ninguna de
77|etiqueta etiqueta ... (una etiqueta padre también incluye a sus hijas)
78|etiqueta etiqueta ...
79|etiqueta etiqueta ...
80|Autor
81|nombres de artistas
82|Fuente
84|Clasificación
85|Sección
86|Arte
87|Generaciones
88|Añadir a la colección
89|Añadir a la categoría
90|Añadir etiquetas
91|etiqueta etiqueta ...
92|Establecer clasificación de contenido
93|Establecer mi valoración
94|Marcar como favorito
96|sin cambios
97|Guardar regla
98|Aplicar a toda la biblioteca
99|Aplicar reglas automáticamente a los elementos nuevos
100|Una regla necesita al menos una condición y una acción. Las reglas se ejecutan en el orden de la lista con cada elemento nuevo (guardado desde un sitio, importado, generado) y después del etiquetado automático.
101|Añade al menos una condición y una acción.
102|Regla guardada.
103|Rellena las condiciones y las acciones y guarda.
104|¿Eliminar la regla «{name}»?
105|¿Ejecutar todas las reglas activas sobre todos los elementos de la biblioteca?
106|Hecho: {n} coincidencias en {rules} reglas.
107|Comparar
108|Comparar las dos (antes / después)...
109|Antes
110|Después
111|Lado a lado
112|Intercambiar
113|Arrastra el divisor o usa ←/→ · Espacio: lado a lado · X: intercambiar
114|En línea
115|Sin conexión
116|Modo sin conexión: nada sale a internet
117|Modo sin conexión: los sitios, el catálogo de manga, CivitAI y las descargas están desactivados. Tu biblioteca, los capítulos guardados y la generación local siguen funcionando. Forge aplica el ajuste en su próximo inicio.
118|Máscara de inpaint
119|Máscara (inpaint)…
120|Editar máscara…
121|Quitar máscara
122|Pincel
123|Borrador (E)
124|Deshacer
125|Borrar
126|Invertir
127|Usar máscara
128|Pinta lo que debe redibujarse. El botón izquierdo pinta, el derecho hace lo contrario, la rueda cambia el tamaño del pincel y Ctrl+Z deshace.
129|Desenfoque de la máscara
130|Contenido enmascarado
131|Original
132|Relleno
133|Ruido latente
134|Latente vacío
135|Solo el área enmascarada (resolución completa)
136|Máscara definida: solo se redibujará la zona pintada.
137|Cuadrícula X/Y…
138|Compara cómo cambian la imagen uno o dos parámetros
139|Cuadrícula X/Y
140|Eje X
141|Eje Y
142|— (una fila)
143|Elegir…
144|valores: 20, 30, 40 o un rango inicio:fin:paso (20:40:10)
145|primer valor = texto a buscar en el prompt, los demás lo reemplazan: cat, dog, fox
146|Pasos
147|CFG
148|Sampler
149|Scheduler
150|Semilla
151|Denoising (img2img)
152|Clip skip
153|Checkpoint
154|Buscar/reemplazar en el prompt
155|{x} × {y} = {n} imágenes
156|{n} imágenes son demasiadas (límite {max})
157|Generar la cuadrícula
158|Forge está ocupado con otra cosa.
159|Generando…
160|La tabla aparecerá aquí.
161|No se generó nada.
162|Hecho: {n} imágenes.
163|Detenido: {n} de {total} imágenes.
164|Guardar como…
165|A la biblioteca
166|Guardado en la biblioteca.
167|Ya está en la biblioteca.
168|Espera a que termine la ejecución o pulsa Detener.
169|Todas las imágenes usan el formulario Generar actual y la misma semilla; solo cambian los parámetros elegidos. Las celdas también se guardan en el historial de generación.
170|Temporada
171|Mi lista
172|Ver
173|Viendo
174|Planeado
175|Completado
176|En pausa
177|Abandonado
178|Reviendo
179|Invierno
180|Primavera
181|Verano
182|Otoño
183|TV
184|TV corto
185|Película
186|Especial
187|OVA
188|ONA
189|Música
190|En emisión
191|Finalizado
192|Aún no emitido
193|Cancelado
194|En pausa
195|d
196|h
197|min
198|El episodio {ep} se está emitiendo ahora
199|Episodio {ep} en {span}
200|{n} episodios
201|Sin descripción.
202|Esta temporada
203|Busca cualquier anime por título
204|Resultados de la búsqueda
205|Abrir
206|Añadir a la lista
207|«{title}»: {status}
208|Estado
209|Episodios vistos
210|Puntuación
211|Guardar
212|Añadir a la lista
213|Quitar de la lista
214|Guardado.
215|Eliminado.
216|¿Quitar {n} elemento(s) de tu lista?
217|Un episodio más visto
218|Establecer estado
219|Sin puntuación
220|Todos
221|Títulos en la lista: {n}
222|Sincronizar con AniList
223|Inicia sesión primero en AniList (botón Cuenta).
224|Sincronizando…
225|Sincronizado: enviados {sent}, recibidos {got}.
226|Título
227|Episodios
228|Puntuación
229|Estado
230|Próximo episodio
231|Cuenta de AniList
232|AniList: sin sesión
233|Sesión iniciada como {name}.
234|Abrir los ajustes de desarrollador de AniList
235|Copiar la URL de redirección
236|Client ID numérico de tu cliente de API
237|Abrir la página de autorización
238|Token de acceso
239|pega el token que aparece al aprobar
240|Iniciar sesión
241|Cerrar sesión
242|Introduce primero el Client ID numérico (paso 2).
243|La lista funciona sin cuenta. Para reflejarla en AniList:\n1. Abre los ajustes de desarrollador y crea un cliente; como URL de redirección usa {redirect}\n2. Pega abajo el ID numérico del cliente y abre la página de autorización.\n3. Aprueba el acceso, copia el token que aparece en la página y pégalo aquí.\nEl token se guarda solo en este equipo.
244|Ver episodios estará disponible pronto
245|Aquí aparecerán las fuentes para ver episodios. El calendario de temporada y tu lista ya funcionan.
246|Seguimiento
247|Seguimiento…
248|Seguimiento: {title}
249|MyAnimeList, AniList, Shikimori, Kitsu y más: una vez vinculado un título, los capítulos que leas se envían al servicio.
250|{name}: sesión iniciada.
251|{name}: sin sesión.
252|El token ha caducado: inicia sesión de nuevo.
253|Abrir la página de inicio de sesión
254|pega la dirección en la que acaba el navegador
255|1. Abre la página de inicio de sesión y aprueba el acceso.\n2. El navegador puede mostrar un error o pedir abrir una aplicación: no pasa nada. Copia la dirección completa de esa página (o el token/código mostrado) y pégala abajo.
256|Iniciar sesión
257|Cerrar sesión
258|usuario o correo electrónico
259|contraseña
260|Sesión iniciada.
261|El servicio no lo aceptó.
262|Sesión cerrada.
263|Estado
264|Capítulos leídos
265|Puntuación
266|Desvincular
267|¿Eliminar también la entrada en {name}? (Sí = eliminar allí también, No = solo desvincular aquí)
268|Vincular con esta entrada
269|Encontrados: {n}
270|{n} cap.
271|No has iniciado sesión en ningún servicio: usa el botón «Seguimiento».
272|Novelas ligeras
273|Añadir libros…
274|Añadir una carpeta…
275|Buscar por título o autor
276|Solo sin terminar
277|Libros
278|Tu estantería está vacía
279|Añade libros EPUB, FB2 o TXT: se recuerdan el progreso de lectura, el tamaño de letra y el tema.
280|Libros: {n}
281|{n} capítulos
282|No se encontraron archivos EPUB / FB2 / TXT.
283|Añadidos: {saved}, ya estaban: {duplicate}, fallidos: {failed}.
284|Marcar como leído
285|Marcar como no leído
286|¿Eliminar «{title}» de la estantería? También se elimina la copia de la biblioteca.
287|Contenido (T)
288|Texto más pequeño (−)
289|Texto más grande (+)
290|Tema: como la aplicación
291|Tema: oscuro
292|Tema: claro
293|Tema: sepia
294|{n} / {total} · {pct}%
295|Archivos locales
296|Retroceder 10 s (←)
297|Avanzar 10 s (→)
298|Abrir en un reproductor externo
299|Esta fuente no tiene stream para el episodio.
300|stream
301|Episodio {n}
302|Este stream necesita cabeceras de petición especiales: usa el botón del reproductor externo (define anime.external_player en config.json, p. ej. mpv).
303|No se puede reproducir: {msg}
304|Buscar en la fuente (vacío = todo / populares)
305|Abrir la carpeta de anime
306|¿Qué título de AniList es este?
307|Este
308|Vincular con AniList…
309|Cambiar vínculo…
310|Desvincular
311|Abrir el sitio
312|№
313|Título
314|Estado
315|Ver
316|Marcar como visto
317|Marcar como no visto
318|Elige un título
319|Haz doble clic en un título para ver sus episodios. Archivos locales: pon una carpeta por serie (con los episodios dentro) en la carpeta de anime. Más sitios e idiomas: botón Extensiones.
320|Aún no hay series: pulsa «Abrir la carpeta de anime» y pon allí una carpeta por serie.
321|Episodios: {n}
322|No se encontraron episodios.
323|Vinculado con AniList: {title}. Los episodios vistos actualizan tu lista.
324|Sin vincular con AniList: los episodios vistos no actualizarán tu lista.
325|visto
326|continuar desde {t}
327|Vinculado.
328|Actualización disponible
329|AniHUB {new} está disponible (tienes {old}).
330|Descargar e instalar
331|Reinstalar esta versión
332|Instalar esta versión anterior
333|Más tarde
334|Omitir esta versión
335|Abrir en GitHub
336|instalada
337|versión preliminar
338|Sin descripción.
339|Esta versión no tiene instalador.
340|Descargando el instalador…
341|Iniciando el instalador; AniHUB se cerrará.
342|Cancelado.
343|Todas las versiones…
344|Versiones: {n}
345|Actualización {v} disponible
346|Acerca de y actualizaciones
347|AniHUB versión {v}
348|Buscar actualizaciones automáticamente (una vez al día)
349|Buscar actualizaciones
350|Tienes la última versión.
351|Abrir la carpeta de registros
352|Descargas
353|En cola de descarga: {n} (consulta Descargas en la barra de estado).
354|Publicación
355|Estado
356|Detalles
357|en cola
358|descargando
359|guardado
360|ya está en la biblioteca
361|fallido
362|cancelado
363|Pausar
364|Reanudar
365|Cancelar seleccionadas
366|Cancelar todas
367|Reintentar fallidas
368|Limpiar terminadas
369|A la vez:
370|Límite de velocidad:
371|ilimitado
372|MB/s
373|Activas: {active} (descargando {running}) · guardadas {done} · duplicadas {dup} · fallidas {failed}
374|Descargas: {n}
375|Descargas
376|imágenes similares ya presentes: {n}
377|guardadas {n}
378|duplicadas {n}
379|fallidas {n}
380|canceladas {n}
381|nada
382|Descargas terminadas: {details}.
383|Descargadas {n}: {details}.
384|Copias de seguridad
385|Hacer copia de la base de datos de la biblioteca automáticamente
386|Incluir los ajustes (config.json) en las copias
387|Cada (días)
388|Conservar las últimas
389|Copiar ahora
390|Restaurar desde una copia…
391|Cancelar la restauración
392|Abrir la carpeta de copias
393|Hay una restauración programada: se aplica al iniciar AniHUB la próxima vez.
394|Última copia: {when} (copias: {n})
395|Aún no hay copias.
396|Creada: {name}
397|La copia está bien ({n} elementos). Reinicia AniHUB para aplicarla; la base de datos actual se conserva al lado como copia.
398|La base de datos de la biblioteca se restauró desde una copia.
399|Límite de caché (miniaturas, vídeos)
400|Comprobación de integridad de la biblioteca
401|Busca registros cuyo archivo ha desaparecido, archivos de la carpeta arts que la biblioteca no conoce y (opcionalmente) archivos que cambiaron desde que se guardaron. No se elimina nada sin preguntar.
402|Verificar también el contenido de los archivos (lento)
403|Comprobar
404|Eliminar registros sin archivos
405|Optimizar la base de datos
406|Abrir la carpeta arts
407|Problema
408|Archivo
409|falta el archivo
410|el contenido cambió
411|no está en la biblioteca
412|Base de datos: correcta
413|Problema en la base de datos: {msg}
414|comprobados: {n}
415|no se encontraron problemas
416|faltan: {missing}, modificados: {damaged}, archivos desconocidos: {orphans}
417|¿Eliminar {n} registros cuyos archivos ya no existen? También se eliminan sus etiquetas y vínculos a colecciones.
418|Registros eliminados: {n}.
419|Base de datos optimizada.
420|Informar de un problema…
421|Informar de un problema
422|Ocurrió un error: infórmalo
423|Este texto es lo que se compartiría: versión, sistema, el último error y el registro reciente. Las claves, tokens, contraseñas y tu nombre de usuario se eliminan automáticamente; léelo antes de publicar. AniHUB no envía nada por sí mismo.
424|¿Qué hiciste, qué esperabas y qué pasó?
425|Incluir el registro reciente
426|El informe:
427|Copiar
428|Copiar y abrir GitHub Issues
429|Copiado al portapapeles.
430|La página del issue está abierta; el informe está en el portapapeles.
431|Informe de problema
432|Ir a una sección, ejecutar una acción, buscar una etiqueta, libro o serie…
433|↑ ↓ elegir · Intro ejecutar · Esc cerrar
434|sección
435|acción
436|biblioteca
437|libro
438|lista de anime
439|Buscar actualizaciones
440|Hacer copia de la biblioteca ahora
441|Abrir descargas
442|Cambiar el modo sin conexión
443|Cambiar tema oscuro / claro
444|Buscar en la biblioteca: {q}
445|Suscripciones
446|Suscribirse
447|Seguir
448|Nombre de la suscripción
449|Escribe primero una búsqueda: la suscripción la sigue.
450|Siguiendo «{name}»: se contarán las publicaciones nuevas.
451|Sin suscripciones
452|En Sitios, escribe una búsqueda (una etiqueta o un artista) y pulsa «Seguir»: las publicaciones nuevas aparecen aquí.
453|Comprobar ahora
454|Comprobar todas
455|Guardar nuevas
456|Marcar como visto
457|Eliminar
458|¿Eliminar la suscripción «{name}»?
459|Activada
460|Guardar las publicaciones nuevas automáticamente
461|nunca
462|{source}: {query}  ·  última comprobación: {when}
463|Publicaciones nuevas: {n}
464|Marcado como visto.
465|Modo sin conexión: sin comprobaciones.
466|Esta fuente ya no está disponible.
467|Publicaciones nuevas: {fresh}, guardadas automáticamente: {saved}
468|Estadísticas
469|elementos en la biblioteca
470|en disco
471|favoritos
472|valorados por ti
473|etiquetas
474|colecciones
475|libros leídos / en la estantería
476|episodios vistos
477|suscripciones
478|en la papelera
479|Añadidos por mes
480|Por fuente
481|Por clasificación de contenido
482|Etiquetas más usadas
483|Artistas más guardados
484|Exportar / compartir
485|Paquete AniHUB (.zip, con etiquetas)…
486|Galería HTML (.zip)…
487|Exportar la colección…
488|Importar un paquete…
489|Paquete AniHUB
490|Exportados {n} a {path}
491|Paquete «{name}»: añadidos {saved}, ya estaban {dup}, fallidos {failed}.
492|Música
493|Buscar pistas o álbumes
494|Abrir la carpeta de música
495|Volver a escanear
496|№
497|Pista
498|Aún no hay música
499|Pon una carpeta por título (un álbum de OST) en la carpeta de música: <biblioteca>/music/<Título>/pistas (mp3, flac, ogg…).
500|No suena nada
501|Archivos sueltos
502|{n} pistas
503|en tu lista: {title}
504|Aleatorio
505|Repetir
506|Modo de edad y filtro de etiquetas
507|Modo de edad
508|12+ — solo contenido seguro
509|16+ — se permiten pechos, el resto del contenido 18+ se oculta
510|18+ — sin restricciones integradas
511|Ocultas por el modo (no editable)
512|El modo 18+ no oculta nada por sí mismo.
513|Mis etiquetas ocultas
514|Separadas por espacios o comas. Un * al final oculta todas las etiquetas que empiecen así: guro*
515|¿Cambiar a 18+? Se mostrará contenido para adultos sin restricciones integradas. Debes tener 18 años o más.
516|Modo de edad
517|Elige un modo. Sus etiquetas restringidas cambian con el modo; puedes añadir tus propias etiquetas ocultas más tarde en Ajustes.
518|12+ — oculta todo lo relacionado con contenido 16+ y 18+
519|16+ — se permiten pechos, el resto del contenido 18+ se filtra
520|18+ — sin restricciones integradas
521|Sin iniciar sesión, Pixiv solo muestra obras para todos los públicos. Para R-18: inicia sesión en pixiv.net en tu navegador, pulsa F12 → Application → Cookies → pixiv.net, copia el valor de PHPSESSID y pégalo aquí (requiere el modo 18+). La cookie se queda en este equipo y solo se envía a pixiv.net.
522|palabras de búsqueda · user:nombre · board:nombre/tablero · un enlace de perfil o tablero
523|Ventana translúcida (Mica)
524|El material de Windows 11: la ventana deja ver el fondo de pantalla y los colores del escritorio. Requiere Windows 11 22H2 o posterior.
525|Extensiones
526|Extensiones: fuentes de repositorios
527|Repositorios
528|Añadir repositorio
529|Quitar
530|Dirección del index.json del repositorio:
531|Un repositorio es un index.json que lista extensiones (como en Aniyomi). Añade solo los que te merezcan confianza.
532|Nombre
533|Idioma
534|Versión
535|Estado
536|Instalar
537|Actualizar
538|Quitar
539|Ajustes
540|Actualizar catálogo
541|instalada
542|Extensiones disponibles: {n}
543|Hecho: {name}
544|¿Instalar «{name}»?\n\nUna extensión es un programa de Python y se ejecuta con tus permisos. Repositorio: {repo}
545|Las extensiones son código de terceros. Instala solo desde repositorios de confianza. El archivo se comprueba con la suma de verificación del repositorio.
546|Idiomas
547|Todos los idiomas
548|Estantería
549|En línea
"""
