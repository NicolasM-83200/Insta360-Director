# Insta360 Director — B.1 (0.3.0)

Évolution de B, sans analyse IA ni suivi. `step1.py`, ses tests, ses fichiers de
configuration et son README restent inchangés. Branche :
`feature/etape-b1-interface-exports`. La fusion sur `main` attend la validation utilisateur.

## Lancer

Depuis PowerShell à la racine du projet, avec le `.venv` Python 3.12 existant :

```powershell
.\.venv\Scripts\python.exe step2.py --project "mappings\mapping_..."
```

Ou `run_step2.cmd --project "mappings\mapping_..."`. Sans argument, un nouveau
projet est créé sous `mappings/`. Cliquer **Ouvrir / lier vidéo** pour choisir un
export 360 mono équirectangulaire : la référence 0 s est extraite si le projet
est vide. Le bouton peut ensuite relier la même source déplacée. Pour un autre
concert, créer un nouveau projet. Les `.insv` bruts ne sont pas assemblés ici.

Le bouton **Importer panorama** demande son instant ; pour un projet sans vidéo,
les exports PNG utilisent cette image à sa résolution conservée. Un projet dont
la vidéo est liée mais inaccessible produit une erreur au rendu final : aucun
remplacement silencieux par un aperçu basse résolution.

## Interface et parcours

- Cinq sujets accessibles en haut ; aperçu principal central au ratio choisi.
- Cliquer sur le panorama du bas pour annoter un sujet, ou tracer sa zone.
  La jonction déplaçable et les boîtes cycliques de B sont conservées.
- Glisser dans le grand aperçu pour orienter la caméra ; molette pour zoomer.
  Ces gestes déplacent la caméra, jamais les annotations du sujet.
- Format, résolution finale, projection et qualité d'aperçu dans le panneau droit.
  Le panneau défile avec sa barre ou la molette ; yaw/pitch/roll/FOV numériques
  restent dans **Réglages avancés**, repliable.
- **Mémoriser** ajoute un cadrage à l'historique de cette caméra et sauvegarde.
  Choisir un élément puis **Restaurer** rétablit direction, roll, FOV, mode et format.
  Les annotations sont conservées et la validation du cadre est retirée.
- **Enregistrer** sauvegarde l'ensemble du projet. Les cadrages mémorisés restent
  disponibles après fermeture/réouverture.
- Les observations de visibilité et la validation sur toutes les références restent
  obligatoires pour **5 MP4**. **MP4 du sujet** autorise un cadrage positionné mais
  non validé pour le contrôler avant validation ; le rapport le signale.
- **PNG du sujet** est un rendu final à la résolution choisie. **Aperçus PNG**
  conserve l'export de toutes les références/caméras positionnées, à taille réduite.

Un point/rectangle blanc est l'annotation du sujet ; une croix est la direction
de caméra. Un avertissement indique si l'annotation n'est pas entièrement dans
le cadre. Ce test géométrique échantillonne les zones : il ne détecte ni corps,
ni occultation et ne garantit pas la visibilité entre les références.

## Formats et résolution

| Format | Résolution finale initiale |
|---|---|
| 16:9 | 1920 × 1080 |
| 9:16 | 1080 × 1920 |
| 4:3 | 1440 × 1080 |
| 3:4 | 1080 × 1440 |
| 1:1 | 1080 × 1080 |
| 2.35:1 | 1880 × 800 (47:20 exact) |

Dimensions personnalisables, entières et paires, entre 64 et 4096 sur chaque axe,
avec le ratio exact du format. Pour 2.35:1, 940×400 et 3760×1600 sont également
possibles. La borne s'applique aussi à la hauteur, donc les formats verticaux
ne sont pas traités comme des paysages recadrés.

Le changement de ratio conserve yaw/pitch/roll. Il conserve la couverture
horizontale quand le cadre devient plus haut ; il élargit la couverture horizontale
quand le cadre devient plus large, pour conserver la couverture verticale.
Si la limite de projection est atteinte, le FOV est plafonné avec avertissement.
Un aller-retour de ratios peut donc élargir le champ : **Restaurer** permet de
revenir exactement à un cadrage mémorisé. Vérifier la zone annotée après chaque
changement. Un simple changement de résolution au même ratio ne change pas le champ.

