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
from PyQt6.QtCore import Qt, QPoint, QTimer, QThread, pyqtSignal, QEvent
from PyQt6.QtGui import (
    QFont, QCursor, QColor, QPainter, QPen,
    QMouseEvent, QIcon,
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
OVH_URL   = "http://51.83.74.243:8000"
OVH_KEY   = "gmp_fGPsjgfjk465fdf48ghHQd5Gsq592GAqpdGe4"
APP_VER   = "1.1.0"
REFRESH_S = 30

def _load_cfg() -> dict:
    try:
        if CFG_FILE.exists():
            return json.loads(CFG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"url": OVH_URL, "key": OVH_KEY}

def _save_cfg(d: dict):
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


# ── TitleBar ──────────────────────────────────────────────────────────────
class TitleBar(QWidget):
    def __init__(self, parent: "MonitorApp"):
        super().__init__(parent)
        self._parent   = parent
        self._drag_pos: QPoint | None = None
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

        _ws = (
            f"QPushButton {{background:transparent;color:{C['dim']};border-radius:4px;font-size:13px;}}"
            f"QPushButton:hover {{background:{C['surface2']};color:{C['text']};}}"
        )
        _wxs = (
            f"QPushButton {{background:transparent;color:{C['dim']};border-radius:4px;font-size:13px;}}"
            f"QPushButton:hover {{background:{C['red_dim']};color:{C['text']};}}"
        )
        b_min = QPushButton("─"); b_min.setFixedSize(28, 28); b_min.setStyleSheet(_ws)
        b_min.clicked.connect(parent.showMinimized)

        self._b_max = QPushButton("□"); self._b_max.setFixedSize(28, 28); self._b_max.setStyleSheet(_ws)
        self._b_max.clicked.connect(self._toggle_max)

        b_cls = QPushButton("✕"); b_cls.setFixedSize(28, 28); b_cls.setStyleSheet(_wxs)
        b_cls.clicked.connect(parent.close)

        for btn in (b_min, self._b_max, b_cls):
            lay.addWidget(btn)

    def _toggle_max(self):
        p = self._parent
        if p.isMaximized(): p.showNormal();    self._b_max.setText("□")
        else:               p.showMaximized(); self._b_max.setText("❐")

    def set_status(self, ok: bool | None, tip: str = ""):
        color = C["green"] if ok is True else C["red"] if ok is False else C["dim"]
        self._dot.setStyleSheet(f"color:{color};background:transparent;font-size:10px;")
        self._conn_lbl.setStyleSheet(
            f"color:{color};background:transparent;font-size:9px;font-family:monospace;"
        )
        if tip: self._dot.setToolTip(tip)

    def set_refresh_label(self, txt: str):
        self._refresh_lbl.setText(txt)

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self._parent.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev: QMouseEvent):
        if self._drag_pos and ev.buttons() == Qt.MouseButton.LeftButton:
            self._parent.move(ev.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _): self._drag_pos = None
    def mouseDoubleClickEvent(self, _): self._toggle_max()

