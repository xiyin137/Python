import sys
import json
import os
import uuid
import subprocess
import textwrap
import re
import shutil
import tempfile
import copy
from datetime import datetime
from io import BytesIO

# --- PYQT6 IMPORTS ---
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
                             QLabel, QLineEdit, QTextEdit, QPushButton, QSplitter, QComboBox, 
                             QMessageBox, QScrollArea, QListWidget, QListWidgetItem,
                             QInputDialog, QFileDialog, QTabWidget, QDialog, 
                             QRadioButton, QButtonGroup, QAbstractItemView, QSlider, QSpinBox,
                             QSizePolicy, QToolBar, QMenu, QFrame, QColorDialog, QCheckBox, QStyle,
                             QGridLayout)
from PyQt6.QtCore import Qt, QPoint, QTimer, QSize, QUrl, QRect
from PyQt6.QtGui import (QPixmap, QImage, QFont, QPainter, QPen, QAction, 
                         QDesktopServices, QCursor, QColor, QIcon, QPalette, QBrush)

# --- MATPLOTLIB SETUP ---
import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

# --- PHYSICS FONT STYLING ---
matplotlib.rcParams['mathtext.fontset'] = 'cm'
matplotlib.rcParams['font.family'] = 'serif' 
matplotlib.rcParams['font.serif'] = ['cmr10']

# --- CONFIGURATION ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(SCRIPT_DIR, "research_tree.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "app_config.json") 
IMG_DIR = os.path.join(SCRIPT_DIR, "research_images")
TEMP_WOLFRAM_IMG_BASE = os.path.join(SCRIPT_DIR, "temp_wolfram_plot").replace("\\", "/")

if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR)

# --- THEME UTILS ---
def apply_dark_theme(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(palette)

# --- CUSTOM WIDGETS ---

class ResizableDraggableContainer(QWidget):
    MARGIN = 10
    MIN_SIZE = 50
    NONE = 0
    MOVE = 1
    RESIZE_L = 2
    RESIZE_R = 3
    RESIZE_T = 4
    RESIZE_B = 5
    RESIZE_TL = 6
    RESIZE_TR = 7
    RESIZE_BL = 8
    RESIZE_BR = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.mode = self.NONE
        self.drag_start_pos = None
        self.rect_start = None
        self.setAutoFillBackground(False)
        self.setStyleSheet("QWidget { border: 1px dashed #777; background-color: rgba(0,0,0,10); }")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        del_action = QAction("Delete Item", self)
        del_action.triggered.connect(self.deleteLater)
        menu.addAction(del_action)
        menu.exec(self.mapToGlobal(pos))

    def _get_resize_mode(self, pos):
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        m = self.MARGIN
        if x < m and y < m: return self.RESIZE_TL
        if x > w - m and y < m: return self.RESIZE_TR
        if x < m and y > h - m: return self.RESIZE_BL
        if x > w - m and y > h - m: return self.RESIZE_BR
        if x < m: return self.RESIZE_L
        if x > w - m: return self.RESIZE_R
        if y < m: return self.RESIZE_T
        if y > h - m: return self.RESIZE_B
        return self.MOVE

    def _set_cursor_shape(self, mode):
        if mode in (self.RESIZE_TL, self.RESIZE_BR): self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif mode in (self.RESIZE_TR, self.RESIZE_BL): self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif mode in (self.RESIZE_L, self.RESIZE_R): self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif mode in (self.RESIZE_T, self.RESIZE_B): self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif mode == self.MOVE: self.setCursor(Qt.CursorShape.SizeAllCursor)
        else: self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mode = self._get_resize_mode(event.pos())
            self.drag_start_pos = event.scenePosition().toPoint()
            self.rect_start = self.geometry()
            self.raise_()

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.MouseButton.LeftButton:
            mode = self._get_resize_mode(event.pos())
            self._set_cursor_shape(mode)
            return
        if self.mode == self.NONE or not self.drag_start_pos: return
        
        curr_pos = event.scenePosition().toPoint()
        
        delta = curr_pos - self.drag_start_pos
        dx, dy = delta.x(), delta.y()
        r = QRect(self.rect_start)
        if self.mode == self.MOVE: r.translate(dx, dy)
        elif self.mode == self.RESIZE_BR:
            r.setWidth(max(self.MIN_SIZE, self.rect_start.width() + dx))
            r.setHeight(max(self.MIN_SIZE, self.rect_start.height() + dy))
        elif self.mode == self.RESIZE_BL:
            new_w = max(self.MIN_SIZE, self.rect_start.width() - dx)
            r.setLeft(self.rect_start.right() - new_w)
            r.setWidth(new_w)
            r.setHeight(max(self.MIN_SIZE, self.rect_start.height() + dy))
        elif self.mode == self.RESIZE_TR:
            new_h = max(self.MIN_SIZE, self.rect_start.height() - dy)
            r.setWidth(max(self.MIN_SIZE, self.rect_start.width() + dx))
            r.setTop(self.rect_start.bottom() - new_h)
            r.setHeight(new_h)
        elif self.mode == self.RESIZE_TL:
            new_w = max(self.MIN_SIZE, self.rect_start.width() - dx)
            new_h = max(self.MIN_SIZE, self.rect_start.height() - dy)
            r.setLeft(self.rect_start.right() - new_w)
            r.setWidth(new_w)
            r.setTop(self.rect_start.bottom() - new_h)
            r.setHeight(new_h)
        elif self.mode == self.RESIZE_R: r.setWidth(max(self.MIN_SIZE, self.rect_start.width() + dx))
        elif self.mode == self.RESIZE_L:
            new_w = max(self.MIN_SIZE, self.rect_start.width() - dx)
            r.setLeft(self.rect_start.right() - new_w)
            r.setWidth(new_w)
        elif self.mode == self.RESIZE_B: r.setHeight(max(self.MIN_SIZE, self.rect_start.height() + dy))
        elif self.mode == self.RESIZE_T:
            new_h = max(self.MIN_SIZE, self.rect_start.height() - dy)
            r.setTop(self.rect_start.bottom() - new_h)
            r.setHeight(new_h)
        self.setGeometry(r)

    def mouseReleaseEvent(self, event):
        self.mode = self.NONE


class ImageContainer(ResizableDraggableContainer):
    def __init__(self, pixmap, title_text, parent=None, image_path=None):
        super().__init__(parent)
        self.image_path = image_path 
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.lbl_title = QLabel(title_text)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet("background-color: rgba(42, 130, 218, 200); color: #fff; font-weight: bold; padding: 2px;")
        self.lbl_title.setFixedHeight(20)
        layout.addWidget(self.lbl_title)
        self.lbl_image = QLabel()
        self.lbl_image.setScaledContents(True)
        self.lbl_image.setPixmap(pixmap)
        self.lbl_image.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.lbl_image)
        self.original_pixmap = pixmap
        start_w = 400
        aspect = pixmap.height() / pixmap.width()
        start_h = int(start_w * aspect) + 20
        self.resize(start_w, start_h)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class TextContainer(ResizableDraggableContainer):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.text_edit = QTextEdit()
        self.text_edit.setText(text)
        self.text_edit.setFont(QFont("Arial", 12))
        self.text_edit.setStyleSheet("background-color: transparent; border: none; color: #000;")
        layout.addWidget(self.text_edit)
        self.resize(250, 150)

class ResearchTreeWidget(QTreeWidget):
    def __init__(self, drop_callback, parent=None):
        super().__init__(parent)
        self.drop_callback = drop_callback
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHeaderHidden(False)
        self.setStyleSheet("QTreeWidget { font-size: 13px; } QHeaderView::section { background-color: #333; color: white; }")

    def dropEvent(self, event):
        super().dropEvent(event)
        self.drop_callback()

