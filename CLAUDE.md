# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language
Toujours répondre en français.

## Project Overview

Application de monitoring PyQt6 pour le VPS OVH Ubuntu 24.04 qui héberge l'API GMAPP. Tableau de bord temps réel avec rafraîchissement toutes les 30s.

**Deux composants :**
- `src/monitor.py` — client PyQt6 autonome (tout en un seul fichier, ~1400 lignes)
- `c:\GMP_AUTOMATION\Builder v2 - test\main_vps.py` — serveur FastAPI sur le VPS, endpoints `/monitor/*`

## Commandes

```bash
# Lancer en mode dev
cd "OVH Monitor/src"
python monitor.py

# Vérifier la syntaxe
python -m py_compile src/monitor.py

# Installer les dépendances
pip install PyQt6

# Builder l'exe (depuis la racine du projet)
# Fermer l'exe avant de rebuilder (il se verrouille)
python -c "
import subprocess, os, shutil
root = r'c:\GMP_AUTOMATION\OVH Monitor'
icon = root + r'\assets\monitor.ico'
src  = root + r'\src\monitor.py'
out  = root + r'\dist'
for d in [root+r'\build', root+r'\GMP_Monitor.spec']:
    if os.path.exists(d):
        if os.path.isdir(d): shutil.rmtree(d)
        else: os.remove(d)
r = subprocess.run(['pyinstaller','--onefile','--windowed',f'--icon={icon}','--name=GMP_Monitor',f'--add-data={icon};assets',f'--distpath={out}',f'--workpath={root}/build',f'--specpath={root}','--noconfirm',src], capture_output=True, text=True)
print('OK' if r.returncode==0 else r.stderr[-300:])
shutil.rmtree(root+r'\build', ignore_errors=True)
"
```

**Distribution :** copier `dist/GMP_Monitor.exe` + `dist/monitor_config.json` ensemble.

## Déploiement serveur

```python
# Déployer main_vps.py sur le VPS (via paramiko, port SSH 2222)
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('51.83.74.243', port=2222, username='ubuntu', password='...')
# SCP main_vps.py → /home/ubuntu/gmapp_api/main.py
# sudo systemctl restart gmapp_api
```

## Connexion OVH

- **URL prod** : `https://bdc.gersmotopieces.com` (via Caddy HTTPS, ports 80/443 ouverts)
- **Clé API** : `gmp_fGPsjgfjk465fdf48ghHQd5Gsq592GAqpdGe4`
- **Config locale** : `monitor_config.json` à la racine du projet (non commité)
- Port 8000 direct : bloqué par UFW — passer obligatoirement par Caddy

## Architecture client (`src/monitor.py`)

### Flux de données
```
QTimer (1s tick) → _refresh() → Worker(thread) → _fetch_all()
                                                      ↓ HTTP (urllib)
                                              _on_data(dict) → update UI
                                              _on_error(str) → status bar
```

`_fetch_all()` appelle séquentiellement : `/monitor/system`, `/monitor/db`, `/monitor/access_log`, `/version`, `/monitor/traffic`. Si **un seul** échoue, tout le refresh échoue → toutes les valeurs restent à `—`.

### Hiérarchie des widgets (classes PyQt6)

| Classe | Rôle |
|--------|------|
| `MonitorApp(QMainWindow)` | Fenêtre principale, grille 4 colonnes |
| `TitleBar` | Barre titre custom avec status dot, boutons pin/TV/settings |
| `_make_status_card()` | Barre horizontale 42px : uptime srv / API GMAPP / API BDC / charge / latence / version |
| `MetricCard` | Carte avec jauge circulaire + sparkline (CPU/RAM — non affichés dans la grille, conservés pour calculs internes) |
| `MetricsHistoryCard` + `_MetricsCanvas` | Graphique historique CPU%+RAM% (aire double, QPainter) |
| `TrafficHistoryCard` + `_TrafficCanvas` | Graphique historique réseau entrant/sortant (QPainter) |
| `DiskCard` | Partitions avec barres de progression (non affiché dans la grille actuelle) |
| `NetworkCard` | TX/RX temps réel avec sparklines (non affiché, conservé pour calculs) |
| `ApiTrafficCard` | Répartition des appels par endpoint (non affiché) |
| `Worker(QThread)` | Exécute une fonction dans un thread, émet `result` ou `error` |

### Layout de la grille (4 colonnes)
```
Row 0 (stretch=0) : Statut serveur — barre horizontale pleine largeur
Row 1 (stretch=2) : MetricsHistoryCard (2 cols) | TrafficHistoryCard (2 cols)
Row 2 (stretch=3) : Journal d'accès API — dépliant (bouton ▲/▼)
```