Les aperçus utilisent un bord maximal de 480 (**Rapide**, défaut), 720
(**Équilibré**) ou 960 (**Détaillé**) pixels, réduit davantage si nécessaire pour
tenir dans la fenêtre. Le ratio reste exact, avec bandes de fond autour de
l'image ; ces bandes ne sont pas incluses dans les exports.

## Projections : correspondances proposées, non propriétaires

Ces noms sont des **approximations de rendus inspirés d'Insta360 Studio**.
Ils ne reproduisent pas ses algorithmes. Les quatre boutons changent réellement
la transformation géométrique, en plus d'un FOV initial adapté.

| Mode | `v360 output` | FOV H initial / limite | Distorsion et usage |
|---|---|---|---|
| Linear | `flat` | 90° / 160° | Rectilinéaire ; lignes droites, étirement marqué des bords à grand FOV. |
| Dewarp | `cylindrical` | 110° / 200° | Cylindrique ; verticales droites dans le repère caméra sans roll, horizontales hors horizon courbes. Ce n'est pas une correction universelle de lentille. |
| Ultra | `sg` | 130° / 240° | Stéréographique ; géométrie radiale, grands angles, lignes courbes et variation d'échelle sur les bords. |
| Mega | `fisheye` | 150° / limite dynamique ≤240° | Fisheye équidistant ; grand champ immersif, courbure forte. Diagonale limitée à 300° pour éviter des rayons repliés au-delà de l'arrière. |

Minimum H : 10°. En Mega portrait, la limite horizontale descend pour respecter
la diagonale ; par exemple elle est d'environ 147° en 9:16. Le preset est alors
plafonné. Ultra et Mega peuvent regarder derrière la caméra virtuelle : ce
comportement géométrique est attendu, pas une erreur de raccord.

Avec `a = largeur/hauteur` et H/V en radians, les formules de FOV vertical sont :

- Linear : `V = 2 atan(tan(H/2)/a)`.
- Dewarp : `V = 2 atan((H/2)/a)`.
- Ultra : `V = 4 atan(tan(H/4)/a)`.
- Mega : `V = H/a` ; limite H diagonale `300° / sqrt(1 + 1/a²)`.

Ces relations conservent l'échelle horizontale/verticale au centre. En portrait,
V augmente ; les distorsions peuvent devenir fortes en haut et en bas. Les
projections sont appliquées dans le repère caméra, puis rotation `ypr` avec roll.
Les sorties sont calculées directement depuis l'équirectangulaire vers la taille
cible. Aucun export 16:9 intermédiaire n'est recadré.

