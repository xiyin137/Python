import sys
import json
import os
import uuid
import subprocess
import textwrap
import re
import shutil
import tempfile
from datetime import datetime

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
                             QLabel, QLineEdit, QTextEdit, QPushButton, QSplitter, QComboBox, 
                             QMessageBox, QScrollArea, QListWidget, QListWidgetItem,
                             QInputDialog, QFileDialog, QTabWidget, QDialog, 
                             QRadioButton, QButtonGroup, QAbstractItemView, QSlider, QSpinBox,
                             QSizePolicy, QToolBar, QMenu, QFrame, QColorDialog, QCheckBox)
from PyQt6.QtCore import Qt, QPoint, QTimer, QSize, QUrl, QRect
from PyQt6.QtGui import QPixmap, QImage, QFont, QPainter, QPen, QAction, QDesktopServices, QCursor, QColor, QIcon

# --- MATPLOTLIB SETUP ---
import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from io import BytesIO

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

# --- CUSTOM WIDGETS ---

class ResizableDraggableContainer(QWidget):
    """ 
    Base class for widgets that can be moved and resized on a canvas.
    """
    MARGIN = 10
    MIN_SIZE = 50

    # Resize Modes
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
        
        # Styles
        self.setAutoFillBackground(False)
        # Dashed border to indicate it is an object, but transparent bg
        self.setStyleSheet("QWidget { border: 1px dashed #999; background-color: transparent; }")
        
        # Context Menu to Delete
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
            self.drag_start_pos = event.globalPosition().toPoint()
            self.rect_start = self.geometry()
            self.raise_()

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.MouseButton.LeftButton:
            mode = self._get_resize_mode(event.pos())
            self._set_cursor_shape(mode)
            return

        if self.mode == self.NONE or not self.drag_start_pos: return

        curr_pos = event.globalPosition().toPoint()
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
        self.lbl_title.setStyleSheet("background-color: rgba(50,50,50,200); color: #fff; font-weight: bold; padding: 2px;")
        self.lbl_title.setFixedHeight(20)
        layout.addWidget(self.lbl_title)
        
        self.lbl_image = QLabel()
        self.lbl_image.setScaledContents(True)
        self.lbl_image.setPixmap(pixmap)
        self.lbl_image.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.lbl_image)
        
        self.original_pixmap = pixmap
        
        # Initial geometry based on image aspect ratio
        start_w = 400
        aspect = pixmap.height() / pixmap.width()
        start_h = int(start_w * aspect) + 20
        self.resize(start_w, start_h)
        
        # Transparent for mouse so the container catches events
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class TextContainer(ResizableDraggableContainer):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        # Margins provide grab area around the text
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.text_edit = QTextEdit()
        self.text_edit.setText(text)
        self.text_edit.setFont(QFont("Arial", 12))
        # Transparent background, no border for the text edit itself
        self.text_edit.setStyleSheet("background-color: transparent; border: none; color: black;")
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

    def dropEvent(self, event):
        super().dropEvent(event)
        self.drop_callback()

# --- CONFIG MANAGER ---
class ConfigManager:
    @staticmethod
    def load_config():
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except: pass
        return {}

    @staticmethod
    def save_config(data):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=4)
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
    if custom_path and os.path.exists(custom_path):
        return custom_path
    
    manual_checks = [
        "/usr/local/bin/wolframscript",
        "/opt/homebrew/bin/wolframscript",
        "/usr/bin/wolframscript"
    ]
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
        possible_bins = [
            os.path.join(path, "Contents", "MacOS", "wolframscript"),
            os.path.join(path, "Contents", "MacOS", "WolframKernel") 
        ]
        for p in possible_bins:
            if os.path.exists(p): return p
    return path

