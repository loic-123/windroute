# WindRoute — Plan de développement pour Claude Code

## Vision du projet

Application Python CLI/web qui, à partir d'une séance planifiée sur intervals.icu, de la localisation du cycliste et de la météo du moment, génère automatiquement un tracé GPX optimisé. L'optimisation tient compte de la physique réelle du cycliste (puissance → vitesse → timing des blocs), du vent, des dénivelés nécessaires pour les intervalles, de l'ensoleillement, et de la popularité des routes via la heatmap Strava.

---

## Règles fondamentales de conception

Ces règles priment sur toute autre logique et ne sont jamais contournées :

1. **Les seules durées figées sont celles des blocs d'effort de la séance.** La durée d'échauffement et la durée de retour/récupération sont élastiques, avec les limites suivantes :
   - Si la durée initiale du segment est **< 1 heure** : allongement maximum de **+40%** de la durée initiale
   - Si la durée initiale du segment est **≥ 1 heure** : allongement maximum de **+20%** de la durée initiale
   - Si la montée idéale ne peut pas être atteinte dans ces limites, sélectionner la meilleure montée atteignable dans le budget, et logger un avertissement expliquant le compromis.

2. **Pour les montées, toujours privilégier une montée trop longue plutôt que trop courte.** Si la durée estimée du bloc sur la montée est inférieure à la durée cible, le cycliste s'arrête en haut avant la fin — c'est acceptable. L'inverse (montée trop courte, bloc interrompu avant l'effort complet) est inacceptable.

3. **La logique vent s'applique uniquement à la structure générale aller/retour du parcours, jamais aux segments d'intervalles.** Pendant les blocs d'effort (intervalles, côtes), le vent est ignoré comme critère d'optimisation : ce qui compte, c'est la qualité de la côte ou du segment. Concrètement :
   - **Aller (échauffement → début des intervalles)** : vent de face préféré. Bearing cible = `wind_direction + 180° ± 45°`.
   - **Retour (fin des intervalles → domicile)** : vent de dos préféré.
   - **Segments d'intervalles eux-mêmes** : contrainte vent totalement ignorée. Si les intervalles sont sur une boucle (mode `repeat` aller-retour sur une côte), le vent dans un sens annule l'autre — ne pas tenter d'optimiser.
   - La contrainte vent est toujours souple et ne bloque jamais la génération de route.

---

## Architecture des fichiers

```
windroute/
├── main.py                  # Point d'entrée CLI
├── config.py                # Clés API, constantes physiques, options
├── api/
│   ├── intervals_client.py  # Wrapper API intervals.icu
│   ├── openmeteo_client.py  # Météo + vent + ensoleillement
│   └── strava_heatmap.py    # Téléchargement tiles heatmap Strava
├── models/
│   ├── athlete.py           # Profil athlète (poids, CdA, FTP)
│   ├── workout.py           # Structure séance parsée
│   ├── weather.py           # Données météo structurées
│   └── route.py             # Objet route avec scoring multi-critères
├── engine/
│   ├── physics.py           # Équations puissance ↔ vitesse
│   ├── timing.py            # Placement temporel des blocs sur le tracé
│   ├── climb_finder.py      # Détection de côtes OSM correspondant aux intervalles
│   ├── wind_optimizer.py    # Logique d'orientation selon vent (aller/retour)
│   ├── sunshine_scorer.py   # Scoring ensoleillement
│   ├── heatmap_scorer.py    # Scoring popularité routes
│   └── route_generator.py   # Génération boucle + export GPX
├── output/
│   ├── gpx_exporter.py
│   └── map_preview.py       # Carte HTML interactive Folium
└── requirements.txt
```

---

## Module 1 — `api/intervals_client.py`

### Ce qu'il doit récupérer

Connexion à l'API intervals.icu via OAuth ou API key (les deux supportés). Pour la séance du jour ou la prochaine séance planifiée de type cycling :

**1. Profil athlète (`GET /api/v1/athlete/{id}`)** :
- Poids du cycliste (kg)
- FTP actuel (W) — utilisé pour résoudre les puissances exprimées en % FTP

