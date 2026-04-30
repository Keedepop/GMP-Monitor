"""
GMP Monitor — Dashboard de surveillance serveur OVH
PyQt6, dark theme identique à GMAPP V5
"""
import sys, os, json, time, datetime, threading, collections
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
    QHBoxLayout, QVBoxLayout, QGridLayout, QScrollArea,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSizePolicy, QLineEdit,
)
from PyQt6.QtCore import Qt, QSize, QPoint, QTimer, QThread, pyqtSignal, QEvent
from PyQt6.QtGui import (
    QFont, QFontDatabase, QCursor, QColor, QPainter, QPen, QBrush,
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
    "red_glow":  "#1f0608",
    "amber":     "#ffb300",
    "amber_dim": "#2d1f00",
    "green":     "#00c853",
    "green_dim": "#051a0e",
    "text":      "#e8eaf0",
    "text2":     "#c8cad4",
    "dim":       "#7a8090",
    "muted":     "#4a5060",
    "entry":     "#0d0e10",
}

# ── Config connexion ──────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent.parent
CFG_FILE   = BASE_DIR / "monitor_config.json"
OVH_URL    = "http://51.83.74.243:8000"
OVH_KEY    = "gmp_fGPsjgfjk465fdf48ghHQd5Gsq592GAqpdGe4"
APP_VER    = "1.0.0"
REFRESH_S  = 30   # intervalle auto-refresh

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

# ── Helpers UI ────────────────────────────────────────────────────────────
def lbl(text="", size=12, bold=False, color=None, mono=False) -> QLabel:
    w = QLabel(text)
    f = QFont("Inter, Segoe UI", size)
    if bold: f.setWeight(QFont.Weight.Bold)
    if mono:  f.setFamily("JetBrains Mono, Consolas, monospace")
    w.setFont(f)
    col = color or C["text"]
    w.setStyleSheet(f"color:{col};background:transparent;")
    return w

def sep() -> QFrame:
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{C['border']};"); return f

def _fmt_bytes(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024: return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Po"

def _fmt_uptime(s: int) -> str:
    d, r = divmod(s, 86400)
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
        self._fn = fn; self._args = args
    def run(self):
        try:    self.result.emit(self._fn(*self._args))
        except Exception as e: self.error.emit(str(e))

# ── Gauge circulaire ──────────────────────────────────────────────────────
class Gauge(QWidget):
    def __init__(self, parent=None, size=110):
        super().__init__(parent)
        self._pct  = 0.0
        self._label = ""
        self._sz = size
        self.setFixedSize(size, size)

    def set_value(self, pct: float, label: str = ""):
        self._pct  = max(0.0, min(100.0, pct))
        self._label = label
        self.update()

    def _arc_color(self) -> str:
        if self._pct >= 85: return C["red"]
        if self._pct >= 60: return C["amber"]
        return C["green"]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = 8
        r = self._sz - 2 * m
        rect = self.rect().adjusted(m, m, -m, -m)

        pen = QPen(QColor(C["surface2"]), 10)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 225 * 16, -270 * 16)

        span = int(-270 * 16 * self._pct / 100)
        if span != 0:
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
            p.setFont(f2); p.setPen(QColor(C["dim"]))
            p.drawText(rect.adjusted(0, 18, 0, 18), Qt.AlignmentFlag.AlignCenter, self._label)

