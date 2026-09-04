"""Sourceter — photo batch renamer GUI.

Run: python app.py
The engine (engine/core.py) never imports anything from this file.

The flow this is built around: Explorer on one side, Sourceter on the other.
Drag a shop's photos across, they arrive selected, type the shop name, repeat.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import (QObject, QRect, QRunnable, QSize, Qt, QThreadPool,
                            Signal, Slot)
from PySide6.QtGui import (QColor, QIcon, QKeySequence, QPainter, QPen,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QStyledItemDelegate,
                               QDialog, QDialogButtonBox, QFileDialog, QFrame,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from engine.core import (FIELD_KINDS, IMAGE_EXTS, Field, commit,
                         default_pattern, find_manifests, format_example,
                         load_paths, plan_renames, sort_photos, suggest_groups,
                         summarize_sources, undo, validate_pattern)

THUMB = 150
PHOTO_ROLE = Qt.UserRole + 1

# Dark, desaturated, distinguishable. One per shop.
GROUP_COLOURS = ["#20303f", "#1f3630", "#3a3122", "#33263a", "#3b2a2c",
                 "#1f3739", "#2a2b42", "#3a2f24"]

# collision / warning row tints for the preview table
ROW_ERROR = "#46232a"
ROW_WARN = "#43371f"

STYLE = """
QWidget { font-size: 13px; color: #e7e9ee; }
QMainWindow, QWidget#central, QDialog { background: #101216; }

QGroupBox {
    border: 1px solid #262a33; border-radius: 12px;
    margin-top: 12px; padding: 12px; background: #171a20;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 14px; padding: 0 6px;
    color: #8b93a3; font-weight: 600;
}

QPushButton {
    background: #1e222a; border: 1px solid #2d323d; border-radius: 8px;
    padding: 8px 14px; color: #d7dbe3; font-weight: 500;
}
QPushButton:hover { background: #262b35; border-color: #3a4150; }
QPushButton:pressed { background: #1a1e25; }
QPushButton:disabled { color: #545b68; background: #16191f; border-color: #23272f; }

QPushButton#primary {
    background: #4f7cff; border: none; border-radius: 8px;
    padding: 10px 24px; color: #ffffff; font-weight: 600;
}
QPushButton#primary:hover { background: #6189ff; }
QPushButton#primary:pressed { background: #4470e6; }
QPushButton#primary:disabled { background: #232833; color: #5b6270; }

QPushButton#rowbtn {
    background: #1e222a; border: 1px solid #3a4150; border-radius: 8px;
    padding: 0; font-size: 16px; font-weight: 700; color: #c3cad6;
}
QPushButton#rowbtn:hover { background: #2a303b; color: #ffffff; border-color: #4f7cff; }
QPushButton#rowbtn:disabled { color: #3c4250; border-color: #23272f; background: #16191f; }
QPushButton#rowdel {
    background: #1e222a; border: 1px solid #3a4150; border-radius: 8px;
    padding: 0; font-size: 16px; font-weight: 700; color: #c3cad6;
}
QPushButton#rowdel:hover { background: #3a2126; color: #ff9b9b; border-color: #6b3138; }
QPushButton#rowdel:disabled { color: #3c4250; border-color: #23272f; background: #16191f; }
QPushButton#quiet {
    border: none; background: transparent; color: #8b93a3; padding: 8px 10px;
}
QPushButton#quiet:hover { color: #e7e9ee; background: #1c2027; }

QPushButton#help {
    border: 1px solid #2d323d; border-radius: 14px; padding: 0;
    color: #8b93a3; font-weight: 700; background: #1e222a;
}
QPushButton#help:hover { color: #e7e9ee; border-color: #4f7cff; }

