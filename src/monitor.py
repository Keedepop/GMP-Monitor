"""
GMP Monitor — Dashboard de surveillance serveur OVH
PyQt6, dark theme identique à GMAPP V5
"""
import sys, json, time, datetime, collections
import urllib.request
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GERSMOTO.GMPMonitor")
    except Exception:
        pass

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QGridLayout,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSizePolicy, QLineEdit,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPointF
from PyQt6.QtGui import (
    QFont, QCursor, QColor, QPainter, QPen, QIcon,
    QPolygonF, QPainterPath, QLinearGradient,
)

# ── Palette identique V5 ──────────────────────────────────────────────────
C: dict[str, str] = {
    "bg":        "#111214",
    "surface":   "#1a1c20",
    "surface2":  "#22252b",
    "panel":     "#1f2126",
    "border":    "#2e3138",
    "border2":   "#3a3f4a",
    "red":       "#e8001d",
    "red_dim":   "#6b0010",
    "amber":     "#ffb300",
    "green":     "#00c853",
    "green_dim": "#051a0e",
    "text":      "#e8eaf0",
    "text2":     "#c8cad4",
    "dim":       "#7a8090",
    "muted":     "#4a5060",
    "entry":     "#0d0e10",
}

# ── Config ────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent.parent
CFG_FILE  = BASE_DIR / "monitor_config.json"
OVH_URL   = "https://bdc.gersmotopieces.com"
OVH_KEY   = "gmp_fGPsjgfjk465fdf48ghHQd5Gsq592GAqpdGe4"
APP_VER   = "1.2.0"
REFRESH_S = 30

def _load_cfg() -> dict[str, Any]:
    try:
        if CFG_FILE.exists():
            return json.loads(CFG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"url": OVH_URL, "key": OVH_KEY}

def _save_cfg(d: dict[str, Any]):
    try:
        CFG_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:
        pass

# ── Helpers ───────────────────────────────────────────────────────────────
def lbl(text="", size=12, bold=False, color=None, mono=False) -> QLabel:
    w = QLabel(text)
    f = QFont("Inter, Segoe UI", size)
    if bold: f.setWeight(QFont.Weight.Bold)
    if mono: f.setFamily("JetBrains Mono, Consolas, monospace")
    w.setFont(f)
    w.setStyleSheet(f"color:{color or C['text']};background:transparent;")
    return w

def sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{C['border']};")
    return f

def _fmt_bytes(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024: return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Po"

def _fmt_rate(bps: float) -> str:
    for unit in ("o/s", "Ko/s", "Mo/s", "Go/s"):
        if bps < 1024: return f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} Go/s"

def _fmt_uptime(s: int) -> str:
    d, r = divmod(int(s), 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}j")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts[:3])

def _fmt_bps(bps: float) -> str:
    """Formate un débit en bits/s lisible (K / M / G)."""
    for unit in ("o/s", "Ko/s", "Mo/s", "Go/s"):
        if bps < 1024: return f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} Go/s"

def _nice_scale(max_val: float) -> float:
    """Arrondit vers le haut pour une échelle graphique lisible."""
    import math
    if max_val <= 0: return 1.0
    mag = 10 ** math.floor(math.log10(max_val))
    for mult in (1, 2, 5, 10):
        if mag * mult >= max_val:
            return float(mag * mult)
    return float(mag * 10)

# ── Worker thread ─────────────────────────────────────────────────────────
class Worker(QThread):
    result = pyqtSignal(object)
    error  = pyqtSignal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self._fn = fn
        self._args = args

    def run(self):
        try:    self.result.emit(self._fn(*self._args))
        except Exception as e: self.error.emit(str(e))

