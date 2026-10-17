# Étape B — cartographie interactive des musiciens

Cette version **prolonge le projet insta360_etape1**. L'étape A reste exécutable telle quelle. Ouvrir ce document pour B ; `README.md` reste le guide original de A.

## Ce qui a été examiné avant les modifications

L'archive originale contient `step1.py`, `views.json`, `run_step1.cmd`, les huit tests de A, le README et les journaux de validation. `step1.py` expose les fonctions réutilisables `projection`, `inspect_video` et `binary` ; ses sorties `report.json` et `references.json` permettent de récupérer la source, les panoramas et les temps demandés.

Le rapport Windows fourni signale Python 3.12.4, FFmpeg 9.0.2, une source HEVC 5760×2880 à 30000/1001 images/s, une durée de 137.370567 s et une référence à 10 s. Le contrôle A a porté sur les métadonnées et l'instant échantillonné. Aucun contrôle intégral de ce rush n'est revendiqué.

**Tous les fichiers de A sont conservés octet pour octet.** Les empreintes sont dans `validation_b/compatibility_a.json`. Aucun renommage de champ dans les JSON de A et aucune nouvelle dépendance imposée à A. Les nouveautés sont dans `step2.py`, `mapping360/`, `requirements-step2.txt` et `tests/test_step2.py`.

## Installation Windows 11 / Python 3.12

Extraire l'archive dans un dossier distinct pour conserver votre installation précédente. Elle contient un dossier `insta360_etape1` complet. Vos dossiers `outputs/run_...` existants peuvent rester à leur emplacement actuel.