QLineEdit {
    border: 1px solid #2d323d; border-radius: 8px; padding: 9px 12px;
    background: #12151a; color: #e7e9ee;
    selection-background-color: #4f7cff; selection-color: #ffffff;
}
QLineEdit:focus { border-color: #4f7cff; background: #141820; }
QLineEdit:disabled { background: #14171c; color: #545b68; }

QComboBox {
    border: 1px solid #2d323d; border-radius: 8px; padding: 7px 11px;
    background: #1e222a; color: #d7dbe3;
}
QComboBox:hover { border-color: #3a4150; }
QComboBox QAbstractItemView {
    background: #1a1e25; border: 1px solid #2d323d;
    selection-background-color: #4f7cff; selection-color: #ffffff;
    outline: none;
}

QListWidget {
    border: 1px solid #262a33; border-radius: 12px; background: #14171c;
    outline: none;
}
QListWidget::item:selected { border: 2px solid #4f7cff; color: #e7e9ee; }

QTableWidget {
    background: #14171c; border: 1px solid #262a33; border-radius: 10px;
    gridline-color: #23272f;
}
QHeaderView::section {
    background: #1a1e25; color: #8b93a3; border: none;
    border-bottom: 1px solid #262a33; padding: 8px;
}

QScrollBar:vertical { background: transparent; width: 10px; margin: 4px; }
QScrollBar::handle:vertical { background: #2d323d; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3a4150; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QLabel#hint { color: #7d8493; }
QLabel#count { color: #8b93a3; }
QLabel#footnote { color: #4a505c; font-size: 11px; font-style: italic; }
QLabel#dropzone {
    color: #6f7787; border: 1px dashed #2d323d; border-radius: 14px;
    background: #14171c; font-size: 15px;
}
QToolTip {
    background: #1a1e25; color: #d7dbe3; border: 1px solid #2d323d;
    padding: 5px; border-radius: 6px;
}
"""


# --------------------------------------------------------------------------- #
# background thumbnail loading
# --------------------------------------------------------------------------- #

class ThumbSignals(QObject):
    ready = Signal(str, QPixmap)


class ThumbJob(QRunnable):
    """Keyed by path, not row — the grid can be reordered while these run."""

    def __init__(self, path: Path, signals: ThumbSignals):
        super().__init__()
        self.path, self.signals = path, signals

    @Slot()
    def run(self) -> None:
        try:
            with Image.open(self.path) as img:
                img.draft("RGB", (THUMB * 2, THUMB * 2))   # fast partial decode
                img = img.convert("RGB")
                img.thumbnail((THUMB, THUMB))
                pix = QPixmap.fromImage(ImageQt(img).copy())
            self.signals.ready.emit(str(self.path), pix)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# the grid: external file drops, internal drag to reorder
# --------------------------------------------------------------------------- #

BADGE = 20          # size of the delete badge drawn on each thumbnail
BADGE_PAD = 7


class PhotoDelegate(QStyledItemDelegate):
    """Draws a small ✕ badge in the corner of every thumbnail."""

    @staticmethod
    def badge_rect(item_rect: QRect) -> QRect:
        return QRect(item_rect.right() - BADGE - BADGE_PAD,
                     item_rect.top() + BADGE_PAD, BADGE, BADGE)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        rect = self.badge_rect(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#3a4150"), 1))
        painter.setBrush(QColor("#22262e"))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#aeb6c4"), 1.6))
        inset = rect.adjusted(6, 6, -6, -6)
        painter.drawLine(inset.topLeft(), inset.bottomRight())
        painter.drawLine(inset.topRight(), inset.bottomLeft())
        painter.restore()


class PhotoGrid(QListWidget):
    dropped = Signal(list)      # list[Path] dropped from outside
    reordered = Signal()
    remove_requested = Signal()
    delete_one = Signal(int)    # the ✕ badge on a single thumbnail

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setGridSize(QSize(THUMB + 36, THUMB + 76))
        self.setResizeMode(QListView.Adjust)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setWordWrap(True)
        self.setSpacing(8)
        self.setUniformItemSizes(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setItemDelegate(PhotoDelegate(self))
        self.setMouseTracking(True)
        self.model().rowsMoved.connect(lambda *_: self.reordered.emit())

    def _badge_at(self, pos):
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        rect = PhotoDelegate.badge_rect(self.visualRect(index))
        return index.row() if rect.contains(pos) else None

    def mousePressEvent(self, event):
        row = self._badge_at(event.position().toPoint())
        if row is not None and event.button() == Qt.LeftButton:
            self.delete_one.emit(row)
            return                      # no selection change, no drag start
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        over = self._badge_at(event.position().toPoint()) is not None
        self.setCursor(Qt.PointingHandCursor if over else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    @staticmethod
    def _paths(event) -> list[Path]:
        if not event.mimeData().hasUrls():
            return []
        return [Path(u.toLocalFile()) for u in event.mimeData().urls()
                if u.isLocalFile()]

    def dragEnterEvent(self, event):
        if self._paths(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)       # internal reorder

    def dragMoveEvent(self, event):
        if self._paths(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = self._paths(event)
        if paths:
            event.acceptProposedAction()
            self.dropped.emit(paths)
        else:
            super().dropEvent(event)            # internal reorder

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.remove_requested.emit()
        else:
            super().keyPressEvent(event)


# --------------------------------------------------------------------------- #
# filename pattern builder
# --------------------------------------------------------------------------- #

class FieldRow(QWidget):
    """One part of the filename: a kind, an optional value, and a minus button."""

    changed = Signal()
    removed = Signal(object)
    moved = Signal(object, int)

    PLACEHOLDERS = {
        "text": "e.g. Audit Q3",
        "date": "blank = each photo's own date",
        "counter": "blank = 001, 002, 003 in the order shown",
    }

    def __init__(self, field: Field, parent=None):
        super().__init__(parent)
        self.kind = QComboBox()
        for key, (label, _) in FIELD_KINDS.items():
            self.kind.addItem(label, key)
        self.kind.setCurrentIndex(self.kind.findData(field.kind))

        self.value = QLineEdit(field.value)
        self.value.setMinimumWidth(200)

        self.up = QPushButton("▲")
        self.down = QPushButton("▼")
        self.minus = QPushButton("✕")
        for b, tip, name in (
                (self.up, "Move this part earlier in the filename", "rowbtn"),
                (self.down, "Move this part later in the filename", "rowbtn"),
                (self.minus, "Remove this part from the filename", "rowdel")):
            b.setObjectName(name)
            b.setFixedSize(38, 36)
            b.setToolTip(tip)
        self.up.clicked.connect(lambda: self.moved.emit(self, -1))
        self.down.clicked.connect(lambda: self.moved.emit(self, 1))

        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.value.textChanged.connect(self.changed)
        self.minus.clicked.connect(lambda: self.removed.emit(self))

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.kind)
        row.addWidget(self.value, 1)
        row.addWidget(self.up)
        row.addWidget(self.down)
        row.addWidget(self.minus)
        self.kind_changed()

    def kind_changed(self):
        kind = self.kind.currentData()
        takes = FIELD_KINDS[kind][1]
        self.value.setEnabled(takes)
        self.value.setPlaceholderText(
            self.PLACEHOLDERS.get(kind, "") if takes
            else ("taken from the shop name you assign" if kind == "shop"
                  else "the photo's current filename"))
        if not takes:
            self.value.clear()
        self.changed.emit()

    def field(self) -> Field:
        return Field(self.kind.currentData(), self.value.text())


class PatternBuilder(QGroupBox):
    """Rows of fields joined by underscores, with a live example."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__("Filename pattern", parent)
        self.rows: list[FieldRow] = []

        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(4)

        plus = QPushButton("+  Add a part")
        plus.clicked.connect(lambda: self.add_field(Field("text", "")))
        plus.setToolTip("Add another underscore-separated part to the filename")

        self.example = QLabel()
        self.example.setWordWrap(True)
        self.example.setTextInteractionFlags(Qt.TextSelectableByMouse)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background:#262a33; border:none; max-height:1px;")

        outer = QVBoxLayout(self)
        outer.addLayout(self.rows_box)
        bottom = QHBoxLayout()
        bottom.addWidget(plus)
        bottom.addStretch(1)
        outer.addLayout(bottom)
        outer.addWidget(line)
        outer.addWidget(self.example)

        for field in default_pattern("", ""):
            self.add_field(field)

    def add_field(self, field: Field):
        row = FieldRow(field)
        row.changed.connect(self.refresh)
        row.removed.connect(self.remove_field)
        row.moved.connect(self.move_field)
        self.rows.append(row)
        self.rows_box.addWidget(row)
        self.refresh()

    def remove_field(self, row: FieldRow):
        if len(self.rows) == 1:
            return
        self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self.refresh()

    def move_field(self, row: FieldRow, delta: int):
        i = self.rows.index(row)
        j = i + delta
        if not 0 <= j < len(self.rows):
            return
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        self.rows_box.removeWidget(row)
        self.rows_box.insertWidget(j, row)
        self.refresh()

    def pattern(self) -> list[Field]:
        return [row.field() for row in self.rows]

    def refresh(self):
        pattern = self.pattern()
        try:
            validate_pattern(pattern)
        except ValueError as exc:
            self.example.setText(f"⚠  {exc}")
            self.example.setStyleSheet("color:#ff8a8a;")
        else:
            self.example.setText(f"Example:   {format_example(pattern)}")
            for i, row in enumerate(self.rows):
                row.up.setEnabled(i > 0)
                row.down.setEnabled(i < len(self.rows) - 1)
                row.minus.setEnabled(len(self.rows) > 1)
            self.example.setStyleSheet("color:#6ee7a8; font-weight:600;")
        self.changed.emit()

    def is_valid(self) -> bool:
        try:
            validate_pattern(self.pattern())
            return True
        except ValueError:
            return False


class PreviewDialog(QDialog):
    def __init__(self, plans, parent=None, date_fixed=True):
        super().__init__(parent)
        self.setWindowTitle("Preview")
        self.resize(760, 560)
        self.plans = plans

        collisions = sum(1 for p in plans if p.collision)
        warned = sum(1 for p in plans if p.already_renamed)

        table = QTableWidget(0, 3, self)
        table.setHorizontalHeaderLabels(["Current name", "", "New name"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        last_group = None
        for plan in plans:
            if plan.photo.group_label != last_group:
                last_group = plan.photo.group_label
                r = table.rowCount()
                table.insertRow(r)
                head = QTableWidgetItem(f"  {last_group}")
                font = head.font(); font.setBold(True); head.setFont(font)
                table.setItem(r, 0, head)
                table.setSpan(r, 0, 1, 3)

            r = table.rowCount()
            table.insertRow(r)
            note = ""
            colour = None
            if plan.collision:
                note, colour = "  — name already exists", QColor(ROW_ERROR)
            elif plan.already_renamed:
                note, colour = "  — looks renamed before", QColor(ROW_WARN)
            cells = [QTableWidgetItem(plan.old_name),
                     QTableWidgetItem("→"),
                     QTableWidgetItem(plan.new_name + note)]
            for col, cell in enumerate(cells):
                if colour:
                    cell.setBackground(colour)
                table.setItem(r, col, cell)
        table.resizeColumnToContents(1)

        guessed = sum(1 for p in plans if p.photo.capture_source == "mtime")
        summary = QLabel(
            f"{len(plans)} photos. "
            + (f"{collisions} collision(s) — fix these first. " if collisions else "")
            + (f"{warned} look already renamed. " if warned else "")
            + ((f"The date for {guessed} photo(s) comes from the file's modified "
                f"date, not the camera — type a date in the Date box to override. ")
               if guessed and not date_fixed else "")
        )
        summary.setWordWrap(True)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        self.go = buttons.addButton(f"Rename {len(plans)} photos",
                                    QDialogButtonBox.AcceptRole)
        self.go.setEnabled(collisions == 0)
        cancel.clicked.connect(self.reject)
        self.go.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(table)
        layout.addWidget(buttons)


HOW_TO_USE = [
    ("1.  Drag photos in",
     "Put Explorer on one side and Sourceter on the other. Drag one shop's "
     "photos across. They land in the grid already selected — you don't have "
     "to select anything."),
    ("2.  Type the shop name",
     "The cursor is already in the box. Type the shop name and press Enter. "
     "Those photos turn one colour and take that name."),
    ("3.  Repeat for the next shop",
     "Drag the next batch across. It arrives selected too, so it's drag, "
     "type, Enter — once per shop."),
    ("4.  Tidy up if you need to",
     "Click the small ✕ on a photo to take it out of the list — or select "
     "several and press Remove selected. Neither one deletes anything from "
     "your computer. To change the order, just drag a photo to where you "
     "want it — the order decides the numbering."),
    ("5.  Check the filename",
     "The Filename box at the bottom shows an example of what you'll get. "
     "Add or remove parts with + and ✕, reorder them with ▲ ▼, and type the "
     "assignment name in the "
     "first box. Leave the Number blank and it counts 001, 002, 003 in the "
     "order the photos are shown."),
    ("6.  Confirm",
     "Press Confirm and rename. You'll see the full before-and-after list "
     "first — nothing changes until you press the button in that window."),
    ("If something goes wrong",
     "Press Undo a run and pick the run you want reversed. Every rename is "
     "written to a spreadsheet in the same folder before anything is "
     "touched, so the original names are never lost."),
]


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("How to use Sourceter")
        self.resize(560, 620)

        layout = QVBoxLayout(self)
        for title, body in HOW_TO_USE:
            head = QLabel(title)
            head.setStyleSheet("font-weight:600; color:#e7e9ee; margin-top:8px;")
            text = QLabel(body)
            text.setWordWrap(True)
            text.setStyleSheet("color:#98a0b0;")
            layout.addWidget(head)
            layout.addWidget(text)
        layout.addStretch(1)

        buttons = QDialogButtonBox()
        close = buttons.addButton("Got it", QDialogButtonBox.AcceptRole)
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        layout.addWidget(buttons)


class UndoDialog(QDialog):
    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Undo a previous run")
        self.resize(600, 340)
        self.entries = entries          # list[(folder, ManifestInfo)]

        self.list = QListWidget(self)
        for folder, m in entries:
            self.list.addItem(
                f"{m.run_time.strftime('%d %b %Y, %H:%M')}   ·   {m.count} photos"
                f"   ·   {folder.name}")
        self.list.setCurrentRow(0)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        undo_btn = buttons.addButton("Undo this run", QDialogButtonBox.AcceptRole)
        undo_btn.setObjectName("primary")
        undo_btn.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Pick the run to reverse:"))
        layout.addWidget(self.list)
        layout.addWidget(buttons)

    def chosen(self):
        return self.entries[self.list.currentRow()]


# --------------------------------------------------------------------------- #
# main window
# --------------------------------------------------------------------------- #

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sourceter")
        self.resize(1060, 860)
        self.setAcceptDrops(True)

        self.photos: list = []
        self.icons: dict[str, QIcon] = {}
        self.sort_mode = "manual"          # arrival order, until she says otherwise
        self.group_mode = "batch"          # each drop is its own batch
        self.pool = QThreadPool.globalInstance()
        self.signals = ThumbSignals()
        self.signals.ready.connect(self.set_thumb)

        # --- top bar ------------------------------------------------------- #
        add_photos = QPushButton("Add photos")
        add_folder = QPushButton("Add folder")
        add_photos.clicked.connect(self.pick_photos)
        add_folder.clicked.connect(self.pick_folder)
        self.count_label = QLabel("")
        self.count_label.setObjectName("count")
        clear_all = QPushButton("Remove all")
        clear_all.setObjectName("quiet")
        clear_all.clicked.connect(self.clear_all)

        help_btn = QPushButton("?")
        help_btn.setObjectName("help")
        help_btn.setFixedSize(28, 28)
        help_btn.setToolTip("How to use Sourceter")
        help_btn.clicked.connect(lambda: HelpDialog(self).exec())

        top = QHBoxLayout()
        top.addWidget(add_photos)
        top.addWidget(add_folder)
        top.addSpacing(10)
        top.addWidget(self.count_label, 1)
        top.addWidget(clear_all)
        top.addWidget(help_btn)

        # --- naming ---------------------------------------------------------- #
        self.shop = QLineEdit()
        self.shop.setPlaceholderText("Shop name for the selected photos — press Enter")
        self.shop.returnPressed.connect(self.assign_selection)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.assign_selection)

        self.select_all_btn = QPushButton("Select all")
        self.deselect_btn = QPushButton("Clear selection")
        self.remove_btn = QPushButton("Remove selected")
        self.select_all_btn.clicked.connect(lambda: self.grid.selectAll())
        self.deselect_btn.clicked.connect(lambda: self.grid.clearSelection())
        self.remove_btn.clicked.connect(self.remove_selected)

        self.status = QLabel("")
        self.status.setObjectName("hint")

        name_box = QGroupBox("Name the shop")
        name_layout = QVBoxLayout(name_box)
        row1 = QHBoxLayout()
        row1.addWidget(self.shop, 1)
        row1.addWidget(apply_btn)
        row2 = QHBoxLayout()
        row2.addWidget(self.select_all_btn)
        row2.addWidget(self.deselect_btn)
        row2.addWidget(self.remove_btn)
        row2.addStretch(1)
        row2.addWidget(self.status)
        name_layout.addLayout(row1)
        name_layout.addLayout(row2)

        # --- grid, with an empty state -------------------------------------- #
        self.grid = PhotoGrid()
        self.grid.dropped.connect(self.add_paths)
        self.grid.reordered.connect(self.grid_reordered)
        self.grid.remove_requested.connect(self.remove_selected)
        self.grid.delete_one.connect(self.remove_one)
        self.grid.itemSelectionChanged.connect(self.selection_changed)

        self.dropzone = QLabel("Drag photos here from Explorer\n\n"
                               "A folder works too. Each batch you drop arrives\n"
                               "selected, so you can name the shop straight away.\n\n"
                               "New to this?  Click the  ?  at the top right.")
        self.dropzone.setObjectName("dropzone")
        self.dropzone.setAlignment(Qt.AlignCenter)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.dropzone)
        self.stack.addWidget(self.grid)

        # --- options (folded away) ------------------------------------------ #
        self.sort_box = QComboBox()
        for label, key in (("Order: as added", "manual"),
                           ("Order: capture time", "capture"),
                           ("Order: filename", "name"),
                           ("Order: automatic", "auto")):
            self.sort_box.addItem(label, key)
        self.group_box = QComboBox()
        for label, key in (("Group: each drop", "batch"),
                           ("Group: by time gaps", "time"),
                           ("Group: by filename numbering", "sequence"),
                           ("Group: one group", "none")):
            self.group_box.addItem(label, key)
        self.sort_box.currentIndexChanged.connect(self.modes_changed)
        self.group_box.currentIndexChanged.connect(self.modes_changed)


        self.options = QWidget()
        opt_row = QHBoxLayout(self.options)
        opt_row.setContentsMargins(0, 0, 0, 0)
        opt_row.addWidget(self.sort_box)
        opt_row.addWidget(self.group_box)
        opt_row.addStretch(1)
        self.options.hide()

        self.options_btn = QPushButton("Options")
        self.options_btn.setObjectName("quiet")
        self.options_btn.clicked.connect(self.toggle_options)

        # --- pattern and footer --------------------------------------------- #
        self.builder = PatternBuilder()
        self.builder.setTitle("Filename")
        self.builder.changed.connect(self.refresh_buttons)

        self.preview_btn = QPushButton("Confirm and rename")
        self.preview_btn.setObjectName("primary")
        self.preview_btn.clicked.connect(self.do_preview)
        self.preview_btn.setEnabled(False)
        undo_btn = QPushButton("Undo a run")
        undo_btn.clicked.connect(self.do_undo)

        footer = QHBoxLayout()
        footer.addWidget(undo_btn)
        footer.addWidget(self.options_btn)
        footer.addStretch(1)
        footer.addWidget(self.preview_btn)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(name_box)
        layout.addWidget(self.options)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.builder)
        layout.addLayout(footer)

        footnote = QLabel("For my hardworking propshopper..  :)")
        footnote.setObjectName("footnote")
        footnote.setAlignment(Qt.AlignRight)
        layout.addWidget(footnote)
        central = QWidget()
        central.setObjectName("central")
        central.setLayout(layout)
        self.setCentralWidget(central)

        QShortcut(QKeySequence.Delete, self.grid, self.remove_selected)
        self.refresh_labels()

    def toggle_options(self):
        self.options.setVisible(not self.options.isVisible())

    # ---- drag and drop onto the window itself ------------------------------ #

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            self.add_paths(paths)

    # ---- loading ----------------------------------------------------------- #

    def pick_photos(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choose photos", "", f"Images ({exts})")
        if files:
            self.add_paths([Path(f) for f in files])

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose photo folder")
        if path:
            self.add_paths([Path(path)])

    def clear_all(self):
        if self.photos and QMessageBox.question(
                self, "Remove all",
                f"Take all {len(self.photos)} photos out of the list?\n"
                f"Nothing is deleted from disk.") != QMessageBox.Yes:
            return
        self.photos = []
        self.icons.clear()
        self.grid.clear()
        self.refresh_view()

    def add_paths(self, paths: list[Path]):
        """Add files and/or folders, then select exactly what just arrived."""
        known = {str(p.path) for p in self.photos}
        try:
            photos = load_paths(paths, self.sort_mode, existing=self.photos)
        except Exception as exc:
            QMessageBox.warning(self, "Could not read those files", str(exc))
            return
        arrived = [p for p in photos if str(p.path) not in known]
        if not arrived:
            self.flash("Those photos are already in the list.")
            return

        self.photos = photos
        if self.group_mode != "batch":
            self.autogroup()
        self.rebuild_grid()
        for photo in arrived:
            if str(photo.path) not in self.icons:
                self.pool.start(ThumbJob(photo.path, self.signals))

        self.select_paths({str(p.path) for p in arrived})
        self.refresh_view()
        self.shop.setFocus()
        self.flash(f"{len(arrived)} photos added and selected — type the shop name.")

    def select_paths(self, paths: set[str]):
        self.grid.clearSelection()
        first = None
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if item.data(PHOTO_ROLE) in paths:
                item.setSelected(True)
                first = first if first is not None else item
        if first is not None:
            self.grid.scrollToItem(first)

    def autogroup(self):
        """Only used when she has asked for automatic grouping."""
        groups = suggest_groups(self.photos, 30, self.group_mode)
        for index, group in enumerate(groups, start=1):
            for i in group:
                if not self.photos[i].group_label:
                    self.photos[i].group_label = f"Group {index}"

    def rebuild_grid(self):
        """Redraw from self.photos, reusing thumbnails already loaded."""
        selected = {self.grid.item(r).data(PHOTO_ROLE)
                    for r in range(self.grid.count())
                    if self.grid.item(r).isSelected()}
        blocked = self.grid.blockSignals(True)
        self.grid.clear()
        placeholder = QPixmap(THUMB, THUMB)
        placeholder.fill(QColor("#1b1f26"))
        for photo in self.photos:
            icon = self.icons.get(str(photo.path), QIcon(placeholder))
            item = QListWidgetItem(icon, "")
            item.setData(PHOTO_ROLE, str(photo.path))
            item.setTextAlignment(Qt.AlignHCenter)
            item.setSelected(str(photo.path) in selected)
            self.grid.addItem(item)
        self.grid.blockSignals(blocked)

    @Slot(str, QPixmap)
    def set_thumb(self, path: str, pix: QPixmap):
        icon = QIcon(pix)
        self.icons[path] = icon
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if item.data(PHOTO_ROLE) == path:
                item.setIcon(icon)
                break

    # ---- selection, order, removal ----------------------------------------- #

    def selected_rows(self) -> list[int]:
        return sorted(i.row() for i in self.grid.selectedIndexes())

    def selection_changed(self):
        self.refresh_buttons()

    def remove_selected(self):
        rows = self.selected_rows()
        if not rows:
            return
        for row in reversed(rows):
            self.photos.pop(row)
        self.rebuild_grid()
        self.refresh_view()
        self.flash(f"{len(rows)} photo(s) taken out of the list "
                   f"(still on disk, untouched).")

    def remove_one(self, row: int):
        if not 0 <= row < len(self.photos):
            return
        name = self.photos[row].name
        self.photos.pop(row)
        self.rebuild_grid()
        self.refresh_view()
        self.flash(f"{name} taken out of the list (still on disk, untouched).")

    def grid_reordered(self):
        by_path = {str(p.path): p for p in self.photos}
        order = [by_path[self.grid.item(r).data(PHOTO_ROLE)]
                 for r in range(self.grid.count())
                 if self.grid.item(r).data(PHOTO_ROLE) in by_path]
        if len(order) == len(self.photos):
            self.photos = order
        self.set_manual()
        self.refresh_view()

    def move_selection(self, delta: int):
        rows = self.selected_rows()
        if not rows or not self.photos:
            return
        if (delta < 0 and rows[0] == 0) or \
           (delta > 0 and rows[-1] == len(self.photos) - 1):
            return
        for row in (rows if delta < 0 else reversed(rows)):
            target = row + delta
            self.photos[row], self.photos[target] = \
                self.photos[target], self.photos[row]
        self.set_manual()
        self.rebuild_grid()
        self.grid.clearSelection()
        for row in rows:
            self.grid.item(row + delta).setSelected(True)
        self.refresh_view()

    def set_manual(self):
        self.sort_mode = "manual"
        if self.sort_box.currentData() != "manual":
            self.sort_box.blockSignals(True)
            self.sort_box.setCurrentIndex(self.sort_box.findData("manual"))
            self.sort_box.blockSignals(False)

    def modes_changed(self):
        self.sort_mode = self.sort_box.currentData()
        self.group_mode = self.group_box.currentData()
        if not self.photos:
            return
        for photo in self.photos:
            if photo.group_label.startswith("Group "):
                photo.group_label = ""
        sort_photos(self.photos, self.sort_mode)
        if self.group_mode != "batch":
            self.autogroup()
        self.rebuild_grid()
        self.refresh_view()

    # ---- naming ------------------------------------------------------------- #

    def assign_selection(self):
        name = self.shop.text().strip()
        rows = self.selected_rows()
        if not name:
            self.flash("Type a shop name first.")
            return
        if not rows:
            self.flash("Nothing selected — pick some photos, or use Select all.")
            return
        for row in rows:
            self.photos[row].group_label = name
        self.shop.clear()
        self.refresh_view()
        self.flash(f"{len(rows)} photos named “{name}”.")

    # ---- painting the state ------------------------------------------------- #

    def flash(self, message: str):
        self.status.setText(message)

    def refresh_view(self):
        self.stack.setCurrentIndex(1 if self.photos else 0)
        self.refresh_labels()

    def refresh_labels(self):
        colours: dict[str, QColor] = {}
        for photo in self.photos:
            if photo.group_label and photo.group_label not in colours:
                colours[photo.group_label] = QColor(
                    GROUP_COLOURS[len(colours) % len(GROUP_COLOURS)])

        for row, photo in enumerate(self.photos):
            item = self.grid.item(row)
            if item is None:
                continue
            mark = "*" if photo.capture_source == "mtime" else ""
            item.setText(f"{row + 1}   {photo.name}\n"
                         f"{photo.capture_time.strftime('%d %b %H:%M')}{mark}\n"
                         f"{photo.group_label or 'not named yet'}")
            item.setBackground(colours.get(photo.group_label, QColor("#1a1d23")))
            item.setToolTip(str(photo.path))

        needs_shop = any(f.kind == "shop" for f in self.builder.pattern())
        pending = sum(1 for p in self.photos if not p.group_label)
        shops = len(colours)
        if not self.photos:
            self.count_label.setText("")
        else:
            folders = {p.path.parent for p in self.photos}
            where = (next(iter(folders)).name if len(folders) == 1
                     else f"{len(folders)} folders")
            bits = [f"{len(self.photos)} photos", f"{shops} shop(s)", where]
            if needs_shop and pending:
                bits.append(f"{pending} still unnamed")
            self.count_label.setText("   ·   ".join(bits))
        self.refresh_buttons()

    def refresh_buttons(self):
        has = bool(self.photos)
        picked = bool(self.grid.selectedIndexes())
        self.select_all_btn.setEnabled(has)
        self.deselect_btn.setEnabled(picked)
        self.remove_btn.setEnabled(picked)
        self.shop.setEnabled(has)
        if not has:
            self.preview_btn.setEnabled(False)
            return
        needs_shop = any(f.kind == "shop" for f in self.builder.pattern())
        pending = sum(1 for p in self.photos if not p.group_label) if needs_shop else 0
        self.preview_btn.setEnabled(pending == 0 and self.builder.is_valid())

    # ---- preview and commit -------------------------------------------------- #

    def do_preview(self):
        pattern = self.builder.pattern()
        try:
            plans = plan_renames(self.photos, pattern=pattern)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot plan the rename", str(exc))
            return

        date_fixed = all(f.value.strip() for f in pattern if f.kind == "date")
        dialog = PreviewDialog(plans, self, date_fixed=date_fixed)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            result = commit(plans)
        except Exception as exc:
            QMessageBox.critical(self, "Rename failed", str(exc))
            return
        logs = "\n".join(str(p) for p in result.manifest_paths)
        QMessageBox.information(
            self, "Done",
            f"Renamed {result.renamed} photos.\nLog saved as:\n{logs}")

        self.photos = []
        self.icons.clear()
        self.grid.clear()
        self.refresh_view()
        self.flash(f"Renamed {result.renamed} photos. Drag the next batch in.")

    # ---- undo ---------------------------------------------------------------- #

    def do_undo(self):
        folders = {p.path.parent for p in self.photos}
        if not folders:
            path = QFileDialog.getExistingDirectory(
                self, "Which folder should I look in?")
            if not path:
                return
            folders = {Path(path)}
        entries = [(f, m) for f in folders for m in find_manifests(f)]
        entries.sort(key=lambda e: e[1].run_time, reverse=True)
        if not entries:
            QMessageBox.information(self, "Nothing to undo",
                                    "No previous run was logged in that folder.")
            return
        dialog = UndoDialog(entries, self)
        if dialog.exec() != QDialog.Accepted:
            return
        folder, chosen = dialog.chosen()
        if QMessageBox.question(
                self, "Undo",
                f"Reverse the run from "
                f"{chosen.run_time.strftime('%d %b %Y, %H:%M')} "
                f"({chosen.count} photos in {folder.name})?") != QMessageBox.Yes:
            return

        result = undo(chosen.path)
        lines = [f"Restored {len(result.restored)} photos."]
        if result.missing:
            lines.append("Missing (moved or deleted since): "
                         + ", ".join(result.missing))
        if result.blocked:
            lines.append("Skipped, original name already taken: "
                         + ", ".join(result.blocked))
        QMessageBox.information(self, "Undo complete", "\n".join(lines))


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
