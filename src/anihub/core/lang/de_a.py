"""German, keys 0-549."""
DATA = r"""
0|Bilder
1|Manga
2|Generierung
3|Anime
4|Romane
5|Einstellungen
6|Seiten durchsuchen
7|Bibliothek
8|Dieser Bereich wird in einer späteren Phase umgesetzt.
9|Tags durch Leerzeichen getrennt, -Tag zum Ausschließen
10|Suchen
11|Quelle
12|In der Bibliothek speichern
13|Öffnen
14|Schließen
15|Wird geladen...
16|Keine weiteren Ergebnisse
17|Fehler: {msg}
18|Gespeichert: {saved}, Duplikate: {dup}, fehlgeschlagen: {failed}
19|Geladen: {n}
20|Elemente in der Bibliothek: {n}
21|Maus: Seitenpfeile oder Mausrad zum Blättern · Schaltflächen unten · Tasten: ←/→ Leertaste P F T L M S Esc
22|Zurück (←)
23|Weiter (→)
24|Diashow (P)
25|Favorit (L)
26|Bewertung
27|Keine Bewertung
28|In der Bibliothek speichern (S)
29|Tags (T)
30|Vollbild (F)
31|Schließen (Esc)
32|Wiedergabe / Pause
33|Ton (M)
34|Vorheriges Kapitel ([)
35|Nächstes Kapitel (])
36|Vorherige Seite
37|Nächste Seite
38|Links
39|Rechts
40|Vollbild (F)
41|Schließen (Esc)
42|Filter
43|Nach Genres, Tags, Status und mehr suchen
44|Bei der Quelle anmelden
45|Anmelden / Einstellungen dieser Quelle ändern
46|Nur ungelesene
47|Beliebiges Genre
48|Beliebiger Status
49|Unbekannt
50|Laufend
51|Abgeschlossen
52|Lizenziert
53|Veröffentlichung beendet
54|Abgebrochen
55|Pausiert
56|Genre oder Tag finden
57|Zurücksetzen
58|Filter anwenden
59|Diese Quelle hat keine Filter: Nutzen Sie die Titelsuche.
60|Aufsteigend
61|Klick: einschließen → ausschließen → aus
62|Einstellungen: {name}
63|Diese Quelle hat keine Einstellungen.
64|Gespeichert.
65|Quellen, die ein Konto brauchen, fragen hier nach Benutzername und Passwort. Änderungen werden sofort gespeichert und bei der nächsten Anfrage von der Quelle verwendet. Seiten mit Anmeldung über eine Webseite oder Cloudflare-Prüfung werden vom Backend nicht unterstützt.
66|Automatische Regeln
67|Neu
68|Löschen
69|Regeln laufen von oben nach unten
70|Name der Regel
71|Neue Regel
72|Wenn ein Element…
73|…dann Folgendes tun
74|Alle Tags hat
75|Irgendein Tag hat
76|Keines von diesen hat
77|Tag Tag ... (ein Eltern-Tag umfasst auch seine Kinder)
78|Tag Tag ...
79|Tag Tag ...
80|Autor
81|Künstlernamen
82|Quelle
84|Einstufung
85|Bereich
86|Bilder
87|Generierungen
88|Zur Sammlung hinzufügen
89|Zur Kategorie hinzufügen
90|Tags hinzufügen
91|Tag Tag ...
92|Inhaltseinstufung festlegen
93|Meine Bewertung festlegen
94|Als Favorit markieren
96|unverändert
97|Regel speichern
98|Auf die ganze Bibliothek anwenden
99|Regeln automatisch auf neue Elemente anwenden
100|Eine Regel braucht mindestens eine Bedingung und eine Aktion. Regeln laufen in der Reihenfolge der Liste bei jedem neuen Element (von einer Seite gespeichert, importiert, generiert) und nach dem automatischen Taggen.
101|Fügen Sie mindestens eine Bedingung und eine Aktion hinzu.
102|Regel gespeichert.
103|Füllen Sie Bedingungen und Aktionen aus und speichern Sie dann.
104|Die Regel „{name}“ löschen?
105|Alle aktivierten Regeln auf jedes Element der Bibliothek anwenden?
106|Fertig: {n} Treffer in {rules} Regeln.
107|Vergleichen
108|Die beiden vergleichen (vorher / nachher)...
109|Vorher
110|Nachher
111|Nebeneinander
112|Tauschen
113|Trennlinie ziehen oder ←/→ · Leertaste: nebeneinander · X: tauschen
114|Online
115|Offline
116|Offline-Modus: Nichts geht ins Internet
117|Offline-Modus: Seiten, Manga-Katalog, CivitAI und Downloads sind abgeschaltet. Ihre Bibliothek, gespeicherte Kapitel und lokale Generierung funktionieren weiter. Forge übernimmt die Einstellung beim nächsten Start.
118|Inpaint-Maske
119|Maske (Inpaint)…
120|Maske bearbeiten…
121|Maske entfernen
122|Pinsel
123|Radierer (E)
124|Rückgängig
125|Leeren
126|Umkehren
127|Maske verwenden
128|Malen Sie über das, was neu gezeichnet werden soll. Linke Taste malt, rechte macht das Gegenteil, das Mausrad ändert die Pinselgröße, Strg+Z macht rückgängig.
129|Maskenunschärfe
130|Maskierter Inhalt
131|Original
132|Füllen
133|Latentes Rauschen
134|Latent leer
135|Nur der maskierte Bereich (volle Auflösung)
136|Maske gesetzt: Nur der bemalte Bereich wird neu gezeichnet.
137|X/Y-Raster…
138|Vergleichen, wie ein oder zwei Parameter das Bild verändern
139|X/Y-Raster
140|X-Achse
141|Y-Achse
142|— (eine Zeile)
143|Auswählen…
144|Werte: 20, 30, 40 oder ein Bereich Start:Ende:Schritt (20:40:10)
145|erster Wert = Text, der im Prompt gesucht wird, die übrigen ersetzen ihn: cat, dog, fox
146|Schritte
147|CFG
148|Sampler
149|Scheduler
150|Seed
151|Denoising (img2img)
152|Clip skip
153|Checkpoint
154|Prompt suchen/ersetzen
155|{x} × {y} = {n} Bilder
156|{n} Bilder sind zu viele (Grenze {max})
157|Raster erzeugen
158|Forge ist mit etwas anderem beschäftigt.
159|Wird generiert…
160|Die Tabelle erscheint hier.
161|Es wurde nichts generiert.
162|Fertig: {n} Bilder.
163|Angehalten: {n} von {total} Bildern.
164|Speichern unter…
165|In die Bibliothek
166|In der Bibliothek gespeichert.
167|Bereits in der Bibliothek.
168|Warten Sie, bis der Lauf endet, oder klicken Sie auf Stopp.
169|Jedes Bild verwendet das aktuelle Formular „Generieren“ und denselben Seed; nur die gewählten Parameter ändern sich. Die Zellen werden auch im Generierungsverlauf gespeichert.
170|Saison
171|Meine Liste
172|Ansehen
173|Sehe ich
174|Geplant
175|Abgeschlossen
176|Pausiert
177|Abgebrochen
178|Sehe ich erneut
179|Winter
180|Frühling
181|Sommer
182|Herbst
183|TV
184|TV-Kurzserie
185|Film
186|Special
187|OVA
188|ONA
189|Musik
190|Läuft
191|Beendet
192|Noch nicht gestartet
193|Abgebrochen
194|Pausiert
195|T
196|Std
197|Min
198|Folge {ep} läuft gerade
199|Folge {ep} in {span}
200|{n} Folgen
201|Keine Beschreibung.
202|Diese Saison
203|Beliebigen Anime nach Titel suchen
204|Suchergebnisse
205|Öffnen
206|Zur Liste hinzufügen
207|„{title}“: {status}
208|Status
209|Gesehene Folgen
210|Bewertung
211|Speichern
212|Zur Liste hinzufügen
213|Aus der Liste entfernen
214|Gespeichert.
215|Entfernt.
216|{n} Element(e) aus Ihrer Liste entfernen?
217|Noch eine Folge gesehen
218|Status setzen
219|Keine Bewertung
220|Alle
221|Titel in der Liste: {n}
222|Mit AniList synchronisieren
223|Melden Sie sich zuerst bei AniList an (Schaltfläche Konto).
224|Synchronisiere…
225|Synchronisiert: gesendet {sent}, empfangen {got}.
226|Titel
227|Folgen
228|Bewertung
229|Status
230|Nächste Folge
231|AniList-Konto
232|AniList: nicht angemeldet
233|Angemeldet als {name}.
234|AniList-Entwicklereinstellungen öffnen
235|Weiterleitungs-URL kopieren
236|numerische Client-ID Ihres API-Clients
237|Autorisierungsseite öffnen
238|Zugriffstoken
239|Token einfügen, das nach der Freigabe angezeigt wird
240|Anmelden
241|Abmelden
242|Geben Sie zuerst die numerische Client-ID ein (Schritt 2).
243|Die Liste funktioniert ohne Konto. So spiegeln Sie sie zu AniList:\n1. Öffnen Sie die Entwicklereinstellungen und erstellen Sie einen Client; als Weiterleitungs-URL verwenden Sie {redirect}\n2. Fügen Sie unten die numerische ID des Clients ein und öffnen Sie die Autorisierungsseite.\n3. Geben Sie den Zugriff frei, kopieren Sie das auf der Seite angezeigte Token und fügen Sie es hier ein.\nDas Token wird nur auf diesem Computer gespeichert.
244|Folgen ansehen kommt bald
245|Quellen zum Ansehen von Folgen erscheinen hier. Der Saisonkalender und Ihre Liste funktionieren bereits.
246|Tracker
247|Tracking…
248|Tracking: {title}
249|MyAnimeList, AniList, Shikimori, Kitsu und mehr: Sobald ein Titel verknüpft ist, werden gelesene Kapitel an den Tracker gesendet.
250|{name}: angemeldet.
251|{name}: nicht angemeldet.
252|Das Token ist abgelaufen: Bitte erneut anmelden.
253|Anmeldeseite öffnen
254|Adresse einfügen, auf der der Browser landet
255|1. Öffnen Sie die Anmeldeseite und geben Sie den Zugriff frei.\n2. Der Browser zeigt danach womöglich einen Fehler oder fragt, ob eine App geöffnet werden soll: Das ist in Ordnung. Kopieren Sie die vollständige Adresse dieser Seite (oder das angezeigte Token/den Code) und fügen Sie sie unten ein.
256|Anmelden
257|Abmelden
258|Benutzername oder E-Mail
259|Passwort
260|Angemeldet.
261|Der Tracker hat es nicht akzeptiert.
262|Abgemeldet.
263|Status
264|Gelesene Kapitel
265|Bewertung
266|Verknüpfung lösen
267|Auch den Eintrag auf {name} löschen? (Ja = dort ebenfalls löschen, Nein = nur hier lösen)
268|Mit diesem Eintrag verknüpfen
269|Gefunden: {n}
270|{n} Kap.
271|Sie sind bei keinem Tracker angemeldet: Nutzen Sie die Schaltfläche „Tracker“.
272|Light Novels
273|Bücher hinzufügen…
274|Ordner hinzufügen…
275|Nach Titel oder Autor suchen
276|Nur unfertige
277|Bücher
278|Ihr Regal ist leer
279|Fügen Sie EPUB-, FB2- oder TXT-Bücher hinzu: Lesefortschritt, Schriftgröße und Design werden gemerkt.
280|Bücher: {n}
281|{n} Kapitel
282|Keine EPUB- / FB2- / TXT-Dateien gefunden.
283|Hinzugefügt: {saved}, schon vorhanden: {duplicate}, fehlgeschlagen: {failed}.
284|Als gelesen markieren
285|Als ungelesen markieren
286|„{title}“ aus dem Regal löschen? Die Kopie in der Bibliothek wird ebenfalls entfernt.
287|Inhalt (T)
288|Kleinerer Text (−)
289|Größerer Text (+)
290|Design: wie die App
291|Design: dunkel
292|Design: hell
293|Design: Sepia
294|{n} / {total} · {pct} %
295|Lokale Dateien
296|10 s zurück (←)
297|10 s vor (→)
298|In einem externen Player öffnen
299|Diese Quelle hat keinen Stream für die Folge.
300|Stream
301|Folge {n}
302|Dieser Stream braucht besondere Anfrage-Header: Nutzen Sie die Schaltfläche für den externen Player (anime.external_player in config.json setzen, z. B. mpv).
303|Wiedergabe nicht möglich: {msg}
304|In der Quelle suchen (leer = alles / beliebt)
305|Anime-Ordner öffnen
306|Welcher AniList-Titel ist das?
307|Dieser
308|Mit AniList verknüpfen…
309|Verknüpfung ändern…
310|Verknüpfung lösen
311|Seite öffnen
312|№
313|Titel
314|Zustand
315|Ansehen
316|Als gesehen markieren
317|Als ungesehen markieren
318|Titel auswählen
319|Doppelklicken Sie auf einen Titel, um seine Folgen zu sehen. Lokale Dateien: Legen Sie einen Ordner pro Serie (mit den Folgen darin) in den Anime-Ordner. Mehr Seiten und Sprachen: Schaltfläche Erweiterungen.
320|Noch keine Serien: Klicken Sie auf „Anime-Ordner öffnen“ und legen Sie dort einen Ordner pro Serie an.
321|Folgen: {n}
322|Keine Folgen gefunden.
323|Mit AniList verknüpft: {title}. Gesehene Folgen aktualisieren Ihre Liste.
324|Nicht mit AniList verknüpft: Gesehene Folgen aktualisieren Ihre Liste nicht.
325|gesehen
326|ab {t} fortsetzen
327|Verknüpft.
328|Update verfügbar
329|AniHUB {new} ist verfügbar (Sie haben {old}).
330|Herunterladen und installieren
331|Diese Version neu installieren
332|Diese ältere Version installieren
333|Später
334|Diese Version überspringen
335|Auf GitHub öffnen
336|installiert
337|Vorabversion
338|Keine Beschreibung.
339|Dieses Release hat kein Installationsprogramm.
340|Installationsprogramm wird heruntergeladen…
341|Installationsprogramm wird gestartet; AniHUB wird geschlossen.
342|Abgebrochen.
343|Alle Versionen…
344|Releases: {n}
345|Update {v} verfügbar
346|Info und Updates
347|AniHUB Version {v}
348|Automatisch nach Updates suchen (einmal täglich)
349|Nach Updates suchen
350|Sie haben die neueste Version.
351|Protokollordner öffnen
352|Downloads
353|Zum Download eingereiht: {n} (siehe Downloads in der Statusleiste).
354|Beitrag
355|Status
356|Details
357|in Warteschlange
358|lädt
359|gespeichert
360|bereits in der Bibliothek
361|fehlgeschlagen
362|abgebrochen
363|Pause
364|Fortsetzen
365|Ausgewählte abbrechen
366|Alle abbrechen
367|Fehlgeschlagene wiederholen
368|Fertige entfernen
369|Gleichzeitig:
370|Geschwindigkeitsgrenze:
371|unbegrenzt
372|MB/s
373|Aktiv: {active} (lädt {running}) · gespeichert {done} · Duplikate {dup} · fehlgeschlagen {failed}
374|Downloads: {n}
375|Downloads
376|ähnliche Bilder bereits vorhanden: {n}
377|gespeichert {n}
378|Duplikate {n}
379|fehlgeschlagen {n}
380|abgebrochen {n}
381|nichts
382|Downloads abgeschlossen: {details}.
383|{n} heruntergeladen: {details}.
384|Sicherungen
385|Bibliotheksdatenbank automatisch sichern
386|Einstellungen (config.json) in Sicherungen einschließen
387|Alle (Tage)
388|Die letzten behalten
389|Jetzt sichern
390|Aus einer Sicherung wiederherstellen…
391|Wiederherstellung abbrechen
392|Sicherungsordner öffnen
393|Eine Wiederherstellung ist geplant: Sie wird beim nächsten Start von AniHUB angewendet.
394|Letzte Sicherung: {when} (Sicherungen: {n})
395|Noch keine Sicherungen.
396|Erstellt: {name}
397|Die Sicherung ist in Ordnung ({n} Elemente). Starten Sie AniHUB neu, um sie anzuwenden; die aktuelle Datenbank bleibt daneben als Kopie erhalten.
398|Die Bibliotheksdatenbank wurde aus einer Sicherung wiederhergestellt.
399|Cache-Grenze (Vorschauen, Videos)
400|Integritätsprüfung der Bibliothek
401|Sucht Einträge, deren Datei verschwunden ist, Dateien im arts-Ordner, die die Bibliothek nicht kennt, und (optional) Dateien, die sich seit dem Speichern geändert haben. Ohne Nachfrage wird nichts gelöscht.
402|Auch Dateiinhalte prüfen (langsam)
403|Prüfen
404|Einträge ohne Dateien entfernen
405|Datenbank optimieren
406|arts-Ordner öffnen
407|Problem
408|Datei
409|Datei fehlt
410|Inhalt geändert
411|nicht in der Bibliothek
412|Datenbank: OK
413|Datenbankproblem: {msg}
414|geprüft: {n}
415|keine Probleme gefunden
416|fehlend: {missing}, geändert: {damaged}, unbekannte Dateien: {orphans}
417|{n} Einträge entfernen, deren Dateien fehlen? Ihre Tags und Sammlungsverknüpfungen werden ebenfalls entfernt.
418|Entfernte Einträge: {n}.
419|Die Datenbank wurde optimiert.
420|Problem melden…
421|Problem melden
422|Ein Fehler ist aufgetreten: melden
423|Dieser Text würde geteilt: Version, System, der letzte Fehler und das aktuelle Protokoll. Schlüssel, Tokens, Passwörter und Ihr Benutzername werden automatisch entfernt; lesen Sie ihn vor dem Absenden. AniHUB selbst sendet nichts.
424|Was haben Sie getan, was erwartet und was ist passiert?
425|Aktuelles Protokoll einschließen
426|Der Bericht:
427|Kopieren
428|Kopieren und GitHub Issues öffnen
429|In die Zwischenablage kopiert.
430|Die Issue-Seite ist geöffnet; der Bericht liegt in der Zwischenablage.
431|Problembericht
432|Zu einem Bereich springen, eine Aktion ausführen, einen Tag, ein Buch oder eine Serie finden…
433|↑ ↓ wählen · Enter ausführen · Esc schließen
434|Bereich
435|Aktion
436|Bibliothek
437|Buch
438|Anime-Liste
439|Nach Updates suchen
440|Bibliothek jetzt sichern
441|Downloads öffnen
442|Offline-Modus umschalten
443|Dunkles / helles Design umschalten
444|Bibliothek durchsuchen: {q}
445|Abonnements
446|Abonnieren
447|Folgen
448|Name des Abonnements
449|Geben Sie zuerst eine Suche ein: Das Abonnement folgt ihr.
450|„{name}“ wird verfolgt: Neue Beiträge werden gezählt.
451|Keine Abonnements
452|Geben Sie unter Seiten eine Suche ein (ein Tag oder ein Künstler) und klicken Sie auf „Folgen“: Neue Beiträge erscheinen hier.
453|Jetzt prüfen
454|Alle prüfen
455|Neue speichern
456|Als gesehen markieren
457|Löschen
458|Das Abonnement „{name}“ löschen?
459|Aktiviert
460|Neue Beiträge automatisch speichern
461|nie
462|{source}: {query}  ·  letzte Prüfung: {when}
463|Neue Beiträge: {n}
464|Als gesehen markiert.
465|Offline-Modus: keine Prüfungen.
466|Diese Quelle ist nicht mehr verfügbar.
467|Neue Beiträge: {fresh}, automatisch gespeichert: {saved}
468|Statistik
469|Elemente in der Bibliothek
470|auf dem Datenträger
471|Favoriten
472|von Ihnen bewertet
473|Tags
474|Sammlungen
475|gelesene Bücher / im Regal
476|gesehene Folgen
477|Abonnements
478|im Papierkorb
479|Hinzugefügt pro Monat
480|Nach Quelle
481|Nach Inhaltseinstufung
482|Meistgenutzte Tags
483|Meistgespeicherte Künstler
484|Exportieren / teilen
485|AniHUB-Paket (.zip, mit Tags)…
486|HTML-Galerie (.zip)…
487|Sammlung exportieren…
488|Paket importieren…
489|AniHUB-Paket
490|{n} nach {path} exportiert
491|Paket „{name}“: hinzugefügt {saved}, schon vorhanden {dup}, fehlgeschlagen {failed}.
492|Musik
493|Titel oder Alben suchen
494|Musikordner öffnen
495|Neu einlesen
496|№
497|Titel
498|Noch keine Musik
499|Legen Sie einen Ordner pro Titel (ein OST-Album) in den Musikordner: <Bibliothek>/music/<Titel>/Stücke (mp3, flac, ogg…).
500|Nichts wird abgespielt
501|Einzelne Dateien
502|{n} Stücke
503|in Ihrer Liste: {title}
504|Zufällig
505|Wiederholen
506|Altersmodus und Tag-Filter
507|Altersmodus
508|12+ — nur unbedenkliche Inhalte
509|16+ — Brüste erlaubt, übrige 18+-Inhalte ausgeblendet
510|18+ — keine eingebauten Einschränkungen
511|Vom Modus ausgeblendet (nicht bearbeitbar)
512|Der 18+-Modus blendet von sich aus nichts aus.
513|Meine ausgeblendeten Tags
514|Durch Leerzeichen oder Kommas getrennt. Ein * am Ende blendet alle Tags mit diesem Anfang aus: guro*
515|Zu 18+ wechseln? Inhalte für Erwachsene werden ohne eingebaute Einschränkungen angezeigt. Sie müssen mindestens 18 Jahre alt sein.
516|Altersmodus
517|Wählen Sie einen Modus. Seine eingeschränkten Tags ändern sich mit dem Modus; eigene ausgeblendete Tags können Sie später in den Einstellungen hinzufügen.
518|12+ — blendet alles zu 16+- und 18+-Inhalten aus
519|16+ — Brüste erlaubt, übrige 18+-Inhalte werden herausgefiltert
520|18+ — keine eingebauten Einschränkungen
521|Ohne Anmeldung zeigt Pixiv nur jugendfreie Werke. Für R-18: Melden Sie sich im Browser bei pixiv.net an, drücken Sie F12 → Application → Cookies → pixiv.net, kopieren Sie den Wert von PHPSESSID und fügen Sie ihn hier ein (18+-Modus nötig). Das Cookie bleibt auf diesem Computer und wird nur an pixiv.net gesendet.
522|Suchbegriffe · user:Name · board:Name/Board · ein Profil- oder Board-Link
523|Durchscheinendes Fenster (Mica)
524|Das Windows-11-Material: Das Fenster lässt Hintergrundbild und Desktopfarben durchscheinen. Benötigt Windows 11 22H2 oder neuer.
525|Erweiterungen
526|Erweiterungen: Quellen aus Repositories
527|Repositories
528|Repository hinzufügen
529|Entfernen
530|Adresse der index.json des Repositorys:
531|Ein Repository ist eine index.json, die Erweiterungen auflistet (wie bei Aniyomi). Fügen Sie nur vertrauenswürdige hinzu.
532|Name
533|Sprache
534|Version
535|Status
536|Installieren
537|Aktualisieren
538|Entfernen
539|Einstellungen
540|Katalog aktualisieren
541|installiert
542|Verfügbare Erweiterungen: {n}
543|Fertig: {name}
544|„{name}“ installieren?\n\nEine Erweiterung ist ein Python-Programm und läuft mit Ihren Rechten. Repository: {repo}
545|Erweiterungen sind Code von Dritten. Installieren Sie nur aus vertrauenswürdigen Repositories. Die Datei wird mit der Prüfsumme des Repositorys abgeglichen.
546|Sprachen
547|Alle Sprachen
548|Regal
549|Online
"""