Dans PowerShell, depuis le nouveau dossier `insta360_etape1` :

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-step2.txt
.\.venv\Scripts\python.exe -m tkinter
```

La dernière commande doit ouvrir une petite fenêtre Tcl/Tk : la fermer ensuite. Si elle échoue, modifier l'installation officielle de Python et activer le composant Tcl/Tk. B utilise **Tkinter, NumPy et Pillow**, sans serveur web, compte, clé API ou téléchargement de modèle. OpenCV/librosa restent réservés aux étapes qui en auront besoin.

Installer FFmpeg/FFprobe ou conserver ceux déjà employés par A. Tous les appels ont `shell=False` et acceptent les espaces et accents des chemins.

## Lancement conseillé : reprendre votre dossier A

```powershell
.\.venv\Scripts\python.exe step2.py --run "C:\Users\nicom\Downloads\insta360_etape1\insta360_etape1\outputs\run_20261011_163155_024992ec"
```

**Adapter le chemin si vous avez déplacé ce dossier.** B lit `report.json`, `references.json` et, s'il est présent, `probe.json`. Les panoramas référencés doivent toujours se trouver dans les sous-dossiers indiqués par A. B en copie des versions PNG dans un **nouveau** dossier `mappings/mapping_...`. Il ne réécrit rien dans A.

À la réouverture, reprendre le projet B existant plutôt que réimporter A :

```powershell
.\.venv\Scripts\python.exe step2.py --project "D:\360Prototype\insta360_etape1\mappings\mapping_...\musiciens.json"
```

### Ouvrir directement le panorama déjà fourni

L'archive inclut votre panorama de 10 s dans un projet sans attribution de rôles :

```powershell
.\.venv\Scripts\python.exe step2.py --project ".\exemple_panorama_fourni"
```

Son chemin source est celui de votre rapport Windows. Si la vidéo a été déplacée, cliquer sur **Lier / déplacer la source vidéo**. Le fichier `musiciens.json` à la racine est un modèle vide, pas une cartographie validée. Le fichier actif de cet exemple se trouve dans `exemple_panorama_fourni/musiciens.json`.

Lancement sans argument : ouvre un projet vide et propose **Importer dossier A**. Autre possibilité, importer un panorama isolé à un instant que vous connaissez :

```powershell
.\.venv\Scripts\python.exe step2.py --panorama "D:\Concerts\panorama.png" --time 10
```

Pour des exécutables FFmpeg hors PATH, ajouter aux commandes :

```powershell
--ffmpeg "C:\Tools\ffmpeg\bin\ffmpeg.exe" --ffprobe "C:\Tools\ffmpeg\bin\ffprobe.exe"
```

Ces chemins sont des arguments de lancement, à redonner à chaque ouverture. `run_step2.cmd` transmet les arguments au même programme.

## Utiliser l'interface

1. Choisir **Chanteur**, **Guitariste**, **Bassiste**, **Batteur** ou **Groupe entier** dans la liste ou sous les miniatures.
2. En mode **Point**, cliquer sur le centre voulu du sujet. Rien n'est détecté automatiquement.
3. En mode **Zone du corps / groupe**, glisser pour tracer une zone. Le centre et le FOV sont proposés à partir de votre rectangle. L'estimation géométrique couvre la zone avec une marge de 12 % sur les tangentes de projection ; ce n'est pas une mesure IA.
4. Corriger **yaw**, **pitch**, **FOV horizontal** avec les curseurs. Les champs numériques acceptent aussi une valeur, confirmée par Entrée ou perte de focus. Le retour visuel est recalculé en mémoire, avec temporisation de 35 ms entre les changements ; sa fluidité dépend du PC.
5. Choisir un instant dans la liste **Référence**. Pour en ajouter un, saisir des secondes puis cliquer sur **+**. Seul cet instant est décodé depuis la vidéo source ; une image déjà extraite est mise en cache. Cela peut prendre quelques secondes sur une vidéo HEVC 5,7K.
6. Pour chaque sujet et chaque référence, choisir **visible**, **partiel**, **masque** ou **hors_champ**, puis **Enregistrer observation**.
7. Quand toutes les références ont été examinées avec le cadrage actuel, cliquer sur **Valider cette caméra**. Répéter pour les cinq sujets.
8. **Enregistrer musiciens.json**, puis **Enregistrer les aperçus PNG**. Les cinq caméras renseignées donnent cinq PNG par instant, en 960×540.
9. Choisir le début et la durée des extraits (5 s par défaut), puis **Exporter les 5 MP4**. Le panneau de droite peut défiler verticalement sur les petits écrans.

Les FOV initiaux sont des **préréglages à valider**, sans position présumée : chanteur 65°, guitariste 70°, bassiste 70°, batteur 90°, groupe 115°. Aucune caméra n'a de yaw/pitch tant que vous ne la positionnez pas. Un rectangle propose un autre FOV selon sa taille ; les curseurs ont toujours priorité.

### Ce que signifie « validée »

Une caméra validée a été réglée et tous ses instants de référence ont une observation manuelle à jour. Cela **ne signifie pas** que son sujet est toujours visible : une observation `masque` ou `partiel` reste conservée et n'est pas transformée en `visible`.

Changer l'orientation ou le FOV invalide la validation du cadrage. Les observations antérieures restent dans le JSON avec leur signature de cadrage, mais ne comptent plus comme vérifications actuelles. Ajouter un instant exige une nouvelle observation pour chaque caméra. Il n'y a ni suivi, ni trajectoire, ni interpolation : la même caméra fixe est comparée à tous les instants.

Une caméra non positionnée n'a ni aperçu fictif ni export vidéo. Les brouillons peuvent être sauvegardés. Les cinq MP4 exigent cinq caméras validées, pour éviter un export accidentel de directions non vérifiées.

## Jonction 360° et conventions vérifiées

Les coordonnées normalisées utilisent le bord gauche/haut comme origine : `u=x/largeur`, `v=y/hauteur`. Le centre du pixel `i` vaut `(i+0.5)/taille`.

| Point du panorama | u | v | yaw FFmpeg | pitch FFmpeg |
|---|---:|---:|---:|---:|
| Centre | 0,5 | 0,5 | 0° | 0° |
| Trois quarts à droite | 0,75 | 0,5 | +90° | 0° |
| Quart gauche | 0,25 | 0,5 | −90° | 0° |
| Centre, quart supérieur | 0,5 | 0,25 | 0° | +45° |
| Jonction gauche/droite | 0 ou 1 | 0,5 | −180° ou +180° | 0° |

Formules : `yaw = wrap(360*u - 180)` et `pitch = 90 - 180*v`. L'ordre de rotation est `ypr`, avec `roll=0`, comme dans A. Le champ vertical est dérivé du champ horizontal pour conserver le ratio 16:9.

Le curseur **Déplacer la jonction** décale uniquement l'affichage du panorama. Les clics sont reconvertis dans les coordonnées d'origine. Les boîtes emploient **l'arc horizontal le plus court, ≤180°** : une sélection de 0,98 à 0,02 traverse la jonction et couvre 4 % de la largeur, pas 96 %. Le rectangle final est dessiné en deux parties si nécessaire. Pour une sélection visuelle plus intuitive, déplacer la jonction loin du sujet avant de tracer la zone.

Une caméra rectilinéaire limitée à 160° ne peut pas couvrir toutes les configurations de scène, notamment des musiciens répartis sur plus d'un demi-tour autour de la caméra. Une zone trop vaste déclenche un avertissement et un FOV plafonné ; ce n'est pas une garantie d'inclure le groupe. Vérifier humainement le cadre et les bords étirés. Les pôles rendent la longitude géométriquement ambiguë ; le yaw choisi est conservé.

## Export des cinq courts extraits

Le rendu utilise **directement le fichier source original**, avec `v360` avant l'encodage H.264. Il n'utilise pas les PNG 1920×960 comme source vidéo. La sortie GUI est 1280×720, FOV/yaw/pitch fixes, AAC 192 kbit/s si une piste audio existe. Il n'y a ni découpage automatique du morceau ni assemblage multicaméra.

Début et durée sont bornés par la durée source ; la durée doit être >0 et ≤30 s. La fréquence du fichier source n'est pas forcée à 30 i/s. Les temps sont des temps de recherche demandés : ils ne constituent pas encore une grille de montage à l'image près. La durée réellement observée après encodage figure dans le rapport.

Une sortie distincte `clips_DATE_identifiant` contient :

- `chanteur.mp4`, `guitariste.mp4`, `bassiste.mp4`, `batteur.mp4`, `groupe.mp4` ;
- `musiciens.snapshot.json`, configuration utilisée exactement pour ce rendu ;
- `render_report.json`, commandes, filtres, version FFmpeg, dimensions source/sortie, audio et métadonnées FFprobe de chaque extrait.

Export sans interface, depuis un projet déjà validé :

```powershell
.\.venv\Scripts\python.exe step2.py --project "D:\360Prototype\mappings\mapping_..." --export-clips --start 10 --duration 5 --width 1920 --height 1080
```

Pour lier un chemin source explicitement en ligne de commande, ajouter `--source "D:\Concerts\morceau_360.mp4" --confirm-equirectangular`. La taille, la durée et, après la première liaison, une empreinte partielle du début et de la fin du fichier sont comparées. Cette empreinte rapide n'est **pas** un hachage intégral de la vidéo. Un autre morceau doit avoir son propre projet.

Les commandes FFmpeg sont consignées dans `step2.log`. Une sauvegarde précédente du JSON est conservée dans `musiciens.previous.json`. Les sorties partielles d'un export échoué restent dans leur dossier, avec `status: failed` dans le rapport. L'interface attend la fin d'une opération FFmpeg avant de permettre sa fermeture ; elle ne propose pas encore de bouton d'annulation.

## Structure de musiciens.json

- `schema_version`, `artifact_type`, `app_version` : identification/version du format B.
- `coordinate_system` : projection, origine, formules, ordre de rotation et ratio de sortie.
- `source` : chemin Windows, taille, date, durée, piste vidéo, métadonnées et empreinte partielle lorsqu'elle a été liée.
- `references` : identifiant, PNG relatif au projet, SHA-256, dimensions et instant demandé.
- `cameras` : cinq identifiants stables `chanteur`, `guitariste`, `bassiste`, `batteur`, `groupe`.
- Pour chaque caméra : yaw/pitch, `center_uv` courant, FOV, origine du FOV, état de validation.
- `annotations` : points cliqués, coordonnées normalisées et pixels, rectangles cycliques, référence et date.
- `reviews` : observations manuelles de visibilité, référence et signature du cadrage examiné.
- `annotation_origin: manual`, `ai_detection: null`, `ai_detections: []` : distinction explicite, **aucun score IA**.

Le point de clic initial et la position courante du centre de caméra peuvent différer après correction par curseur : l'un est une annotation, l'autre le cadrage final. Les références sont copiées dans le dossier B, dont les chemins restent relatifs. Déplacer tout le dossier conserve les annotations et les images ; il faut relier la vidéo si son chemin absolu a changé.

**Exporter views pour A** écrit `views.step1.json`, accepté par le `--views` original de A. Ce fichier est distinct de `views.json` livré avec A et ne modifie aucune sortie précédente.

## Tests et preuves de validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe step2.py --check-conventions
```