Références techniques :
[documentation v360](https://ffmpeg.org/ffmpeg-filters.html#v360) et
[implémentation FFmpeg](https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/vf_v360.c),
fonctions `flat_to_xyz`, `cylindrical_to_xyz`, `stereographic_to_xyz`, `fisheye_to_xyz`.
Les correspondances sont un choix du projet, pas une affirmation d'équivalence
avec les modes Insta360. Les tests portent sur FFmpeg installé, pas uniquement
sur la documentation courante.

## Données et architecture pour la suite

Schéma `musiciens.json` **v2**, application 0.3.0 :

| Responsabilité | Champs / module |
|---|---|
| Direction de caméra | `yaw`, `pitch`, `roll`, `center_uv` dans chaque caméra |
| Position du sujet | `annotations[].point` et `bbox`, associés à une référence |
| Profil de projection | `projection.mode` ; `h_fov` conservé au niveau caméra pour continuité avec B |
| Format / résolution | `output.format`, `output.width`, `output.height` par caméra |
| Encodage | `export_settings` du projet : CRF, preset H.264, débit AAC |
| Historique de cadrage | `saved_framings` par caméra ; n'inclut pas les annotations |
| Contrats de format / FOV | `mapping360/profiles.py` |
| Projection interactive | `mapping360/preview.py`, pur NumPy |
| Persistance / migration | `mapping360/project.py` |
| Rendus et rapports | `mapping360/render.py`, indépendant de Tk |
| Interface | `mapping360/ui_studio.py`, réutilise les opérations de `ui.py` |

La migration v1 se fait sur une copie en mémoire. Elle conserve yaw/pitch/FOV,
annotations, références, source, observations et validations encore applicables.
Elle ajoute Linear, roll=0 et **1280×720** pour retrouver le comportement MP4
historique. Les nouveaux projets démarrent en 1920×1080. Les signatures
d'observation incluent désormais mode, roll et ratio, mais pas la résolution.

À la première sauvegarde d'un fichier v1, `musiciens.v1.original.json` conserve
ses octets, sans être réécrit aux sauvegardes suivantes. La copie tournante
`musiciens.previous.json` et l'écriture atomique sont conservées. Un ancien B
ne peut pas lire v2 : pour revenir à B, utiliser la copie v1.

L'export `views.step1.json` reste disponible pour des caméras Linear, roll=0,
16:9. Les autres cas sont refusés explicitement pour ne pas prétendre exporter
vers A un cadrage qu'il ne peut pas reproduire.

## Exports et CLI

```powershell
# Cinq caméras validées, chacune avec son profil enregistré
.\.venv\Scripts\python.exe step2.py --project "mappings\mapping_..." --export-clips --start 10 --duration 5

# Extrait d'une caméra, même en brouillon, pour validation
.\.venv\Scripts\python.exe step2.py --project "mappings\mapping_..." --export-clips --camera chanteur --format 9:16 --projection Ultra --start 10 --duration 3

# PNG final : --time doit correspondre à une référence existante
.\.venv\Scripts\python.exe step2.py --project "mappings\mapping_..." --export-image --camera groupe --time 10

# Résolution personnalisée au ratio voulu
.\.venv\Scripts\python.exe step2.py --project "mappings\mapping_..." --export-clips --camera groupe --format 2.35:1 --width 940 --height 400 --duration 2
```

Les overrides CLI de cadrage s'appliquent en mémoire ; ils ne réécrivent pas le
projet enregistré. Une modification de ratio/projection invalide sa validation :
utiliser `--camera` pour l'essai, puis valider dans l'interface avant l'export global.
`--source` constitue en revanche une liaison explicite et sauvegarde le projet.

Le rendu vidéo conserve le chemin direct vers la source haute résolution,
la première piste audio si présente et la fréquence source (pas de `-r` imposé).
La durée reste bornée à 30 s. Les rapports incluent commandes, profils, tailles,
FFprobe, durées et état final. Le snapshot contient la source vérifiée avec son
empreinte partielle. `output_size` reste renseigné si toutes les caméras ont la
même taille ; `output_sizes` décrit chaque caméra.

Les contrôles vérifient dimensions, durée demandée, présence audio attendue,
débuts et durées audio/vidéo avec une tolérance adaptée à la cadence. Ce ne sont
pas des preuves de synchronisation musicale à l'échantillon près. Les tests
synthétiques comparent aussi une image MP4 décodée à l'aperçu NumPy. Les originaux
restent en lecture seule, les exports portent des noms de dossiers uniques.

## Tests et performances

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m mapping360.benchmark --output "mappings\benchmark_b1.json"
```

Le benchmark effectue un échauffement puis sept mesures par mode/format et taille,
sur un panorama synthétique 1920×960. Il mesure projection + échantillonnage CPU,
hors décodage, redimensionnement d'affichage et Tk. Les mesures sont disponibles
dans `validation_b1/benchmark.json` ; le résumé et les limites sont dans
`validation_b1/RESULTATS.md`.

Les aperçus sont calculés dans un worker distinct de Tk ; les demandes en attente
sont remplacées par la plus récente. Aucun sous-processus FFmpeg n'est lancé pour
tourner ou zoomer. La grille normalisée est mise en cache (quatre tailles maximum).
Les callbacks Tk sont annulés à la fermeture. Les opérations FFmpeg longues
restent sans bouton d'annulation, comme B.

## Validation utilisateur avant fusion

1. Ouvrir un projet B existant, vérifier le même cadre Linear/16:9 avant sauvegarde.
2. Tester le glisser, la molette, la zone et le panneau avancé (dont roll).
3. Passer aux six formats et aux quatre modes ; vérifier notamment un corps entier
   en portrait, les bords du groupe et les avertissements de zone hors cadre.
4. Mémoriser deux cadrages, les restaurer, fermer et rouvrir ; vérifier les valeurs.
5. Lier le rush, exporter un PNG et un MP4 de trois secondes en 9:16 puis en 2.35:1.
6. Contrôler visuellement cadre, distorsion, netteté et synchronisation perceptible.
7. Refaire les observations et valider les cinq caméras, puis exporter les cinq MP4.

La validation esthétique et audio sur le concert reste humaine. Pas de garantie
HDR/tonemapping, pas de mouvement interpolé, pas de suivi, pas de timeline Resolve
ni de serveur MCP à cette étape. **Aucune fusion sur main sans validation.**