# ── MiniGraph (sparkline) ─────────────────────────────────────────────────
class MiniGraph(QWidget):
    def __init__(self, color=None, parent=None):
        super().__init__(parent)
        self._data: collections.deque = collections.deque(maxlen=60)
        self._color = color or C["green"]
        self.setFixedHeight(36)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def push(self, v: float):
        self._data.append(v); self.update()

    def paintEvent(self, _):
        if len(self._data) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pts = list(self._data)
        mx  = max(pts) or 1
        xs  = [int(i / (len(pts) - 1) * (w - 2)) + 1 for i in range(len(pts))]
        ys  = [int(h - 2 - (v / 100) * (h - 4)) for v in pts]
        pen = QPen(QColor(self._color), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for i in range(1, len(xs)):
            p.drawLine(xs[i-1], ys[i-1], xs[i], ys[i])

# ── Carte métrique ────────────────────────────────────────────────────────
class MetricCard(QWidget):
    def __init__(self, title: str, graph_color: str = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};"
            "border-radius:8px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)

        head = QWidget(); head.setStyleSheet("background:transparent;")
        hh = QHBoxLayout(head); hh.setContentsMargins(0,0,0,0)
        self._title_lbl = lbl(title, size=10, bold=True, color=C["dim"])
        hh.addWidget(self._title_lbl)
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
        bh = QHBoxLayout(body); bh.setContentsMargins(0,0,0,0); bh.setSpacing(12)

        self.gauge = Gauge(size=100)
        bh.addWidget(self.gauge)

        info = QWidget(); info.setStyleSheet("background:transparent;")
        iv = QVBoxLayout(info); iv.setContentsMargins(0,0,0,0); iv.setSpacing(3)
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
            self._badge.setText(badge)
            self._badge.show()
        else:
            self._badge.hide()
        color = C["red"] if pct >= 85 else C["amber"] if pct >= 60 else C["green"]
        self._val1.setStyleSheet(f"color:{color};background:transparent;")

# ── TitleBar ──────────────────────────────────────────────────────────────
class TitleBar(QWidget):
    def __init__(self, parent: "MonitorApp"):
        super().__init__(parent)
        self._parent = parent
        self._drag_pos: QPoint | None = None
        self.setFixedHeight(52)
        self.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 12, 0)
        lay.setSpacing(0)

        logo = lbl("GMP MONITOR", size=15, bold=True, color=C["red"])
        lay.addWidget(logo)
        lay.addSpacing(16)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color:{C['dim']};background:transparent;font-size:10px;")
        lay.addWidget(self._dot)
        lay.addSpacing(4)
        self._conn_lbl = lbl("OVH", size=9, mono=True, color=C["dim"])
        lay.addWidget(self._conn_lbl)
        lay.addSpacing(16)

        self._refresh_lbl = lbl("", size=9, mono=True, color=C["muted"])
        lay.addWidget(self._refresh_lbl)
        lay.addStretch()

        self._ver_lbl = lbl(f"v{APP_VER}", size=9, mono=True, color=C["muted"])
        lay.addWidget(self._ver_lbl)
        lay.addSpacing(16)

        _ws = f"""
            QPushButton {{ background:transparent;color:{C['dim']};border-radius:4px;font-size:13px; }}
            QPushButton:hover {{ background:{C['surface2']};color:{C['text']}; }}
        """
        _wxs = _ws.replace(
            f"QPushButton:hover {{ background:{C['surface2']};color:{C['text']}; }}",
            f"QPushButton:hover {{ background:{C['red_dim']};color:{C['text']}; }}"
        )
        b_min = QPushButton("─"); b_min.setFixedSize(28,28); b_min.setStyleSheet(_ws)
        b_min.clicked.connect(parent.showMinimized); lay.addWidget(b_min)

        self._b_max = QPushButton("□"); self._b_max.setFixedSize(28,28); self._b_max.setStyleSheet(_ws)
        self._b_max.clicked.connect(self._toggle_max); lay.addWidget(self._b_max)

        b_cls = QPushButton("✕"); b_cls.setFixedSize(28,28); b_cls.setStyleSheet(_wxs)
        b_cls.clicked.connect(parent.close); lay.addWidget(b_cls)

    def _toggle_max(self):
        p = self._parent
        if p.isMaximized(): p.showNormal(); self._b_max.setText("□")
        else:               p.showMaximized(); self._b_max.setText("❐")

    def set_status(self, ok: bool | None, tip: str = ""):
        color = C["green"] if ok is True else C["red"] if ok is False else C["dim"]
        self._dot.setStyleSheet(f"color:{color};background:transparent;font-size:10px;")
        self._conn_lbl.setStyleSheet(f"color:{color};background:transparent;font-size:9px;font-family:monospace;")
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
        self.setMinimumSize(920, 600)
        self.resize(1100, 720)
        self.setStyleSheet(f"QMainWindow,QWidget#root{{background:{C['bg']};border:1px solid {C['border2']};}}")

        icon_p = BASE_DIR / "assets" / "monitor.ico"
        if icon_p.exists(): self.setWindowIcon(QIcon(str(icon_p)))

        self._cfg = _load_cfg()
        self._workers: list[QThread] = []
        self._last_refresh: float = 0.0
        self._countdown = REFRESH_S

        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        main = QVBoxLayout(root); main.setContentsMargins(0,0,0,0); main.setSpacing(0)

        self._title_bar = TitleBar(self)
        main.addWidget(self._title_bar)

        self._content = QWidget()
        self._content.setStyleSheet(f"background:{C['bg']};")
        main.addWidget(self._content, stretch=1)

        self._build_ui()

        # Countdown timer (1s)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

        # Premier fetch
        QTimer.singleShot(200, self._refresh)

    def _build_ui(self):
        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        # ── Barre actions ──────────────────────────────────────────────────
        actions = QWidget(); actions.setStyleSheet("background:transparent;")
        ah = QHBoxLayout(actions); ah.setContentsMargins(0,0,0,0); ah.setSpacing(8)

        cfg = self._cfg
        self._url_entry = QLineEdit(cfg.get("url", OVH_URL))
        self._url_entry.setFixedHeight(30)
        self._url_entry.setPlaceholderText("http://IP:PORT")
        self._url_entry.setStyleSheet(
            f"QLineEdit{{background:{C['entry']};border:1px solid {C['border2']};"
            f"border-radius:4px;padding:2px 8px;color:{C['text']};font-size:10px;font-family:monospace;}}"
        )
        self._url_entry.setFixedWidth(220)

        self._key_entry = QLineEdit(cfg.get("key", OVH_KEY))
        self._key_entry.setFixedHeight(30)
        self._key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_entry.setPlaceholderText("API Key")
        self._key_entry.setStyleSheet(
            f"QLineEdit{{background:{C['entry']};border:1px solid {C['border2']};"
            f"border-radius:4px;padding:2px 8px;color:{C['text']};font-size:10px;font-family:monospace;}}"
        )
        self._key_entry.setFixedWidth(180)

        _btn_style = f"""
            QPushButton {{
                background:{C['surface2']};color:{C['text']};border:1px solid {C['border2']};
                border-radius:4px;padding:4px 14px;font-size:10px;font-weight:700;
            }}
            QPushButton:hover {{background:{C['border']};}}
            QPushButton:disabled {{color:{C['muted']};}}
        """
        refresh_btn = QPushButton("⟳  ACTUALISER")
        refresh_btn.setFixedHeight(30)
        refresh_btn.setStyleSheet(_btn_style.replace(
            f"background:{C['surface2']};color:{C['text']};",
            f"background:{C['red_dim']};color:{C['text']};"
        ).replace(
            f"border:1px solid {C['border2']};",
            f"border:1px solid {C['red_dim']};"
        ))
        refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh_btn.clicked.connect(self._refresh)

        save_btn = QPushButton("💾")
        save_btn.setFixedSize(30, 30)
        save_btn.setStyleSheet(_btn_style)
        save_btn.setToolTip("Sauvegarder la configuration")
        save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save_btn.clicked.connect(self._save_cfg)

        ah.addWidget(lbl("Serveur :", size=9, color=C["dim"]))
        ah.addWidget(self._url_entry)
        ah.addWidget(lbl("Clé :", size=9, color=C["dim"]))
        ah.addWidget(self._key_entry)
        ah.addWidget(save_btn)
        ah.addSpacing(8)
        ah.addWidget(refresh_btn)
        ah.addStretch()
        self._latency_lbl = lbl("", size=9, mono=True, color=C["dim"])
        ah.addWidget(self._latency_lbl)
        lay.addWidget(actions)

        # ── Grille de cartes ───────────────────────────────────────────────
        grid = QWidget(); grid.setStyleSheet("background:transparent;")
        gl = QGridLayout(grid); gl.setContentsMargins(0,0,0,0); gl.setSpacing(10)

        self._card_cpu  = MetricCard("CPU",  graph_color=C["red"])
        self._card_ram  = MetricCard("RAM",  graph_color=C["amber"])
        self._card_disk = MetricCard("DISQUE", graph_color=C["green"])
        gl.addWidget(self._card_cpu,  0, 0)
        gl.addWidget(self._card_ram,  0, 1)
        gl.addWidget(self._card_disk, 0, 2)

        # Carte uptime / statut serveur
        self._card_status = self._make_status_card()
        gl.addWidget(self._card_status, 0, 3)

        # Carte base de données
        self._card_db = self._make_db_card()
        gl.addWidget(self._card_db, 1, 0, 1, 2)

        # Carte log d'accès
        self._card_log = self._make_log_card()
        gl.addWidget(self._card_log, 1, 2, 1, 2)

        gl.setColumnStretch(0, 1); gl.setColumnStretch(1, 1)
        gl.setColumnStretch(2, 1); gl.setColumnStretch(3, 1)
        gl.setRowStretch(0, 0); gl.setRowStretch(1, 1)

        lay.addWidget(grid, stretch=1)

    def _make_status_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        cv = QVBoxLayout(card); cv.setContentsMargins(16,12,16,12); cv.setSpacing(6)
        cv.addWidget(lbl("STATUT SERVEUR", size=10, bold=True, color=C["dim"]))
        cv.addWidget(sep())

        def _row(k, v_widget):
            r = QWidget(); r.setStyleSheet("background:transparent;")
            rh = QHBoxLayout(r); rh.setContentsMargins(0,0,0,0); rh.setSpacing(8)
            rh.addWidget(lbl(k, size=9, color=C["dim"]))
            rh.addStretch()
            rh.addWidget(v_widget)
            return r

        self._st_uptime_srv = lbl("—", size=10, mono=True)
        self._st_uptime_api = lbl("—", size=10, mono=True)
        self._st_load       = lbl("—", size=10, mono=True)
        self._st_ping       = lbl("—", size=10, mono=True)
        self._st_version    = lbl("—", size=10, mono=True)
        self._st_requests   = lbl("—", size=10, mono=True)

        cv.addWidget(_row("Uptime serveur",  self._st_uptime_srv))
        cv.addWidget(_row("Uptime API",      self._st_uptime_api))
        cv.addWidget(_row("Charge (1m)",     self._st_load))
        cv.addWidget(_row("Latence API",     self._st_ping))
        cv.addWidget(_row("Requêtes loggées",self._st_requests))
        cv.addWidget(_row("Dernière version",self._st_version))
        cv.addStretch()
        return card

    def _make_db_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:{C['surface']};border:1px solid {C['border']};border-radius:8px;"
        )
        cv = QVBoxLayout(card); cv.setContentsMargins(16,12,16,12); cv.setSpacing(6)
        cv.addWidget(lbl("BASE DE DONNÉES", size=10, bold=True, color=C["dim"]))
        cv.addWidget(sep())

        self._db_table = QTableWidget(0, 3)
        self._db_table.setHorizontalHeaderLabels(["Table", "Lignes", "Taille"])
        self._db_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._db_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._db_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._db_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._db_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._db_table.setAlternatingRowColors(False)
        self._db_table.verticalHeader().setVisible(False)
        self._db_table.setShowGrid(False)
        self._db_table.setStyleSheet(f"""
            QTableWidget {{
                background:{C['surface']};border:none;color:{C['text']};
                font-size:10px;gridline-color:{C['border']};
            }}
            QHeaderView::section {{
                background:{C['surface2']};color:{C['dim']};
                border:none;border-bottom:1px solid {C['border']};
                padding:4px 8px;font-size:9px;font-weight:700;
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
        cv = QVBoxLayout(card); cv.setContentsMargins(16,12,16,12); cv.setSpacing(6)

        hdr = QWidget(); hdr.setStyleSheet("background:transparent;")
        hh = QHBoxLayout(hdr); hh.setContentsMargins(0,0,0,0)
        hh.addWidget(lbl("JOURNAL D'ACCÈS API", size=10, bold=True, color=C["dim"]))
        hh.addStretch()
        self._log_count_lbl = lbl("", size=9, mono=True, color=C["muted"])
        hh.addWidget(self._log_count_lbl)
        cv.addWidget(hdr)
        cv.addWidget(sep())

        self._log_table = QTableWidget(0, 5)
        self._log_table.setHorizontalHeaderLabels(["Horodatage", "IP", "Méthode", "Chemin", "Statut / ms"])
        self._log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._log_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._log_table.verticalHeader().setVisible(False)
        self._log_table.setShowGrid(False)
        self._log_table.setAlternatingRowColors(False)
        self._log_table.setStyleSheet(f"""
            QTableWidget {{
                background:{C['surface']};border:none;color:{C['text']};font-size:9px;
                font-family:monospace;
            }}
            QHeaderView::section {{
                background:{C['surface2']};color:{C['dim']};
                border:none;border-bottom:1px solid {C['border']};
                padding:3px 8px;font-size:9px;font-weight:700;
            }}
            QTableWidget::item {{padding:2px 8px;border-bottom:1px solid {C['border']};}}
            QTableWidget::item:selected {{background:{C['surface2']};}}
        """)
        self._log_table.verticalHeader().setDefaultSectionSize(22)
        cv.addWidget(self._log_table)
        return card

    # ── Logique fetch ─────────────────────────────────────────────────────

    def _save_cfg(self):
        url = self._url_entry.text().strip().rstrip("/")
        key = self._key_entry.text().strip()
        self._cfg = {"url": url, "key": key}
        _save_cfg(self._cfg)

    def _api(self, path: str, n: int | None = None) -> Any:
        url  = self._cfg.get("url", OVH_URL).rstrip("/")
        key  = self._cfg.get("key", OVH_KEY)
        full = f"{url}{path}" + (f"?n={n}" if n else "")
        req  = urllib.request.Request(full, headers={"X-API-Key": key})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def _fetch_all(self) -> dict:
        t0   = time.time()
        sys_ = self._api("/monitor/system")
        db_  = self._api("/monitor/db")
        log_ = self._api("/monitor/access_log", n=80)
        ver_ = self._api("/version")
        lat  = round((time.time() - t0) * 1000)
        return {"sys": sys_, "db": db_, "log": log_, "ver": ver_, "lat_ms": lat}

    def _refresh(self):
        url = self._url_entry.text().strip()
        key = self._key_entry.text().strip()
        if not url:
            return
        self._cfg = {"url": url, "key": key}
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
        self._last_refresh = time.time()
        self._countdown = REFRESH_S
        self._title_bar.set_status(True, "Serveur OVH connecté")
        lat = data.get("lat_ms", 0)
        self._latency_lbl.setText(f"latence {lat} ms")

        sys_ = data.get("sys", {})
        db_  = data.get("db",  {})
        log_ = data.get("log", {})
        ver_ = data.get("ver", {})

        if sys_.get("ok"):
            cpu  = sys_.get("cpu_percent", 0)
            ramp = sys_.get("ram_percent", 0)
            ramt = sys_.get("ram_total", 0)
            ramu = sys_.get("ram_used",  0)
            diskp = sys_.get("disk_percent", 0)
            diskt = sys_.get("disk_total", 0)
            disku = sys_.get("disk_used",  0)
            load  = sys_.get("load_avg", [])
            uptime = sys_.get("uptime_s", 0)

            self._card_cpu.update_values(
                cpu, f"{cpu:.1f} %",
                f"{os.cpu_count() or '?'} cœurs logiques",
            )
            self._card_ram.update_values(
                ramp, f"{ramp:.1f} %",
                f"{_fmt_bytes(ramu)} / {_fmt_bytes(ramt)}",
                badge=f"{_fmt_bytes(ramt - ramu)} libre"
            )
            self._card_disk.update_values(
                diskp, f"{diskp:.1f} %",
                f"{_fmt_bytes(disku)} / {_fmt_bytes(diskt)}",
                badge=f"{_fmt_bytes(diskt - disku)} libre"
            )
            self._st_uptime_srv.setText(_fmt_uptime(uptime))
            self._st_load.setText(f"{load[0]:.2f}" if load else "—")
        else:
            err = sys_.get("error", "Indisponible")
            for card in (self._card_cpu, self._card_ram, self._card_disk):
                card.gauge.set_value(0)

        if log_.get("ok"):
            up_api = log_.get("uptime_api_s", 0)
            total  = log_.get("total", 0)
            self._st_uptime_api.setText(_fmt_uptime(up_api))
            self._st_requests.setText(str(total))
            self._update_log_table(log_.get("log", []))

        if db_.get("ok"):
            self._update_db_table(db_.get("counts", {}), db_.get("sizes", {}))

        self._st_ping.setText(f"{lat} ms")
        self._st_version.setText(ver_.get("version", "?"))

    def _on_error(self, err: str):
        self._title_bar.set_status(False, f"Erreur : {err[:80]}")
        self._title_bar.set_refresh_label(f"Erreur — {err[:60]}")

    def _update_log_table(self, rows: list):
        self._log_count_lbl.setText(f"{len(rows)} entrées")
        self._log_table.setRowCount(0)
        self._log_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            status = row.get("status", 0)
            ms     = row.get("ms", 0)
            color  = C["green"] if status < 400 else C["amber"] if status < 500 else C["red"]

            def _item(txt, col=None):
                it = QTableWidgetItem(str(txt))
                it.setForeground(QColor(col or C["text2"]))
                return it

            self._log_table.setItem(i, 0, _item(row.get("ts",""), C["muted"]))
            self._log_table.setItem(i, 1, _item(row.get("ip",""), C["dim"]))
            self._log_table.setItem(i, 2, _item(row.get("method",""), C["amber"]))
            self._log_table.setItem(i, 3, _item(row.get("path",""), C["text2"]))
            self._log_table.setItem(i, 4, _item(f"{status}  {ms}ms", color))

    def _update_db_table(self, counts: dict, sizes: dict):
        rows = sorted(counts.items(), key=lambda x: -x[1])
        self._db_table.setRowCount(len(rows))
        for i, (table, count) in enumerate(rows):
            sz = sizes.get(table, {}).get("pretty", "?")

            def _item(txt, col=None):
                it = QTableWidgetItem(str(txt))
                it.setForeground(QColor(col or C["text2"]))
                return it

            self._db_table.setItem(i, 0, _item(table, C["amber"]))
            self._db_table.setItem(i, 1, _item(f"{count:,}".replace(",", " "), C["text"]))
            self._db_table.setItem(i, 2, _item(sz, C["dim"]))

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

    # ── Resize drag ───────────────────────────────────────────────────────
    def resizeEvent(self, ev):
        super().resizeEvent(ev)

    _RB = 6
    _EC = {
        "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
        "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
        "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
        "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
    }
    _EQ = {
        "n": Qt.Edge.TopEdge, "s": Qt.Edge.BottomEdge,
        "e": Qt.Edge.RightEdge, "w": Qt.Edge.LeftEdge,
        "ne": Qt.Edge.TopEdge|Qt.Edge.RightEdge, "nw": Qt.Edge.TopEdge|Qt.Edge.LeftEdge,
        "se": Qt.Edge.BottomEdge|Qt.Edge.RightEdge, "sw": Qt.Edge.BottomEdge|Qt.Edge.LeftEdge,
    }
    def _edge(self, lp):
        x,y,w,h,B = lp.x(),lp.y(),self.width(),self.height(),self._RB
        L,R,T,Bo = x<B, x>w-B, y<B, y>h-B
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