Les tests d'intégration nécessitent FFmpeg/FFprobe dans le PATH ; sinon ils sont explicitement ignorés. `--check-conventions` accepte `--ffmpeg` pour un chemin personnalisé.

Validation effectuée : **25 tests réussis sous Linux, Python 3.12.14**, incluant les huit tests originaux A et 17 tests B. NumPy 2.3.5, Pillow 12.3.0. Les huit comparaisons expérimentales avec FFmpeg couvrent les axes, les rotations combinées, la jonction à ±179° et un cadrage proche du pôle. L'écart moyen des aperçus est inférieur à 0,2 niveau par canal sur 255 sur cette mire ; cette mesure ne prétend pas valider une chaîne colorimétrique HDR.

Le test de rendu crée une **vidéo synthétique** avec son, génère cinq vrais MP4 temporaires, contrôle leurs pistes audio et durées, vérifie l'emploi de la source vidéo dans chaque commande et confirme le SHA-256 inchangé de l'original. Ces médias temporaires sont supprimés après test et ne sont jamais présentés comme des images de votre concert.

Les journaux et résultats se trouvent dans `validation_b/`. **L'environnement de développement ne dispose pas d'affichage graphique : l'interaction Tk et le lancement Windows de B restent à tester sur votre poste.** Le succès Windows de A ne constitue pas une validation de l'interface B.

