# Insta360 — prototype local, étape 1

Diagnostic, lecture vidéo et références de cadrage pour Windows 11. Le traitement s'effectue intégralement sur votre ordinateur, sans clé API ni service payant.

## Périmètre livré

- Vérification de Python, FFmpeg, FFprobe et exécution réelle d'un filtre `v360` de test.
- Inspection de la première piste vidéo non attachée : codec, dimensions, durée, fréquences, audio et métadonnées dans `probe.json`.
- Validation 2:1, pixels carrés, rotation, décodage des images demandées ; contrôle intégral vidéo facultatif.
- Un panorama PNG 1920×960 toutes les 30 secondes par défaut.
- **Cinq vues fixes PNG 640×360 par panorama**, calculées à partir de la même image.
- Galerie HTML locale, configuration des orientations, rapports JSON et logs.
- Codes de sortie : 0 succès, 1 erreur, 2 arguments CLI invalides, 130 interruption.

Il s'agit de références fixes, pas encore de cinq vidéos MP4. Analyse IA, analyse audio, montage, mouvements de caméra, MP4 et timeline Resolve sont réservés aux étapes suivantes. OpenCV et librosa sont seulement signalés s'ils sont installés ; ils ne sont pas nécessaires ici. Aucun musicien ni événement n'est détecté ou inventé.

## 1. Préparer la source

Utiliser un fichier vidéo **déjà assemblé, mono, équirectangulaire couvrant 360°×180°**, idéalement MP4 H.264/H.265, exporté depuis votre logiciel Insta360. Ne pas utiliser un export plat déjà recadré, une paire de vues fisheye, un fichier stéréo ou un `.insv` brut. Ce prototype ne réalise ni assemblage des lentilles ni stabilisation gyroscopique.

Le panorama complet doit présenter un rapport largeur/hauteur de 2:1 (par exemple 5760×2880). Ce rapport ne prouve pas sa projection : vous la confirmez explicitement avec `--confirm-equirectangular`. Les aperçus sont destinés au cadrage, sans gestion HDR/tonemapping de référence ; privilégier un export SDR pour ce test.

Conserver votre fichier original à son emplacement habituel. Le script le lit uniquement. Il crée un nouveau sous-dossier unique à chaque exécution, utilise FFmpeg en mode non-écrasement et n'effectue aucune suppression.

## 2. Installer sous Windows 11

Décompresser ce dossier dans `D:\360Prototype\insta360_etape1` (ou tout autre chemin). Installer Python 3.11 ou 3.12 et une distribution Windows de FFmpeg contenant `ffmpeg.exe`, `ffprobe.exe` et le filtre `v360`.

Sources officielles :
- Python pour Windows : https://www.python.org/downloads/windows/
- Page FFmpeg orientant vers les compilations Windows : https://ffmpeg.org/download.html

Dans **PowerShell**, depuis le dossier extrait :

```powershell
Set-Location "D:\360Prototype\insta360_etape1"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe step1.py --check-only
```

Adapter `-3.11` à votre version installée (par exemple `-3.12`). L'activation PowerShell du venv n'est pas nécessaire. `requirements.txt` ne contient aucune dépendance Python externe à cette étape.

Si FFmpeg n'est pas dans le PATH, fournir ses chemins **sur chaque commande**, par exemple :

```powershell
.\.venv\Scripts\python.exe step1.py --check-only --ffmpeg "C:\Tools\ffmpeg\bin\ffmpeg.exe" --ffprobe "C:\Tools\ffmpeg\bin\ffprobe.exe"
```

Le dossier créé contient `environment.json`, `report.json` et `run.log`. La présence des paquets facultatifs ne vérifie pas leur bon fonctionnement : celui-ci sera testé lorsque ces paquets seront utilisés.

## 3. Premier essai : un panorama et cinq vues

Choisir un instant où la scène est visible. Cet exemple ne prélève que l'instant 10 secondes :

```powershell
.\.venv\Scripts\python.exe step1.py --source "D:\Concerts\morceau_360.mp4" --output "D:\Concerts\tests_360" --confirm-equirectangular --start 10 --end 11 --interval 30
```

Ouvrir `gallery.html` dans le sous-dossier `run_...` indiqué à la fin du traitement. Il fonctionne hors connexion et référence les images locales : garder tout le dossier ensemble.

Les cinq angles initiaux ont des yaw de −144°, −72°, 0°, 72° et 144°, un pitch nul et un champ horizontal de 90°. Ce sont **des directions de calibration**, pas des positions supposées de musiciens. Elles explorent l'horizon ; le cinquième angle n'est pas encore un plan large de scène validé.

## 4. Régler manuellement les cinq cadrages

Ouvrir `views.json` avec un éditeur de texte. Chaque entrée propose :

| Champ | Signification | Limites de ce prototype |
|---|---|---|
| `id` | Nom stable du fichier de vue | Lettres minuscules, chiffres, `_` ; commencer par une lettre |
| `subject` | Attribution manuelle facultative | `null` tant que non identifiée visuellement |
| `yaw` | Orientation horizontale, convention FFmpeg v360 | −180° à +180° |
| `pitch` | Inclinaison verticale, convention FFmpeg v360 | −90° à +90° |
| `h_fov` | Champ de vision horizontal | 10° à 160° |

`yaw=0, pitch=0` est le repère du panorama, sans lien implicite avec l'avant de la scène. Modifier un angle, relancer l'essai d'une seconde et observer le résultat pour confirmer le sens de déplacement. La convention est celle de FFmpeg, avec `roll=0` et ordre de rotation `ypr`. Les yaw −180° et +180° désignent la même direction.