**2. Séance planifiée (`GET /api/v1/athlete/{id}/events`)** :
- Filtrer par date = aujourd'hui ou prochaine séance de type cycling
- Récupérer la structure complète du workout au format intervals.icu (JSON)

**3. Parser la structure de la séance en blocs**

La séance est décomposée en une liste ordonnée de blocs :

```json
{
  "type": "warmup" | "interval" | "recovery" | "cooldown",
  "duration_seconds": 300,
  "power_watts": 280,
  "power_percent_ftp": 95.0,
  "repeat_count": 1,
  "cadence_target": null
}
```

**Point critique — parser récursif** : les séances intervals.icu peuvent contenir des groupes de répétitions imbriqués (ex : 5× [5min @ 105% + 3min @ 50%]). Le parser doit déplier récursivement toutes les répétitions en une liste **plate et séquentielle** de blocs individuels. Chaque bloc est identifié par son index dans cette liste.

**Extraction de la puissance** :
- Si la séance est définie en `target_watts` → utiliser directement
- Si en `% FTP` → multiplier par FTP athlète
- Si en RPE ou HR uniquement → mapper vers les zones de puissance standard (documenter la limitation, utiliser une estimation conservative)

La puissance extraite pour chaque bloc d'intervalle est la valeur centrale utilisée dans tous les calculs physiques en aval.

---

## Module 2 — `engine/physics.py`

### Modèle physique complet puissance → vitesse

Fonction centrale :

```
power_to_speed(power_w, grade_percent, wind_component_ms,
               cda, weight_kg, bike_weight_kg, temp_c, altitude_m)
→ speed_ms: float
```

**Équation fondamentale** :

```
P_total = P_aero + P_roulement + P_gravité
```

**P_aero** (résistance aérodynamique) :
```
P_aero = 0.5 × ρ_air × CdA × (v_cycliste + v_vent_face)² × v_cycliste
```
- `ρ_air` = densité de l'air calculée dynamiquement via la formule barométrique internationale (fonction de température et altitude). Valeur de référence : 1.225 kg/m³ à 15°C, niveau de la mer.
- `CdA` = coefficient aérodynamique × surface frontale (configurable selon position)
- `v_vent_face` = composante du vent dans l'axe de déplacement. **Calcul** : pour chaque segment de route, calculer le bearing (cap géographique en degrés 0-360°), calculer `angle_relatif = bearing_route - direction_vent`, puis `v_vent_face = v_vent × cos(angle_relatif)`. Positif = vent de face (résistance), négatif = vent de dos (assistance).

**P_roulement** :
```
P_roulement = Crr × (m_cycliste + m_vélo) × g × cos(α) × v_cycliste
```
- `Crr` configurable (0.004 route sèche, 0.006 route mouillée)
- `α` = angle de pente en radians

**P_gravité** :
```
P_gravité = (m_cycliste + m_vélo) × g × sin(α) × v_cycliste
```

**Résolution numérique** : résoudre `P_total(v) = P_target` avec `scipy.optimize.brentq` sur [0.5, 25] m/s. Si brentq échoue (ex : puissance physiquement insuffisante pour avancer), retourner une vitesse plancher de 1.0 m/s avec un warning loggé.

**Valeurs CdA par défaut selon position** :
| Position | CdA (m²) |
|---|---|
| Mains sur le dessus | 0.40 |
| Sur les cocottes | 0.36 |
| En danseuse | 0.44 |
| Descente guidon bas | 0.28 |
| CLM / tri | 0.24 |

---

## Module 3 — `engine/timing.py`

### Placement temporel des blocs sur le tracé

**Entrée** : liste plate des blocs + vitesse estimée par bloc (calculée via physics.py) + graphe OSMnx.

**Sortie** : pour chaque bloc, la distance cumulée depuis le départ et la position lat/lon approximative de son début et de sa fin.

**Algorithme** :
1. Parcourir les arêtes OSMnx séquentiellement depuis le nœud de départ
2. Pour chaque bloc, accumuler `distance += vitesse_bloc × dt` jusqu'à `duration_seconds`
3. Interpoler linéairement entre les nœuds OSM pour trouver le point exact de changement de bloc
4. Stocker `(lat, lon, elapsed_distance_m, elapsed_time_s)` pour chaque transition bloc