### Journal d'accès — points importants
- **Filtre à l'ingestion** (`_LOG_SKIP`) : `/monitor/*`, `/openapi.json`, `/favicon` sont ignorés avant d'entrer dans le deque. `/version` est **visible** (endpoint métier — check MàJ clients).
- Deque `_log_history` : maxlen=5000, uniquement des appels réels (pas de polling monitor)
- Auto-chargement au démarrage : `QTimer.singleShot(1500, self._load_history)` charge le fichier JSONL serveur
- Journal dépliant : `_toggle_journal()` modifie `_log_body.setVisible()` + `_grid_layout.setRowStretch()`

### Graphiques historiques
- Données : endpoint `/monitor/traffic?hours=N` — retourne des samples JSON avec `ts`, `tx_bps`, `rx_bps`, `cpu`, `ram`
- Sampler serveur : toutes les 60s dans `traffic_log.jsonl`, rétention 7 jours
- Les deux cartes (MetricsHistory + TrafficHistory) utilisent les **mêmes samples**
- Downsample automatique si `len(data) > widget_width`
- Sélecteur de plage (6h/24h/48h/7j) sur TrafficHistoryCard → déclenche `_refresh()`

### Gestion mode frozen (PyInstaller)
```python
_frozen    = getattr(sys, "frozen", False)
BASE_DIR   = Path(sys.executable).parent if _frozen else Path(__file__).resolve().parent.parent
ASSETS_DIR = (Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "assets") if _frozen else (BASE_DIR / "assets")
CFG_FILE   = BASE_DIR / "monitor_config.json"
```
En mode frozen, `monitor_config.json` doit être à côté de l'exe.

## Architecture serveur (`main_vps.py`)

### Endpoints `/monitor/*`
| Endpoint | Description |
|----------|-------------|
| `GET /monitor/ping` | Health check public (sans auth) |
| `GET /monitor/system` | CPU, RAM, disques, uptime serveur, uptime API BDC (port 8001 via psutil), réseau |
| `GET /monitor/db` | Counts + tailles tables PostgreSQL |
| `GET /monitor/access_log?n=200&history=1` | Log mémoire (500 max) ou fichier JSONL complet |
| `GET /monitor/traffic?hours=24` | Historique trafic+métriques depuis `traffic_log.jsonl` |

### Logging persistant
- **`access_log.jsonl`** : chaque requête HTTP loggée via `_AccessLogMiddleware` (BaseHTTPMiddleware)
- **`traffic_log.jsonl`** : samples CPU/RAM/réseau toutes les 60s via `_traffic_sampler()` (asyncio task)
- Rétention : 7 jours glissants, nettoyage automatique via `_trim_jsonl()`

### Lifecycle FastAPI
```python
@asynccontextmanager
async def lifespan(app_):
    task = asyncio.create_task(_traffic_sampler())
    yield
    task.cancel()
```
Le sampler démarre au lancement du service et s'arrête proprement à l'extinction. **Le premier sample arrive 60s après le démarrage du service.**

### Infrastructure VPS
- Service systemd : `gmapp_api` → uvicorn sur `0.0.0.0:8000`
- Service systemd : `gmapp_bdc` → uvicorn sur `127.0.0.1:8001`
- Caddy reverse proxy : `bdc.gersmotopieces.com` → port 8000 (tout sauf routes BDC spécifiques)
- PostgreSQL : base `gmapp_db`, user `postgres`
- Firewall UFW : 2222 (SSH), 80, 443 seulement — port 8000 bloqué de l'extérieur

## Palette de couleurs

```python
C = {
    "bg": "#111214", "surface": "#1a1c20", "surface2": "#22252b",
    "border": "#2e3138", "border2": "#3a3f4a",
    "red": "#e8001d", "red_dim": "#6b0010",
    "amber": "#ffb300", "green": "#00c853",
    "text": "#e8eaf0", "dim": "#7a8090", "muted": "#4a5060",
}
```

Identique à GMAPP V5. Ne pas modifier cette palette sans synchroniser avec V5.

## Pièges connus

- **Pyright strict mode** : les dicts JSON non typés génèrent des warnings. Utiliser `dict[str, Any]` sur les paramètres de méthodes qui reçoivent des données JSON. Les `list[Any]` évitent les warnings sur les collections.
- **Rebuild exe** : PyInstaller supprime l'exe avant de le recréer. Si l'exe est verrouillé (en cours d'exécution), le build laisse un exe manquant.
- **build.ps1** : le script PowerShell a des problèmes d'encodage avec PowerShell 5.1. Préférer le build via Python subprocess (voir commande ci-dessus).
- **Déploiement serveur** : toujours vérifier que `grep -c monitor_traffic /home/ubuntu/gmapp_api/main.py` retourne `1` après déploiement. Un déploiement raté laisse une ancienne version qui fait planter `_fetch_all` (404 sur `/monitor/traffic`).
