# Validation B.1 — 19 octobre 2026

## Audit initial et lots

- Départ : `main`, commit `fc51575`, arbre propre, aucun AGENTS.md présent.
- B existant : géométrie rectilinéaire NumPy, projets v1, Tkinter, rendus FFmpeg
  16:9 fixes. Pas de suivi ni d'analyse IA ; ces fonctionnalités restent hors périmètre.
- Environnement : Windows 11, Python 3.12.4, NumPy 2.5.4, Pillow 12.3.0,
  FFmpeg/FFprobe 9.0.2. Aucune nouvelle dépendance installée pour B.1.
- Proposition d'interface présentée avant implémentation : sujets en haut,
  aperçu central, panorama en bas, paramètres simplifiés et panneau avancé repliable.
- Lot moteur/migration : 32 tests réussis, dont 48 comparaisons géométriques.
- Lot exports : tests B.1 réussis pour les 24 combinaisons format/projection,
  PNG, image décodée du MP4, audio, absence d'audio et intégrité de la source.
- Lot interface/CLI : suite finale **38 tests, 52,250 s, OK, aucun ignoré**.
  Journal réel : `tests.log`.

La première tentative de tests était bloquée par les droits du répertoire
temporaire du bac à sable ; les tests ont été relancés hors de cette restriction.
Le test historique B lisait un JSON UTF-8 avec l'encodage Windows implicite : la
comparaison de chemins accentués échouait. Sa lecture a été corrigée en UTF-8,
sans affaiblir les assertions. Les huit fichiers A sont identiques aux SHA-256
du manifeste `validation_b/compatibility_a.json`.

## Ce qui a été réellement vérifié

- Six ratios exacts, dimensions paires et validation des résolutions.
- Quatre projections distinctes à FOV commun (pas seulement quatre zooms).
- 48 comparaisons NumPy/FFmpeg : quatre modes × six ratios × deux orientations,
  dont yaw 179°, pitch 35°, roll 23°. Moyenne absolue <2 et percentile 99 <5
  niveaux par canal sur 255 sur une mire continue.
- 24 combinaisons export PNG/MP4 : dimensions, durée, piste audio, débuts A/V,
  chemin de la source vidéo, différence moyenne image MP4/aperçu <6 niveaux.
- PNG CLI aux six résolutions finales et MP4 CLI 1080×1920.
- SHA-256 inchangé de la vidéo synthétique après la matrice d'exports.
- Export depuis panorama seul, et MP4 sans piste audio.
- Migration v1 en mémoire, préservation des observations applicables, copie v1
  originale persistante, aller-retour JSON des paramètres et cadrages mémorisés.
- Changement de ratio sans déplacer l'annotation ; changement de résolution
  seule conservant la validation ; refus d'un export A non représentable.
- Tests Tk : point, zone, orientation souris, zoom, roll, sélection du sujet,
  formats, projections, mémoire/restauration, observations et validation.
- Vérification visuelle Windows : ouverture sur une copie du panorama fourni,
  affichage 16:9 et 9:16, centrage de l'aperçu, glisser de souris, séparation des
  repères caméra/sujet, sauvegarde puis fermeture sans modifier le projet exemple.

## Performance

`benchmark.json` contient 72 cas : quatre modes × six ratios × trois tailles.
Panorama synthétique 1920×960 ; échauffement puis sept répétitions par cas.
La mesure finale a été relancée après la suite de tests, pour ne pas exécuter
les encodages de test en parallèle. Elle inclut projection et échantillonnage
NumPy ; elle exclut décodage, transfert vers Tk et affichage. Les ms indiquées
dans l'interface suivent également le temps de calcul, pas la latence bout en bout.

Le profil Rapide (480 pixels maximum) est le défaut. L'interface reste sur le
thread Tk ; un worker calcule les aperçus et remplace les demandes en attente
par la plus récente. Aucun lancement FFmpeg pour un geste de cadrage.

| Bord maximal | Médianes observées selon mode/ratio | Plus grand p95 |
|---|---|---|
| 480 px | 20,07–63,24 ms | 65,75 ms |
| 720 px | 45,64–132,09 ms | 138,10 ms |
| 960 px | 86,67–234,51 ms | 243,05 ms |

## Limites et validation restante

- Pas de mesure garantie à 30/60 images/s : dépend du CPU et du ratio.
- La comparaison sur mire valide la géométrie, pas la fidélité aux modes propriétaires
  Insta360, la qualité HDR ni le comportement sous tous les éclairages de concert.
- Les exports vidéo automatisés sont synthétiques ; vérifier encore des extraits
  du concert réel, la qualité perçue et la synchronisation à l'écoute.
- L'absence de modification de source est hachée dans les tests ; en production,
  contrôles taille/date et empreinte partielle pour la liaison, pas SHA-256 intégral.
- Durée limitée à 30 secondes, pas d'annulation FFmpeg, pas de suivi, ni de
  réalisation musicale, ni d'intégration Resolve/MCP.
- Aucun projet utilisateur existant n'a été migré/sauvegardé pendant les tests.
  La vérification graphique a utilisé un nouveau projet ignoré par Git.
- `main` reste au commit de référence. La fusion attend la validation utilisateur.
