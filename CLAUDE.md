# CLAUDE.md — GMP Monitor

## Language
Always respond in French.

## Project Overview
Application de monitoring du serveur OVH (VPS Ubuntu 24.04) qui héberge l'API GMAPP.
PyQt6, dark theme identique à GMAPP V5.

## Run
```bash
cd src
python monitor.py
```

## Install
```bash
pip install PyQt6 PyQt6-WebEngine
```

## Architecture
- `src/monitor.py` — application PyQt6 autonome (tout en un seul fichier)
- Serveur : `c:\GMP_AUTOMATION\Builder v2 - test\main_vps.py` (endpoints /monitor/*)

## Connexion OVH
- URL  : http://51.83.74.243:8000
- Clé  : gmp_fGPsjgfjk465fdf48ghHQd5Gsq592GAqpdGe4
- Sauvegardée dans `monitor_config.json` (racine du projet)

## Endpoints serveur utilisés
- GET /monitor/ping        — health check public
- GET /monitor/system      — CPU, RAM, Disk, uptime (nécessite psutil sur serveur)
- GET /monitor/db          — counts + tailles tables PostgreSQL
- GET /monitor/access_log  — 500 dernières requêtes API loggées en mémoire
- GET /version             — version GMAPP publiée

## Design
- Palette C identique à V5 (voir monitor.py)
- Refresh automatique toutes les 30 secondes
- Jauge circulaire CSS custom pour CPU/RAM/Disk
- Sparkline (mini graphe) historique 60 points
- Table journal d'accès avec code couleur HTTP