Ce module permet à `climb_finder.py` de savoir exactement à quelle distance depuis le domicile les intervalles doivent commencer, et donc où placer les montées dans le tracé.

**Règle d'élasticité avec limites** : si la montée idéale est plus éloignée que la distance couverte par l'échauffement initial, l'échauffement peut s'allonger dans les limites suivantes :

```
durée_initiale < 3600s  →  allongement max = durée_initiale × 0.40
durée_initiale ≥ 3600s  →  allongement max = durée_initiale × 0.20
```

Si la montée idéale reste hors de portée même avec cet allongement, sélectionner la meilleure montée atteignable dans le budget élastique et logguer un warning Rich expliquant le compromis (ex : "Montée optimale à 28 km, budget échauffement max = 21 km — montée alternative sélectionnée à 19 km"). Même logique pour le retour.

---

## Module 4 — `api/openmeteo_client.py`

### Données météo (Open-Meteo, gratuit, sans clé API)

Récupérer à la position du cycliste et à l'heure de départ estimée :

| Variable | Usage |
|---|---|
| `windspeed_10m` (km/h) | Calcul physique + scoring vent |
| `winddirection_10m` (degrés) | Orientation du tracé |
| `temperature_2m` (°C) | Calcul densité air ρ |
| `cloudcover` (%) | Scoring ensoleillement |
| `precipitation` (mm) | Alerte conditions dégradées |
| `surface_pressure` (hPa) | Calcul ρ_air précis |

Récupérer les données **horaires sur les 6 prochaines heures** pour anticiper les changements de vent en cours de sortie. Si la direction du vent tourne de plus de 45° pendant la fenêtre de sortie, ajouter un avertissement dans le résumé final.

---

## Module 5 — `engine/wind_optimizer.py`

### Logique de vent : principe aller/retour uniquement

**Option activable** : `USE_WIND_OPTIMIZATION: bool`

**Périmètre strict** : la logique vent ne s'applique qu'aux segments d'échauffement (aller) et de retour/cooldown. Elle est **totalement ignorée** pendant les blocs d'intervalles et les côtes.

**Principe** :
- **Aller (échauffement)** : vent de face. Direction de départ cible = `wind_direction + 180° ± 45°`. Le cycliste repart face au vent quand ses jambes sont fraîches.
- **Retour (cooldown)** : vent de dos. La route de retour est orientée dans le secteur `wind_direction ± 45°`.
- **Blocs d'intervalles** : aucune contrainte vent. Si les intervalles sont réalisés en mode `repeat` sur une côte (montée + descente + remontée), le vent alterne de toute façon — aucune optimisation n'est possible ni souhaitable. Le moteur de routage ne tient pas compte du vent pour placer ou orienter les segments d'intervalles.

**Implémentation** : le bearing préféré est calculé une seule fois et passé uniquement au `route_generator` pour les phases d'échauffement et de retour. Les appels de routage pour les phases d'intervalles reçoivent `wind_bearing=None` (contrainte désactivée).

Si aucune route cyclable n'existe dans le secteur préféré (bearing ± 45°), élargir progressivement par tranches de 15° jusqu'à ± 90° maximum. Au-delà, ignorer la contrainte vent pour ce segment et logger un warning.

---

## Module 6 — `engine/climb_finder.py`

### Détection et sélection des côtes pour les intervalles

**Entrée** :
- Graphe OSMnx de la zone avec données d'élévation
- Pour chaque bloc d'intervalle : `duration_seconds`, `power_watts`
- Profil athlète : CdA, poids, poids vélo
- Météo : vent sur la zone

**Étape 1 : Enrichissement élévation**

Pour chaque nœud OSMnx sans altitude, interroger l'API Open-Elevation (gratuit, open source) ou le package `elevation` (SRTM 30m). Enrichir les nœuds avec `elevation_m`. Calculer pour chaque arête le `grade_percent = Δelevation / length × 100`.

**Étape 2 : Détection des montées continues**

Fusionner les arêtes consécutives avec `grade > MIN_CLIMB_GRADE_PERCENT` (défaut : 3%) en segments de montée continus. Pour chaque montée candidate :