Après observation, vous pouvez attribuer quatre vues aux musiciens en renseignant `subject`, puis élargir la cinquième et l'orienter vers la scène. Ne renseigner ces valeurs qu'après validation visuelle. Garder exactement cinq entrées. Une valeur `subject` est enregistrée comme déclaration manuelle, jamais comme résultat IA.

Le champ vertical est calculé à partir du champ horizontal et du ratio de sortie :

`v_fov = 2 × atan(tan(h_fov / 2) × hauteur / largeur)`

Les calculs convertissent degrés et radians. Cela évite de déformer la perspective en imposant un champ vertical arbitraire. Un grand FOV rectilinéaire étire fortement les bords ; 160° est une borne technique, pas une recommandation esthétique.

## 5. Échantillonner le morceau entier

```powershell
.\.venv\Scripts\python.exe step1.py --source "D:\Concerts\morceau_360.mp4" --output "D:\Concerts\tests_360" --confirm-equirectangular --interval 30
```

Une vidéo de 180 secondes génère des références à 0, 30, 60, 90, 120 et 150 secondes. La borne de fin est exclue. `--start` et `--end` sont des secondes relatives au début de lecture du fichier, pas des timecodes de projet Resolve. Les timestamps JSON sont les **temps de recherche demandés**, pas les PTS exacts des images sélectionnées ; un arrondi à la trame vidéo peut intervenir, particulièrement en fréquence variable.

Le script refuse un nombre de prélèvements supérieur à 100 par défaut (`--max-samples` permet de changer cette limite). Les vues proviennent du panorama réduit : c'est rapide et adapté au repérage, pas un rendu final haute résolution.

Pour contrôler le décodage de toute la piste vidéo, ajouter `--full-decode-check`. Ce contrôle lit toute la vidéo et peut être long. Sans cette option, la réussite prouve seulement la lecture des métadonnées et le décodage aux instants échantillonnés. La piste audio n'est pas contrôlée par cette étape.

Raccourci facultatif avec FFmpeg dans le PATH :

```powershell
.\run_step1.cmd "D:\Concerts\morceau_360.mp4"
```

**Ce raccourci confirme automatiquement que votre source est équirectangulaire.** Ne l'utiliser qu'après avoir vérifié ce point. Il traite tout le fichier avec l'intervalle par défaut. Utiliser la commande Python pour personnaliser le test.

## Sorties

Chaque exécution crée un nouveau dossier `run_DATE_HEURE_identifiant` :

- `run.log` : versions appelées, commandes exactes, messages FFmpeg et erreurs.
- `environment.json` : environnement et disponibilité des outils.
- `probe.json` : métadonnées FFprobe complètes.
- `views.used.json` : copie des cinq cadrages effectivement utilisés.
- `references.json` : références d'images et temps demandés, attributions manuelles, détection IA à `null`.
- `report.json` : état final, source, mode de validation et nombre d'échantillons.
- `gallery.html` : panorama et cinq vues par instant.
- `ref_0000`, etc. : six images par instant.

En cas d'erreur, les sorties partielles sont conservées et `report.json` indique `failed`. La galerie complète n'est créée qu'après une extraction réussie. Les erreurs de syntaxe de commande sont affichées directement par argparse avant création d'un dossier. Les logs contiennent les chemins locaux : les relire avant de les partager.

## Tests reproductibles

Depuis le dossier du projet :

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

FFmpeg et FFprobe doivent être dans le PATH pour les tests d'intégration ; sinon ils sont indiqués comme ignorés. Les tests fabriquent une mire vidéo temporaire explicitement synthétique, puis vérifient le décodage complet, les douze images produites à deux instants, les dimensions et le SHA-256 inchangé de la source. Ils couvrent aussi l'absence de confirmation, une source invalide, un mauvais ratio, un temps hors vidéo, les valeurs NaN et les règles d'échantillonnage. Aucune détection n'est simulée.

Validation effectuée lors de la livraison : **8 tests réussis dans l'environnement Linux disponible**, avec FFmpeg installé. Windows 11 et les rushs Insta360 réels n'ont pas été testés ici. `validation/` contient un journal réel de diagnostic et le compte rendu des tests. La mire de test n'est pas une validation de l'assemblage ou de la qualité d'un concert réel.

### Validation attendue sur votre poste

1. `--check-only` termine avec un code 0.
2. L'essai à un instant donne un panorama complet et cinq vues sans étirement anormal.
3. Les angles ajustés permettent de reconnaître les quatre musiciens et de valider un plan large.
4. Les prélèvements sur l'ensemble du morceau restent lisibles.
5. Conserver les valeurs validées de `views.json` pour la prochaine étape.

Si la projection apparaît fausse malgré le ratio 2:1, vérifier le type d'export. Si un musicien n'est pas visible ou reste masqué, laisser son attribution à `null` : cette étape ne fait ni suivi ni estimation de position.

## Références techniques

Documentation officielle utilisée pour les options et le comportement :

- FFmpeg `v360`, projections et angles : https://ffmpeg.org/ffmpeg-filters.html#v360
- FFprobe, inspection et sortie JSON : https://ffmpeg.org/ffprobe.html
- FFmpeg, recherche temporelle et sélection de pistes : https://ffmpeg.org/ffmpeg.html
- Python `subprocess`, exécution sans shell : https://docs.python.org/3/library/subprocess.html

Les commandes sont passées comme listes d'arguments avec `shell=False`, pour gérer notamment les espaces et les caractères accentués des chemins Windows. Aucun chemin source n'est interpolé dans une commande shell ni dans le filtre v360.