# --- DRAWING WIDGET (IMPROVED) ---
class ScribbleArea(QWidget):
    MODE_DRAW = 0
    MODE_ERASE = 1
    MODE_TEXT = 2
    MODE_IMAGE = 3 
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents)
        
        # Canvas Size
        self.canvas_width = 2000
        self.canvas_height = 2000
        self.setFixedSize(self.canvas_width, self.canvas_height)
        
        self.current_mode = self.MODE_DRAW
        self.scribbling = False
        self.myPenWidth = 2
        self.myPenColor = Qt.GlobalColor.black
        
        self.show_grid = False
        self.undo_stack = []
        
        # Transparent Background Layer (Pixels)
        self.image = QImage(self.canvas_width, self.canvas_height, QImage.Format.Format_ARGB32_Premultiplied)
        self.image.fill(Qt.GlobalColor.white)
        self.lastPoint = QPoint()

    def set_mode(self, mode):
        self.current_mode = mode
        if mode == self.MODE_TEXT:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        elif mode == self.MODE_ERASE:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_pen_color(self, color):
        self.myPenColor = color

    def set_pen_width(self, width):
        self.myPenWidth = width

    def toggle_grid(self, show):
        self.show_grid = show
        self.update()

    def extend_page(self, added_height=1000):
        self.canvas_height += added_height
        self.setFixedSize(self.canvas_width, self.canvas_height)
        
        # Create new image and copy old one
        new_image = QImage(self.canvas_width, self.canvas_height, QImage.Format.Format_ARGB32_Premultiplied)
        new_image.fill(Qt.GlobalColor.white)
        
        painter = QPainter(new_image)
        painter.drawImage(0, 0, self.image)
        painter.end()
        
        self.image = new_image
        self.update()

    def save_undo_state(self):
        # Limit stack size
        if len(self.undo_stack) > 10:
            self.undo_stack.pop(0)
        self.undo_stack.append(self.image.copy())

    def undo(self):
        if self.undo_stack:
            self.image = self.undo_stack.pop()
            self.update()

    def clear_canvas(self):
        self.save_undo_state()
        self.image.fill(Qt.GlobalColor.white)
        # Remove floating widgets
        for child in self.children():
            if isinstance(child, (ImageContainer, TextContainer)):
                child.deleteLater()
        self.update()
        
    def flatten_layers(self):
        """Merges all floating widgets (Text/Images) into the background image."""
        self.save_undo_state()
        
        painter = QPainter(self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Identify children to process
        children_to_process = [c for c in self.children() if isinstance(c, (ImageContainer, TextContainer))]
        
        for child in children_to_process:
            pos = child.pos()
            
            if isinstance(child, ImageContainer):
                # Render the widget exactly as it appears (excluding the dashed border logic which is outside paintEvent usually, 
                # but ResizableDraggableContainer draws border via stylesheet. We rely on render() grabbing the widget content)
                # To avoid the border, we render the inner label? No, simpler to render the widget but we might catch the border.
                # Actually, stylesheet borders are painted. 
                # Best approach: Draw the pixmap directly for images.
                
                # Draw the title background and text
                title_h = child.lbl_title.height()
                painter.fillRect(pos.x(), pos.y(), child.width(), title_h, QColor(50, 50, 50, 200))
                painter.setPen(Qt.GlobalColor.white)
                painter.drawText(QRect(pos.x(), pos.y(), child.width(), title_h), Qt.AlignmentFlag.AlignCenter, child.lbl_title.text())
                
                # Draw the image
                pix = child.lbl_image.pixmap()
                if pix:
                    img_rect = QRect(pos.x(), pos.y() + title_h, child.lbl_image.width(), child.lbl_image.height())
                    painter.drawPixmap(img_rect, pix)
                
            elif isinstance(child, TextContainer):
                # For text, we want the text content, but we need to account for the layout margins (10)
                # child.text_edit is the inner widget.
                inner_pos = child.mapToParent(child.text_edit.pos())
                child.text_edit.render(painter, inner_pos)

            # Remove the interactive widget
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
        
        if self.show_grid:
            self._draw_grid_overlay(painter, rect)

    def _draw_grid_overlay(self, painter, rect):
        grid_pen = QPen(QColor(220, 230, 255))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        
        step = 40
        l = rect.left()
        r = rect.right()
        t = rect.top()
        b = rect.bottom()
        
        start_x = (l // step) * step
        start_y = (t // step) * step
        
        for x in range(start_x, r + step, step):
            painter.drawLine(x, t, x, b)
        for y in range(start_y, b + step, step):
            painter.drawLine(l, y, r, y)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.current_mode == self.MODE_TEXT:
                self.add_text_widget(event.pos())
                self.set_mode(self.MODE_DRAW) 
            else:
                self.save_undo_state() # Push to history before drawing
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
            painter.setPen(QPen(Qt.GlobalColor.white, self.myPenWidth, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        else:
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
        if not os.path.exists(filepath):
            return {"settings": {}, "topics": []}
        try:
            with open(filepath, "r") as f:
                raw_data = json.load(f)
                if isinstance(raw_data, list):
                    data_wrapper = {"settings": {}, "topics": raw_data}
                else:
                    data_wrapper = raw_data
                return data_wrapper
        except Exception as e:
            print(f"Load Error: {e}")
            return {"settings": {}, "topics": []}

    @staticmethod
    def save_data(data_wrapper, filepath):
        try:
            with open(filepath, "w") as f:
                json.dump(data_wrapper, f, indent=4)
        except IOError as e:
            print(f"Error saving file: {e}")

# --- MATH RENDERER ---
def render_content_to_pixmap(text_content, fontsize=14):
    if not text_content: return None
    try:
        math_pattern = r'\$.*?\$'
        lines = []
        paragraphs = text_content.split('\n')
        
        wrap_width = int(80 * (14.0 / fontsize))
        
        for paragraph in paragraphs:
            math_chunks = re.findall(math_pattern, paragraph)
            placeholder_text = paragraph
            for i, chunk in enumerate(math_chunks):
                placeholder_text = placeholder_text.replace(chunk, f"__MATH_{i}__", 1)
            
            wrapped = textwrap.wrap(placeholder_text, width=wrap_width)
            if not wrapped and not paragraph.strip(): wrapped = [""]

            for i, line in enumerate(wrapped):
                for j, chunk in enumerate(math_chunks):
                    placeholder = f"__MATH_{j}__"
                    if placeholder in line: line = line.replace(placeholder, chunk)
                wrapped[i] = line
            lines.extend(wrapped)

        final_text = "\n".join(lines)
        line_height_factor = 0.035 * fontsize
        height = max(0.5, len(lines) * line_height_factor)
        
        fig = Figure(figsize=(10.0, height), dpi=150)
        canvas = FigureCanvasAgg(fig)
        
        fig.text(0.01, 0.98, final_text, fontsize=fontsize, 
                 horizontalalignment='left', verticalalignment='top')
        canvas.draw()
        
        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1)
        buf.seek(0)
        return QPixmap.fromImage(QImage.fromData(buf.getvalue()))
    except Exception:
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
        
        layout.addWidget(self.r1)
        layout.addWidget(self.r2)
        layout.addWidget(self.r3)
        layout.addWidget(self.r4)
        
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
        
        self.timer = QTimer()
        if self.autosave_interval > 0:
            self.timer.start(self.autosave_interval)
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
        
        left_label = QLabel("📚 Research Tree")
        left_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        left_layout.addWidget(left_label)

        self.tree_widget = ResearchTreeWidget(self.on_tree_dropped)
        self.tree_widget.setColumnCount(2)
        self.tree_widget.setHeaderLabels(["Topic", "Status"])
        self.tree_widget.setColumnWidth(0, 220) 
        self.tree_widget.itemClicked.connect(self.on_tree_select)
        
        left_layout.addWidget(self.tree_widget, 1)
        
        btn_layout = QHBoxLayout()
        self.btn_root = QPushButton("New Topic")
        self.btn_root.clicked.connect(self.add_root_topic)
        self.btn_sub = QPushButton("Add Sub-topic")
        self.btn_sub.clicked.connect(self.add_sub_topic)
        btn_layout.addWidget(self.btn_root)
        btn_layout.addWidget(self.btn_sub)
        left_layout.addLayout(btn_layout)
        
        self.btn_del = QPushButton("Delete Selected")
        self.btn_del.setStyleSheet("color: #e57373;") 
        self.btn_del.clicked.connect(self.delete_item)
        left_layout.addWidget(self.btn_del)
        
        self.btn_save = QPushButton("Save All Changes")
        self.btn_save.setStyleSheet("background-color: #007AFF; color: white; font-weight: bold; padding: 6px;")
        self.btn_save.clicked.connect(lambda: self.save_current_idea(manual=True))
        left_layout.addWidget(self.btn_save)

        self.btn_settings = QPushButton("⚙️ Settings")
        self.btn_settings.clicked.connect(self.open_settings)
        left_layout.addWidget(self.btn_settings)

        # 2. RIGHT PANEL
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Header
        self.input_title = QLineEdit()
        self.input_title.setPlaceholderText("Topic Title")
        self.input_title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.input_title.textChanged.connect(self.update_title_live)
        
        self.combo_status = QComboBox()
        self.combo_status.addItems(["Idea", "Deriving", "Drafting", "Published", "Abandoned"])
        header_layout = QHBoxLayout()
        header_layout.addWidget(self.input_title)
        header_layout.addWidget(QLabel("Status:"))
        header_layout.addWidget(self.combo_status)
        right_layout.addLayout(header_layout)

        # Tabs
        self.tabs = QTabWidget()
        
        # --- TAB 1: NOTES ---
        self.tab_notes = QWidget()
        notes_layout = QVBoxLayout(self.tab_notes)
        notes_splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.input_content = QTextEdit()
        self.input_content.setPlaceholderText("Notes & Derivations... (Use $...$ for LaTeX)")
        self.input_content.setFont(QFont("Consolas", 11))
        
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0,0,0,0)
        
        prev_ctrl_layout = QHBoxLayout()
        self.btn_render = QPushButton("Update Preview")
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

        self.lbl_preview = QLabel("Math Preview")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_preview.setStyleSheet("background: white; padding: 10px;")
        
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidget(self.lbl_preview)
        self.preview_scroll.setWidgetResizable(True)
        
        preview_layout.addLayout(prev_ctrl_layout)
        preview_layout.addWidget(self.preview_scroll)
        
        notes_splitter.addWidget(self.input_content)
        notes_splitter.addWidget(preview_container)
        notes_layout.addWidget(notes_splitter)
        
        # --- TAB 2: SCRATCH PAPER (IMPROVED) ---
        self.tab_scratch = QWidget()
        scratch_main_layout = QVBoxLayout(self.tab_scratch)
        
        # Toolbar
        scratch_toolbar = QFrame()
        scratch_toolbar.setStyleSheet("background-color: #e0e0e0; border-bottom: 1px solid #aaa;")
        st_layout = QHBoxLayout(scratch_toolbar)
        st_layout.setContentsMargins(5, 4, 5, 4)
        
        # Undo
        btn_undo = QPushButton("↩ Undo")
        btn_undo.setFixedWidth(60)
        btn_undo.clicked.connect(lambda: self.scribble_area.undo())
        st_layout.addWidget(btn_undo)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        st_layout.addWidget(line)

        # Pen Control
        btn_pen = QPushButton("✏️ Pen")
        btn_pen.setCheckable(True)
        btn_pen.setChecked(True)
        btn_pen.clicked.connect(lambda: self.set_scratch_mode(ScribbleArea.MODE_DRAW, btn_pen))
        
        self.btn_color = QPushButton("Color")
        self.btn_color.setStyleSheet("background-color: black; color: white; border: 1px solid gray;")
        self.btn_color.setFixedWidth(50)
        self.btn_color.clicked.connect(self.select_pen_color)
        
        self.spin_width = QSpinBox()
        self.spin_width.setRange(1, 20)
        self.spin_width.setValue(2)
        self.spin_width.setPrefix("Sz: ")
        self.spin_width.valueChanged.connect(self.update_pen_width)
        
        st_layout.addWidget(btn_pen)
        st_layout.addWidget(self.btn_color)
        st_layout.addWidget(self.spin_width)

        # Eraser
        btn_erase = QPushButton("⬜ Eraser")
        btn_erase.setCheckable(True)
        btn_erase.clicked.connect(lambda: self.set_scratch_mode(ScribbleArea.MODE_ERASE, btn_erase))
        st_layout.addWidget(btn_erase)
        
        # Tools
        btn_text = QPushButton("T Text")
        btn_text.clicked.connect(lambda: self.set_scratch_mode(ScribbleArea.MODE_TEXT, None))
        
        btn_img = QPushButton("🖼️ Img")
        btn_img.clicked.connect(self.add_scratch_image)
        
        st_layout.addWidget(btn_text)
        st_layout.addWidget(btn_img)
        
        # Flatten Tool
        btn_flatten = QPushButton("⬇ Merge")
        btn_flatten.setToolTip("Merge text and images into the background layer")
        btn_flatten.clicked.connect(lambda: self.scribble_area.flatten_layers())
        st_layout.addWidget(btn_flatten)
        
        # View/Page Controls
        check_grid = QCheckBox("Grid")
        check_grid.toggled.connect(lambda c: self.scribble_area.toggle_grid(c))
        st_layout.addWidget(check_grid)
        
        btn_extend = QPushButton("⏬ Extend Page")
        btn_extend.clicked.connect(lambda: self.scribble_area.extend_page())
        st_layout.addWidget(btn_extend)

        st_layout.addStretch()
        
        btn_clear_scratch = QPushButton("🗑️ Clear")
        btn_clear_scratch.clicked.connect(self.clear_scratch)
        st_layout.addWidget(btn_clear_scratch)
        
        # Group logic for Pen/Eraser buttons
        self.scratch_btn_group = QButtonGroup(self)
        self.scratch_btn_group.addButton(btn_pen)
        self.scratch_btn_group.addButton(btn_erase)
        
        self.scribble_area = ScribbleArea()
        scratch_scroll = QScrollArea()
        scratch_scroll.setWidget(self.scribble_area)
        scratch_scroll.setWidgetResizable(True)
        
        scratch_main_layout.addWidget(scratch_toolbar)
        scratch_main_layout.addWidget(scratch_scroll)
        
        # --- TAB 3: MATHEMATICA ---
        self.tab_wolfram = QWidget()
        wolf_layout = QVBoxLayout(self.tab_wolfram)
        
        self.wolf_main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Top: Input
        top_w = QWidget()
        top_l = QVBoxLayout(top_w)
        top_l.setContentsMargins(0,0,0,0)
        top_l.addWidget(QLabel("<b>Code Input:</b>"))
        
        code_font = QFont("Consolas", 12)
        code_font.setStyleHint(QFont.StyleHint.Monospace)

        self.input_wolfram = QTextEdit()
        self.input_wolfram.setFont(code_font)
        self.input_wolfram.setPlaceholderText("Integrate[x^2, x]\nPlot[Sin[x],{x,0,10}]")
        self.input_wolfram.setStyleSheet("background-color: #f5f5f5; color: #333;")
        top_l.addWidget(self.input_wolfram)
        self.btn_run_wolf = QPushButton("▶ Run Code")
        self.btn_run_wolf.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_run_wolf.clicked.connect(self.run_wolfram_code)
        top_l.addWidget(self.btn_run_wolf)
        
        # Bottom: Output Splitter
        self.wolf_out_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Text Output
        self.output_wolfram = QTextEdit()
        self.output_wolfram.setReadOnly(True)
        self.output_wolfram.setFont(code_font)
        self.output_wolfram.setPlaceholderText("Output Text...")
        self.output_wolfram.setStyleSheet("background-color: #222; color: #00FF00;")
        
        # Graphics Area (Freeform Canvas)
        gfx_widget = QWidget()
        gfx_layout = QVBoxLayout(gfx_widget)
        gfx_layout.setContentsMargins(0,0,0,0)
        
        self.wolfram_scroll = QScrollArea()
        self.wolfram_scroll.setStyleSheet("background-color: #333;")
        
        self.wolfram_canvas = QWidget()
        self.wolfram_canvas.setFixedSize(3000, 3000) # Large virtual canvas
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

        # --- TAB 4: REFERENCES ---
        self.tab_refs = QWidget()
        ref_layout = QVBoxLayout(self.tab_refs)
        self.ref_list = QListWidget()
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
        self.tabs.addTab(self.tab_wolfram, "🐺 Mathematica")
        self.tabs.addTab(self.tab_refs, "🔗 References")

        right_layout.addWidget(self.tabs)

        self.main_splitter.addWidget(left_widget)
        self.main_splitter.addWidget(right_widget)
        self.main_splitter.setStretchFactor(1, 2)
        
        main_layout.addWidget(self.main_splitter)
        
        self.refresh_tree()
        self.enable_right_panel(False)

    # --- SCRATCHPAD HELPERS ---
    def set_scratch_mode(self, mode, btn=None):
        self.scribble_area.set_mode(mode)
        # Ensure buttons reflect state (if set programmatically)
        if btn:
            btn.setChecked(True)

    def select_pen_color(self):
        c = QColorDialog.getColor(self.scribble_area.myPenColor, self, "Pen Color")
        if c.isValid():
            self.scribble_area.set_pen_color(c)
            # Update button style to show color, but keep text readable (simplified)
            self.btn_color.setStyleSheet(f"background-color: {c.name()}; border: 1px solid gray;")

    def update_pen_width(self):
        w = self.spin_width.value()
        self.scribble_area.set_pen_width(w)

    def add_scratch_image(self):
        if not self.current_idea_id: return
        path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.scribble_area.add_image_widget(path, "Imported")
            self.set_scratch_mode(ScribbleArea.MODE_DRAW)
            # Reset pen button visual
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

    def on_tree_dropped(self):
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
        for i in range(root.childCount()):
            traverse(root.child(i), None)
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
        # Iterate over ImageContainers in the canvas
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
        
        # Clear existing images on canvas
        for child in self.wolfram_canvas.findChildren(ImageContainer):
            child.deleteLater()

        QApplication.processEvents()

        exe_path = locate_wolfram_engine()
        
        if not exe_path:
            resp = QMessageBox.question(self, "Wolfram Not Found", 
                                        "Could not find 'wolframscript'. Locate manually?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if resp == QMessageBox.StandardButton.Yes:
                fname, _ = QFileDialog.getOpenFileName(self, "Locate wolframscript", "/Applications")
                if fname:
                    safe_path = sanitize_app_path(fname)
                    ConfigManager.set_wolfram_path(safe_path)
                    exe_path = safe_path
                else:
                    self.output_wolfram.setText("Cancelled.")
                    return
            else:
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

            # ROBUST RUNNER CODE
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

            proc = subprocess.run(
                [exe_path, '-file', runner_path],
                capture_output=True, text=True, timeout=60
            )
            
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
                            # Move to permanent storage
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
            
            if has_graphics:
                self.slider_wolf_zoom.setValue(100)
                
            self.statusBar().showMessage("Done.", 3000)

        except Exception as e:
            self.output_wolfram.setText(f"Execution Error: {str(e)}")
            self.statusBar().showMessage("Error.", 3000)

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

        for item_data in roots:
            tree_item = QTreeWidgetItem([item_data['title'], item_data.get('status', 'Idea')])
            tree_item.setData(0, Qt.ItemDataRole.UserRole, item_data['id'])
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
                    child_item = QTreeWidgetItem([item_data['title'], item_data.get('status', 'Idea')])
                    child_item.setData(0, Qt.ItemDataRole.UserRole, item_data['id'])
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
            for child in self.wolfram_canvas.findChildren(ImageContainer): child.deleteLater()
            self.scribble_area.clear_canvas()

    def add_root_topic(self): self._add_item(None)
    def add_sub_topic(self):
        curr = self.tree_widget.currentItem()
        if not curr: return
        self._add_item(curr.data(0, Qt.ItemDataRole.UserRole))

    def _add_item(self, parent_id):
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
        
        self.input_content.setText(idea.get('content', ''))
        
        # Wolfram
        self.input_wolfram.setText(idea.get('wolfram_code', ''))
        self.output_wolfram.setText(idea.get('wolfram_output', ''))
        
        for child in self.wolfram_canvas.findChildren(ImageContainer):
            child.deleteLater()
            
        # Restore Wolfram Plots
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
        self.slider_latex_zoom.setValue(100)
        
        idx = self.combo_status.findText(idea.get('status', 'Idea'))
        if idx >= 0: self.combo_status.setCurrentIndex(idx)
        
        # References
        self.ref_list.clear()
        for ref in idea.get('references', []):
            item = QListWidgetItem(f"[{ref['type'].upper()}] {ref['name']}")
            item.setData(Qt.ItemDataRole.UserRole, ref)
            self.ref_list.addItem(item)
            
        # Scratchpad Restore
        self.scribble_area.clear_canvas()
        bg_path = os.path.join(IMG_DIR, f"{iid}_bg.png")
        if os.path.exists(bg_path): self.scribble_area.set_background_image(bg_path)
        
        # Restore Floating Scratch Objects
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
            idea['wolfram_code'] = self.input_wolfram.toPlainText()
            idea['wolfram_output'] = self.output_wolfram.toPlainText()
            
            # SAVE WOLFRAM OBJECTS
            objs = []
            for child in self.wolfram_canvas.findChildren(ImageContainer):
                rect = child.geometry()
                objs.append({
                    "path": child.image_path,
                    "title": child.lbl_title.text(),
                    "geometry": [rect.x(), rect.y(), rect.width(), rect.height()]
                })
            idea['wolfram_objects'] = objs
            
            # SAVE SCRATCHPAD
            # 1. Background
            bg_path = os.path.join(IMG_DIR, f"{idea['id']}_bg.png")
            self.scribble_area.save_background(bg_path)
            
            # 2. Floating Objects
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

            DataManager.save_data(self.data_wrapper, self.current_file)
            
            iterator = QTreeWidgetItemIterator(self.tree_widget)
            while iterator.value():
                item = iterator.value()
                if item.data(0, Qt.ItemDataRole.UserRole) == self.current_idea_id:
                    if item.text(1) != idea['status']: item.setText(1, idea['status'])
                    break
                iterator += 1
            
            if manual:
                self.render_preview()
                QMessageBox.information(self, "Saved", "All data saved.")
        except Exception as e:
            print(f"Save failed: {e}")

    def render_preview(self):
        fs = self.spin_font_size.value()
        pixmap = render_content_to_pixmap(self.input_content.toPlainText(), fontsize=fs)
        if pixmap: 
            self.latex_pixmap_original = pixmap
            self.update_latex_zoom()
        else: 
            self.lbl_preview.setText("No text.")
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
        d['references'].append({"type": t, "path": p, "name": n})
        self.ref_list.addItem(QListWidgetItem(f"[{t.upper()}] {n}"))
        DataManager.save_data(self.data_wrapper, self.current_file)

    def open_reference(self, item):
        ref_data = item.data(Qt.ItemDataRole.UserRole)
        if not ref_data: return
        path = ref_data.get('path', '')
        rtype = ref_data.get('type', 'url')
        if rtype == 'url':
            QDesktopServices.openUrl(QUrl(path))
        else:
            if os.path.exists(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            else:
                QMessageBox.warning(self, "File Not Found", f"Could not find file at:\n{path}")

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
    app.setStyle("Fusion") 
    window = PhysicsApp()
    window.show()
    sys.exit(app.exec())