# ── Gauge circulaire ──────────────────────────────────────────────────────
class Gauge(QWidget):
    def __init__(self, parent=None, size=100):
        super().__init__(parent)
        self._pct   = 0.0
        self._label = ""
        self._sz    = size
        self.setFixedSize(size, size)

    def set_value(self, pct: float, label: str = ""):
        self._pct   = max(0.0, min(100.0, pct))
        self._label = label
        self.update()

    def resize_to(self, size: int):
        self._sz = size
        self.setFixedSize(size, size)
        self.update()

    def _arc_color(self) -> str:
        if self._pct >= 85: return C["red"]
        if self._pct >= 60: return C["amber"]
        return C["green"]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m    = 8
        rect = self.rect().adjusted(m, m, -m, -m)

        pen = QPen(QColor(C["surface2"]), 10)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 225 * 16, -270 * 16)

        span = int(-270 * 16 * self._pct / 100)
        if span:
            pen2 = QPen(QColor(self._arc_color()), 10)
            pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen2)
            p.drawArc(rect, 225 * 16, span)

        p.setPen(QColor(C["text"]))
        f = QFont("Inter, Segoe UI", int(self._sz * 0.17), QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(rect.adjusted(0, -6, 0, -6), Qt.AlignmentFlag.AlignCenter, f"{self._pct:.0f}%")
        if self._label:
            f2 = QFont("JetBrains Mono, Consolas", int(self._sz * 0.09))
            p.setFont(f2)
            p.setPen(QColor(C["dim"]))
            p.drawText(rect.adjusted(0, 18, 0, 18), Qt.AlignmentFlag.AlignCenter, self._label)

# ── MiniGraph (sparkline) — auto-scale ou plafond fixe ───────────────────
class MiniGraph(QWidget):
    def __init__(self, color=None, parent=None, fixed_max: float | None = 100.0):
        super().__init__(parent)
        self._data      : collections.deque = collections.deque(maxlen=60)
        self._color     = color or C["green"]
        self._fixed_max = fixed_max   # None → auto-scale sur les données
        self.setFixedHeight(36)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def push(self, v: float):
        self._data.append(v)
        self.update()

    def paintEvent(self, _):
        if len(self._data) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pts  = list(self._data)
        mx   = self._fixed_max if self._fixed_max is not None else (max(pts) or 1)
        xs   = [int(i / (len(pts) - 1) * (w - 2)) + 1 for i in range(len(pts))]
        ys   = [int(h - 2 - (v / mx) * (h - 4)) for v in pts]
        pen  = QPen(QColor(self._color), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for i in range(1, len(xs)):
            p.drawLine(xs[i - 1], ys[i - 1], xs[i], ys[i])

# ── Carte métrique (CPU / RAM / Disque) ───────────────────────────────────
class MetricCard(QWidget):
    def __init__(self, title: str, graph_color: str = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)

        head = QWidget(); head.setStyleSheet("background:transparent;")
        hh   = QHBoxLayout(head); hh.setContentsMargins(0, 0, 0, 0)
        hh.addWidget(lbl(title, size=10, bold=True, color=C["dim"]))
        hh.addStretch()
        self._badge = lbl("", size=9, mono=True)
        self._badge.setStyleSheet(
            f"color:{C['dim']};background:{C['surface2']};border:1px solid {C['border']};"
            "border-radius:3px;padding:1px 5px;"
        )
        self._badge.hide()
        hh.addWidget(self._badge)
        lay.addWidget(head)

        body = QWidget(); body.setStyleSheet("background:transparent;")
        bh   = QHBoxLayout(body); bh.setContentsMargins(0, 0, 0, 0); bh.setSpacing(12)

        self.gauge = Gauge(size=100)
        bh.addWidget(self.gauge)

        info = QWidget(); info.setStyleSheet("background:transparent;")
        iv   = QVBoxLayout(info); iv.setContentsMargins(0, 0, 0, 0); iv.setSpacing(3)
        self._val1 = lbl("—", size=11, bold=True)
        self._val2 = lbl("—", size=9, color=C["dim"])
        self._val3 = lbl("",  size=9, color=C["muted"])
        self.graph = MiniGraph(color=graph_color or C["green"])
        iv.addStretch()
        iv.addWidget(self._val1)
        iv.addWidget(self._val2)
        iv.addWidget(self._val3)
        iv.addSpacing(4)
        iv.addWidget(self.graph)
        bh.addWidget(info, stretch=1)
        lay.addWidget(body)

    def update_values(self, pct: float, v1: str, v2: str, v3: str = "", badge: str = ""):
        self.gauge.set_value(pct)
        self._val1.setText(v1)
        self._val2.setText(v2)
        self._val3.setText(v3)
        self.graph.push(pct)
        if badge:
            self._badge.setText(badge); self._badge.show()
        else:
            self._badge.hide()
        color = C["red"] if pct >= 85 else C["amber"] if pct >= 60 else C["green"]
        self._val1.setStyleSheet(f"color:{color};background:transparent;")

# ── Carte réseau (upload + download) ─────────────────────────────────────
class NetworkCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        head = QWidget(); head.setStyleSheet("background:transparent;")
        hh   = QHBoxLayout(head); hh.setContentsMargins(0, 0, 0, 0)
        hh.addWidget(lbl("RÉSEAU", size=10, bold=True, color=C["dim"]))
        hh.addStretch()
        self._badge = lbl("", size=9, mono=True)
        self._badge.setStyleSheet(
            f"color:{C['dim']};background:{C['surface2']};border:1px solid {C['border']};"
            "border-radius:3px;padding:1px 5px;"
        )
        hh.addWidget(self._badge)
        lay.addWidget(head)
        lay.addWidget(sep())

        self._tx_lbl   = lbl("↑  —", size=11, bold=True, color=C["red"])
        self._tx_total = lbl("",      size=9,  color=C["dim"])
        self.tx_graph  = MiniGraph(color=C["red"],   fixed_max=None)

        self._rx_lbl   = lbl("↓  —", size=11, bold=True, color=C["green"])
        self._rx_total = lbl("",      size=9,  color=C["dim"])
        self.rx_graph  = MiniGraph(color=C["green"], fixed_max=None)

        for direction_lbl, total_lbl, graph in [
            (self._tx_lbl, self._tx_total, self.tx_graph),
            (self._rx_lbl, self._rx_total, self.rx_graph),
        ]:
            row = QWidget(); row.setStyleSheet("background:transparent;")
            rv  = QVBoxLayout(row); rv.setContentsMargins(0, 2, 0, 2); rv.setSpacing(1)
            rv.addWidget(direction_lbl)
            rv.addWidget(total_lbl)
            rv.addWidget(graph)
            lay.addWidget(row)

        lay.addStretch()

    def update_values(self, tx_rate: float, rx_rate: float,
                      tx_total: int, rx_total: int, elapsed: float):
        self._tx_lbl.setText(f"↑  {_fmt_rate(tx_rate)}")
        self._rx_lbl.setText(f"↓  {_fmt_rate(rx_rate)}")
        self._tx_total.setText(f"Total envoyé : {_fmt_bytes(tx_total)}")
        self._rx_total.setText(f"Total reçu   : {_fmt_bytes(rx_total)}")
        self._badge.setText(f"Δ {elapsed:.0f}s")
        self.tx_graph.push(tx_rate)
        self.rx_graph.push(rx_rate)

    def set_unavailable(self):
        self._tx_lbl.setText("↑  —")
        self._rx_lbl.setText("↓  —")
        self._tx_total.setText("")
        self._rx_total.setText("")
        self._badge.setText("non exposé")

# ── Carte stockage — toutes les partitions ───────────────────────────────
class _PartBar(QWidget):
    """Barre de progression horizontale fine pour une partition."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pct = 0.0
        self.setFixedHeight(5)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_pct(self, pct: float):
        self._pct = max(0.0, min(100.0, pct))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C["surface2"]))
        color = C["red"] if self._pct >= 85 else C["amber"] if self._pct >= 60 else C["green"]
        w = max(0, int(self.width() * self._pct / 100))
        if w:
            p.fillRect(0, 0, w, self.height(), QColor(color))


class DiskCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(16, 12, 16, 12)
        self._outer.setSpacing(4)

        head = QWidget(); head.setStyleSheet("background:transparent;")
        hh   = QHBoxLayout(head); hh.setContentsMargins(0, 0, 0, 0)
        hh.addWidget(lbl("STOCKAGE", size=10, bold=True, color=C["dim"]))
        hh.addStretch()
        self._badge = lbl("", size=9, mono=True)
        self._badge.setStyleSheet(
            f"color:{C['dim']};background:{C['surface2']};border:1px solid {C['border']};"
            "border-radius:3px;padding:1px 5px;"
        )
        hh.addWidget(self._badge)
        self._outer.addWidget(head)
        self._outer.addWidget(sep())

        self._rows_widget = QWidget(); self._rows_widget.setStyleSheet("background:transparent;")
        self._rows_lay    = QVBoxLayout(self._rows_widget)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(6)
        self._outer.addWidget(self._rows_widget)
        self._outer.addStretch()

        self._part_rows: list = []   # (mount_lbl, bar, pct_lbl, free_lbl)

    def update_disks(self, disks: list):
        n = len(disks)
        self._badge.setText(f"{n} partition{'s' if n > 1 else ''}")

        # Créer ou recycler les lignes
        while len(self._part_rows) < n:
            container = QWidget(); container.setStyleSheet("background:transparent;")
            cv = QVBoxLayout(container); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(2)

            top = QWidget(); top.setStyleSheet("background:transparent;")
            th  = QHBoxLayout(top); th.setContentsMargins(0, 0, 0, 0); th.setSpacing(4)
            mount_lbl = lbl("", size=9, mono=True, color=C["amber"])
            mount_lbl.setFixedWidth(72)
            pct_lbl   = lbl("", size=9, mono=True)
            pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            pct_lbl.setFixedWidth(38)
            free_lbl  = lbl("", size=9, color=C["dim"])
            free_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            th.addWidget(mount_lbl)
            th.addStretch()
            th.addWidget(free_lbl)
            th.addWidget(pct_lbl)
            cv.addWidget(top)

            bar = _PartBar()
            cv.addWidget(bar)

            self._rows_lay.addWidget(container)
            self._part_rows.append((mount_lbl, bar, pct_lbl, free_lbl, container))

        # Masquer les lignes excédentaires
        for idx, (_, _, _, _, ctr) in enumerate(self._part_rows):
            ctr.setVisible(idx < n)

        # Remplir les données
        for idx, d in enumerate(disks):
            mount_lbl, bar, pct_lbl, free_lbl, _ = self._part_rows[idx]
            pct   = d.get("percent", 0)
            free  = d.get("free", 0)
            color = C["red"] if pct >= 85 else C["amber"] if pct >= 60 else C["green"]
            mount_lbl.setText(d.get("mountpoint", "?"))
            bar.set_pct(pct)
            pct_lbl.setText(f"{pct:.0f}%")
            pct_lbl.setStyleSheet(f"color:{color};background:transparent;")
            free_lbl.setText(f"{_fmt_bytes(free)} libre")

    def set_unavailable(self):
        self._badge.setText("—")
        for _, bar, pct_lbl, free_lbl, _ in self._part_rows:
            bar.set_pct(0)
            pct_lbl.setText("—")
            free_lbl.setText("")


# ── Barre colorée fixe (trafic API) ──────────────────────────────────────
class _ColorBar(QWidget):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._pct   = 0.0
        self._color = color
        self.setFixedHeight(5)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_pct(self, pct: float):
        self._pct = max(0.0, min(100.0, pct))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C["surface2"]))
        w = max(0, int(self.width() * self._pct / 100))
        if w:
            p.fillRect(0, 0, w, self.height(), QColor(self._color))


# ── Carte Trafic API ──────────────────────────────────────────────────────
class ApiTrafficCard(QWidget):
    _CATS = [
        ("Dyson",    "/dyson",    C["red"]),
        ("Prix",     "/prix",     C["amber"]),
        ("Bible",    "/bible",    "#7c8cf8"),
        ("Version",  "/version",  "#00bcd4"),
        ("Wishlist", "/wishlist", C["dim"]),
        ("Autres",   None,        C["muted"]),
    ]
    _MONITOR = ("/monitor/", "/favicon")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        head = QWidget(); head.setStyleSheet("background:transparent;")
        hh = QHBoxLayout(head); hh.setContentsMargins(0, 0, 0, 0)
        hh.addWidget(lbl("TRAFIC API", size=10, bold=True, color=C["dim"]))
        hh.addStretch()
        self._badge = lbl("", size=9, mono=True)
        self._badge.setStyleSheet(
            f"color:{C['dim']};background:{C['surface2']};border:1px solid {C['border']};"
            "border-radius:3px;padding:1px 5px;"
        )
        hh.addWidget(self._badge)
        lay.addWidget(head)
        lay.addWidget(sep())

        self._rows: list = []
        for name, _, color in self._CATS:
            row = QWidget(); row.setStyleSheet("background:transparent;")
            rv = QHBoxLayout(row); rv.setContentsMargins(0, 1, 0, 1); rv.setSpacing(6)
            name_lbl = lbl(name, size=9, color=C["dim"])
            name_lbl.setFixedWidth(52)
            count_lbl = lbl("—", size=9, mono=True)
            count_lbl.setFixedWidth(36)
            count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            bar = _ColorBar(color)
            rv.addWidget(name_lbl)
            rv.addWidget(bar, stretch=1)
            rv.addWidget(count_lbl)
            lay.addWidget(row)
            self._rows.append((name_lbl, bar, count_lbl))

        lay.addWidget(sep())
        self._ip_lbl = lbl("", size=9, color=C["dim"])
        lay.addWidget(self._ip_lbl)
        lay.addStretch()

    def update_from_logs(self, logs: list):
        cats: dict = {name: 0 for name, _, _ in self._CATS}
        ip_counts: collections.Counter = collections.Counter()
        for row in logs:
            path = row.get("path", "")
            ip   = row.get("ip", "")
            if any(path.startswith(p) for p in self._MONITOR):
                continue
            if ip:
                ip_counts[ip] += 1
            matched = False
            for name, prefix, _ in self._CATS[:-1]:
                if prefix and path.startswith(prefix):
                    cats[name] += 1
                    matched = True
                    break
            if not matched:
                cats["Autres"] += 1
        total = sum(cats.values()) or 1
        for i, (name, _, _) in enumerate(self._CATS):
            _, bar, count_lbl = self._rows[i]
            n = cats.get(name, 0)
            bar.set_pct(n / total * 100)
            count_lbl.setText(str(n))
        n_ips = len(ip_counts)
        self._badge.setText(f"{n_ips} IP{'s' if n_ips > 1 else ''}")
        if ip_counts:
            top_ip, top_n = ip_counts.most_common(1)[0]
            self._ip_lbl.setText(f"Top : {top_ip} ({top_n} req)")
        else:
            self._ip_lbl.setText("")


# ── Graphique historique CPU + RAM ────────────────────────────────────────
class _MetricsCanvas(QWidget):
    """Zone de dessin QPainter : CPU% (rouge) + RAM% (ambre) superposés."""

    CPU_CLR = C["red"]
    RAM_CLR = C["amber"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[Any] = []
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[Any]):
        self._data = data
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        ML, MR, MT, MB = 38, 12, 8, 36
        CW = W - ML - MR
        CH = H - MT - MB

        if not self._data or CW < 10 or CH < 10:
            p.setPen(QColor(C["dim"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "En attente du premier sample…")
            p.end(); return

        data = self._data
        if len(data) > CW:
            step = len(data) / CW
            data = [data[int(i * step)] for i in range(int(CW))]
        n = len(data)

        cpu_vals = [d.get("cpu", 0) for d in data]
        ram_vals = [d.get("ram", 0) for d in data]
        scale    = 100.0  # axe fixe 0-100 %

        # ── grille + labels Y (0 / 25 / 50 / 75 / 100 %) ─────────────
        p.setFont(QFont("Consolas", 7))
        for pct in (0, 25, 50, 75, 100):
            gy = MT + int(CH * (1 - pct / 100))
            p.setPen(QPen(QColor(C["border"]), 1, Qt.PenStyle.DotLine))
            p.drawLine(ML, gy, ML + CW, gy)
            p.setPen(QColor(C["muted"]))
            p.drawText(0, gy - 9, ML - 4, 18,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{pct}%")

        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawLine(ML, MT, ML, MT + CH)

        def _area(vals: list[float]) -> QPolygonF:
            pts = [QPointF(ML + CW * i / max(n - 1, 1),
                           MT + CH - CH * min(v / scale, 1.0))
                   for i, v in enumerate(vals)]
            pts += [QPointF(ML + CW, MT + CH), QPointF(ML, MT + CH)]
            return QPolygonF(pts)

        def _line(vals: list[float], color: str):
            path = QPainterPath()
            for i, v in enumerate(vals):
                x = ML + CW * i / max(n - 1, 1)
                y = MT + CH - CH * min(v / scale, 1.0)
                if i == 0: path.moveTo(x, y)
                else:      path.lineTo(x, y)
            p.setPen(QPen(QColor(color), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        for vals, clr in [(ram_vals, self.RAM_CLR), (cpu_vals, self.CPU_CLR)]:
            fill = QColor(clr); fill.setAlpha(35)
            p.setBrush(fill); p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(_area(vals))
            _line(vals, clr)

        # ── labels X ──────────────────────────────────────────────────
        N_TICKS = min(6, n - 1)
        p.setPen(QColor(C["muted"]))
        p.setFont(QFont("Consolas", 7))
        for i in range(N_TICKS + 1):
            idx = int(i * (n - 1) / N_TICKS)
            x   = ML + int(CW * idx / max(n - 1, 1))
            ts  = data[idx].get("ts", "")
            try:
                dt      = datetime.datetime.fromisoformat(ts)
                lbl_txt = dt.strftime("%d/%m %H:%M")
            except Exception:
                lbl_txt = ts[-11:] if len(ts) >= 11 else ts
            p.drawText(x - 32, H - MB + 3, 64, 16,
                       Qt.AlignmentFlag.AlignHCenter, lbl_txt)
        p.end()


class MetricsHistoryCard(QWidget):
    """Carte historique CPU + RAM — plage partagée avec TrafficHistoryCard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        self.setMinimumHeight(180)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 8)
        lay.setSpacing(6)

        head = QWidget(); head.setStyleSheet("background:transparent;")
        hh   = QHBoxLayout(head); hh.setContentsMargins(0, 0, 0, 0); hh.setSpacing(8)
        hh.addWidget(lbl("CPU + RAM — HISTORIQUE", size=10, bold=True, color=C["dim"]))
        hh.addStretch()
        for color, label in [(_MetricsCanvas.CPU_CLR, "CPU"),
                              (_MetricsCanvas.RAM_CLR, "RAM")]:
            dot = QWidget(); dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{color};border-radius:2px;")
            hh.addWidget(dot)
            hh.addWidget(lbl(label, size=9, color=C["dim"]))
            hh.addSpacing(4)
        lay.addWidget(head)

        self._canvas = _MetricsCanvas(self)
        lay.addWidget(self._canvas, stretch=1)

        self._stats_lbl = lbl("", size=8, mono=True, color=C["muted"])
        lay.addWidget(self._stats_lbl)

    def set_data(self, data: list[Any]):
        self._canvas.set_data(data)
        if data:
            cpu_max = max((d.get("cpu", 0) for d in data), default=0)
            ram_max = max((d.get("ram", 0) for d in data), default=0)
            self._stats_lbl.setText(
                f"{len(data)} samples  ·  CPU max {cpu_max:.1f}%  ·  RAM max {ram_max:.1f}%"
            )
        else:
            self._stats_lbl.setText("En attente du premier sample (60 s après démarrage)…")


# ── Graphique historique trafic réseau ────────────────────────────────────
class _TrafficCanvas(QWidget):
    """Zone de dessin QPainter pour le graphique trafic (aire double)."""

    _TX_CLR = "#4fc3f7"   # sortant — bleu clair
    _RX_CLR = "#f9a825"   # entrant — ambre

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[Any] = []
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[Any]):
        self._data = data
        self.update()

    # ── dessin ──────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        ML, MR, MT, MB = 62, 12, 8, 36   # marges (gauche, droite, haut, bas)
        CW = W - ML - MR
        CH = H - MT - MB

        if not self._data or CW < 10 or CH < 10:
            p.setPen(QColor(C["dim"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aucune donnée — en attente de samples…")
            p.end(); return

        # ── downsample si beaucoup de points ──────────────────────────
        data = self._data
        if len(data) > CW:
            step = len(data) / CW
            data = [data[int(i * step)] for i in range(int(CW))]
        n = len(data)

        tx_vals = [d.get("tx_bps", 0) for d in data]
        rx_vals = [d.get("rx_bps", 0) for d in data]
        max_val = max(max(tx_vals, default=0), max(rx_vals, default=0))
        scale   = _nice_scale(max_val) if max_val > 0 else 1.0

        # ── grille horizontale + labels Y ─────────────────────────────
        N_GRID = 4
        p.setFont(QFont("Consolas", 7))
        for i in range(N_GRID + 1):
            gy  = MT + CH - int(CH * i / N_GRID)
            val = scale * i / N_GRID
            # ligne pointillée
            p.setPen(QPen(QColor(C["border"]), 1, Qt.PenStyle.DotLine))
            p.drawLine(ML, gy, ML + CW, gy)
            # label
            p.setPen(QColor(C["muted"]))
            txt = _fmt_bps(val)
            p.drawText(0, gy - 9, ML - 5, 18,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, txt)

        # ── axe vertical gauche ───────────────────────────────────────
        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawLine(ML, MT, ML, MT + CH)

        # ── fonction : construire le polygone d'aire ──────────────────
        def _area_polygon(vals: list[float]) -> QPolygonF:
            pts = []
            for i, v in enumerate(vals):
                x = ML + CW * i / max(n - 1, 1)
                y = MT + CH - CH * min(v / scale, 1.0)
                pts.append(QPointF(x, y))
            # fermer vers le bas
            pts.append(QPointF(ML + CW, MT + CH))
            pts.append(QPointF(ML,      MT + CH))
            return QPolygonF(pts)

        # ── fonction : tracer la ligne supérieure ─────────────────────
        def _draw_line(vals: list[float], color: str):
            path = QPainterPath()
            for i, v in enumerate(vals):
                x = ML + CW * i / max(n - 1, 1)
                y = MT + CH - CH * min(v / scale, 1.0)
                if i == 0: path.moveTo(x, y)
                else:      path.lineTo(x, y)
            p.setPen(QPen(QColor(color), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        # ── sortant (TX) ─────────────────────────────────────────────
        fill_tx = QColor(self._TX_CLR); fill_tx.setAlpha(45)
        p.setBrush(fill_tx); p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(_area_polygon(tx_vals))
        _draw_line(tx_vals, self._TX_CLR)

        # ── entrant (RX) ─────────────────────────────────────────────
        fill_rx = QColor(self._RX_CLR); fill_rx.setAlpha(45)
        p.setBrush(fill_rx); p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(_area_polygon(rx_vals))
        _draw_line(rx_vals, self._RX_CLR)

        # ── labels X (timestamps) ────────────────────────────────────
        N_TICKS = min(8, n - 1)
        p.setPen(QColor(C["muted"]))
        p.setFont(QFont("Consolas", 7))
        for i in range(N_TICKS + 1):
            idx = int(i * (n - 1) / N_TICKS)
            x   = ML + int(CW * idx / max(n - 1, 1))
            ts  = data[idx].get("ts", "")
            try:
                dt  = datetime.datetime.fromisoformat(ts)
                lbl_txt = dt.strftime("%d/%m %H:%M")
            except Exception:
                lbl_txt = ts[-11:] if len(ts) >= 11 else ts
            p.drawText(x - 32, H - MB + 3, 64, 16,
                       Qt.AlignmentFlag.AlignHCenter, lbl_txt)

        p.end()


class TrafficHistoryCard(QWidget):
    """Carte pleine largeur : historique trafic entrant / sortant."""

    _RANGES = [("6h", 6), ("24h", 24), ("48h", 48), ("7j", 168)]

    def __init__(self, on_range_change, parent=None):
        super().__init__(parent)
        self._on_range = on_range_change
        self._hours    = 24
        self.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        self.setMinimumHeight(180)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 8)
        lay.setSpacing(6)

        # ── en-tête ──────────────────────────────────────────────────
        head = QWidget(); head.setStyleSheet("background:transparent;")
        hh   = QHBoxLayout(head); hh.setContentsMargins(0, 0, 0, 0); hh.setSpacing(8)

        hh.addWidget(lbl("TRAFIC RÉSEAU — HISTORIQUE", size=10, bold=True, color=C["dim"]))
        hh.addStretch()

        # Légende
        for color, label in [(_TrafficCanvas._RX_CLR, "Entrant"),
                              (_TrafficCanvas._TX_CLR, "Sortant")]:
            dot = QWidget(); dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{color};border-radius:2px;")
            hh.addWidget(dot)
            hh.addWidget(lbl(label, size=9, color=C["dim"]))
            hh.addSpacing(4)

        hh.addSpacing(8)

        # Boutons plage
        _btn_ss = (
            f"QPushButton{{background:transparent;color:{C['dim']};border:1px solid {C['border2']};"
            f"border-radius:3px;padding:1px 7px;font-size:8px;font-family:Consolas;}}"
            f"QPushButton:checked{{background:{C['red_dim']};color:{C['text']};"
            f"border-color:{C['red_dim']};}}"
            f"QPushButton:hover{{border-color:{C['border']};}}"
        )
        self._range_btns = []
        for label, hours in self._RANGES:
            b = QPushButton(label)
            b.setFixedHeight(20); b.setCheckable(True)
            b.setStyleSheet(_btn_ss)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _, h=hours, btn=b: self._select_range(h, btn))
            self._range_btns.append(b)
            hh.addWidget(b)
        self._range_btns[1].setChecked(True)   # 24h par défaut

        lay.addWidget(head)

        # ── canvas ───────────────────────────────────────────────────
        self._canvas = _TrafficCanvas(self)
        lay.addWidget(self._canvas, stretch=1)

        # ── ligne de stats ────────────────────────────────────────────
        self._stats_lbl = lbl("", size=8, mono=True, color=C["muted"])
        lay.addWidget(self._stats_lbl)

    def _select_range(self, hours: int, btn: QPushButton):
        self._hours = hours
        for b in self._range_btns:
            b.setChecked(b is btn)
        self._on_range(hours)

    def set_data(self, data: list[Any]):
        self._canvas.set_data(data)
        if data:
            tx_max = max((d.get("tx_bps", 0) for d in data), default=0)
            rx_max = max((d.get("rx_bps", 0) for d in data), default=0)
            self._stats_lbl.setText(
                f"{len(data)} samples  ·  "
                f"Sortant max {_fmt_bps(tx_max)}  ·  "
                f"Entrant max {_fmt_bps(rx_max)}"
            )
        else:
            self._stats_lbl.setText("En attente du premier sample (60 s après démarrage)…")

    @property
    def hours(self) -> int:
        return self._hours


# ── TitleBar ──────────────────────────────────────────────────────────────
class TitleBar(QWidget):
    def __init__(self, parent: "MonitorApp"):
        super().__init__(parent)
        self._parent   = parent
        self.setFixedHeight(52)
        self.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 12, 0)
        lay.setSpacing(0)

        lay.addWidget(lbl("GMP MONITOR", size=15, bold=True, color=C["red"]))
        lay.addSpacing(16)

        self._dot      = QLabel("●")
        self._dot.setStyleSheet(f"color:{C['dim']};background:transparent;font-size:10px;")
        self._conn_lbl = lbl("OVH", size=9, mono=True, color=C["dim"])
        lay.addWidget(self._dot)
        lay.addSpacing(4)
        lay.addWidget(self._conn_lbl)
        lay.addSpacing(16)

        self._refresh_lbl = lbl("", size=9, mono=True, color=C["muted"])
        lay.addWidget(self._refresh_lbl)
        lay.addStretch()

        lay.addWidget(lbl(f"v{APP_VER}", size=9, mono=True, color=C["muted"]))
        lay.addSpacing(16)

        _ws_chk = (
            f"QPushButton {{background:transparent;color:{C['dim']};border-radius:4px;font-size:11px;}}"
            f"QPushButton:hover {{background:{C['surface2']};color:{C['text']};}}"
            f"QPushButton:checked {{background:{C['border2']};color:{C['text']};}}"
        )

        self._refresh_cycle_btn = QPushButton("30s")
        self._refresh_cycle_btn.setFixedSize(36, 28)
        self._refresh_cycle_btn.setStyleSheet(_ws_chk)
        self._refresh_cycle_btn.setToolTip("Intervalle de rafraîchissement")
        self._refresh_cycle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._refresh_cycle_btn.clicked.connect(parent._cycle_refresh)

        self._pin_btn = QPushButton("📌")
        self._pin_btn.setFixedSize(28, 28)
        self._pin_btn.setStyleSheet(_ws_chk)
        self._pin_btn.setToolTip("Épingler au premier plan")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pin_btn.clicked.connect(parent._toggle_always_on_top)

        self._tv_btn = QPushButton("⊞")
        self._tv_btn.setFixedSize(28, 28)
        self._tv_btn.setStyleSheet(_ws_chk)
        self._tv_btn.setToolTip("Mode tableau de bord")
        self._tv_btn.setCheckable(True)
        self._tv_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._tv_btn.clicked.connect(parent._toggle_tv_mode)

        self._cfg_btn = QPushButton("⚙")
        self._cfg_btn.setFixedSize(28, 28)
        self._cfg_btn.setStyleSheet(_ws_chk)
        self._cfg_btn.setToolTip("Paramètres de connexion")
        self._cfg_btn.setCheckable(True)
        self._cfg_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._cfg_btn.clicked.connect(parent._toggle_settings)

        lay.addSpacing(8)
        for btn in (self._refresh_cycle_btn, self._pin_btn, self._tv_btn, self._cfg_btn):
            lay.addWidget(btn)

    def set_status(self, ok: bool | None, tip: str = ""):
        color = C["green"] if ok is True else C["red"] if ok is False else C["dim"]
        self._dot.setStyleSheet(f"color:{color};background:transparent;font-size:10px;")
        self._conn_lbl.setStyleSheet(
            f"color:{color};background:transparent;font-size:9px;font-family:monospace;"
        )
        if tip: self._dot.setToolTip(tip)

    def set_refresh_label(self, txt: str):
        self._refresh_lbl.setText(txt)


# ══════════════════════════════════════════════════════════════════════════
# FENÊTRE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════
class MonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(960, 700)
        self.resize(1200, 820)
        self.setWindowTitle("GMP Monitor")
        self.setStyleSheet(f"QMainWindow,QWidget#root{{background:{C['bg']};}}")

        icon_p = BASE_DIR / "assets" / "monitor.ico"
        if icon_p.exists(): self.setWindowIcon(QIcon(str(icon_p)))

        self._cfg: dict[str, Any] = _load_cfg()
        self._workers   : list[QThread] = []
        self._refresh_s = REFRESH_S
        self._countdown = self._refresh_s

        # Historique cumulatif des logs de session
        self._log_history : collections.deque = collections.deque(maxlen=1000)
        self._log_seen    : set = set()        # clés (ts, ip, method, path) déjà vues
        self._log_filter  : str = "all"
        self._log_new_count: int = 0
        self._openapi_exposed: bool = True  # mis à jour au 1er fetch
        self._own_ip      : str | None = None  # IP du poste monitor, détectée automatiquement
        self._tv_mode       : bool = False
        self._always_on_top : bool = False
        self._refresh_intervals = [5, 10, 30, 60]
        self._refresh_idx       = 2          # 30s par défaut
        self._refresh_s         = REFRESH_S

        # Suivi des compteurs réseau précédents pour calcul de débit
        self._prev_net_sent: int | None = None
        self._prev_net_recv: int | None = None
        self._prev_net_time: float = 0.0

        # Plage sélectionnée pour l'historique trafic
        self._traffic_hours: int = 24

        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        main = QVBoxLayout(root); main.setContentsMargins(0, 0, 0, 0); main.setSpacing(0)

        self._title_bar = TitleBar(self)
        main.addWidget(self._title_bar)

        self._content = QWidget()
        self._content.setStyleSheet(f"background:{C['bg']};")
        main.addWidget(self._content, stretch=1)

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

        QTimer.singleShot(200,  self._refresh)
        QTimer.singleShot(1500, self._load_history)   # journal pré-rempli au démarrage

    # ── Construction UI ───────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        _field_ss = (
            f"QLineEdit{{background:{C['entry']};border:1px solid {C['border2']};"
            f"border-radius:4px;padding:2px 8px;color:{C['text']};font-size:10px;font-family:monospace;}}"
        )
        _btn = (
            f"QPushButton{{background:{C['surface2']};color:{C['text']};border:1px solid {C['border2']};"
            f"border-radius:4px;padding:4px 14px;font-size:10px;font-weight:700;}}"
            f"QPushButton:hover{{background:{C['border']};}}"
            f"QPushButton:disabled{{color:{C['muted']};}}"
        )
        _btn_red = (
            f"QPushButton{{background:{C['red_dim']};color:{C['text']};border:1px solid {C['red_dim']};"
            f"border-radius:4px;padding:4px 14px;font-size:10px;font-weight:700;}}"
            f"QPushButton:hover{{background:{C['border']};}}"
        )

        # ── Panneau paramètres (masqué par défaut) ────────────────────────
        self._settings_panel = QWidget()
        self._settings_panel.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};"
            f"border-radius:6px;"
        )
        sp = QHBoxLayout(self._settings_panel)
        sp.setContentsMargins(14, 8, 14, 8); sp.setSpacing(10)

        self._url_entry = QLineEdit(self._cfg.get("url", OVH_URL))
        self._url_entry.setFixedHeight(28); self._url_entry.setFixedWidth(260)
        self._url_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self._url_entry.setPlaceholderText("https://domaine.com")
        self._url_entry.setStyleSheet(_field_ss)

        self._key_entry = QLineEdit(self._cfg.get("key", OVH_KEY))
        self._key_entry.setFixedHeight(28); self._key_entry.setFixedWidth(220)
        self._key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_entry.setPlaceholderText("API Key")
        self._key_entry.setStyleSheet(_field_ss)

        save_btn = QPushButton("💾  Sauvegarder"); save_btn.setFixedHeight(28)
        save_btn.setStyleSheet(_btn)
        save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save_btn.clicked.connect(self._save_cfg)

        sp.addWidget(lbl("Serveur :", size=9, color=C["dim"]))
        sp.addWidget(self._url_entry)
        sp.addWidget(lbl("Clé API :", size=9, color=C["dim"]))
        sp.addWidget(self._key_entry)
        sp.addWidget(save_btn)
        sp.addStretch()

        self._settings_panel.setVisible(False)
        lay.addWidget(self._settings_panel)

        # ── Barre d'actions ───────────────────────────────────────────────
        actions = QWidget(); actions.setStyleSheet("background:transparent;")
        ah = QHBoxLayout(actions); ah.setContentsMargins(0, 0, 0, 0); ah.setSpacing(8)

        refresh_btn = QPushButton("⟳  ACTUALISER"); refresh_btn.setFixedHeight(30)
        refresh_btn.setStyleSheet(_btn_red)
        refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh_btn.clicked.connect(self._refresh)

        self._latency_lbl = lbl("", size=9, mono=True, color=C["dim"])

        ah.addWidget(refresh_btn)
        ah.addStretch()
        ah.addWidget(self._latency_lbl)
        self._actions_bar = actions
        lay.addWidget(actions)

        # Grille
        grid = QWidget(); grid.setStyleSheet("background:transparent;")
        gl = QGridLayout(grid); gl.setContentsMargins(0, 0, 0, 0); gl.setSpacing(10)

        # Ligne 0 : STOCKAGE (2 cols) · STATUT (2 cols)
        self._card_cpu    = MetricCard("CPU", graph_color=C["red"])    # non affiché
        self._card_ram    = MetricCard("RAM", graph_color=C["amber"])  # non affiché
        self._card_disk   = DiskCard()
        self._card_status = self._make_status_card()
        gl.addWidget(self._card_disk,   0, 0, 1, 2)
        gl.addWidget(self._card_status, 0, 2, 1, 2)

        # Objets conservés mais non affichés (calculs internes)
        self._card_db      = self._make_db_card()
        self._card_network = NetworkCard()
        self._card_traffic = ApiTrafficCard()

        # Ligne 1 : CPU+RAM historique (2 cols) · Réseau historique (2 cols)
        self._card_metrics_history = MetricsHistoryCard()
        self._card_traffic_history = TrafficHistoryCard(
            on_range_change=self._on_traffic_range_change
        )
        gl.addWidget(self._card_metrics_history, 1, 0, 1, 2)
        gl.addWidget(self._card_traffic_history,  1, 2, 1, 2)

        # Ligne 2 : Journal d'accès (dépliant)
        self._card_log = self._make_log_card()
        gl.addWidget(self._card_log, 2, 0, 1, 4)

        self._grid_layout = gl
        for col in range(4): gl.setColumnStretch(col, 1)
        gl.setRowStretch(0, 0)
        gl.setRowStretch(1, 2)   # graphiques — grande portion
        gl.setRowStretch(2, 3)   # journal ouvert — encore plus grand

        lay.addWidget(grid, stretch=1)

    def _make_status_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        cv = QVBoxLayout(card); cv.setContentsMargins(16, 12, 16, 12); cv.setSpacing(6)
        cv.addWidget(lbl("STATUT SERVEUR", size=10, bold=True, color=C["dim"]))
        cv.addWidget(sep())

        def _row(k, w):
            r  = QWidget(); r.setStyleSheet("background:transparent;")
            rh = QHBoxLayout(r); rh.setContentsMargins(0, 0, 0, 0); rh.setSpacing(8)
            rh.addWidget(lbl(k, size=9, color=C["dim"]))
            rh.addStretch()
            rh.addWidget(w)
            return r

        self._st_uptime_srv = lbl("—", size=10, mono=True)
        self._st_uptime_api = lbl("—", size=10, mono=True)
        self._st_load       = lbl("—", size=10, mono=True)
        self._st_ping       = lbl("—", size=10, mono=True)
        self._st_requests   = lbl("—", size=10, mono=True)
        self._st_version    = lbl("—", size=10, mono=True)

        cv.addWidget(_row("Uptime serveur",   self._st_uptime_srv))
        cv.addWidget(_row("Uptime API",       self._st_uptime_api))
        cv.addWidget(_row("Charge 1m",        self._st_load))
        cv.addWidget(_row("Latence API",      self._st_ping))
        cv.addWidget(_row("Requêtes loggées", self._st_requests))
        cv.addWidget(_row("Dernière version", self._st_version))
        self._st_ver_notes = lbl("", size=8, color=C["muted"])
        self._st_ver_notes.setWordWrap(True)
        cv.addWidget(self._st_ver_notes)

        cv.addWidget(sep())
        cv.addWidget(lbl("SÉCURITÉ", size=9, bold=True, color=C["dim"]))
        self._sec_https   = lbl("⚠  HTTP — communication non chiffrée", size=9, color=C["amber"])
        self._sec_openapi = lbl("⚠  /openapi.json accessible sans auth", size=9, color=C["amber"])
        self._sec_auth    = lbl("✓  Auth X-API-Key sur toutes les routes", size=9, color=C["green"])
        cv.addWidget(self._sec_https)
        cv.addWidget(self._sec_openapi)
        cv.addWidget(self._sec_auth)
        cv.addStretch()
        return card

    def _make_db_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        cv = QVBoxLayout(card); cv.setContentsMargins(16, 12, 16, 12); cv.setSpacing(6)
        cv.addWidget(lbl("BASE DE DONNÉES", size=10, bold=True, color=C["dim"]))
        cv.addWidget(sep())

        self._db_table = QTableWidget(0, 3)
        self._db_table.setHorizontalHeaderLabels(["Table", "Lignes", "Taille"])
        self._db_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._db_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._db_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._db_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._db_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._db_table.verticalHeader().setVisible(False)
        self._db_table.setShowGrid(False)
        self._db_table.setAlternatingRowColors(False)
        self._db_table.setStyleSheet(f"""
            QTableWidget {{
                background:{C['surface']};border:none;color:{C['text']};font-size:10px;
            }}
            QHeaderView::section {{
                background:{C['surface2']};color:{C['dim']};border:none;
                border-bottom:1px solid {C['border']};padding:4px 8px;
                font-size:9px;font-weight:700;
            }}
            QTableWidget::item {{padding:4px 8px;border-bottom:1px solid {C['border']};}}
            QTableWidget::item:selected {{background:{C['surface2']};}}
        """)
        cv.addWidget(self._db_table)
        return card

    def _make_log_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        cv = QVBoxLayout(card); cv.setContentsMargins(16, 10, 16, 10); cv.setSpacing(4)

        # ── En-tête ───────────────────────────────────────────────────────
        hdr = QWidget(); hdr.setStyleSheet("background:transparent;")
        hh  = QHBoxLayout(hdr); hh.setContentsMargins(0, 0, 0, 0); hh.setSpacing(6)

        # Bouton dépliant ▲/▼
        self._log_toggle_btn = QPushButton("▲")
        self._log_toggle_btn.setFixedSize(22, 22)
        self._log_toggle_btn.setStyleSheet(
            f"QPushButton{{background:{C['surface2']};color:{C['dim']};"
            f"border:1px solid {C['border']};border-radius:3px;font-size:10px;font-weight:700;}}"
            f"QPushButton:hover{{color:{C['text']};}}"
        )
        self._log_toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._log_toggle_btn.setToolTip("Replier / déplier le journal")
        self._log_toggle_btn.clicked.connect(self._toggle_journal)
        hh.addWidget(self._log_toggle_btn)

        hh.addWidget(lbl("JOURNAL D'ACCÈS API", size=10, bold=True, color=C["dim"]))
        hh.addSpacing(8)
        self._log_count_lbl = lbl("", size=9, mono=True, color=C["muted"])
        hh.addWidget(self._log_count_lbl)
        hh.addStretch()

        # Styles boutons filtre
        _fb = (
            f"QPushButton{{background:{C['surface2']};color:{C['dim']};"
            f"border:1px solid {C['border']};border-radius:3px;"
            f"padding:2px 10px;font-size:9px;font-weight:700;}}"
            f"QPushButton:hover{{color:{C['text']};}}"
        )
        _fa = (
            f"QPushButton{{background:{C['border2']};color:{C['text']};"
            f"border:1px solid {C['border2']};border-radius:3px;"
            f"padding:2px 10px;font-size:9px;font-weight:700;}}"
            f"QPushButton:hover{{color:{C['text']};}}"
        )
        self._filter_btns: dict[str, QPushButton] = {}
        self._filter_style_base   = _fb
        self._filter_style_active = _fa
        for code, label in [("all","TOUT"), ("2xx","2xx"), ("4xx","4xx"), ("5xx","5xx"), ("err","ERREURS")]:
            btn = QPushButton(label); btn.setFixedHeight(22)
            btn.setCheckable(True); btn.setChecked(code == "all")
            btn.setStyleSheet(_fa if code == "all" else _fb)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda _checked, c=code: self._set_log_filter(c))
            self._filter_btns[code] = btn
            hh.addWidget(btn)

        hh.addSpacing(8)

        def _log_btn_ss(color: str) -> str:
            return (
                f"QPushButton{{background:{C['surface2']};color:{color};"
                f"border:1px solid {C['border']};border-radius:3px;padding:2px 10px;font-size:9px;}}"
                f"QPushButton:hover{{background:{C['border']};}}"
            )

        hist_btn = QPushButton("↓ Historique"); hist_btn.setFixedHeight(22)
        hist_btn.setStyleSheet(_log_btn_ss(C["green"]))
        hist_btn.setToolTip("Charger tout l'historique depuis le fichier serveur")
        hist_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        hist_btn.clicked.connect(self._load_history)
        hh.addWidget(hist_btn)

        clear_btn = QPushButton("Vider"); clear_btn.setFixedHeight(22)
        clear_btn.setStyleSheet(_log_btn_ss(C["amber"]))
        clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_btn.clicked.connect(self._clear_log)
        hh.addWidget(clear_btn)

        cv.addWidget(hdr)

        # Barre de recherche textuelle
        search_row = QWidget(); search_row.setStyleSheet("background:transparent;")
        sh = QHBoxLayout(search_row); sh.setContentsMargins(0, 0, 0, 0); sh.setSpacing(6)
        self._log_search = QLineEdit()
        self._log_search.setFixedHeight(24)
        self._log_search.setPlaceholderText("Filtrer : IP, chemin, méthode, code…")
        self._log_search.setStyleSheet(
            f"QLineEdit{{background:{C['entry']};border:1px solid {C['border2']};"
            f"border-radius:3px;padding:1px 8px;color:{C['text']};font-size:9px;font-family:monospace;}}"
            f"QLineEdit:focus{{border:1px solid {C['border2']};}}"
        )
        self._log_search.textChanged.connect(lambda _: self._render_log_table())
        sh.addWidget(self._log_search)

        clear_search_btn = QPushButton("✕")
        clear_search_btn.setFixedSize(24, 24)
        clear_search_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['muted']};border:none;font-size:11px;}}"
            f"QPushButton:hover{{color:{C['text']};}}"
        )
        clear_search_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_search_btn.clicked.connect(lambda: self._log_search.clear())
        sh.addWidget(clear_search_btn)

        self._log_table = QTableWidget(0, 6)
        self._log_table.setHorizontalHeaderLabels(
            ["Horodatage", "IP", "Méthode", "Chemin", "Statut", "ms"]
        )
        self._log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._log_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._log_table.verticalHeader().setVisible(False)
        self._log_table.setShowGrid(False)
        self._log_table.setAlternatingRowColors(False)
        self._log_table.verticalHeader().setDefaultSectionSize(22)
        self._log_table.setStyleSheet(f"""
            QTableWidget {{
                background:{C['surface']};border:none;color:{C['text']};
                font-size:9px;font-family:monospace;
            }}
            QHeaderView::section {{
                background:{C['surface2']};color:{C['dim']};border:none;
                border-bottom:1px solid {C['border']};padding:3px 8px;
                font-size:9px;font-weight:700;
            }}
            QTableWidget::item {{padding:2px 8px;border-bottom:1px solid {C['border']};}}
            QTableWidget::item:selected {{background:{C['surface2']};}}
        """)

        # Contenu dépliant (recherche + table)
        self._log_body = QWidget(); self._log_body.setStyleSheet("background:transparent;")
        bv = QVBoxLayout(self._log_body); bv.setContentsMargins(0, 4, 0, 0); bv.setSpacing(4)
        bv.addWidget(search_row)
        bv.addWidget(sep())
        bv.addWidget(self._log_table)

        cv.addWidget(self._log_body)
        self._log_journal_collapsed = False
        return card

    # ── Fetch / données ───────────────────────────────────────────────────

    def _cycle_refresh(self):
        self._refresh_idx = (self._refresh_idx + 1) % len(self._refresh_intervals)
        self._refresh_s   = self._refresh_intervals[self._refresh_idx]
        self._countdown   = self._refresh_s
        self._title_bar._refresh_cycle_btn.setText(f"{self._refresh_s}s")

    def _toggle_settings(self):
        visible = not self._settings_panel.isVisible()
        self._settings_panel.setVisible(visible)
        self._title_bar._cfg_btn.setChecked(visible)

    def _toggle_journal(self):
        self._log_journal_collapsed = not self._log_journal_collapsed
        collapsed = self._log_journal_collapsed
        self._log_body.setVisible(not collapsed)
        self._log_toggle_btn.setText("▼" if collapsed else "▲")
        if collapsed:
            self._grid_layout.setRowStretch(1, 1)   # graphiques : tout l'espace
            self._grid_layout.setRowStretch(2, 0)   # journal : juste le header
            self._card_log.setMaximumHeight(44)
        else:
            self._grid_layout.setRowStretch(1, 2)   # graphiques : 2/5
            self._grid_layout.setRowStretch(2, 3)   # journal : 3/5
            self._card_log.setMaximumHeight(16_777_215)

    def _toggle_always_on_top(self):
        self._always_on_top = not self._always_on_top
        flags = Qt.WindowType.Window
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self._title_bar._pin_btn.setChecked(self._always_on_top)

    def _toggle_tv_mode(self):
        self._tv_mode = not self._tv_mode
        self._actions_bar.setVisible(not self._tv_mode)
        gauge_size = 140 if self._tv_mode else 100
        for card in (self._card_cpu, self._card_ram):
            card.gauge.resize_to(gauge_size)
        if self._tv_mode:
            self.showMaximized()
        self._title_bar._tv_btn.setChecked(self._tv_mode)

    def _save_cfg(self):
        url = self._url_entry.text().strip().rstrip("/")
        key = self._key_entry.text().strip()
        self._cfg = {"url": url, "key": key}
        _save_cfg(self._cfg)

    def _api(self, path: str, n: int | None = None, extra: str = "") -> Any:
        url  = self._cfg.get("url", OVH_URL).rstrip("/")
        key  = self._cfg.get("key", OVH_KEY)
        qs   = "&".join(filter(None, [f"n={n}" if n else "", extra]))
        full = f"{url}{path}" + (f"?{qs}" if qs else "")
        req  = urllib.request.Request(full, headers={"X-API-Key": key})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def _on_traffic_range_change(self, hours: int):
        self._traffic_hours = hours
        self._refresh()

    def _fetch_all(self) -> dict:
        t0      = time.time()
        hours   = self._traffic_hours
        sys_    = self._api("/monitor/system")
        db_     = self._api("/monitor/db")
        log_    = self._api("/monitor/access_log", n=200)
        ver_    = self._api("/version")
        traffic_= self._api("/monitor/traffic", extra=f"hours={hours}")
        lat     = round((time.time() - t0) * 1000)
        # Vérifie si /openapi.json est accessible sans authentification
        openapi_exposed = False
        try:
            url = self._cfg.get("url", OVH_URL).rstrip("/") + "/openapi.json"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as r:
                openapi_exposed = (r.status == 200)
        except Exception:
            pass
        return {"sys": sys_, "db": db_, "log": log_, "ver": ver_,
                "traffic": traffic_, "lat_ms": lat,
                "openapi_exposed": openapi_exposed}

    def _refresh(self):
        url = self._url_entry.text().strip()
        if not url: return
        self._cfg = {"url": url, "key": self._key_entry.text().strip()}
        self._countdown = self._refresh_s
        self._title_bar.set_refresh_label("Actualisation…")
        self._latency_lbl.setText("")
        self._title_bar.set_status(None)
        w = Worker(self._fetch_all)
        w.result.connect(self._on_data)
        w.error.connect(self._on_error)
        self._workers.append(w)
        w.start()

    def _on_data(self, data: dict[str, Any]):
        self._countdown = self._refresh_s
        self._title_bar.set_status(True, "Serveur OVH connecté")
        lat = data.get("lat_ms", 0)
        self._latency_lbl.setText(f"latence {lat} ms")

        sys_ = data.get("sys", {})
        db_  = data.get("db",  {})
        log_ = data.get("log", {})
        ver_ = data.get("ver", {})

        if sys_.get("ok"):
            cpu       = sys_.get("cpu_percent", 0)
            ramt      = sys_.get("ram_total", 0)
            ramu      = sys_.get("ram_used",  0)
            ramp      = sys_.get("ram_percent", 0)
            ram_free  = sys_.get("ram_free",  0)
            ram_cache = sys_.get("ram_cached", 0)
            load      = sys_.get("load_avg", [])
            uptime    = sys_.get("uptime_s", 0)
            cpu_count = sys_.get("cpu_count", "?")

            self._card_cpu.update_values(
                cpu, f"{cpu:.1f} %",
                f"{cpu_count} cœur{'s' if cpu_count not in (1,'?') else ''} (VPS)",
            )
            self._card_ram.update_values(
                ramp,
                f"{ramp:.1f} %",
                f"{_fmt_bytes(ramu)} / {_fmt_bytes(ramt)}",
                v3=f"{_fmt_bytes(ram_cache)} cache",
                badge=f"{_fmt_bytes(ram_free)} libre",
            )
            self._card_disk.update_disks(sys_.get("disks", []))
            self._st_uptime_srv.setText(_fmt_uptime(uptime))
            self._st_load.setText(f"{load[0]:.2f}" if load else "—")

            # ── Bande passante réseau ──────────────────────────────────────
            net_sent = sys_.get("net_bytes_sent")
            net_recv = sys_.get("net_bytes_recv")
            now = time.time()
            if net_sent is not None and net_recv is not None:
                if self._prev_net_sent is not None and self._prev_net_time > 0:
                    elapsed = now - self._prev_net_time
                    if elapsed > 0:
                        tx_rate = max(0, (net_sent - self._prev_net_sent) / elapsed)
                        rx_rate = max(0, (net_recv - self._prev_net_recv) / elapsed)
                        self._card_network.update_values(
                            tx_rate, rx_rate, net_sent, net_recv, elapsed
                        )
                self._prev_net_sent = net_sent
                self._prev_net_recv = net_recv
                self._prev_net_time = now
            else:
                self._card_network.set_unavailable()
        else:
            self._card_cpu.gauge.set_value(0)
            self._card_ram.gauge.set_value(0)
            self._card_disk.set_unavailable()
            self._card_network.set_unavailable()

        if log_.get("ok"):
            self._st_uptime_api.setText(_fmt_uptime(log_.get("uptime_api_s", 0)))
            self._st_requests.setText(str(log_.get("total", 0)))
            self._ingest_log_entries(log_.get("log", []))

        if db_.get("ok"):
            self._update_db_table(db_.get("counts", {}), db_.get("sizes", {}))

        self._st_ping.setText(f"{lat} ms")
        self._st_version.setText(ver_.get("version", "?"))

        notes = ver_.get("notes", "")
        self._st_ver_notes.setText(
            (notes[:100] + "…") if len(notes) > 100 else notes
        )

        openapi_exp = data.get("openapi_exposed", True)
        self._openapi_exposed = openapi_exp
        if openapi_exp:
            self._sec_openapi.setText("⚠  /openapi.json accessible sans auth")
            self._sec_openapi.setStyleSheet(f"color:{C['amber']};background:transparent;")
        else:
            self._sec_openapi.setText("✓  /openapi.json protégé")
            self._sec_openapi.setStyleSheet(f"color:{C['green']};background:transparent;")

        url = self._cfg.get("url", OVH_URL)
        if url.startswith("https://"):
            self._sec_https.setText("✓  HTTPS — communication chiffrée (TLS)")
            self._sec_https.setStyleSheet(f"color:{C['green']};background:transparent;")
        else:
            self._sec_https.setText("⚠  HTTP — communication non chiffrée")
            self._sec_https.setStyleSheet(f"color:{C['amber']};background:transparent;")

        self._card_traffic.update_from_logs(list(self._log_history))

        # ── Historiques trafic + CPU/RAM ──────────────────────────────────────
        traf_ = data.get("traffic", {})
        if traf_.get("ok"):
            samples = traf_.get("data", [])
            self._card_traffic_history.set_data(samples)
            self._card_metrics_history.set_data(samples)

    def _on_error(self, err: str):
        self._title_bar.set_status(False, f"Erreur : {err[:80]}")
        self._title_bar.set_refresh_label(f"Erreur — {err[:60]}")

    # ── Journal cumulatif ─────────────────────────────────────────────────

    def _ingest_log_entries(self, rows: list):
        new_count = 0
        for row in rows:
            key = (row.get("ts",""), row.get("ip",""), row.get("method",""), row.get("path",""))
            if key not in self._log_seen:
                self._log_seen.add(key)
                self._log_history.appendleft(row)   # plus récent en tête
                new_count += 1
        # Détecter l'IP propre du moniteur à partir des entrées /openapi.json déjà loggées
        if self._own_ip is None:
            for row in self._log_history:
                if row.get("path") == "/openapi.json":
                    self._own_ip = row.get("ip")
                    break
        self._log_new_count = new_count
        self._render_log_table()

    def _set_log_filter(self, code: str):
        self._log_filter = code
        for k, btn in self._filter_btns.items():
            btn.setChecked(k == code)
            btn.setStyleSheet(
                self._filter_style_active if k == code else self._filter_style_base
            )
        self._render_log_table()

    def _clear_log(self):
        self._log_history.clear()
        self._log_seen.clear()
        self._log_new_count = 0
        self._log_table.setRowCount(0)
        self._log_count_lbl.setText("Vidé")

    def _load_history(self):
        """Charge l'historique complet depuis le fichier JSONL du serveur."""
        self._log_count_lbl.setText("Chargement de l'historique…")
        w = Worker(lambda: self._api("/monitor/access_log", n=5000, extra="history=1"))
        w.result.connect(self._on_history_data)
        w.error.connect(lambda e: self._log_count_lbl.setText(f"Erreur : {e[:60]}"))
        self._workers.append(w)
        w.start()

    def _on_history_data(self, data: dict[str, Any]):
        if not data.get("ok"):
            self._log_count_lbl.setText(f"Erreur historique : {data.get('error','?')}")
            return
        self._ingest_log_entries(data.get("log", []))
        self._card_traffic.update_from_logs(list(self._log_history))
        total_file = data.get("total", 0)
        self._log_count_lbl.setText(
            f"{len(self._log_history)} entrées chargées (fichier serveur : {total_file} lignes)"
        )

    def _render_log_table(self):
        filt = self._log_filter
        visible = []
        search = self._log_search.text().strip().lower()

        _MONITOR_PREFIXES = ("/monitor/", "/version")

        for row in self._log_history:
            s    = row.get("status", 0)
            path = row.get("path", "")

            # Filtre statut HTTP
            if filt == "2xx" and not (200 <= s < 300): continue
            if filt == "4xx" and not (400 <= s < 500): continue
            if filt == "5xx" and not (s >= 500):        continue
            if filt == "err" and not (s >= 400):        continue

            # Filtre texte libre
            haystack = " ".join([
                row.get("ts",""), row.get("ip",""),
                row.get("method",""), path,
                str(s), str(row.get("ms",""))
            ]).lower()
            if search:
                if search not in haystack:
                    continue
            else:
                # Masquer les appels internes du moniteur sauf si recherche active
                if any(path.startswith(p) for p in _MONITOR_PREFIXES):
                    continue
                # Masquer /openapi.json de notre propre IP — les autres IPs restent visibles
                if path == "/openapi.json" and self._own_ip and row.get("ip") == self._own_ip:
                    continue

            visible.append(row)

        total = len(self._log_history)
        shown = len(visible)
        nc    = self._log_new_count if not search else 0
        suffix = f"  (+{nc} nouveaux)" if nc > 0 else ""
        if search:
            suffix = f"  — filtre : « {search} »"
        self._log_count_lbl.setText(f"{shown} affichés / {total} total{suffix}")

        self._log_table.setRowCount(0)
        self._log_table.setRowCount(shown)

        for i, row in enumerate(visible):
            status = row.get("status", 0)
            ms     = row.get("ms", 0)
            color  = C["green"] if status < 400 else C["amber"] if status < 500 else C["red"]
            # Surlignage vert-sombre pour les entrées nouvelles (seulement en vue "tout")
            is_new = filt == "all" and i < nc

            def _cell(txt, col=None, bg=None):
                it = QTableWidgetItem(str(txt))
                it.setForeground(QColor(col or C["text2"]))
                if bg: it.setBackground(QColor(bg))
                return it

            bg = C["green_dim"] if is_new else None
            self._log_table.setItem(i, 0, _cell(row.get("ts",""),     C["muted"], bg))
            self._log_table.setItem(i, 1, _cell(row.get("ip",""),     C["dim"],   bg))
            self._log_table.setItem(i, 2, _cell(row.get("method",""), C["amber"], bg))
            self._log_table.setItem(i, 3, _cell(row.get("path",""),   C["text2"], bg))
            self._log_table.setItem(i, 4, _cell(str(status),          color,      bg))
            self._log_table.setItem(i, 5, _cell(f"{ms}ms",            C["dim"],   bg))

    # ── Base de données ───────────────────────────────────────────────────

    def _update_db_table(self, counts: dict, sizes: dict):
        rows = sorted(counts.items(), key=lambda x: -x[1])
        self._db_table.setRowCount(len(rows))
        for i, (table, count) in enumerate(rows):
            sz = sizes.get(table, {}).get("pretty", "?")

            def _cell(txt, col=None):
                it = QTableWidgetItem(str(txt))
                it.setForeground(QColor(col or C["text2"]))
                return it

            self._db_table.setItem(i, 0, _cell(table, C["amber"]))
            self._db_table.setItem(i, 1, _cell(f"{count:,}".replace(",", " "), C["text"]))
            self._db_table.setItem(i, 2, _cell(sz, C["dim"]))

    # ── Countdown ─────────────────────────────────────────────────────────

    def _tick(self):
        if self._countdown > 0:
            self._countdown -= 1
        if self._countdown <= 0:
            self._refresh()
        else:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self._title_bar.set_refresh_label(
                f"Actualisation dans {self._countdown}s — {ts}"
            )



def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MonitorApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