# --- CONFIG MANAGER ---
class ConfigManager:
    @staticmethod
    def load_config():
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: return json.load(f)
            except: pass
        return {}

    @staticmethod
    def save_config(data):
        try:
            with open(CONFIG_FILE, 'w') as f: json.dump(data, f, indent=4)
        except: pass

    @staticmethod
    def get_last_file():
        cfg = ConfigManager.load_config()
        path = cfg.get("last_opened", DEFAULT_DATA_FILE)
        if os.path.exists(path): return path
        return DEFAULT_DATA_FILE

    @staticmethod
    def set_last_file(path):
        cfg = ConfigManager.load_config()
        cfg["last_opened"] = path
        ConfigManager.save_config(cfg)

    @staticmethod
    def get_wolfram_path():
        cfg = ConfigManager.load_config()
        return cfg.get("wolfram_path", None)

    @staticmethod
    def set_wolfram_path(path):
        cfg = ConfigManager.load_config()
        cfg["wolfram_path"] = path
        ConfigManager.save_config(cfg)

# --- HELPER: FIND WOLFRAM ---
def locate_wolfram_engine():
    custom_path = ConfigManager.get_wolfram_path()
    if custom_path and os.path.exists(custom_path): return custom_path
    manual_checks = ["/usr/local/bin/wolframscript", "/opt/homebrew/bin/wolframscript", "/usr/bin/wolframscript"]
    for p in manual_checks:
        if os.path.exists(p): return p
    path = shutil.which("wolframscript")
    if path: return path
    paths = [
        "/Applications/WolframScript.app/Contents/MacOS/wolframscript",
        "/Applications/Mathematica.app/Contents/MacOS/wolframscript",
        r"C:\Program Files\Wolfram Research\WolframScript\wolframscript.exe",
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def sanitize_app_path(path):
    if path.endswith(".app"):
        possible_bins = [os.path.join(path, "Contents", "MacOS", "wolframscript"),
                         os.path.join(path, "Contents", "MacOS", "WolframKernel")]
        for p in possible_bins:
            if os.path.exists(p): return p
    return path

# --- DRAWING WIDGET ---
class ScribbleArea(QWidget):
    MODE_DRAW = 0
    MODE_ERASE = 1
    MODE_TEXT = 2
    MODE_IMAGE = 3
    MODE_HIGHLIGHT = 4 
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents)
        self.canvas_width = 2000
        self.canvas_height = 2000
        self.setFixedSize(self.canvas_width, self.canvas_height)
        self.current_mode = self.MODE_DRAW
        self.scribbling = False
        self.myPenWidth = 2
        self.myPenColor = Qt.GlobalColor.black
        self.show_grid = False
        self.undo_stack = []
        self.image = QImage(self.canvas_width, self.canvas_height, QImage.Format.Format_ARGB32_Premultiplied)
        self.image.fill(Qt.GlobalColor.white) 
        self.lastPoint = QPoint()

    def set_mode(self, mode):
        self.current_mode = mode
        if mode == self.MODE_TEXT: self.setCursor(Qt.CursorShape.IBeamCursor)
        elif mode == self.MODE_ERASE: self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == self.MODE_HIGHLIGHT: self.setCursor(Qt.CursorShape.ArrowCursor)
        else: self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_pen_color(self, color): self.myPenColor = color
    def set_pen_width(self, width): self.myPenWidth = width

    def toggle_grid(self, show):
        self.show_grid = show
        self.update()

    def save_undo_state(self):
        if len(self.undo_stack) > 10: self.undo_stack.pop(0)
        self.undo_stack.append(self.image.copy())

    def undo(self):
        if self.undo_stack:
            self.image = self.undo_stack.pop()
            self.update()

    def clear_canvas(self):
        self.save_undo_state()
        self.image.fill(Qt.GlobalColor.white)
        for child in self.children():
            if isinstance(child, (ImageContainer, TextContainer)): child.deleteLater()
        self.update()
        
    def flatten_layers(self):
        self.save_undo_state()
        painter = QPainter(self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        children_to_process = [c for c in self.children() if isinstance(c, (ImageContainer, TextContainer))]
        for child in children_to_process:
            pos = child.pos()
            if isinstance(child, ImageContainer):
                title_h = child.lbl_title.height()
                painter.fillRect(pos.x(), pos.y(), child.width(), title_h, QColor(42, 130, 218, 200))
                painter.setPen(Qt.GlobalColor.white)
                painter.drawText(QRect(pos.x(), pos.y(), child.width(), title_h), Qt.AlignmentFlag.AlignCenter, child.lbl_title.text())
                pix = child.lbl_image.pixmap()
                if pix:
                    img_rect = QRect(pos.x(), pos.y() + title_h, child.lbl_image.width(), child.lbl_image.height())
                    painter.drawPixmap(img_rect, pix)
            elif isinstance(child, TextContainer):
                inner_pos = child.mapToParent(child.text_edit.pos())
                child.text_edit.render(painter, inner_pos)
            child.deleteLater()
        painter.end()
        self.update()

    def set_background_image(self, file_path):
        loaded_image = QImage()
        if loaded_image.load(file_path):
            w = max(self.canvas_width, loaded_image.width())
            h = max(self.canvas_height, loaded_image.height())
            if w > self.canvas_width or h > self.canvas_height:
                self.canvas_width = w
                self.canvas_height = h
                self.setFixedSize(w, h)
                self.image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            loaded_image = loaded_image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            painter = QPainter(self.image)
            painter.fillRect(self.image.rect(), Qt.GlobalColor.white)
            painter.drawImage(0, 0, loaded_image)
            painter.end()
            self.update()

    def save_background(self, file_path):
        self.image.save(file_path)

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = event.rect()
        painter.drawImage(rect, self.image, rect)
        if self.show_grid: self._draw_grid_overlay(painter, rect)

    def _draw_grid_overlay(self, painter, rect):
        grid_pen = QPen(QColor(200, 200, 200)) 
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        step = 40
        l, r, t, b = rect.left(), rect.right(), rect.top(), rect.bottom()
        start_x = (l // step) * step
        start_y = (t // step) * step
        for x in range(start_x, r + step, step): painter.drawLine(x, t, x, b)
        for y in range(start_y, b + step, step): painter.drawLine(l, y, r, y)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.current_mode == self.MODE_TEXT:
                self.add_text_widget(event.pos())
                self.set_mode(self.MODE_DRAW) 
            else:
                self.save_undo_state()
                self.lastPoint = event.position().toPoint()
                self.scribbling = True

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton) and self.scribbling:
            self.drawLineTo(event.position().toPoint())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.scribbling:
            self.drawLineTo(event.position().toPoint())
            self.scribbling = False

    def drawLineTo(self, endPoint):
        painter = QPainter(self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.current_mode == self.MODE_ERASE:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source) 
            painter.setPen(QPen(Qt.GlobalColor.white, self.myPenWidth * 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        elif self.current_mode == self.MODE_HIGHLIGHT:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply) 
            pen = QPen(QColor(255, 255, 0), self.myPenWidth * 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.BevelJoin)
            painter.setPen(pen)
        else:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(self.myPenColor, self.myPenWidth, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(self.lastPoint, endPoint)
        self.update()
        self.lastPoint = endPoint

    def add_text_widget(self, pos, text=""):
        tc = TextContainer(text, self)
        tc.move(pos)
        tc.show()
        return tc

    def add_image_widget(self, path, title="Image"):
        pix = QPixmap(path)
        if not pix.isNull():
            ic = ImageContainer(pix, title, self, path)
            ic.move(50, 50)
            ic.show()
            return ic
        return None

# --- DATA MANAGER ---
class DataManager:
    @staticmethod
    def load_data(filepath):
        if not os.path.exists(filepath): return {"settings": {}, "topics": []}
        try:
            with open(filepath, "r") as f:
                raw_data = json.load(f)
                if isinstance(raw_data, list): return {"settings": {}, "topics": raw_data}
                return raw_data
        except Exception as e:
            print(f"Load Error: {e}")
            return {"settings": {}, "topics": []}

    @staticmethod
    def save_data(data_wrapper, filepath):
        try:
            with open(filepath, "w") as f: json.dump(data_wrapper, f, indent=4)
        except IOError as e: print(f"Error saving file: {e}")

# --- MATH RENDERER (Fixed: Smart Wrap + Auto-Crop) ---
def render_content_to_pixmap(text_content, fontsize=14):
    if not text_content: return None
    try:
        math_pattern = r'\$.*?\$'
        lines = []
        paragraphs = text_content.split('\n')
        
        # 1. Increase wrap width significantly (from 90 to 110).
        # This prevents LaTeX-heavy lines from wrapping too early.
        wrap_width = int(110 * (14.0 / fontsize))
        
        for paragraph in paragraphs:
            math_chunks = re.findall(math_pattern, paragraph)
            placeholder_text = paragraph
            for i, chunk in enumerate(math_chunks):
                # Use a placeholder that is unique but not excessively long
                placeholder_text = placeholder_text.replace(chunk, f"__M{i}__", 1)
            
            wrapped = textwrap.wrap(placeholder_text, width=wrap_width)
            if not wrapped and not paragraph.strip(): wrapped = [""]
            
            for i, line in enumerate(wrapped):
                for j, chunk in enumerate(math_chunks):
                    placeholder = f"__M{j}__"
                    if placeholder in line: line = line.replace(placeholder, chunk)
                wrapped[i] = line
            lines.extend(wrapped)
            
        final_text = "\n".join(lines)
        
        line_height_factor = 0.045 * fontsize 
        height = max(0.5, len(lines) * line_height_factor) + 0.5
        
        # 2. Use a VERY wide figure (16 inches) to ensure nothing is ever cut off on the right.
        # The 'tight' layout saving later will strip the unused space.
        fig = Figure(figsize=(16.0, height), dpi=150, facecolor='#252525') 
        canvas = FigureCanvasAgg(fig)
        
        fig.text(0.01, 0.98, final_text, fontsize=fontsize, color='white',
                 horizontalalignment='left', verticalalignment='top', wrap=True)
                 
        canvas.draw()
        buf = BytesIO()
        
        # 3. bbox_inches='tight' calculates the exact bounding box of the text 
        # and crops the image to fit. This removes the large empty gap on the right.
        # pad_inches adds a small breathing room.
        fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.2, facecolor=fig.get_facecolor())
        buf.seek(0)
        return QPixmap.fromImage(QImage.fromData(buf.getvalue()))
    except Exception as e: 
        print(f"Render Error: {e}")
        return None

# --- SETTINGS DIALOG ---
class SettingsDialog(QDialog):
    def __init__(self, current_interval, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setGeometry(300, 300, 300, 200)
        self.interval = current_interval
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Auto-Save Interval:"))
        self.group = QButtonGroup(self)
        self.r1 = QRadioButton("Manual Only")
        self.r2 = QRadioButton("30 Seconds")
        self.r3 = QRadioButton("1 Minute")
        self.r4 = QRadioButton("5 Minutes")
        self.group.addButton(self.r1, 0)
        self.group.addButton(self.r2, 30000)
        self.group.addButton(self.r3, 60000)
        self.group.addButton(self.r4, 300000)
        btn = self.group.button(current_interval)
        if btn: btn.setChecked(True)
        else: self.r1.setChecked(True)
        layout.addWidget(self.r1); layout.addWidget(self.r2); layout.addWidget(self.r3); layout.addWidget(self.r4)
        btn_save = QPushButton("Save Settings")
        btn_save.clicked.connect(self.save_and_close)
        layout.addWidget(btn_save)
        self.setLayout(layout)
    def save_and_close(self):
        self.interval = self.group.checkedId()
        self.accept()

# --- MAIN GUI ---
class PhysicsApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Theoretical Physics Organizer")
        self.setGeometry(100, 100, 1400, 900)
        
        self.current_file = ConfigManager.get_last_file()
        self.data_wrapper = DataManager.load_data(self.current_file)
        self.data = self.data_wrapper["topics"]
        self.settings = self.data_wrapper["settings"]
        
        self.current_idea_id = None
        self.autosave_interval = self.settings.get("autosave_interval", 0)
        self.latex_pixmap_original = None
        self.tree_undo_stack = [] 
        
        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(1000) 
        self.render_timer.timeout.connect(self.render_preview)
        
        self.timer = QTimer()
        if self.autosave_interval > 0: self.timer.start(self.autosave_interval)
        self.timer.timeout.connect(self.auto_save)
        
        self.create_menu()
        self.init_ui()
        self.setWindowTitle(f"Theoretical Physics Organizer - {os.path.basename(self.current_file)}")

    def create_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')
        open_action = QAction('Open Database...', self)
        open_action.triggered.connect(self.open_database)
        file_menu.addAction(open_action)
        save_as_action = QAction('Save Database As...', self)
        save_as_action.triggered.connect(self.save_database_as)
        file_menu.addAction(save_as_action)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 1. LEFT PANEL
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5,5,5,5)
        
        left_label = QLabel("📚 Research Tree")
        left_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        left_layout.addWidget(left_label)

        self.tree_widget = ResearchTreeWidget(self.on_tree_dropped)
        self.tree_widget.setColumnCount(2)
        self.tree_widget.setHeaderLabels(["Topic", "Status"])
        
        # --- RESTORE COLUMN WIDTHS FROM SETTINGS ---
        col0_w = self.settings.get("tree_col0_width", 160)
        col1_w = self.settings.get("tree_col1_width", 100)
        self.tree_widget.setColumnWidth(0, col0_w)
        self.tree_widget.setColumnWidth(1, col1_w)
        
        # CONNECT SIGNALS TO SAVE WIDTHS IMMEDIATELY
        self.tree_widget.header().sectionResized.connect(self.save_ui_layout_state)
        
        self.tree_widget.itemClicked.connect(self.on_tree_select)
        left_layout.addWidget(self.tree_widget, 1)
        
        # --- LEFT BUTTONS: 2x2 Grid Layout ---
        tree_btn_layout = QGridLayout()
        tree_btn_layout.setSpacing(5)
        
        self.btn_root = QPushButton("+ Root")
        self.btn_root.clicked.connect(self.add_root_topic)
        self.btn_root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.btn_sub = QPushButton("+ Child")
        self.btn_sub.clicked.connect(self.add_sub_topic)
        self.btn_sub.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.btn_del = QPushButton("− Delete")
        self.btn_del.setStyleSheet("color: #ff6b6b;") 
        self.btn_del.clicked.connect(self.delete_item)
        self.btn_del.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.btn_undo_tree = QPushButton("↩ Undo")
        self.btn_undo_tree.setToolTip("Undo last structure change")
        self.btn_undo_tree.clicked.connect(self.undo_tree_action)
        self.btn_undo_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        tree_btn_layout.addWidget(self.btn_root, 0, 0)
        tree_btn_layout.addWidget(self.btn_sub, 0, 1)
        tree_btn_layout.addWidget(self.btn_del, 1, 0)
        tree_btn_layout.addWidget(self.btn_undo_tree, 1, 1)
        
        left_layout.addLayout(tree_btn_layout)
        
        # --- BOTTOM BUTTONS: 1x2 Row ---
        bottom_btns = QHBoxLayout()
        self.btn_save = QPushButton("💾 Save All")
        self.btn_save.setStyleSheet("background-color: #007AFF; color: white; font-weight: bold; padding: 6px; border-radius: 4px;")
        self.btn_save.clicked.connect(lambda: self.save_current_idea(manual=True))
        
        self.btn_settings = QPushButton("⚙️ Config")
        self.btn_settings.clicked.connect(self.open_settings)
        
        bottom_btns.addWidget(self.btn_save)
        bottom_btns.addWidget(self.btn_settings)
        left_layout.addLayout(bottom_btns)

        # 2. RIGHT PANEL
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5,5,5,5)

        # Header
        self.input_title = QLineEdit()
        self.input_title.setPlaceholderText("Topic Title")
        self.input_title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.input_title.setStyleSheet("padding: 5px; border: 1px solid #444; border-radius: 4px; background: #333; color: white;")
        self.input_title.textChanged.connect(self.update_title_live)
        
        self.combo_status = QComboBox()
        self.combo_status.addItems(["Idea", "Deriving", "Drafting", "Published", "Abandoned"])
        self.combo_status.setStyleSheet("padding: 5px;")
        self.combo_status.currentIndexChanged.connect(self.update_tree_status_live)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(self.input_title, 1)
        header_layout.addWidget(QLabel("Status:"))
        header_layout.addWidget(self.combo_status)
        right_layout.addLayout(header_layout)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #444; } QTabBar::tab { background: #333; color: #aaa; padding: 8px; } QTabBar::tab:selected { background: #555; color: white; }")
        
        # --- TAB 1: NOTES ---
        self.tab_notes = QWidget()
        notes_layout = QVBoxLayout(self.tab_notes)
        
        self.notes_splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.input_content = QTextEdit()
        self.input_content.setPlaceholderText("Notes & Derivations... (Use $...$ for LaTeX)")
        self.input_content.setFont(QFont("Consolas", 11))
        self.input_content.setStyleSheet("background-color: #252525; color: #e0e0e0; border: none; padding: 5px;")
        self.input_content.textChanged.connect(lambda: self.render_timer.start())
        
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0,0,0,0)
        
        prev_ctrl_layout = QHBoxLayout()
        self.btn_render = QPushButton("Force Update Preview")
        self.btn_render.clicked.connect(self.render_preview)
        
        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(8, 40)
        self.spin_font_size.setValue(14)
        self.spin_font_size.setPrefix("Font Size: ")
        self.spin_font_size.valueChanged.connect(self.render_preview)
        
        self.slider_latex_zoom = QSlider(Qt.Orientation.Horizontal)
        self.slider_latex_zoom.setRange(50, 200)
        self.slider_latex_zoom.setValue(100)
        self.slider_latex_zoom.valueChanged.connect(self.update_latex_zoom)
        
        prev_ctrl_layout.addWidget(self.btn_render)
        prev_ctrl_layout.addWidget(self.spin_font_size)
        prev_ctrl_layout.addWidget(QLabel("  View Zoom:"))
        prev_ctrl_layout.addWidget(self.slider_latex_zoom)
        prev_ctrl_layout.addStretch()

        self.lbl_preview = QLabel("Math Preview (Auto-updates)")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_preview.setStyleSheet("background: #252525; padding: 10px; color: #888;")
        
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidget(self.lbl_preview)
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setStyleSheet("background: #252525; border: none;")
        
        preview_layout.addLayout(prev_ctrl_layout)
        preview_layout.addWidget(self.preview_scroll)
        
        self.notes_splitter.addWidget(self.input_content)
        self.notes_splitter.addWidget(preview_container)
        notes_layout.addWidget(self.notes_splitter)
        
        # --- TAB 2: SCRATCH PAPER ---
        self.tab_scratch = QWidget()
        scratch_main_layout = QVBoxLayout(self.tab_scratch)
        
        scratch_toolbar = QFrame()
        scratch_toolbar.setStyleSheet("background-color: #444; border-bottom: 1px solid #555;")
        st_layout = QHBoxLayout(scratch_toolbar)
        st_layout.setContentsMargins(5, 4, 5, 4)
        
        btn_undo = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack), "Undo")
        btn_undo.clicked.connect(lambda: self.scribble_area.undo())
        st_layout.addWidget(btn_undo)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        st_layout.addWidget(line)

        btn_pen = QPushButton("✏️ Pen")
        btn_pen.setCheckable(True)
        btn_pen.setChecked(True)
        btn_pen.clicked.connect(lambda: self.set_scratch_mode(ScribbleArea.MODE_DRAW, btn_pen))
        
        btn_high = QPushButton("🖍️ Highlt")
        btn_high.setCheckable(True)
        btn_high.clicked.connect(lambda: self.set_scratch_mode(ScribbleArea.MODE_HIGHLIGHT, btn_high))
        
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(24, 24)
        self.btn_color.setStyleSheet("background-color: black; border: 1px solid gray; border-radius: 12px;")
        self.btn_color.clicked.connect(self.select_pen_color)
        
        self.spin_width = QSpinBox()
        self.spin_width.setRange(1, 20)
        self.spin_width.setValue(2)
        self.spin_width.setPrefix("Sz: ")
        self.spin_width.valueChanged.connect(self.update_pen_width)
        
        st_layout.addWidget(btn_pen)
        st_layout.addWidget(btn_high)
        st_layout.addWidget(self.btn_color)
        st_layout.addWidget(self.spin_width)

        btn_erase = QPushButton("⬜ Eraser")
        btn_erase.setCheckable(True)
        btn_erase.clicked.connect(lambda: self.set_scratch_mode(ScribbleArea.MODE_ERASE, btn_erase))
        st_layout.addWidget(btn_erase)
        
        st_layout.addWidget(line)
        
        btn_text = QPushButton("T Text")
        btn_text.clicked.connect(lambda: self.set_scratch_mode(ScribbleArea.MODE_TEXT, None))
        
        btn_img = QPushButton("🖼️ Img")
        btn_img.clicked.connect(self.add_scratch_image)
        
        st_layout.addWidget(btn_text)
        st_layout.addWidget(btn_img)
        
        btn_flatten = QPushButton("⬇ Merge")
        btn_flatten.setToolTip("Merge text and images into the background layer")
        btn_flatten.clicked.connect(lambda: self.scribble_area.flatten_layers())
        st_layout.addWidget(btn_flatten)
        
        check_grid = QCheckBox("Grid")
        check_grid.toggled.connect(lambda c: self.scribble_area.toggle_grid(c))
        st_layout.addWidget(check_grid)
        
        st_layout.addStretch()
        
        btn_clear_scratch = QPushButton("🗑️ Clear")
        btn_clear_scratch.clicked.connect(self.clear_scratch)
        st_layout.addWidget(btn_clear_scratch)
        
        self.scratch_btn_group = QButtonGroup(self)
        self.scratch_btn_group.addButton(btn_pen)
        self.scratch_btn_group.addButton(btn_erase)
        self.scratch_btn_group.addButton(btn_high)
        
        self.scribble_area = ScribbleArea()
        scratch_scroll = QScrollArea()
        scratch_scroll.setWidget(self.scribble_area)
        scratch_scroll.setWidgetResizable(True)
        scratch_scroll.setStyleSheet("background: #202020;")
        
        scratch_main_layout.addWidget(scratch_toolbar)
        scratch_main_layout.addWidget(scratch_scroll)
        
        # --- TAB 3: MATHEMATICA ---
        self.tab_wolfram = QWidget()
        wolf_layout = QVBoxLayout(self.tab_wolfram)
        self.wolf_main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        top_w = QWidget()
        top_l = QVBoxLayout(top_w)
        top_l.setContentsMargins(0,0,0,0)
        top_l.addWidget(QLabel("<b>Wolfram Input:</b>"))
        
        self.input_wolfram = QTextEdit()
        self.input_wolfram.setFont(QFont("Consolas", 12))
        self.input_wolfram.setPlaceholderText("Integrate[x^2, x]\nPlot[Sin[x],{x,0,10}]")
        self.input_wolfram.setStyleSheet("background-color: #252525; color: #fff;")
        top_l.addWidget(self.input_wolfram)
        
        self.btn_run_wolf = QPushButton("▶ Run Code (Shift+Enter)")
        self.btn_run_wolf.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 5px;")
        self.btn_run_wolf.clicked.connect(self.run_wolfram_code)
        short = QAction(self)
        short.setShortcut("Shift+Return")
        short.triggered.connect(self.run_wolfram_code)
        self.addAction(short)
        top_l.addWidget(self.btn_run_wolf)
        
        self.wolf_out_splitter = QSplitter(Qt.Orientation.Vertical)
        self.output_wolfram = QTextEdit()
        self.output_wolfram.setReadOnly(True)
        self.output_wolfram.setFont(QFont("Consolas", 11))
        self.output_wolfram.setPlaceholderText("Results...")
        self.output_wolfram.setStyleSheet("background-color: #1e1e1e; color: #00FF00;")
        
        gfx_widget = QWidget()
        gfx_layout = QVBoxLayout(gfx_widget)
        gfx_layout.setContentsMargins(0,0,0,0)
        
        self.wolfram_scroll = QScrollArea()
        self.wolfram_scroll.setStyleSheet("background-color: #2e2e2e;")
        self.wolfram_canvas = QWidget()
        self.wolfram_canvas.setFixedSize(3000, 3000)
        self.wolfram_canvas.setStyleSheet("background-color: #2e2e2e;")
        self.wolfram_scroll.setWidget(self.wolfram_canvas)
        
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("Global Zoom:"))
        self.slider_wolf_zoom = QSlider(Qt.Orientation.Horizontal)
        self.slider_wolf_zoom.setRange(10, 200) 
        self.slider_wolf_zoom.setValue(100)
        self.slider_wolf_zoom.valueChanged.connect(self.update_wolfram_zoom)
        zoom_layout.addWidget(self.slider_wolf_zoom)
        
        gfx_layout.addWidget(self.wolfram_scroll)
        gfx_layout.addLayout(zoom_layout)
        
        self.wolf_out_splitter.addWidget(self.output_wolfram)
        self.wolf_out_splitter.addWidget(gfx_widget)
        self.wolf_main_splitter.addWidget(top_w)
        self.wolf_main_splitter.addWidget(self.wolf_out_splitter)
        wolf_layout.addWidget(self.wolf_main_splitter)

        # --- TAB 4: PHOTO NOTES ---
        self.tab_photos = QWidget()
        self.init_photo_tab()

        # --- TAB 5: REFERENCES ---
        self.tab_refs = QWidget()
        ref_layout = QVBoxLayout(self.tab_refs)
        self.ref_list = QListWidget()
        self.ref_list.setStyleSheet("background: #252525; color: white;")
        self.ref_list.itemDoubleClicked.connect(self.open_reference)
        
        ref_btns = QHBoxLayout()
        self.btn_add_url = QPushButton("Add URL")
        self.btn_add_url.clicked.connect(self.add_reference_url)
        self.btn_add_file = QPushButton("Attach PDF")
        self.btn_add_file.clicked.connect(self.add_reference_file)
        self.btn_del_ref = QPushButton("Remove Ref")
        self.btn_del_ref.clicked.connect(self.delete_reference)
        ref_btns.addWidget(self.btn_add_url)
        ref_btns.addWidget(self.btn_add_file)
        ref_btns.addWidget(self.btn_del_ref)
        ref_btns.addStretch()
        
        ref_layout.addWidget(QLabel("<b>Research References (Double-click to open):</b>"))
        ref_layout.addWidget(self.ref_list)
        ref_layout.addLayout(ref_btns)

        self.tabs.addTab(self.tab_notes, "📝 Notes")
        self.tabs.addTab(self.tab_scratch, "✏️ Scratch Paper")
        self.tabs.addTab(self.tab_photos, "📷 Photo Notes")
        self.tabs.addTab(self.tab_wolfram, "🐺 Mathematica")
        self.tabs.addTab(self.tab_refs, "🔗 References")

        right_layout.addWidget(self.tabs)

        self.main_splitter.addWidget(left_widget)
        self.main_splitter.addWidget(right_widget)
        
        # --- RESTORE SPLITTER STATE ---
        if "main_splitter_state" in self.settings:
            try:
                self.main_splitter.restoreState(bytes.fromhex(self.settings["main_splitter_state"]))
            except:
                self.main_splitter.setStretchFactor(1, 2)
        else:
            self.main_splitter.setStretchFactor(1, 2)

        # CONNECT SIGNAL TO SAVE SPLITTER STATE
        self.main_splitter.splitterMoved.connect(self.save_ui_layout_state)
        
        main_layout.addWidget(self.main_splitter)
        
        self.refresh_tree()
        self.enable_right_panel(False)

    def init_photo_tab(self):
        layout = QVBoxLayout(self.tab_photos)
        
        toolbar = QHBoxLayout()
        btn_add = QPushButton("Add Photo")
        btn_add.clicked.connect(self.add_photo_note)
        btn_del = QPushButton("Delete Selected")
        btn_del.clicked.connect(self.delete_photo_note)
        
        toolbar.addWidget(btn_add)
        toolbar.addWidget(btn_del)
        toolbar.addStretch()
        
        self.photo_list = QListWidget()
        self.photo_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.photo_list.setIconSize(QSize(200, 200))
        self.photo_list.setSpacing(15)
        self.photo_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.photo_list.setMovement(QListWidget.Movement.Static) 
        self.photo_list.setStyleSheet("""
            QListWidget { background: #222; } 
            QListWidget::item { color: white; padding: 5px; } 
            QListWidget::item:selected { background-color: #0078d7; border-radius: 5px; }
        """)
        self.photo_list.itemDoubleClicked.connect(self.open_photo_note)
        
        layout.addLayout(toolbar)
        layout.addWidget(self.photo_list)

    # --- SAVE UI STATE (Columns & Splitter) ---
    def save_ui_layout_state(self, *args):
        # Save Tree Column Widths
        self.settings["tree_col0_width"] = self.tree_widget.columnWidth(0)
        self.settings["tree_col1_width"] = self.tree_widget.columnWidth(1)
        # Save Main Splitter Position
        self.settings["main_splitter_state"] = self.main_splitter.saveState().data().hex()
        
        # Commit to JSON immediately so it persists even if we don't save a topic
        DataManager.save_data(self.data_wrapper, self.current_file)

    # --- UNDO SYSTEM ---
    def save_tree_state(self):
        """ Snapshots the current data state for undo. """
        if len(self.tree_undo_stack) > 20: self.tree_undo_stack.pop(0)
        self.tree_undo_stack.append(copy.deepcopy(self.data))
        self.btn_undo_tree.setEnabled(True)

    def undo_tree_action(self):
        if not self.tree_undo_stack: return
        self.data = self.tree_undo_stack.pop()
        self.data_wrapper['topics'] = self.data
        DataManager.save_data(self.data_wrapper, self.current_file)
        
        # Restore Tree
        current_id = self.current_idea_id
        self.refresh_tree()
        
        # Try to reselect current item if it exists
        if current_id:
            it = QTreeWidgetItemIterator(self.tree_widget)
            found = False
            while it.value():
                if it.value().data(0, Qt.ItemDataRole.UserRole) == current_id:
                    self.tree_widget.setCurrentItem(it.value())
                    found = True
                    break
                it += 1
            if not found:
                self.current_idea_id = None
                self.enable_right_panel(False)
        
        if not self.tree_undo_stack: self.btn_undo_tree.setEnabled(False)
        self.statusBar().showMessage("Undid last structure change.", 2000)

    # --- SCRATCHPAD HELPERS ---
    def set_scratch_mode(self, mode, btn=None):
        self.scribble_area.set_mode(mode)
        if btn: btn.setChecked(True)

    def select_pen_color(self):
        c = QColorDialog.getColor(self.scribble_area.myPenColor, self, "Pen Color")
        if c.isValid():
            self.scribble_area.set_pen_color(c)
            self.btn_color.setStyleSheet(f"background-color: {c.name()}; border: 1px solid gray; border-radius: 12px;")

    def update_pen_width(self):
        w = self.spin_width.value()
        self.scribble_area.set_pen_width(w)

    def add_scratch_image(self):
        if not self.current_idea_id: return
        path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.scribble_area.add_image_widget(path, "Imported")
            self.set_scratch_mode(ScribbleArea.MODE_DRAW)
            for btn in self.scratch_btn_group.buttons():
                if "Pen" in btn.text(): btn.setChecked(True)

    def clear_scratch(self):
        if QMessageBox.question(self, "Clear", "Clear all scratchpad contents?") == QMessageBox.StandardButton.Yes:
            self.scribble_area.clear_canvas()

    def update_title_live(self, text):
        item = self.tree_widget.currentItem()
        if item: item.setText(0, text)
        if self.current_idea_id:
            idea = self.get_idea_by_id(self.current_idea_id)
            if idea: idea['title'] = text

    def get_status_brush(self, status):
        status_colors = {
            "Idea": QBrush(QColor(100, 200, 255)),
            "Deriving": QBrush(QColor(255, 200, 100)),
            "Drafting": QBrush(QColor(200, 100, 255)),
            "Published": QBrush(QColor(100, 255, 100)),
            "Abandoned": QBrush(QColor(150, 150, 150))
        }
        return status_colors.get(status, QBrush(Qt.GlobalColor.white))

    def update_tree_status_live(self):
        """Immediately update the tree item when the combobox changes."""
        text = self.combo_status.currentText()
        item = self.tree_widget.currentItem()
        if item:
            item.setText(1, text)
            item.setForeground(1, self.get_status_brush(text))
        
        if self.current_idea_id:
            idea = self.get_idea_by_id(self.current_idea_id)
            if idea: idea['status'] = text

    def on_tree_dropped(self):
        self.save_tree_state() 
        new_data_list = []
        def traverse(item, parent_id):
            idea_id = item.data(0, Qt.ItemDataRole.UserRole)
            original_idea = None
            for d in self.data:
                if d['id'] == idea_id:
                    original_idea = d
                    break
            if original_idea:
                original_idea['parent_id'] = parent_id
                new_data_list.append(original_idea)
            for i in range(item.childCount()):
                traverse(item.child(i), idea_id)
        root = self.tree_widget.invisibleRootItem()
        for i in range(root.childCount()): traverse(root.child(i), None)
        self.data = new_data_list
        self.data_wrapper['topics'] = self.data
        DataManager.save_data(self.data_wrapper, self.current_file)

    def update_latex_zoom(self):
        if self.latex_pixmap_original and not self.latex_pixmap_original.isNull():
            scale_percent = self.slider_latex_zoom.value()
            new_width = int(self.latex_pixmap_original.width() * (scale_percent / 100.0))
            new_height = int(self.latex_pixmap_original.height() * (scale_percent / 100.0))
            scaled_pix = self.latex_pixmap_original.scaled(
                new_width, new_height, 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.lbl_preview.setPixmap(scaled_pix)
            self.lbl_preview.adjustSize()

    # --- WOLFRAM EXECUTION ---
    def update_wolfram_zoom(self):
        scale_percent = self.slider_wolf_zoom.value()
        for child in self.wolfram_canvas.findChildren(ImageContainer):
            orig = child.original_pixmap
            if orig and not orig.isNull():
                base_width = 400.0 
                zoom_factor = scale_percent / 100.0
                new_width = int(base_width * zoom_factor)
                aspect = orig.height() / orig.width()
                new_height = int(new_width * aspect) + 20 
                child.resize(new_width, new_height)

    def run_wolfram_code(self):
        code = self.input_wolfram.toPlainText().strip()
        if not code: return
        if not self.current_idea_id:
            QMessageBox.warning(self, "No Topic", "Please select or create a topic first.")
            return

        self.statusBar().showMessage("Running Mathematica code...")
        self.output_wolfram.setText("Processing...")
        for child in self.wolfram_canvas.findChildren(ImageContainer): child.deleteLater()
        QApplication.processEvents()
        
        exe_path = locate_wolfram_engine()
        if not exe_path:
            self.output_wolfram.setText("Error: Execution engine not found.")
            return

        try:
            folder = os.path.dirname(TEMP_WOLFRAM_IMG_BASE)
            for f in os.listdir(folder):
                if f.startswith("temp_wolfram_plot") and f.endswith(".png"):
                    try: os.remove(os.path.join(folder, f))
                    except: pass

            with tempfile.NamedTemporaryFile(mode='w', suffix='.wl', delete=False) as user_file:
                user_file.write(code)
                user_code_path = user_file.name.replace("\\", "/")

            runner_code = f"""
            imgBase = "{TEMP_WOLFRAM_IMG_BASE}";
            plotIdx = 0;
            NiceString[x_] := ToString[x, InputForm];
            NiceString[s_SeriesData] := Module[{{n, v, z0, oterm}},
               n = ToString[Normal[s], InputForm];
               v = s[[1]];
               z0 = s[[2]];
               oterm = If[z0 === 0, ToString[v, InputForm], "(" <> ToString[v, InputForm] <> "-" <> ToString[z0, InputForm] <> ")"];
               n <> " + O[" <> oterm <> "]^" <> ToString[s[[5]]/s[[6]], InputForm]
            ];
            exprList = Import["{user_code_path}", "HeldExpressions"];
            Scan[Function[expr, 
                result = ReleaseHold[expr];
                If[MatchQ[result, _Graphics | _Graphics3D | _Legended | _Image],
                   fname = imgBase <> "_" <> ToString[plotIdx] <> ".png";
                   UsingFrontEnd[Export[fname, result, "PNG"]];
                   Print["--GRAPHICS:" <> ToString[plotIdx] <> "--"];
                   plotIdx++,
                   If[result =!= Null, Print[NiceString[result]]]
                ]
            ], exprList];
            """
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.wls', delete=False) as runner_file:
                runner_file.write(runner_code)
                runner_path = runner_file.name

            proc = subprocess.run([exe_path, '-file', runner_path], capture_output=True, text=True, timeout=60)
            
            try: os.remove(user_code_path)
            except: pass
            try: os.remove(runner_path)
            except: pass

            output_str = ""
            final_output_lines = []
            if proc.stdout: output_str += proc.stdout
            if proc.stderr: output_str += f"\nErrors:\n{proc.stderr}"
            
            lines = output_str.split('\n')
            has_graphics = False
            plot_count = 0
            
            for line in lines:
                if "--GRAPHICS:" in line:
                    m = re.search(r'--GRAPHICS:(\d+)--', line)
                    if m:
                        idx = m.group(1)
                        temp_img_path = f"{TEMP_WOLFRAM_IMG_BASE}_{idx}.png"
                        if os.path.exists(temp_img_path):
                            unique_name = f"wolf_{self.current_idea_id}_{uuid.uuid4().hex}.png"
                            perm_path = os.path.join(IMG_DIR, unique_name)
                            try:
                                shutil.copy(temp_img_path, perm_path)
                                pix = QPixmap(perm_path)
                                if not pix.isNull():
                                    has_graphics = True
                                    title_str = f"Plot {plot_count + 1}"
                                    container = ImageContainer(pix, title_str, self.wolfram_canvas, perm_path)
                                    col = plot_count % 3 
                                    row = plot_count // 3
                                    container.move(20 + (col * 420), 20 + (row * 320))
                                    container.show()
                                    plot_count += 1
                            except Exception as e:
                                final_output_lines.append(f"[Error saving graphics: {e}]")
                        final_output_lines.append(f"[Graphics Generated: Plot {int(idx)+1}]")
                else:
                    final_output_lines.append(line)

            self.output_wolfram.setText("\n".join(final_output_lines).strip())
            if has_graphics: self.slider_wolf_zoom.setValue(100)
            self.statusBar().showMessage("Done.", 3000)

        except Exception as e:
            self.output_wolfram.setText(f"Execution Error: {str(e)}")
            self.statusBar().showMessage("Error.", 3000)

    # --- PHOTO NOTES OPERATIONS ---
    def add_photo_note(self):
        if not self.current_idea_id: return
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Photos", "", "Images (*.jpg *.jpeg *.png *.bmp *.heic *.tif)")
        if not paths: return
        
        for path in paths:
            ext = os.path.splitext(path)[1]
            unique_name = f"photo_{self.current_idea_id}_{uuid.uuid4().hex}{ext}"
            dest_path = os.path.join(IMG_DIR, unique_name)
            try:
                shutil.copy(path, dest_path)
                self._add_photo_widget(dest_path)
            except Exception as e:
                print(f"Error copying photo: {e}")
        
        self.save_current_idea(manual=False)

    def _add_photo_widget(self, path):
        item = QListWidgetItem()
        fname = os.path.basename(path)
        
        if len(fname) > 25:
             display_text = fname[:12] + "..." + fname[-8:]
             item.setText(display_text)
        else:
             item.setText(fname)
        
        item.setToolTip(fname)
        item.setData(Qt.ItemDataRole.UserRole, path)
        
        pix = QPixmap(path)
        if pix.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            item.setIcon(icon)
        else:
            thumb = pix.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            item.setIcon(QIcon(thumb))
            
        self.photo_list.addItem(item)

    def delete_photo_note(self):
        items = self.photo_list.selectedItems()
        if not items: return
        if QMessageBox.question(self, "Delete", "Delete selected photos?") == QMessageBox.StandardButton.Yes:
            for item in items:
                self.photo_list.takeItem(self.photo_list.row(item))
            self.save_current_idea(manual=False)

    def open_photo_note(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # --- FILE OPS ---
    def open_database(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Database", SCRIPT_DIR, "JSON Files (*.json)")
        if path:
            if self.current_idea_id: self.save_current_idea()
            self.current_file = path
            ConfigManager.set_last_file(path)
            self.data_wrapper = DataManager.load_data(path)
            self.data = self.data_wrapper["topics"]
            self.settings = self.data_wrapper["settings"]
            
            self.autosave_interval = self.settings.get("autosave_interval", 0)
            if self.autosave_interval > 0: self.timer.start(self.autosave_interval)
            else: self.timer.stop()
            
            # --- RESTORE LAYOUT FOR NEW FILE ---
            c0 = self.settings.get("tree_col0_width", 160)
            c1 = self.settings.get("tree_col1_width", 100)
            self.tree_widget.setColumnWidth(0, c0)
            self.tree_widget.setColumnWidth(1, c1)
            
            if "main_splitter_state" in self.settings:
                try: self.main_splitter.restoreState(bytes.fromhex(self.settings["main_splitter_state"]))
                except: pass

            self.current_idea_id = None
            self.refresh_tree()
            self.enable_right_panel(False)
            self.setWindowTitle(f"Theoretical Physics Organizer - {os.path.basename(path)}")

    def save_database_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Database As", SCRIPT_DIR, "JSON Files (*.json)")
        if path:
            if self.current_idea_id: self.save_current_idea()
            self.current_file = path
            ConfigManager.set_last_file(path)
            DataManager.save_data(self.data_wrapper, path)
            self.setWindowTitle(f"Theoretical Physics Organizer - {os.path.basename(path)}")

    def open_settings(self):
        dlg = SettingsDialog(self.autosave_interval, self)
        if dlg.exec():
            self.autosave_interval = dlg.interval
            self.settings["autosave_interval"] = self.autosave_interval
            if self.autosave_interval > 0: self.timer.start(self.autosave_interval)
            else: self.timer.stop()
            DataManager.save_data(self.data_wrapper, self.current_file)

    def auto_save(self):
        if self.current_idea_id:
            self.save_current_idea(manual=False)
            self.statusBar().showMessage("Auto-saved...", 2000)

    # --- TREE & CONTENT ---
    def refresh_tree(self):
        self.tree_widget.clear()
        items_map = {}
        roots = [d for d in self.data if d.get('parent_id') is None]
        children = [d for d in self.data if d.get('parent_id') is not None]

        def create_item(data):
            item = QTreeWidgetItem([data['title'], data.get('status', 'Idea')])
            item.setData(0, Qt.ItemDataRole.UserRole, data['id'])
            s = data.get('status', 'Idea')
            item.setForeground(1, self.get_status_brush(s))
            return item

        for item_data in roots:
            tree_item = create_item(item_data)
            self.tree_widget.addTopLevelItem(tree_item)
            items_map[item_data['id']] = tree_item

        unplaced = children
        loops = 0
        while unplaced and loops < 100:
            next_unplaced = []
            for item_data in unplaced:
                pid = item_data['parent_id']
                if pid in items_map:
                    parent_item = items_map[pid]
                    child_item = create_item(item_data)
                    parent_item.addChild(child_item)
                    items_map[item_data['id']] = child_item
                    parent_item.setExpanded(True)
                else:
                    next_unplaced.append(item_data)
            unplaced = next_unplaced
            loops += 1

    def on_tree_select(self, item, col):
        if self.current_idea_id: self.save_current_idea(manual=False)
        if not item: 
            self.current_idea_id = None
            self.enable_right_panel(False)
            return
        
        new_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.current_idea_id = new_id
        
        self.tabs.setCurrentIndex(0)
        
        self.load_idea_details(self.current_idea_id)
        self.enable_right_panel(True)

    def get_idea_by_id(self, iid):
        for d in self.data:
            if d['id'] == iid: return d
        return None

    def enable_right_panel(self, enable):
        self.input_title.setEnabled(enable)
        self.combo_status.setEnabled(enable)
        self.tabs.setEnabled(enable)
        if not enable:
            self.input_title.clear()
            self.input_content.clear()
            self.input_wolfram.clear()
            self.output_wolfram.clear()
            self.lbl_preview.clear()
            self.ref_list.clear()
            self.photo_list.clear()
            for child in self.wolfram_canvas.findChildren(ImageContainer): child.deleteLater()
            self.scribble_area.clear_canvas()

    def add_root_topic(self): self._add_item(None)
    def add_sub_topic(self):
        curr = self.tree_widget.currentItem()
        if not curr: return
        self._add_item(curr.data(0, Qt.ItemDataRole.UserRole))

    def _add_item(self, parent_id):
        self.save_tree_state() # Undo point
        new_id = str(uuid.uuid4())
        new_entry = {
            "id": new_id,
            "parent_id": parent_id,
            "title": "New Topic",
            "status": "Idea",
            "content": "",
            "wolfram_code": "",
            "wolfram_output": "", 
            "wolfram_objects": [], 
            "scratch_objects": [], 
            "references": [],
            "photos": [], 
            "has_drawing": False,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        self.data.append(new_entry)
        DataManager.save_data(self.data_wrapper, self.current_file)
        self.refresh_tree()
        
        it = QTreeWidgetItemIterator(self.tree_widget)
        while it.value():
            if it.value().data(0, Qt.ItemDataRole.UserRole) == new_id:
                self.tree_widget.setCurrentItem(it.value())
                self.on_tree_select(it.value(), 0)
                break
            it += 1

    def load_idea_details(self, iid):
        idea = self.get_idea_by_id(iid)
        if not idea: return
        
        self.input_title.blockSignals(True)
        self.input_title.setText(idea.get('title', ''))
        self.input_title.blockSignals(False)
        
        self.input_content.blockSignals(True)
        self.input_content.setText(idea.get('content', ''))
        self.input_content.blockSignals(False)
        
        self.spin_font_size.blockSignals(True)
        self.slider_latex_zoom.blockSignals(True)
        
        self.spin_font_size.setValue(idea.get('notes_font_size', 14))
        self.slider_latex_zoom.setValue(idea.get('notes_zoom', 100))
        
        splitter_state_hex = idea.get('notes_splitter_state')
        if splitter_state_hex:
            self.notes_splitter.restoreState(bytes.fromhex(splitter_state_hex))
            
        self.spin_font_size.blockSignals(False)
        self.slider_latex_zoom.blockSignals(False)
        
        self.input_wolfram.setText(idea.get('wolfram_code', ''))
        self.output_wolfram.setText(idea.get('wolfram_output', ''))
        
        for child in self.wolfram_canvas.findChildren(ImageContainer): child.deleteLater()
        saved_objs = idea.get('wolfram_objects', [])
        for obj in saved_objs:
            path = obj.get('path')
            if path and os.path.exists(path):
                pix = QPixmap(path)
                if not pix.isNull():
                    container = ImageContainer(pix, obj.get('title', 'Plot'), self.wolfram_canvas, path)
                    geo = obj.get('geometry') 
                    if geo and len(geo) == 4: container.setGeometry(*geo)
                    container.show()
        
        self.slider_wolf_zoom.setValue(100)
        self.latex_pixmap_original = None
        
        self.combo_status.blockSignals(True)
        idx = self.combo_status.findText(idea.get('status', 'Idea'))
        if idx >= 0: self.combo_status.setCurrentIndex(idx)
        self.combo_status.blockSignals(False)
        
        self.ref_list.clear()
        for ref in idea.get('references', []):
            item = QListWidgetItem(f"[{ref['type'].upper()}] {ref['name']}")
            item.setData(Qt.ItemDataRole.UserRole, ref)
            self.ref_list.addItem(item)
            
        self.photo_list.clear()
        for p_path in idea.get('photos', []):
            if os.path.exists(p_path):
                self._add_photo_widget(p_path)

        self.scribble_area.clear_canvas()
        bg_path = os.path.join(IMG_DIR, f"{iid}_bg.png")
        if os.path.exists(bg_path): self.scribble_area.set_background_image(bg_path)
        
        for obj in idea.get('scratch_objects', []):
            if obj['type'] == 'image' and os.path.exists(obj['path']):
                ic = self.scribble_area.add_image_widget(obj['path'], obj.get('title', ''))
                if ic and obj.get('geometry'): ic.setGeometry(*obj['geometry'])
            elif obj['type'] == 'text':
                tc = self.scribble_area.add_text_widget(QPoint(0,0), obj.get('text', ''))
                if tc and obj.get('geometry'): tc.setGeometry(*obj['geometry'])
            
        self.render_preview()

    def save_current_idea(self, manual=False):
        ConfigManager.set_last_file(self.current_file)
        if not self.current_idea_id: 
            if manual: DataManager.save_data(self.data_wrapper, self.current_file)
            return

        idea = self.get_idea_by_id(self.current_idea_id)
        if not idea: return

        try:
            idea['title'] = self.input_title.text().strip()
            idea['status'] = self.combo_status.currentText()
            idea['content'] = self.input_content.toPlainText()
            
            idea['notes_font_size'] = self.spin_font_size.value()
            idea['notes_zoom'] = self.slider_latex_zoom.value()
            idea['notes_splitter_state'] = self.notes_splitter.saveState().data().hex()
            
            idea['wolfram_code'] = self.input_wolfram.toPlainText()
            idea['wolfram_output'] = self.output_wolfram.toPlainText()
            
            objs = []
            for child in self.wolfram_canvas.findChildren(ImageContainer):
                rect = child.geometry()
                objs.append({
                    "path": child.image_path,
                    "title": child.lbl_title.text(),
                    "geometry": [rect.x(), rect.y(), rect.width(), rect.height()]
                })
            idea['wolfram_objects'] = objs
            
            bg_path = os.path.join(IMG_DIR, f"{idea['id']}_bg.png")
            self.scribble_area.save_background(bg_path)
            s_objs = []
            for child in self.scribble_area.children():
                if isinstance(child, ImageContainer) and child.isVisible():
                    rect = child.geometry()
                    s_objs.append({
                        "type": "image",
                        "path": child.image_path,
                        "title": child.lbl_title.text(),
                        "geometry": [rect.x(), rect.y(), rect.width(), rect.height()]
                    })
                elif isinstance(child, TextContainer) and child.isVisible():
                    rect = child.geometry()
                    s_objs.append({
                        "type": "text",
                        "text": child.text_edit.toPlainText(),
                        "geometry": [rect.x(), rect.y(), rect.width(), rect.height()]
                    })
            idea['scratch_objects'] = s_objs
            idea['has_drawing'] = True
            
            photo_paths = []
            for i in range(self.photo_list.count()):
                item = self.photo_list.item(i)
                photo_paths.append(item.data(Qt.ItemDataRole.UserRole))
            idea['photos'] = photo_paths

            DataManager.save_data(self.data_wrapper, self.current_file)
            
            iterator = QTreeWidgetItemIterator(self.tree_widget)
            while iterator.value():
                item = iterator.value()
                if item.data(0, Qt.ItemDataRole.UserRole) == self.current_idea_id:
                    if item.text(0) != idea['title']: item.setText(0, idea['title'])
                    break
                iterator += 1
            
            if manual:
                self.render_preview()
                self.statusBar().showMessage("Saved successfully.", 2000)
        except Exception as e:
            print(f"Save failed: {e}")

    def render_preview(self):
        fs = self.spin_font_size.value()
        pixmap = render_content_to_pixmap(self.input_content.toPlainText(), fontsize=fs)
        if pixmap: 
            self.latex_pixmap_original = pixmap
            self.update_latex_zoom()
        else: 
            self.lbl_preview.setText("No content to render.")
            self.latex_pixmap_original = None

    def add_reference_url(self):
        if not self.current_idea_id: return
        url, ok = QInputDialog.getText(self, "Add URL", "URL / ArXiv ID:")
        if ok and url:
            if re.match(r'\d{4}\.\d{4,5}', url.strip()): url = f"https://arxiv.org/abs/{url.strip()}"
            elif "http" not in url: url = f"https://{url.strip()}"
            self._add_ref("url", url, url)
    
    def add_reference_file(self):
        if not self.current_idea_id: return
        path, _ = QFileDialog.getOpenFileName(self, "PDF", "", "PDF (*.pdf);;All (*)")
        if path: self._add_ref("file", path, os.path.basename(path))

    def _add_ref(self, t, p, n):
        d = self.get_idea_by_id(self.current_idea_id)
        ref_data = {"type": t, "path": p, "name": n}
        d['references'].append(ref_data)
        item = QListWidgetItem(f"[{t.upper()}] {n}")
        item.setData(Qt.ItemDataRole.UserRole, ref_data)
        self.ref_list.addItem(item)
        DataManager.save_data(self.data_wrapper, self.current_file)

    def open_reference(self, item):
        ref_data = item.data(Qt.ItemDataRole.UserRole)
        if not ref_data: return
        path = ref_data.get('path', '')
        rtype = ref_data.get('type', 'url')
        if rtype == 'url': QDesktopServices.openUrl(QUrl(path))
        else:
            if os.path.exists(path): QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            else: QMessageBox.warning(self, "File Not Found", f"Could not find file at:\n{path}")

    def delete_reference(self):
        row = self.ref_list.currentRow()
        if row < 0: return
        d = self.get_idea_by_id(self.current_idea_id)
        del d['references'][row]
        self.ref_list.takeItem(row)
        DataManager.save_data(self.data_wrapper, self.current_file)

    def delete_item(self):
        selected_items = self.tree_widget.selectedItems()
        if not selected_items: return
        msg = f"Delete {len(selected_items)} topics and all their sub-topics?"
        if QMessageBox.question(self, "Delete", msg) == QMessageBox.StandardButton.Yes:
            self.save_tree_state() # Undo point
            ids_to_delete = set()
            def add_children_of(pid):
                for d in self.data:
                    if d['parent_id'] == pid:
                        ids_to_delete.add(d['id'])
                        add_children_of(d['id'])
            for item in selected_items:
                uid = item.data(0, Qt.ItemDataRole.UserRole)
                ids_to_delete.add(uid)
                add_children_of(uid)
            self.data[:] = [d for d in self.data if d['id'] not in ids_to_delete]
            DataManager.save_data(self.data_wrapper, self.current_file)
            self.current_idea_id = None
            self.refresh_tree()
            self.enable_right_panel(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = PhysicsApp()
    window.show()
    sys.exit(app.exec())