```python
{
  "length_m": float,
  "avg_grade_percent": float,
  "max_grade_percent": float,
  "elevation_gain_m": float,
  "grade_stddev": float,   # régularité de la pente
  "start_node": int,
  "end_node": int,
  "road_type": str         # tag OSM highway=*
}
```

**Étape 3 : Matching montée ↔ bloc d'intervalle**

Pour chaque montée candidate, calculer la vitesse estimée en montée via `physics.power_to_speed(power_bloc, avg_grade, wind_on_climb, ...)`.

Durée estimée = `length_m / speed_ms`.

**Règle fondamentale de sélection** :
> Une montée est acceptable si `durée_estimée >= durée_bloc × 0.80`.
> Une montée est préférée si `durée_estimée >= durée_bloc × 1.00`.
> **Il n'y a pas de seuil supérieur.** Une montée de 3× la durée du bloc est préférable à une montée légèrement trop courte.

En pratique, si plusieurs montées dépassent la durée cible, scorer par `grade_stddev` (faible = meilleur, pente régulière), type de route, et score heatmap.

**Étape 4 : Logique multi-intervalles**

Si la séance comporte N répétitions du même bloc d'intervalle :

- **Mode `loop`** : trouver N montées distinctes dans la zone, les relier séquentiellement dans le tracé. Adapté si N ≤ 3.
- **Mode `repeat`** : une seule montée (la meilleure), le cycliste monte → descend → remonte N fois. La descente est modélisée en puissance `recovery` avec vitesse estimée en descente. Adapté si N ≥ 3 et montée > 2 km.
- **Mode `auto`** (défaut) : choisir `repeat` si une montée unique ≥ 2 km est disponible et N ≥ 3, sinon `loop`.

La descente entre deux répétitions en mode `repeat` n'est pas contrainte en durée : elle dure le temps de descendre. Le timing et la distance totale sont recalculés en conséquence.

**Étape 5 : Score de qualité d'une montée**

```
score = w1 × (1 - grade_stddev / grade_stddev_max)   # régularité
      + w2 × road_type_score                           # qualité route OSM
      + w3 × heatmap_score                             # popularité Strava
```
Avec `road_type_score` : `cycleway=1.0`, `secondary=0.85`, `tertiary=0.80`, `primary=0.60`, `trunk=0.30`.

---

## Module 7 — `engine/route_generator.py`

### Génération du tracé complet

**Étape 1 — Calcul du rayon de recherche**

