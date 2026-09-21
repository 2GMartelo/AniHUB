"""French, keys 0-549."""
DATA = r"""
0|Illustrations
1|Manga
2|Génération
3|Anime
4|Romans
5|Réglages
6|Parcourir les sites
7|Bibliothèque
8|Cette section sera mise en place dans une étape ultérieure.
9|Tags séparés par des espaces, -tag pour exclure
10|Rechercher
11|Source
12|Enregistrer dans la bibliothèque
13|Ouvrir
14|Fermer
15|Chargement...
16|Plus aucun résultat
17|Erreur : {msg}
18|Enregistrés : {saved}, doublons : {dup}, échecs : {failed}
19|Chargés : {n}
20|Éléments dans la bibliothèque : {n}
21|Souris : flèches latérales ou molette pour naviguer · boutons en bas · touches : ←/→ Espace P F T L M S Échap
22|Précédent (←)
23|Suivant (→)
24|Diaporama (P)
25|Favori (L)
26|Note
27|Sans note
28|Enregistrer dans la bibliothèque (S)
29|Tags (T)
30|Plein écran (F)
31|Fermer (Échap)
32|Lecture / pause
33|Son (M)
34|Chapitre précédent ([)
35|Chapitre suivant (])
36|Page précédente
37|Page suivante
38|Gauche
39|Droite
40|Plein écran (F)
41|Fermer (Échap)
42|Filtres
43|Rechercher par genres, tags, statut et plus
44|Connexion à la source
45|Se connecter / modifier les réglages de cette source
46|Non lus seulement
47|Tous les genres
48|Tous les statuts
49|Inconnu
50|En cours
51|Terminé
52|Sous licence
53|Publication terminée
54|Annulé
55|En pause
56|Trouver un genre ou un tag
57|Réinitialiser
58|Appliquer les filtres
59|Cette source n'a pas de filtres : utilisez la recherche par titre.
60|Croissant
61|Clic : inclure → exclure → désactivé
62|Réglages : {name}
63|Cette source n'a pas de réglages.
64|Enregistré.
65|Les sources qui exigent un compte demandent ici l'identifiant et le mot de passe. Les changements sont enregistrés aussitôt et utilisés par la source à la requête suivante. Les sites qui se connectent via une page web ou une vérification Cloudflare ne sont pas pris en charge par le moteur.
66|Règles automatiques
67|Nouvelle
68|Supprimer
69|Les règles s'exécutent de haut en bas
70|Nom de la règle
71|Nouvelle règle
72|Quand un élément…
73|…faire ceci
74|A tous les tags
75|A l'un des tags
76|N'a aucun de
77|tag tag ... (un tag parent couvre aussi ses enfants)
78|tag tag ...
79|tag tag ...
80|Auteur
81|noms d'artistes
82|Source
84|Classification
85|Section
86|Illustrations
87|Générations
88|Ajouter à la collection
89|Ajouter à la catégorie
90|Ajouter des tags
91|tag tag ...
92|Définir la classification du contenu
93|Définir ma note
94|Marquer comme favori
96|inchangé
97|Enregistrer la règle
98|Appliquer à toute la bibliothèque
99|Appliquer automatiquement les règles aux nouveaux éléments
100|Une règle demande au moins une condition et une action. Les règles s'exécutent dans l'ordre de la liste pour chaque nouvel élément (enregistré depuis un site, importé, généré) et après l'étiquetage automatique.
101|Ajoutez au moins une condition et une action.
102|Règle enregistrée.
103|Remplissez les conditions et les actions, puis enregistrez.
104|Supprimer la règle « {name} » ?
105|Exécuter toutes les règles activées sur tous les éléments de la bibliothèque ?
106|Terminé : {n} correspondances dans {rules} règles.
107|Comparer
108|Comparer les deux (avant / après)...
109|Avant
110|Après
111|Côte à côte
112|Échanger
113|Faites glisser le séparateur ou utilisez ←/→ · Espace : côte à côte · X : échanger
114|En ligne
115|Hors ligne
116|Mode hors ligne : rien ne part sur Internet
117|Mode hors ligne : les sites, le catalogue de manga, CivitAI et les téléchargements sont désactivés. Votre bibliothèque, les chapitres enregistrés et la génération locale continuent de fonctionner. Forge prendra ce réglage au prochain démarrage.
118|Masque d'inpainting
119|Masque (inpainting)…
120|Modifier le masque…
121|Supprimer le masque
122|Pinceau
123|Gomme (E)
124|Annuler
125|Effacer
126|Inverser
127|Utiliser le masque
128|Peignez ce qui doit être redessiné. Le bouton gauche peint, le droit fait l'inverse, la molette change la taille du pinceau, Ctrl+Z annule.
129|Flou du masque
130|Contenu masqué
131|Original
132|Remplissage
133|Bruit latent
134|Latent vide
135|Uniquement la zone masquée (pleine résolution)
136|Masque défini : seule la zone peinte sera redessinée.
137|Grille X/Y…
138|Comparez comment un ou deux paramètres changent l'image
139|Grille X/Y
140|Axe X
141|Axe Y
142|— (une ligne)
143|Choisir…
144|valeurs : 20, 30, 40 ou une plage début:fin:pas (20:40:10)
145|première valeur = texte à trouver dans le prompt, les autres le remplacent : cat, dog, fox
146|Étapes
147|CFG
148|Sampler
149|Scheduler
150|Seed
151|Denoising (img2img)
152|Clip skip
153|Checkpoint
154|Rechercher/remplacer dans le prompt
155|{x} × {y} = {n} images
156|{n} images, c'est trop (limite {max})
157|Générer la grille
158|Forge est occupé par autre chose.
159|Génération…
160|Le tableau apparaît ici.
161|Rien n'a été généré.
162|Terminé : {n} images.
163|Arrêté : {n} images sur {total}.
164|Enregistrer sous…
165|Vers la bibliothèque
166|Enregistré dans la bibliothèque.
167|Déjà dans la bibliothèque.
168|Attendez la fin de l'exécution ou cliquez sur Arrêter.
169|Chaque image utilise le formulaire Générer actuel et la même seed ; seuls les paramètres choisis changent. Les cellules sont aussi conservées dans l'historique de génération.
170|Saison
171|Ma liste
172|Regarder
173|En cours
174|Prévu
175|Terminé
176|En pause
177|Abandonné
178|Revisionnage
179|Hiver
180|Printemps
181|Été
182|Automne
183|TV
184|TV court
185|Film
186|Spécial
187|OVA
188|ONA
189|Musique
190|En diffusion
191|Terminé
192|Pas encore diffusé
193|Annulé
194|En pause
195|j
196|h
197|min
198|L'épisode {ep} est diffusé en ce moment
199|Épisode {ep} dans {span}
200|{n} épisodes
201|Pas de description.
202|Cette saison
203|Recherchez n'importe quel anime par titre
204|Résultats de la recherche
205|Ouvrir
206|Ajouter à la liste
207|« {title} » : {status}
208|Statut
209|Épisodes vus
210|Note
211|Enregistrer
212|Ajouter à la liste
213|Retirer de la liste
214|Enregistré.
215|Retiré.
216|Retirer {n} élément(s) de votre liste ?
217|Un épisode de plus vu
218|Définir le statut
219|Sans note
220|Tous
221|Titres dans la liste : {n}
222|Synchroniser avec AniList
223|Connectez-vous d'abord à AniList (bouton Compte).
224|Synchronisation…
225|Synchronisé : envoyés {sent}, reçus {got}.
226|Titre
227|Épisodes
228|Note
229|Statut
230|Prochain épisode
231|Compte AniList
232|AniList : non connecté
233|Connecté en tant que {name}.
234|Ouvrir les réglages développeur d'AniList
235|Copier l'URL de redirection
236|Client ID numérique de votre client API
237|Ouvrir la page d'autorisation
238|Jeton d'accès
239|collez le jeton affiché après l'approbation
240|Se connecter
241|Se déconnecter
242|Saisissez d'abord le Client ID numérique (étape 2).
243|La liste fonctionne sans compte. Pour la refléter sur AniList :\n1. Ouvrez les réglages développeur et créez un client ; comme URL de redirection, utilisez {redirect}\n2. Collez ci-dessous l'ID numérique du client et ouvrez la page d'autorisation.\n3. Approuvez l'accès, copiez le jeton affiché sur la page et collez-le ici.\nLe jeton n'est conservé que sur cet ordinateur.
244|Le visionnage d'épisodes arrive bientôt
245|Les sources pour regarder des épisodes apparaîtront ici. Le calendrier de saison et votre liste fonctionnent déjà.
246|Suivi
247|Suivi…
248|Suivi : {title}
249|MyAnimeList, AniList, Shikimori, Kitsu et autres : une fois un titre lié, les chapitres que vous lisez sont envoyés au service.
250|{name} : connecté.
251|{name} : non connecté.
252|Le jeton a expiré : reconnectez-vous.
253|Ouvrir la page de connexion
254|collez l'adresse sur laquelle le navigateur aboutit
255|1. Ouvrez la page de connexion et approuvez l'accès.\n2. Le navigateur peut alors afficher une erreur ou proposer d'ouvrir une application : c'est normal. Copiez l'adresse complète de cette page (ou le jeton/code affiché) et collez-la ci-dessous.
256|Se connecter
257|Se déconnecter
258|identifiant ou e-mail
259|mot de passe
260|Connecté.
261|Le service ne l'a pas accepté.
262|Déconnecté.
263|Statut
264|Chapitres lus
265|Note
266|Dissocier
267|Supprimer aussi l'entrée sur {name} ? (Oui = supprimer là-bas aussi, Non = dissocier ici seulement)
268|Lier à cette entrée
269|Trouvés : {n}
270|{n} ch.
271|Vous n'êtes connecté à aucun service de suivi : utilisez le bouton « Suivi ».
272|Light novels
273|Ajouter des livres…
274|Ajouter un dossier…
275|Rechercher par titre ou auteur
276|Non terminés seulement
277|Livres
278|Votre étagère est vide
279|Ajoutez des livres EPUB, FB2 ou TXT : la progression de lecture, la taille de police et le thème sont mémorisés.
280|Livres : {n}
281|{n} chapitres
282|Aucun fichier EPUB / FB2 / TXT trouvé.
283|Ajoutés : {saved}, déjà présents : {duplicate}, échecs : {failed}.
284|Marquer comme lu
285|Marquer comme non lu
286|Supprimer « {title} » de l'étagère ? La copie de la bibliothèque est aussi supprimée.
287|Sommaire (T)
288|Texte plus petit (−)
289|Texte plus grand (+)
290|Thème : comme l'application
291|Thème : sombre
292|Thème : clair
293|Thème : sépia
294|{n} / {total} · {pct} %
295|Fichiers locaux
296|Reculer de 10 s (←)
297|Avancer de 10 s (→)
298|Ouvrir dans un lecteur externe
299|Cette source n'a pas de flux pour l'épisode.
300|flux
301|Épisode {n}
302|Ce flux exige des en-têtes de requête particuliers : utilisez le bouton du lecteur externe (définissez anime.external_player dans config.json, par ex. mpv).
303|Lecture impossible : {msg}
304|Rechercher dans la source (vide = tout / populaires)
305|Ouvrir le dossier des animes
306|Quel titre AniList est-ce ?
307|Celui-ci
308|Lier à AniList…
309|Changer le lien…
310|Dissocier
311|Ouvrir le site
312|№
313|Titre
314|État
315|Regarder
316|Marquer comme vu
317|Marquer comme non vu
318|Choisissez un titre
319|Double-cliquez sur un titre pour voir ses épisodes. Fichiers locaux : mettez un dossier par série (avec les épisodes dedans) dans le dossier des animes. Plus de sites et de langues : bouton Extensions.
320|Aucune série pour l'instant : cliquez sur « Ouvrir le dossier des animes » et mettez-y un dossier par série.
321|Épisodes : {n}
322|Aucun épisode trouvé.
323|Lié à AniList : {title}. Les épisodes vus mettent à jour votre liste.
324|Non lié à AniList : les épisodes vus ne mettront pas à jour votre liste.
325|vu
326|reprendre à {t}
327|Lié.
328|Mise à jour disponible
329|AniHUB {new} est disponible (vous avez {old}).
330|Télécharger et installer
331|Réinstaller cette version
332|Installer cette version plus ancienne
333|Plus tard
334|Ignorer cette version
335|Ouvrir sur GitHub
336|installée
337|préversion
338|Pas de description.
339|Cette version n'a pas d'installateur.
340|Téléchargement de l'installateur…
341|Lancement de l'installateur ; AniHUB va se fermer.
342|Annulé.
343|Toutes les versions…
344|Versions : {n}
345|Mise à jour {v} disponible
346|À propos et mises à jour
347|AniHUB version {v}
348|Rechercher les mises à jour automatiquement (une fois par jour)
349|Rechercher les mises à jour
350|Vous avez la dernière version.
351|Ouvrir le dossier des journaux
352|Téléchargements
353|En file de téléchargement : {n} (voir Téléchargements dans la barre d'état).
354|Publication
355|Statut
356|Détails
357|en file
358|en cours
359|enregistré
360|déjà dans la bibliothèque
361|échec
362|annulé
363|Pause
364|Reprendre
365|Annuler la sélection
366|Tout annuler
367|Réessayer les échecs
368|Effacer les terminés
369|En même temps :
370|Limite de débit :
371|illimité
372|Mo/s
373|Actifs : {active} (en cours {running}) · enregistrés {done} · doublons {dup} · échecs {failed}
374|Téléchargements : {n}
375|Téléchargements
376|images similaires déjà présentes : {n}
377|enregistrés {n}
378|doublons {n}
379|échecs {n}
380|annulés {n}
381|rien
382|Téléchargements terminés : {details}.
383|Téléchargés {n} : {details}.
384|Sauvegardes
385|Sauvegarder automatiquement la base de la bibliothèque
386|Inclure les réglages (config.json) dans les sauvegardes
387|Tous les (jours)
388|Conserver les dernières
389|Sauvegarder maintenant
390|Restaurer depuis une sauvegarde…
391|Annuler la restauration
392|Ouvrir le dossier des sauvegardes
393|Une restauration est programmée : elle sera appliquée au prochain démarrage d'AniHUB.
394|Dernière sauvegarde : {when} (sauvegardes : {n})
395|Aucune sauvegarde pour l'instant.
396|Créée : {name}
397|La sauvegarde est saine ({n} éléments). Redémarrez AniHUB pour l'appliquer ; la base actuelle est conservée à côté en copie.
398|La base de la bibliothèque a été restaurée depuis une sauvegarde.
399|Limite du cache (aperçus, vidéos)
400|Vérification d'intégrité de la bibliothèque
401|Cherche les enregistrements dont le fichier a disparu, les fichiers du dossier arts que la bibliothèque ne connaît pas et (en option) les fichiers modifiés depuis leur enregistrement. Rien n'est supprimé sans demander.
402|Vérifier aussi le contenu des fichiers (lent)
403|Vérifier
404|Supprimer les enregistrements sans fichier
405|Optimiser la base de données
406|Ouvrir le dossier arts
407|Problème
408|Fichier
409|fichier manquant
410|contenu modifié
411|absent de la bibliothèque
412|Base de données : OK
413|Problème de base de données : {msg}
414|vérifiés : {n}
415|aucun problème trouvé
416|manquants : {missing}, modifiés : {damaged}, fichiers inconnus : {orphans}
417|Supprimer {n} enregistrements dont les fichiers ont disparu ? Leurs tags et liens de collection sont aussi supprimés.
418|Enregistrements supprimés : {n}.
419|La base de données a été optimisée.
420|Signaler un problème…
421|Signaler un problème
422|Une erreur est survenue : signalez-la
423|Ce texte est ce qui serait partagé : version, système, dernière erreur et journal récent. Les clés, jetons, mots de passe et votre nom d'utilisateur sont retirés automatiquement ; relisez-le avant de publier. AniHUB n'envoie rien lui-même.
424|Qu'avez-vous fait, qu'attendiez-vous, que s'est-il passé ?
425|Inclure le journal récent
426|Le rapport :
427|Copier
428|Copier et ouvrir GitHub Issues
429|Copié dans le presse-papiers.
430|La page de l'issue est ouverte ; le rapport est dans le presse-papiers.
431|Rapport de problème
432|Aller à une section, lancer une action, trouver un tag, un livre ou une série…
433|↑ ↓ choisir · Entrée lancer · Échap fermer
434|section
435|action
436|bibliothèque
437|livre
438|liste d'animes
439|Rechercher les mises à jour
440|Sauvegarder la bibliothèque maintenant
441|Ouvrir les téléchargements
442|Basculer le mode hors ligne
443|Basculer le thème sombre / clair
444|Rechercher dans la bibliothèque : {q}
445|Abonnements
446|S'abonner
447|Suivre
448|Nom de l'abonnement
449|Saisissez d'abord une recherche : l'abonnement la suit.
450|Suivi de « {name} » : les nouvelles publications seront comptées.
451|Aucun abonnement
452|Dans Sites, saisissez une recherche (un tag ou un artiste) et cliquez sur « Suivre » : les nouvelles publications apparaissent ici.
453|Vérifier maintenant
454|Tout vérifier
455|Enregistrer les nouveautés
456|Marquer comme vu
457|Supprimer
458|Supprimer l'abonnement « {name} » ?
459|Activé
460|Enregistrer automatiquement les nouvelles publications
461|jamais
462|{source} : {query}  ·  dernière vérification : {when}
463|Nouvelles publications : {n}
464|Marqué comme vu.
465|Mode hors ligne : pas de vérification.
466|Cette source n'est plus disponible.
467|Nouvelles publications : {fresh}, enregistrées automatiquement : {saved}
468|Statistiques
469|éléments dans la bibliothèque
470|sur le disque
471|favoris
472|notés par vous
473|tags
474|collections
475|livres lus / sur l'étagère
476|épisodes vus
477|abonnements
478|dans la corbeille
479|Ajouts par mois
480|Par source
481|Par classification du contenu
482|Tags les plus utilisés
483|Artistes les plus enregistrés
484|Exporter / partager
485|Pack AniHUB (.zip, avec tags)…
486|Galerie HTML (.zip)…
487|Exporter la collection…
488|Importer un pack…
489|Pack AniHUB
490|{n} exportés vers {path}
491|Pack « {name} » : ajoutés {saved}, déjà présents {dup}, échecs {failed}.
492|Musique
493|Rechercher des pistes ou des albums
494|Ouvrir le dossier de musique
495|Réanalyser
496|№
497|Piste
498|Pas encore de musique
499|Mettez un dossier par titre (un album d'OST) dans le dossier de musique : <bibliothèque>/music/<Titre>/pistes (mp3, flac, ogg…).
500|Rien n'est en lecture
501|Fichiers isolés
502|{n} pistes
503|dans votre liste : {title}
504|Aléatoire
505|Répéter
506|Mode d'âge et filtre de tags
507|Mode d'âge
508|12+ — contenu sûr uniquement
509|16+ — poitrine autorisée, le reste du contenu 18+ est masqué
510|18+ — aucune restriction intégrée
511|Masqués par le mode (non modifiable)
512|Le mode 18+ ne masque rien par lui-même.
513|Mes tags masqués
514|Séparés par des espaces ou des virgules. Un * à la fin masque tous les tags qui commencent ainsi : guro*
515|Passer en 18+ ? Le contenu pour adultes sera affiché sans restriction intégrée. Vous devez avoir 18 ans ou plus.
516|Mode d'âge
517|Choisissez un mode. Ses tags restreints changent avec le mode ; vous pourrez ajouter vos propres tags masqués plus tard dans les Réglages.
518|12+ — masque tout ce qui touche au contenu 16+ et 18+
519|16+ — poitrine autorisée, le reste du contenu 18+ est filtré
520|18+ — aucune restriction intégrée
521|Sans connexion, Pixiv n'affiche que les œuvres tout public. Pour le R-18 : connectez-vous à pixiv.net dans votre navigateur, appuyez sur F12 → Application → Cookies → pixiv.net, copiez la valeur de PHPSESSID et collez-la ici (mode 18+ requis). Le cookie reste sur cet ordinateur et n'est envoyé qu'à pixiv.net.
522|mots de recherche · user:nom · board:nom/tableau · un lien de profil ou de tableau
523|Fenêtre translucide (Mica)
524|Le matériau de Windows 11 : la fenêtre laisse transparaître le fond d'écran et les couleurs du bureau. Nécessite Windows 11 22H2 ou plus récent.
525|Extensions
526|Extensions : sources des dépôts
527|Dépôts
528|Ajouter un dépôt
529|Retirer
530|Adresse de l'index.json du dépôt :
531|Un dépôt est un index.json qui liste des extensions (comme dans Aniyomi). N'ajoutez que ceux en qui vous avez confiance.
532|Nom
533|Langue
534|Version
535|État
536|Installer
537|Mettre à jour
538|Retirer
539|Réglages
540|Actualiser le catalogue
541|installée
542|Extensions disponibles : {n}
543|Terminé : {name}
544|Installer « {name} » ?\n\nUne extension est un programme Python qui s'exécute avec vos droits. Dépôt : {repo}
545|Les extensions sont du code tiers. N'installez que depuis des dépôts de confiance. Le fichier est vérifié avec la somme de contrôle du dépôt.
546|Langues
547|Toutes les langues
548|Étagère
549|En ligne
"""
