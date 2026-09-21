"""French, keys 550-1098."""
DATA = r"""
550|Rechercher des light novels par titre
551|Lire
552|Sur l'étagère
553|Le marquage d'âge du site dépasse votre mode d'âge.
554|Masqué par votre filtre de tags.
555|Aucun chapitre.
556|Ajouté à l'étagère.
557|Aucune source pour les langues choisies.
558|masqués par le mode d'âge : {n}
559|Télécharger pour lire hors ligne (EPUB)
560|Téléchargement des chapitres : {done} sur {total}
561|Le livre est téléchargé et se trouve sur l'étagère.
562|Passer
563|Retour
564|Suivant
565|Terminé
566|Étape {n} sur {total}
567|Afficher le tutoriel
568|Bienvenue dans AniHUB !
569|Une courte visite : je vais éclairer les boutons principaux et expliquer leur rôle. Continuez avec « Suivant » ou la touche →, quittez quand vous voulez (Échap).
570|Illustrations
571|La section des images : recherche sur les sites, votre bibliothèque et les abonnements. La barre de gauche change de section.
572|Onglets de la section
573|<b>Sites</b> — recherche sur Internet, <b>Bibliothèque</b> — ce que vous avez enregistré sur le disque, <b>Abonnements</b> — suivez les nouveautés par tag ou artiste.
574|Choisir un site
575|Danbooru, Gelbooru, Pixiv, Pinterest et d'autres. Certains sites ont leurs propres réglages et clés : Réglages, bloc « Identifiants ».
576|Recherche par tags
577|Saisissez des tags séparés par des espaces ; <b>-tag</b> exclut. Dans la visionneuse, chaque tag a un bouton « + » (ajouter à la recherche) et « − » (exclure).
578|Enregistrement
579|Sélectionnez des images dans le flux et cliquez sur « Enregistrer » : le fichier, les tags et l'auteur sont conservés, les doublons ignorés.
580|S'abonner
581|Suivez la recherche actuelle : les nouveautés sont comptées dans l'onglet Abonnements et peuvent être enregistrées automatiquement.
582|Manga
583|Catalogues, bibliothèque et lecteur de manga (via Suwayomi). Filtres par genre, connexion aux sources, suivi des chapitres.
584|Génération
585|Une interface pour Stable Diffusion Forge : génération, file, historique, CivitAI. Le chemin de Forge se règle dans les Réglages.
586|Anime
587|Le calendrier de saison et votre liste (AniList), visionnage d'épisodes et musique.
588|Regarder des animes
589|L'onglet Regarder affiche des animes de sites web et de votre disque. Le bouton « Extensions » ajoute des sources en plusieurs langues depuis des dépôts, comme Aniyomi.
590|Light novels
591|Un lecteur de livres EPUB, FB2 et TXT de votre ordinateur — et en ligne.
592|Étagère et En ligne
593|L'étagère contient vos livres, l'onglet En ligne cherche sur des sites web (RanobeLib, par exemple). Tout livre en ligne peut être téléchargé pour être lu hors ligne.
594|Mode d'âge
595|12+, 16+ ou 18+ : le mode décide quel contenu est visible partout. Ses tags ne sont pas modifiables ; vos propres tags masqués vont dans le champ du dessous.
596|En ligne / hors ligne
597|Le bouton du bas coupe toutes les requêtes Internet — pratique en déplacement. La barre d'état affiche aussi les téléchargements, les mises à jour et l'état des services.
598|C'est tout !
599|Astuce : <b>Ctrl+K</b> ouvre la palette de commandes — un accès rapide à n'importe quelle section ou action. Rejouez la visite dans les Réglages (« Afficher le tutoriel »).
600|Quitter complètement AniHUB ou le garder dans la zone de notification ?
601|Dans la zone de notification, l'application poursuit les téléchargements, les abonnements et la recherche de nouveaux chapitres de manga.
602|Réduire dans la zone de notification
603|Quitter complètement
604|Annuler
605|Mémoriser mon choix
606|À la fermeture de la fenêtre
607|Demander
608|Réduire dans la zone de notification
609|Quitter complètement
610|Bibliothèque
611|Radio
612|Recherche et téléchargement
613|Ajouter une station
614|Retirer
615|Nom
616|Adresse du flux ou de la playlist
617|à moi
618|Choisissez une station (double-clic)
619|Arrêté
620|Anison.FM est une radio d'anime. Vos propres stations : l'adresse d'un flux (mp3/aac) ou une playlist .pls / .m3u.
621|Erreur : {msg}
622|aucune adresse de flux dans la playlist
623|le flux ne s'ouvre pas
624|Anime : trouver des openings et endings (vide : nouveautés)
625|Anime
626|Morceau
627|Artiste
628|Écouter
629|Arrêter
630|Télécharger dans la bibliothèque
631|Plus
632|Morceaux trouvés : {n}
633|Lecture : {title}
634|Téléchargement : {n}…
635|Morceaux téléchargés : {n}
636|Personnalisé
637|Arrière-plan
638|Panneaux
639|Texte
640|Accent
641|Réinitialiser
642|Défilement fluide à la molette
643|Génération d'images (Stable Diffusion)
644|La section Génération fonctionne avec Stable Diffusion Forge et nécessite une carte graphique NVIDIA. Vérification de votre ordinateur :
645|Votre ordinateur convient. Que faire pour Forge ?
646|Votre ordinateur convient, avec des limites :
647|Votre ordinateur ne convient pas à Stable Diffusion Forge : la section Génération et toutes les fonctions qui en dépendent seront donc masquées. Vous pourrez vérifier à nouveau plus tard dans les Réglages.
648|Télécharger Forge (environ 1,8 Go) dans le dossier :
649|Forge est déjà téléchargé — choisissez son dossier :
650|Décider plus tard (la section reste, indiquez le chemin dans les Réglages)
651|Il n'y a pas de Forge dans ce dossier (webui\webui.bat introuvable). Choisissez le dossier du paquet Forge ou son sous-dossier webui.
652|Les cartes RTX 50 demandent un PyTorch récent : le paquet téléchargeable peut ne pas les prendre en charge. Avec une RTX 50, mieux vaut indiquer un Forge déjà configuré.
653|Carte graphique : {d} ({gb} Go de mémoire vidéo)
654|Mémoire : {gb} Go
655|Espace disque libre : {gb} Go
656|Aucune carte graphique NVIDIA trouvée (CUDA requis)
657|Moins de 4 Go de mémoire vidéo
658|4–6 Go de mémoire vidéo : modèles légers et petites tailles seulement
659|Moins de 8 Go de mémoire
660|Moins de 16 Go de mémoire : attendez-vous à des ralentissements
661|Moins de 15 Go libres : choisissez un autre disque pour Forge
662|Génération d'images
663|Revérifier l'ordinateur
664|Télécharger Forge…
665|La section Génération est activée.
666|La section Génération est désactivée : cet ordinateur ne convient pas à Stable Diffusion Forge.
667|Redémarrez AniHUB pour que le changement prenne effet.
668|Installation de Stable Diffusion Forge
669|Téléchargement de Forge (environ 1,8 Go) et décompression dans :\n{dest}
670|Recherche de la dernière version…
671|Téléchargé {done} sur {total} Mo
672|Décompression (quelques minutes)…
673|Terminé. Forge est installé : {path}
674|Échec : {msg}
675|Fermer
676|Impossible d'afficher {name}. Ouvrez la page dans un navigateur : {url}
677|Artiste
678|Copyright
679|Personnages
680|Tags
681|Méta
682|Rechercher ce tag
683|Ajouter à la recherche
684|Exclure de la recherche
685|Copier
686|Langue
687|Thème
688|Suivre le système
689|Clair
690|Sombre
691|Dossier de la bibliothèque
692|Classifications de contenu affichées
693|Proxy (http://hôte:port ou socks5://hôte:port)
694|Intervalle min. entre requêtes API (ms)
695|Téléchargements parallèles max.
696|Identifiants des sites
697|Enregistrer
698|Réglages enregistrés. Le changement de langue s'applique après le redémarrage.
699|Ouvrir le dossier
700|Tout public
701|Sensible
702|Douteux
703|Explicite
704|Assistant AniHUB
705|Bienvenue
706|Choisissez la langue de l'interface et le thème.
707|Dossier de la bibliothèque
708|Où AniHUB doit-il ranger votre bibliothèque ? Choisissez un dossier sur un disque avec assez d'espace libre.
709|Espace libre : {gb:.1f} Go
710|Le dossier n'est pas accessible en écriture.
711|Vérification du système
712|Exigences des modules optionnels (vous pouvez continuer dans tous les cas).
713|Terminé
714|Tout est prêt. Cliquez sur Terminer pour lancer AniHUB.
715|Parcourir...
716|Java trouvé : {d}
717|Java introuvable. Il est nécessaire pour lire des mangas (Suwayomi). Installez Java 17+ ; l'installation automatique viendra plus tard.
718|GPU : {d}
719|Aucun GPU NVIDIA détecté. Stable Diffusion en a besoin.
720|GPU : {d}. Moins de 6 Go de VRAM : la génération peut être limitée.
721|Espace disque libre : {gb:.1f} Go
722|Seulement {gb:.1f} Go libres. Une bibliothèque en demande bien plus.
723|Afficher AniHUB
724|Quitter
725|AniHUB continue de fonctionner dans la zone de notification.
726|Générer
727|Générations enregistrées
728|Démarrer Forge
729|Arrêter Forge
730|Dossier de Forge...
731|Journal de Forge
732|Prompt
733|Prompt négatif
734|Checkpoint
735|Sampler
736|Scheduler
737|Étapes
738|Taille
739|Seed (-1 = aléatoire)
740|Nombre de lots
741|Taille du lot
742|Préparation (chargement du modèle)...
743|Générer
744|Arrêter
745|Arrêt...
746|Effacer les résultats
747|Classification
748|Terminé : {n} image(s). Les fichiers sont dans le dossier sd de la bibliothèque.
749|Démarrez Forge pour générer (le bouton ci-dessus).
750|arrêté
751|démarrage...
752|en cours
753|en cours (externe)
754|planté
755|Forge a été lancé en dehors d'AniHUB, AniHUB ne l'arrêtera donc pas.
756|Forge s'est arrêté de façon inattendue. Ouvrez le journal.
757|Dossier de Forge (avec webui.bat)
758|Port de l'API
759|API seule, sans interface web (--nowebui)
760|Arguments de lancement supplémentaires
761|Arrêter Forge après inactivité, minutes (0 = jamais)
762|En lecture
763|Terminé
764|En pause
765|Abandonné
766|À lire
767|Bibliothèque
768|Parcourir
769|Extensions
770|Mises à jour
771|Démarrer le service manga
772|Arrêter
773|Démarrer avec AniHUB (pour les alertes de nouveaux chapitres)
774|Démarrez le service manga (bouton ci-dessus) pour utiliser cette section.
775|La lecture de manga utilise le moteur Suwayomi, qui exécute les extensions Tachiyomi. AniHUB le téléchargera (environ 340 Mo, avec son propre Java, rien d'autre à installer).
776|Télécharger et installer Suwayomi
777|Annuler
778|Recherche de la dernière version...
779|Téléchargement : {done:.0f} / {total:.0f} Mo
780|Vérification...
781|Décompression...
782|Terminé
783|Filtrer la bibliothèque par titre
784|Rechercher de nouveaux chapitres
785|Interrogation des sources sur les nouveaux chapitres...
786|Tous
787|Titres dans la bibliothèque : {n}
788|Populaires
789|Récents
790|Rechercher des titres dans cette source
791|Aucune source pour l'instant : installez une extension dans l'onglet Extensions.
792|Actualiser depuis la source
793|Commencer la lecture
794|Continuer la lecture
795|Chapitre
796|Groupe
797|Date
798|Titre
799|Marquer comme lu
800|Marquer comme non lu
801|Télécharger pour lire hors ligne
802|Supprimer le téléchargement
803|★ Dans la bibliothèque
804|☆ Ajouter à la bibliothèque
805|(sans catégorie)
806|Chapitres : {n}, non lus : {unread}
807|En file de téléchargement...
808|Téléchargement : {n} en file, actuel {p} %
809|Chapitres : {n}
810|Nouveaux chapitres : {n} ({titles})
811|Rechercher des extensions
812|Installées seulement
813|Installer depuis un fichier...
814|Nom
815|Langue
816|Version
817|État
818|Désinstaller
819|Dépôts :
820|URL de l'index du dépôt d'extensions
821|Ajouter
822|Retirer
823|Toutes les langues
824|Traitement du catalogue...
825|Traitement : {name}...
826|installée
827|mise à jour disponible
828|(obsolète)
829|Affichées : {n} sur {total}. Les extensions 18+ apparaissent quand la classification Explicite est activée dans les Réglages.
830|Windows verrouille ce fichier d'extension tant que le service tourne. Arrêtez le service manga, relancez-le puis réessayez.
831|Astuce : préférez la version .jar d'une extension ; certains .apk sont refusés par le moteur.
832|Page simple
833|Double page
834|Webtoon
835|De droite à gauche
836|Ce chapitre n'a pas de pages
837|Port du service manga
838|Rechercher de nouveaux chapitres toutes les (minutes)
839|Date d'ajout
840|Taille du fichier
841|Classification du contenu
842|Nom
843|Mes étoiles
844|Note du site
845|Auteur
846|Croissant / décroissant
847|Tous
848|Favoris
849|Catégories
850|Collections
851|Tags intelligents
852|Corbeille
853|par défaut
854|Nouvelle catégorie...
855|Nouvelle collection...
856|Renommer...
857|Supprimer
858|Définir par défaut (les nouveaux éléments vont ici)
859|Retirer le défaut
860|Monter
861|Descendre
862|Nom :
863|Ce nom est déjà utilisé.
864|Supprimer cette catégorie ? Les éléments restent dans la bibliothèque.
865|Supprimer cette collection ? Les éléments restent dans la bibliothèque.
866|Vider la corbeille
867|Toutes notes
868|Importer...
869|Outils
870|Actions
871|Affichés : {shown} sur {total}
872|Sélectionnés : {n}
873|les éléments sont supprimés définitivement après {days} jours
874|Sélectionnez d'abord des éléments
875|Restaurer
876|Supprimer définitivement
877|Supprimer définitivement {n} élément(s) ? Cette action est irréversible.
878|Modifier les tags...
879|Lancer l'étiqueteur automatique
880|Étiqueter automatiquement tous les éléments sans tags
881|Étiquetage automatique de {n} élément(s)...
882|Étiquetés automatiquement : {n}
883|Ajouter à la collection
884|Retirer de cette collection
885|Ajouter à la catégorie
886|Retirer de cette catégorie
887|Classification du contenu
888|Ma note
889|Sans note
890|♥ Ajouter aux favoris
891|Retirer des favoris
892|Envoyer vers img2img
893|Afficher dans le dossier
894|Mettre à la corbeille
895|Mettre {n} élément(s) à la corbeille ? Vous pourrez les restaurer depuis là.
896|Oui
897|Oui, toujours
898|Non
899|Tags ({n} élément(s))
900|Saisissez un tag à ajouter (des suggestions apparaissent)
901|Ajouter
902|Décochez un tag pour le retirer.
903|Coché : sur tous les éléments sélectionnés. Partiellement coché : sur certains. Cochez pour ajouter à tous, décochez pour retirer de tous.
904|Gestionnaire de tags
905|Hiérarchie
906|Tags intelligents
907|Filtrer les tags
908|Tag
909|Éléments
910|Tag parent
911|Définir le parent
912|Retirer le parent
913|Renommer / fusionner...
914|Nouveau nom (un tag existant sera fusionné) :
915|Supprimer le tag
916|Supprimer le tag {name} de toute la bibliothèque ?
917|Un tag parent trouve aussi tout ce qui porte ses enfants (chercher 'vocaloid' trouve 'hatsune_miku').
918|Tags dans la hiérarchie : {n}
919|Nom du tag intelligent
920|Ajouter un tag au groupe
921|Retirer la sélection
922|Nouveau
923|Enregistrer
924|Supprimer
925|Donnez un nom au tag intelligent et au moins un tag.
926|Un tag intelligent est un dossier de tags : chercher '@nom' trouve les éléments ayant N'IMPORTE LEQUEL d'entre eux (enfants inclus). Vous pouvez aussi cliquer dessus dans la barre latérale.
927|Importer des images locales
928|Ajouter un dossier...
929|Ajouter des fichiers...
930|Effacer
931|(catégorie par défaut)
932|Étiqueter avec l'étiqueteur automatique (définit aussi la classification)
933|L'étiqueteur automatique est désactivé ou son modèle n'est pas téléchargé : voir les Réglages.
934|Classification :
935|Catégorie :
936|Importer
937|Annuler
938|Les fichiers sont copiés dans la bibliothèque ; les doublons exacts sont ignorés, les images similaires signalées.
939|Importés : {saved}, doublons ignorés : {duplicate}, échecs : {failed}, éventuellement similaires : {similar}, annulés : {cancelled}
940|Trouver des images similaires
941|Fichier
942|Taille
943|Dimensions
944|Classification
945|Analyse...
946|Cocher toutes sauf la plus grande de chaque groupe
947|Mettre les cochées à la corbeille
948|Groupes d'images visuellement similaires (copies redimensionnées ou recompressées). Le plus gros fichier est listé en premier.
949|Groupe {n} ({k} images)
950|Groupes trouvés : {n}
951|Aucune image similaire trouvée.
952|Mises à la corbeille : {n}
953|doublons possibles : {n}
954|Enregistrer et avertir
955|Ignorer
956|Désactivé
957|Images visuellement similaires à l'enregistrement
958|Vider la corbeille après (jours, 0 = jamais)
959|Demander avant de mettre à la corbeille
960|Bibliothèque
961|Étiqueteur automatique (WD14)
962|Étiqueter automatiquement les images importées et les publications sans tags
963|Modèle
964|Télécharger le modèle
965|installé
966|non téléchargé (~{mb} Mo, tourne sur le processeur)
967|Confiance des tags
968|Confiance des personnages
969|Image source (img2img)
970|Choisir...
971|Retirer
972|Force du denoising
973|Générer (img2img)
974|Image chargée comme source img2img. Démarrez Forge s'il ne tourne pas, puis cliquez sur Générer.
975|File
976|Historique
977|Enregistrer le préréglage...
978|Supprimer
979|(préréglage)
980|Préréglage appliqué : {name}
981|Styles
982|Enregistrer le prompt comme style...
983|Supprimer le style
984|Charger depuis une image...
985|Cette image n'a pas de paramètres de génération.
986|Paramètres chargés depuis {name}
987|(auto)
988|garder ceux de Forge
989|Clip skip
990|Hires fix
991|comme les étapes
992|Agrandir de
993|Upscaler
994|Étapes hires
995|Denoising hires
996|Variation de seed
997|Seed de variation
998|Force de la variation
999|Ajouter à la file
1000|Combien de copies mettre en file (chacune avec une seed aléatoire)
1001|En file : {n}
1002|Écrivez d'abord un prompt.
1003|Agrandir
1004|Agrandissement de {n} image(s)...
1005|Agrandies : {n}. Les fichiers sont dans le dossier sd.
1006|Poids :
1007|Insérer dans le prompt
1008|Disponibles : {n}
1009|Statut
1010|Paramètres
1011|Backend
1012|Images
1013|Démarrer la file
1014|Pause après l'actuelle
1015|Annuler l'actuelle
1016|Dupliquer
1017|Retirer
1018|Effacer les terminées
1019|en attente
1020|en cours
1021|terminée
1022|échec
1023|annulée
1024|Aucun backend Forge en marche : démarrez-en un, puis cliquez de nouveau sur Démarrer la file.
1025|Planification
1026|Exécuter la file à
1027|tous les jours
1028|une fois
1029|Démarrer Forge automatiquement s'il ne tourne pas
1030|Arrêter le Forge démarré par AniHUB quand la file est terminée
1031|Seulement si le PC est resté inactif pendant (minutes, 0 = ignorer)
1032|Prochaine exécution : {when}
1033|La planification est désactivée.
1034|L'exécution planifiée a démarré.
1035|L'heure planifiée est venue, mais la file est vide.
1036|Backends
1037|GPU par défaut
1038|Rechercher des prompts et des seeds
1039|Charger les paramètres
1040|Enregistrer comme préréglage...
1041|Répéter (file)
1042|Retirer de l'historique
1043|Vider l'historique
1044|Vider tout l'historique ? Les fichiers image ne sont pas supprimés.
1045|Affichés : {shown} sur {total}
1046|Préréglage enregistré : {name}
1047|En file : {n}
1048|Collez un lien de modèle CivitAI
1049|Ouvrir
1050|Rechercher sur CivitAI
1051|Checkpoints
1052|LoRA
1053|Embeddings
1054|VAE
1055|Les plus téléchargés
1056|Les mieux notés
1057|Les plus récents
1058|Tout modèle de base
1059|Inclure 18+
1060|Activez la classification Explicite dans les Réglages pour chercher des modèles 18+.
1061|Plus de résultats
1062|Version
1063|Fichier
1064|Télécharger vers Forge
1065|Ouvrir sur CivitAI
1066|Trouvés : {n}
1067|Ce n'est pas un lien de modèle CivitAI.
1068|Mots déclencheurs : {words}
1069|Indiquez d'abord le dossier de Forge (Réglages).
1070|Téléchargement de {name} vers {folder}...
1071|Installé : {path}
1072|Téléchargement annulé.
1073|Génération
1074|Backends supplémentaires : le même Forge sur un autre port, attaché à un GPU (redémarrez AniHUB pour appliquer).
1075|Actif
1076|Nom
1077|Port
1078|GPU
1079|Ajouter un backend
1080|Retirer la sélection
1081|Clé API CivitAI
1082|facultatif : nécessaire pour certains fichiers
1083|Depuis une image
1084|Les résultats apparaîtront ici
1085|Écrivez un prompt, démarrez Forge et cliquez sur Générer. Chaque image est enregistrée sur le disque ; choisissez celles à garder.
1086|Le service manga est arrêté
1087|Rien ici pour l'instant
1088|Enregistrez des images depuis l'onglet Sites ou importez un dossier : elles apparaîtront ici.
1089|Trouvez quelque chose à regarder
1090|Choisissez une source, saisissez des tags et cliquez sur Rechercher. Utilisez -tag pour exclure.
1091|Apparence
1092|Stockage et contenu
1093|Réseau
1094|Retour
1095|Suivant
1096|Terminer
1097|Annuler
1098|La bibliothèque est indisponible
"""