```
distance_totale_estimée = sum(speed_bloc_i × duration_bloc_i)
rayon_km = distance_totale_estimée / (2 × π) × facteur_boucle
```
Le facteur de boucle vaut 1.2 par défaut (une boucle n'est jamais un cercle parfait).

**Étape 2 — Chargement du graphe OSMnx**

```python
G = osmnx.graph_from_point(
    (lat, lon),
    dist=rayon_km * 1000,
    network_type='bike',
    retain_all=False
)
```
Appliquer le filtre `ROAD_TYPE_FILTER`. Enrichir avec élévations.

**Étape 3 — Construction du tracé**

1. Nœud de départ = position du cycliste (nœud OSMnx le plus proche)
2. Calculer la distance nécessaire pour l'échauffement = `speed_warmup × duration_warmup_initial`. Cette distance est le rayon minimum jusqu'au pied de la première montée.
3. Trouver le chemin OSMnx du domicile vers le pied de la première montée en respectant le bearing préféré (contrainte souple du `wind_optimizer`). Utiliser `osmnx.shortest_path` avec poids custom combinant distance + pénalité de déviation du bearing préféré.
4. Enchaîner les montées sélectionnées (et descentes si mode `repeat`).
5. Calculer le chemin de retour depuis la fin du dernier bloc vers le domicile. Le retour doit être dans le secteur vent favorable (deuxième moitié du parcours). Si le retour est plus long que la durée de cooldown initiale, allonger silencieusement le cooldown — ne jamais tronquer.
6. Assembler en liste ordonnée de nœuds OSMnx.

**Étape 4 — Vérification de cohérence**

Après assemblage, vérifier :
- Tous les blocs d'intervalles tombent sur des montées sélectionnées (tolérance : ±500 m de décalage acceptable)
- La distance totale est cohérente avec la somme des distances estimées par bloc (alerte si écart > 15%)
- Pas de segment avec `grade > 20%` sur les portions d'échauffement ou de retour

**Étape 5 — Génération de 3 tracés candidats**

Générer 3 variantes avec des paramètres légèrement différents :
- **Option A** : optimisation maximale sur le vent (bearing le plus strict)
- **Option B** : optimisation maximale sur la qualité des côtes (meilleures montées disponibles, même si bearing moins bon)
- **Option C** : compromis pondéré selon les poids configurés

Scorer chaque tracé selon le système de scoring global.

**Format interne Route** :

```python
@dataclass
class Route:
    nodes: List[int]
    coords: List[Tuple[float, float, float]]  # (lat, lon, ele)
    segments: List[RouteSegment]              # chaque segment avec bloc associé
    total_distance_km: float
    total_elevation_m: float
    wind_score: float        # % du temps avec vent favorable
    climb_score: float       # % des intervalles sur bonnes côtes
    sunshine_score: float
    heatmap_score: float
    overall_score: float
    warmup_duration_actual_s: int    # peut différer de l'initial
    cooldown_duration_actual_s: int  # peut différer de l'initial
```

---

## Module 8 — `engine/sunshine_scorer.py`

**Option activable** : `USE_SUNSHINE_OPTIMIZATION: bool`

Pour chaque segment du tracé et le timing estimé du cycliste sur ce segment, récupérer la valeur `cloudcover` Open-Meteo à l'heure correspondante. Score de sunshine = proportion du temps de trajet avec `cloudcover < 40%`.

En cas de conflit vent vs ensoleillement (le secteur ensoleillé est dans le mauvais sens du vent), le paramètre `SUNSHINE_WEIGHT` (défaut : 0.15) assure que l'ensoleillement ne surpasse jamais la logique de vent ou de côtes.

---

## Module 9 — `api/strava_heatmap.py`

**Option activable** : `USE_STRAVA_HEATMAP: bool`

La heatmap globale Strava est disponible sous forme de tiles PNG au format XYZ/slippy map :
```
https://heatmap-external-a.strava.com/tiles-auth/cycling/bluered/{z}/{x}/{y}.png
```
Cette URL nécessite un cookie d'authentification Strava valide (`_strava4_session`).

**Implémentation** :
1. Authentification OAuth2 Strava avec scope `read` — récupérer l'access_token
2. Construire les URLs de tiles pour la bounding box du tracé au zoom level 14
3. Télécharger les tiles PNG (avec cache local en `.cache/heatmap/`)
4. Décoder l'intensité des pixels (canal rouge = intensité trafic cycliste)
5. Pour chaque arête du graphe OSMnx, interpoler les pixels correspondants et calculer un score moyen normalisé [0, 1]

**Fallback** : si les tiles retournent 403 ou si le token est absent, scorer toutes les arêtes à 0.5 (neutre) et logger un warning clair. L'application fonctionne sans la heatmap.

---

## Module 10 — `output/gpx_exporter.py`

Exporter le tracé sélectionné en GPX valide, compatible Garmin et Wahoo.

**Structure GPX** :
- Métadonnées : nom (ex : `"Intervalles Seuil — Vent NE 18km/h — 12 mars"`), auteur, date, description du parcours
- `<trkpt lat lon>` avec `<ele>` pour chaque point du tracé
- `<extensions>` Garmin : inclure la puissance cible pour chaque segment (certains head units peuvent l'afficher)
- Waypoints marqueurs pour chaque début et fin de bloc d'intervalle (avec nom : `"INT_1_START"`, `"INT_1_END"`, etc.)

**Fichier JSON résumé** généré en parallèle :

```json
{
  "workout_name": "5×5min @ 105%FTP",
  "generated_at": "2025-03-29T08:00:00",
  "total_distance_km": 72.4,
  "total_elevation_m": 890,
  "warmup_distance_km": 22.1,
  "cooldown_distance_km": 18.3,
  "wind_direction_deg": 45,
  "wind_direction_label": "NE",
  "wind_speed_kmh": 18,
  "tailwind_percent": 62,
  "climbs": [
    {
      "id": "climb_1",
      "length_km": 4.2,
      "avg_grade_percent": 5.1,
      "elevation_gain_m": 214,
      "matched_interval": "INT_1 à INT_5 (mode repeat)",
      "estimated_duration_s": 340
    }
  ],
  "sunshine_score": 0.78,
  "heatmap_score": 0.65,
  "overall_score": 0.81,
  "warnings": ["Vent tourne de 40° prévu à 10h30"]
}
```

---

## Module 11 — `output/map_preview.py`

Carte HTML interactive via **Folium** :

- Tracé coloré par type de bloc :
  - Échauffement → vert
  - Blocs d'intervalles → rouge
  - Récupérations inter-blocs → orange
  - Cooldown/retour → gris
- Flèches vent animées superposées sur le tracé (flèche indiquant la direction, couleur selon tailwind/headwind)
- Marqueurs au début et à la fin de chaque bloc d'intervalle avec popup (puissance cible, durée, vitesse estimée sur ce segment)
- Marqueurs de début/fin de chaque montée avec popup (longueur, pente moyenne, dénivelé)
- Légende des couleurs
- Overlay heatmap Strava semi-transparent si activé (tiles chargés dans la carte Folium)
- Indication ensoleillement si activé (segments colorés par intensité solaire)

---

## `config.py` — Tous les paramètres configurables

```python
# ── Credentials ──────────────────────────────────────────────────
INTERVALS_ICU_API_KEY = ""
INTERVALS_ICU_ATHLETE_ID = ""
STRAVA_ACCESS_TOKEN = ""       # optionnel

# ── Profil vélo ───────────────────────────────────────────────────
CDA = 0.36                     # m², position cocottes par défaut
BIKE_WEIGHT_KG = 8.0
CRR = 0.004                    # coefficient roulement (route sèche)

# ── Options d'optimisation ────────────────────────────────────────
USE_WIND_OPTIMIZATION = True
USE_SUNSHINE_OPTIMIZATION = True
USE_STRAVA_HEATMAP = False     # nécessite token Strava

# ── Paramètres de route ───────────────────────────────────────────
ROAD_TYPE_FILTER = "road"      # "road" | "gravel" | "mixed"
CLIMB_MODE = "auto"            # "loop" | "repeat" | "auto"
MAX_ROUTE_RADIUS_KM = 50
MIN_CLIMB_GRADE_PERCENT = 3.0

# ── Logique montées ───────────────────────────────────────────────
# Pas de seuil supérieur sur la durée de la montée.
# Une montée trop longue est toujours préférée à une trop courte.
CLIMB_MIN_DURATION_RATIO = 0.80   # durée_montée >= 80% durée_bloc
REPEAT_MODE_MIN_CLIMB_KM = 2.0    # longueur min pour mode repeat
REPEAT_MODE_MIN_INTERVALS = 3     # nb min d'intervalles pour mode repeat

# ── Logique vent ──────────────────────────────────────────────────
# Aller face au vent, retour vent de dos.
# Contrainte souple — s'élargit progressivement si pas de route.
WIND_BEARING_TOLERANCE_DEG = 45   # tolérance initiale
WIND_BEARING_MAX_TOLERANCE_DEG = 90  # tolérance maximale

# ── Durées élastiques (échauffement et retour uniquement) ─────────
# Seules les durées des blocs d'intervalles sont figées.
# L'échauffement et le retour peuvent s'allonger dans ces limites :
#   durée initiale < 1h  →  max +40% de la durée initiale
#   durée initiale ≥ 1h  →  max +20% de la durée initiale
WARMUP_MIN_DURATION_S = 600        # 10 min minimum absolu
COOLDOWN_MIN_DURATION_S = 300      # 5 min minimum absolu
WARMUP_ELASTIC_RATIO_SHORT = 0.40  # +40% si durée initiale < 3600s
WARMUP_ELASTIC_RATIO_LONG = 0.20   # +20% si durée initiale >= 3600s
# Même ratios appliqués au cooldown/retour

# ── Scoring (poids, somme = 1.0) ──────────────────────────────────
WIND_WEIGHT = 0.35
CLIMB_WEIGHT = 0.40
SUNSHINE_WEIGHT = 0.15
HEATMAP_WEIGHT = 0.10
```

---

## `main.py` — Flux d'exécution complet

```
 1. Charger config + arguments CLI (--lat, --lon, --date, --dry-run)
 2. Récupérer localisation du cycliste (paramètre CLI ou géoloc IP en fallback)
 3. [intervals.icu] Récupérer profil athlète → FTP, poids
 4. [intervals.icu] Récupérer séance du jour → parser blocs (récursif)
 5. Calculer puissances absolues (W) pour chaque bloc
 6. [Open-Meteo] Récupérer météo horaire → vent, température, cloudcover
 7. Alerter si précipitations ou vent > 50 km/h
 8. [physics.py] Calculer vitesse estimée par bloc (terrain plat, vent moyen)
 9. Estimer distance totale et durée totale de la sortie
10. [timing.py] Calculer timing séquentiel des blocs
11. [OSMnx] Charger graphe cycliste dans le rayon calculé (avec cache)
12. [Open-Elevation/SRTM] Enrichir les nœuds sans altitude
13. [strava_heatmap.py] Charger heatmap (si activé)
14. [climb_finder.py] Détecter montées candidates → matcher ↔ blocs d'intervalles
15. [wind_optimizer.py] Calculer bearing préféré (aller face au vent)
16. [route_generator.py] Générer 3 tracés candidats (A, B, C)
17. Scorer les 3 tracés
18. Afficher résumé CLI des 3 options avec scores détaillés (via Rich)
19. Utilisateur sélectionne A/B/C (ou auto-sélection si --auto)
20. [gpx_exporter.py] Exporter GPX + JSON résumé
21. [map_preview.py] Générer carte HTML
22. Afficher chemins des fichiers générés
```

---

## Dépendances (`requirements.txt`)

```
osmnx>=1.9
networkx>=3.0
gpxpy>=1.6
scipy>=1.11
numpy>=1.26
requests>=2.31
folium>=0.15
elevation>=1.1        # données SRTM 30m
click>=8.1            # interface CLI
rich>=13.0            # output CLI coloré et structuré
python-dotenv>=1.0    # gestion des clés API
```

---

## Points de vigilance pour Claude Code

### 1. Données d'élévation OSMnx
Les nœuds OSM n'ont pas systématiquement d'altitude. Utiliser en priorité l'API `open-elevation` (open source, gratuite) et en fallback le package `elevation` (SRTM 30m). Prévoir les deux et documenter le choix dans le README.

### 2. Résolution numérique `brentq`
Peut échouer si la puissance est physiquement insuffisante pour avancer contre un fort vent de face sur pente positive. Gérer l'exception avec `try/except ValueError` et retourner une vitesse plancher de 1.0 m/s avec un warning loggé dans Rich.

### 3. Séances sans intervalles
Si la séance du jour est purement endurance (pas de bloc d'intervalle ou bloc unique), désactiver le `climb_finder` et générer une boucle classique wind-optimized, sans contrainte de montée.

### 4. Strava heatmap tiles auth
Les tiles nécessitent un cookie de session web ou un access_token OAuth. Implémenter avec `try/except` et fallback propre (score 0.5 neutre) si les tiles retournent 403. Logguer clairement l'échec d'authentification.

### 5. Performance OSMnx sur grands rayons
Pour un rayon de 40-50 km, le graphe peut dépasser 100 000 nœuds. Implémenter un cache local du graphe en `.cache/osm/` (sérialisation pickle) avec invalidation par bounding box. Afficher une barre de progression Rich lors du chargement initial.

### 6. Cohérence des durées élastiques bornées
Le `route_generator` ne doit **jamais** retourner un tracé où les blocs d'intervalles sont tronqués. Si le budget élastique de l'échauffement est insuffisant pour atteindre la montée idéale, sélectionner la meilleure montée dans le budget disponible — ne jamais dépasser les ratios `WARMUP_ELASTIC_RATIO_*`. Documenter clairement dans le JSON résumé : `warmup_initial_s`, `warmup_actual_s`, `warmup_max_allowed_s`, et le cas échéant `climb_downgraded: true` avec la raison.

### 7. Mode sans connexion intervals.icu
Prévoir un mode `--manual` où l'utilisateur passe directement les paramètres de séance en arguments CLI (`--intervals "5x300w:300s/150w:180s"`) pour permettre l'utilisation sans compte intervals.icu.