### Test utilisateur court

1. Ouvrir `exemple_panorama_fourni` : vérifier que le panorama réel apparaît et qu'aucun sujet n'est préattribué.
2. Cliquer un sujet identifiable et vérifier que le centre de l'aperçu correspond au clic.
3. Déplacer la jonction puis cliquer le même sujet : le cadrage doit rester équivalent.
4. Tracer une zone, ajuster le FOV et enregistrer ; fermer puis rouvrir le projet pour vérifier la persistance.
5. Ajouter deux instants, par exemple 30 et 60 s, avec votre vidéo liée ; renseigner les observations pour les cinq caméras.
6. Valider les cinq caméras, enregistrer les aperçus et exporter 5 s à 10 s. Vérifier les cinq MP4, leur audio et leur cadrage.

**État des livrables :** code, interface, tests, modèle `musiciens.json` et projet avec votre panorama sont fournis. Les rôles n'ont pas été attribués à votre place. Les cinq aperçus personnalisés sont produits après vos annotations ; les cinq extraits réels sont produits sur votre ordinateur, qui possède la vidéo 5,7K. Seuls le panorama et les métadonnées ont été disponibles pendant ce développement.

## Organisation pour les évolutions suivantes

- `geometry.py` : conversions sphériques et projection des aperçus.
- `project.py` : format de données, annotations, observations et sauvegardes.
- `render.py` : extraction ponctuelle, validation expérimentale et rendu FFmpeg.
- `ui.py` : interactions humaines uniquement.
- `step2.py` : point d'entrée GUI/CLI.

Les fonctions de traitement ne dépendent pas de Tk et pourront être exposées ultérieurement via MCP. Le schéma sépare annotations et futures détections. Aucun réalisateur automatique, suivi, modèle IA, mouvement interpolé ou serveur MCP n'est implémenté dans B.

## Sources techniques officielles

- FFmpeg v360, projections, FOV et rotations : https://ffmpeg.org/ffmpeg-filters.html#v360
- Code officiel v360, complément aux tests expérimentaux : https://ffmpeg.org/doxygen/trunk/vf__v360_8c_source.html
- FFmpeg, options de recherche temporelle et encodage : https://ffmpeg.org/ffmpeg.html
- FFprobe, métadonnées JSON : https://ffmpeg.org/ffprobe.html
- Tkinter, installation et fonctionnement : https://docs.python.org/3.12/library/tkinter.html
- Python Windows : https://www.python.org/downloads/windows/
- Téléchargement FFmpeg : https://ffmpeg.org/download.html