# ══════════════════════════════════════════════════════════════════════════
# FENÊTRE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════
class MonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setMinimumSize(960, 700)
        self.resize(1200, 820)
        self.setStyleSheet(
            f"QMainWindow,QWidget#root{{background:{C['bg']};border:1px solid {C['border2']};}}"
        )

        icon_p = BASE_DIR / "assets" / "monitor.ico"
        if icon_p.exists(): self.setWindowIcon(QIcon(str(icon_p)))

        self._cfg       = _load_cfg()
        self._workers   : list[QThread] = []
        self._countdown = REFRESH_S

        # Historique cumulatif des logs de session
        self._log_history : collections.deque = collections.deque(maxlen=1000)
        self._log_seen    : set = set()        # clés (ts, ip, method, path) déjà vues
        self._log_filter  : str = "all"
        self._log_new_count: int = 0

        # Suivi des compteurs réseau précédents pour calcul de débit
        self._prev_net_sent: int | None = None
        self._prev_net_recv: int | None = None
        self._prev_net_time: float = 0.0

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

        QTimer.singleShot(200, self._refresh)

    # ── Construction UI ───────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        # Barre d'actions
        actions = QWidget(); actions.setStyleSheet("background:transparent;")
        ah = QHBoxLayout(actions); ah.setContentsMargins(0, 0, 0, 0); ah.setSpacing(8)

        self._url_entry = QLineEdit(self._cfg.get("url", OVH_URL))
        self._url_entry.setFixedHeight(30); self._url_entry.setFixedWidth(220)
        self._url_entry.setPlaceholderText("http://IP:PORT")
        self._url_entry.setStyleSheet(
            f"QLineEdit{{background:{C['entry']};border:1px solid {C['border2']};"
            f"border-radius:4px;padding:2px 8px;color:{C['text']};font-size:10px;font-family:monospace;}}"
        )

        self._key_entry = QLineEdit(self._cfg.get("key", OVH_KEY))
        self._key_entry.setFixedHeight(30); self._key_entry.setFixedWidth(180)
        self._key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_entry.setPlaceholderText("API Key")
        self._key_entry.setStyleSheet(
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

        save_btn = QPushButton("💾"); save_btn.setFixedSize(30, 30)
        save_btn.setStyleSheet(_btn); save_btn.setToolTip("Sauvegarder la configuration")
        save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save_btn.clicked.connect(self._save_cfg)

        refresh_btn = QPushButton("⟳  ACTUALISER"); refresh_btn.setFixedHeight(30)
        refresh_btn.setStyleSheet(_btn_red)
        refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh_btn.clicked.connect(self._refresh)

        self._latency_lbl = lbl("", size=9, mono=True, color=C["dim"])

        ah.addWidget(lbl("Serveur :", size=9, color=C["dim"]))
        ah.addWidget(self._url_entry)
        ah.addWidget(lbl("Clé :", size=9, color=C["dim"]))
        ah.addWidget(self._key_entry)
        ah.addWidget(save_btn)
        ah.addSpacing(8)
        ah.addWidget(refresh_btn)
        ah.addStretch()
        ah.addWidget(self._latency_lbl)
        lay.addWidget(actions)

        # Grille
        grid = QWidget(); grid.setStyleSheet("background:transparent;")
        gl = QGridLayout(grid); gl.setContentsMargins(0, 0, 0, 0); gl.setSpacing(10)

        # Ligne 0 : CPU · RAM · STOCKAGE · STATUT
        self._card_cpu    = MetricCard("CPU", graph_color=C["red"])
        self._card_ram    = MetricCard("RAM", graph_color=C["amber"])
        self._card_disk   = DiskCard()
        self._card_status = self._make_status_card()
        gl.addWidget(self._card_cpu,    0, 0)
        gl.addWidget(self._card_ram,    0, 1)
        gl.addWidget(self._card_disk,   0, 2)
        gl.addWidget(self._card_status, 0, 3)

        # Ligne 1 : BASE DE DONNÉES (2 cols) · RÉSEAU (2 cols)
        self._card_db      = self._make_db_card()
        self._card_network = NetworkCard()
        gl.addWidget(self._card_db,      1, 0, 1, 2)
        gl.addWidget(self._card_network, 1, 2, 1, 2)

        # Ligne 2 : Journal d'accès (4 cols, prend tout l'espace restant)
        self._card_log = self._make_log_card()
        gl.addWidget(self._card_log, 2, 0, 1, 4)

        for col in range(4): gl.setColumnStretch(col, 1)
        gl.setRowStretch(0, 0)
        gl.setRowStretch(1, 0)
        gl.setRowStretch(2, 1)

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
        cv = QVBoxLayout(card); cv.setContentsMargins(16, 12, 16, 12); cv.setSpacing(6)

        # En-tête
        hdr = QWidget(); hdr.setStyleSheet("background:transparent;")
        hh  = QHBoxLayout(hdr); hh.setContentsMargins(0, 0, 0, 0); hh.setSpacing(6)
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
        cv.addWidget(search_row)

        cv.addWidget(sep())

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
        cv.addWidget(self._log_table)
        return card

    # ── Fetch / données ───────────────────────────────────────────────────

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

    def _fetch_all(self) -> dict:
        t0   = time.time()
        sys_ = self._api("/monitor/system")
        db_  = self._api("/monitor/db")
        log_ = self._api("/monitor/access_log", n=200)
        ver_ = self._api("/version")
        lat  = round((time.time() - t0) * 1000)
        return {"sys": sys_, "db": db_, "log": log_, "ver": ver_, "lat_ms": lat}

    def _refresh(self):
        url = self._url_entry.text().strip()
        if not url: return
        self._cfg = {"url": url, "key": self._key_entry.text().strip()}
        self._countdown = REFRESH_S
        self._title_bar.set_refresh_label("Actualisation…")
        self._latency_lbl.setText("")
        self._title_bar.set_status(None)
        w = Worker(self._fetch_all)
        w.result.connect(self._on_data)
        w.error.connect(self._on_error)
        self._workers.append(w)
        w.start()

    def _on_data(self, data: dict):
        self._countdown = REFRESH_S
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

    def _on_history_data(self, data: dict):
        if not data.get("ok"):
            self._log_count_lbl.setText(f"Erreur historique : {data.get('error','?')}")
            return
        self._ingest_log_entries(data.get("log", []))
        total_file = data.get("total", 0)
        self._log_count_lbl.setText(
            f"{len(self._log_history)} entrées chargées (fichier serveur : {total_file} lignes)"
        )

    def _render_log_table(self):
        filt = self._log_filter
        visible = []
        search = self._log_search.text().strip().lower()

        for row in self._log_history:
            s = row.get("status", 0)
            # Filtre statut HTTP
            if filt == "2xx" and not (200 <= s < 300): continue
            if filt == "4xx" and not (400 <= s < 500): continue
            if filt == "5xx" and not (s >= 500):        continue
            if filt == "err" and not (s >= 400):        continue
            # Filtre texte libre
            if search:
                haystack = " ".join([
                    row.get("ts",""), row.get("ip",""),
                    row.get("method",""), row.get("path",""),
                    str(s), str(row.get("ms",""))
                ]).lower()
                if search not in haystack:
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

    # ── Redimensionnement sans bords natifs ───────────────────────────────

    _RB = 6
    _EC = {
        "n":  Qt.CursorShape.SizeVerCursor,   "s":  Qt.CursorShape.SizeVerCursor,
        "e":  Qt.CursorShape.SizeHorCursor,   "w":  Qt.CursorShape.SizeHorCursor,
        "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
        "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
    }
    _EQ = {
        "n":  Qt.Edge.TopEdge,    "s": Qt.Edge.BottomEdge,
        "e":  Qt.Edge.RightEdge,  "w": Qt.Edge.LeftEdge,
        "ne": Qt.Edge.TopEdge  | Qt.Edge.RightEdge,
        "nw": Qt.Edge.TopEdge  | Qt.Edge.LeftEdge,
        "se": Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        "sw": Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
    }

    def _edge(self, lp):
        x, y, w, h, B = lp.x(), lp.y(), self.width(), self.height(), self._RB
        L, R, T, Bo = x < B, x > w - B, y < B, y > h - B
        if T and L: return "nw"
        if T and R: return "ne"
        if Bo and L: return "sw"
        if Bo and R: return "se"
        if T: return "n"
        if Bo: return "s"
        if L: return "w"
        if R: return "e"
        return None

    def installEventFilter(self, obj): super().installEventFilter(obj)

    def eventFilter(self, _obj, ev):
        t = ev.type()
        if t == QEvent.Type.MouseMove and isinstance(ev, QMouseEvent):
            edge = self._edge(self.mapFromGlobal(ev.globalPosition().toPoint()))
            self.setCursor(QCursor(self._EC[edge])) if edge else self.unsetCursor()
        elif t == QEvent.Type.MouseButtonPress and isinstance(ev, QMouseEvent):
            if ev.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
                edge = self._edge(self.mapFromGlobal(ev.globalPosition().toPoint()))
                if edge:
                    h = self.windowHandle()
                    if h: h.startSystemResize(self._EQ[edge])
                    return True
        return False


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MonitorApp()
    win.installEventFilter(win)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
