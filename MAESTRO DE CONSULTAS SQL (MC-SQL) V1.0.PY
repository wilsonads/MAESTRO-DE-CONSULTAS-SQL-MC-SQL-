import sys
import os
import re
import time
import json
from datetime import datetime
import pandas as pd
import pyodbc
from sqlalchemy import create_engine, text
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QComboBox, QLabel, QMessageBox, QLineEdit, QListWidget,
    QGroupBox, QSplitter, QProgressBar, QStatusBar, QListWidgetItem,
    QFileDialog, QHeaderView, QAction, QShortcut, QScrollArea,
    QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QAbstractItemView,
    QInputDialog, QKeySequenceEdit, QMenu, QTabWidget, QCheckBox,
    QPlainTextEdit, QFrame, QToolButton, QSizePolicy
)
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject, QPoint, QSize
from PyQt5.QtGui import (
    QColor, QFont, QKeySequence, QSyntaxHighlighter, QTextCharFormat,
    QFontDatabase, QTextCursor, QIcon, QPixmap, QPainter
)
# ==========================
# Configuración y constantes
# ==========================
DATA_DIRECTORY = "sql_editor_data"
SQL_KEYWORDS = [
    'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'GROUP BY', 'ORDER BY',
    'HAVING', 'AS', 'IN', 'IS', 'NULL', 'LIKE', 'ILIKE', 'BETWEEN', 'LIMIT',
    'OFFSET', 'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE',
    'TRUNCATE', 'ALTER', 'TABLE', 'DROP', 'DATABASE', 'SCHEMA',
    'VIEW', 'INDEX', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'JOIN', 'ON',
    'DISTINCT', 'UNION', 'ALL', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
    'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'TOP', 'WITH', 'CUBE', 'ROLLUP', 'PIVOT'
]
# Palabras clave de SQL que modifican datos
DANGER_KEYWORDS = ['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'DROP', 'ALTER', 'CREATE']
# ==========================
# Utilidades
# ==========================
def safe_os_open(path):
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)
        elif sys.platform == 'darwin':
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        pass
def load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default
def save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error guardando JSON {path}: {e}")
# ==========================
# StatusBar Widget personalizado
# ==========================
class StatusBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200) # Ajusta el ancho para el nuevo panel
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.status_label = QLabel("Desconectado")
        self.elapsed_label = QLabel("Tiempo: 0.0s")
        self.row_count_label = QLabel("Filas: 0")
        self.estado_label = QLabel("Estado: N/A")
        self.estado_bar = QProgressBar()
        self.estado_bar.setTextVisible(True)
        self.estado_bar.setFixedHeight(16)
        self.estado_bar.setToolTip("Distribución de valores 0 y 1 en la columna ESTADO")
        self.estado_bar.setStyleSheet("QProgressBar { text-align: center; border-radius: 6px; border: 1px solid #666666; }")
        layout.addWidget(self.status_label)
        layout.addWidget(self.elapsed_label)
        layout.addWidget(self.row_count_label)
        layout.addWidget(self.estado_label)
        layout.addWidget(self.estado_bar)
# ==========================
# Stores adicionales
# ==========================
class FavoritesStore:
    def __init__(self, path):
        self.path = path
        self._data = load_json(self.path, {"tables": {}, "queries": {}})
    def save(self):
        save_json(self.path, self._data)
    def is_table_fav(self, table):
        return bool(self._data.get("tables", {}).get(table, {}).get("favorite", False))
    def set_table_fav(self, table, fav: bool):
        t = self._data.setdefault("tables", {}).setdefault(table, {})
        t["favorite"] = bool(fav)
        self.save()
    def is_query_fav(self, name):
        return bool(self._data.get("queries", {}).get(name, {}).get("favorite", False))
    def set_query_fav(self, name, fav: bool):
        q = self._data.setdefault("queries", {}).setdefault(name, {})
        q["favorite"] = bool(fav)
        self.save()
class SortConfigStore:
    def __init__(self, path):
        self.path = path
        self._data = load_json(self.path, {})
    def get(self, key):
        return list(self._data.get(key, []))
    def set(self, key, config_list):
        self._data[key] = list(config_list)
        save_json(self.path, self._data)
class NotesStore:
    def __init__(self, path):
        self.path = path
        self._data = load_json(self.path, {})
    def get_notes(self):
        return self._data.get("notes", "")
    def save_notes(self, notes):
        self._data["notes"] = notes
        save_json(self.path, self._data)
class ErrorLogStore:
    def __init__(self, path):
        self.path = path
        self._data = load_json(self.path, {"errors": []})
    def log_error(self, error_type, error_message, timestamp):
        error_entry = {
            "type": error_type,
            "message": error_message,
            "timestamp": timestamp
        }
        self._data["errors"].append(error_entry)
        save_json(self.path, self._data)
    def get_errors(self):
        return self._data.get("errors", [])
# ==========================
# Resaltador SQL
# ==========================
class SQLHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None, app_window=None):
        super().__init__(parent)
        self.app_window = app_window
        self.highlightingRules = []
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#0080FF"))  # Blue for SQL functions/keywords
        for word in SQL_KEYWORDS:
            pattern = rf'\b{re.escape(word)}\b'
            self.highlightingRules.append((re.compile(pattern, re.IGNORECASE), keyword_format))
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#004400"))  # Dark green for strings
        self.highlightingRules.append((re.compile(r"'[^']*'"), string_format))
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#008600"))  # Muted green for numbers
        self.highlightingRules.append((re.compile(r"\b\d+\b"), number_format))
        single_comment_format = QTextCharFormat()
        single_comment_format.setForeground(QColor("#808080"))  # Gray for comments
        self.highlightingRules.append((re.compile(r"--[^\n]*"), single_comment_format))
        self.multiLineCommentFormat = QTextCharFormat()
        self.multiLineCommentFormat.setForeground(QColor("#808080"))  # Gray for multiline comments
        self.commentStartExpression = re.compile(r"/\*")
        self.commentEndExpression = re.compile(r"\*/")
        self.variableFormat = QTextCharFormat()
        self.variableFormat.setForeground(QColor("#004400"))  # Yellow for variables
        self.tableFormat = QTextCharFormat()
        self.tableFormat.setForeground(QColor("#004400"))  # Orange for table names
        self.columnFormat = QTextCharFormat()
        self.columnFormat.setForeground(QColor("#FF0000"))  # Red for column names
    def highlightBlock(self, text):
        for pattern, fmt in self.highlightingRules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        self.setCurrentBlockState(0)
        
        start_idx = 0
        while start_idx >= 0:
            start_match = self.commentStartExpression.search(text, start_idx)
            if not start_match:
                break
            
            end_match = self.commentEndExpression.search(text, start_match.start())
            if not end_match:
                self.setCurrentBlockState(1)
                length = len(text) - start_match.start()
            else:
                length = end_match.start() - start_match.start() + 2
            
            self.setFormat(start_match.start(), length, self.multiLineCommentFormat)
            start_idx = start_match.start() + length
            
        if self.previousBlockState() == 1:
            start_idx = 0
            end_match = self.commentEndExpression.search(text)
            if end_match:
                self.setCurrentBlockState(0)
                length = end_match.start() + 2
            else:
                self.setCurrentBlockState(1)
                length = len(text)
            self.setFormat(start_idx, length, self.multiLineCommentFormat)
        if self.app_window and getattr(self.app_window, 'all_tables', None):
            for t in self.app_window.all_tables:
                rgx = re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)
                for m in rgx.finditer(text):
                    self.setFormat(m.start(), m.end() - m.start(), self.tableFormat)
        if self.app_window and getattr(self.app_window, 'table_columns', None):
            for c in self.app_window.table_columns:
                rgx = re.compile(rf"\b{re.escape(c)}\b", re.IGNORECASE)
                for m in rgx.finditer(text):
                    self.setFormat(m.start(), m.end() - m.start(), self.columnFormat)
        if self.app_window and getattr(self.app_window, 'variables_panel', None):
            for name in self.app_window.variables_panel.get_variables().keys():
                rgx = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
                for m in rgx.finditer(text):
                    self.setFormat(m.start(), m.end() - m.start(), self.variableFormat)
# ==========================
# Editor SQL con autocompletado contextual
# ==========================
class SQLEditor(QTextEdit):
    def __init__(self, app_window=None, parent=None):
        super().__init__(parent)
        self.app_window = app_window
        self.setPlaceholderText("Escribe tu consulta SQL aquí…")
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.highlighter = SQLHighlighter(self.document(), app_window)
        self.suggestions_popup = QListWidget()
        self.suggestions_popup.setWindowFlags(Qt.Popup)
        self.suggestions_popup.setFocusPolicy(Qt.NoFocus)
        self.suggestions_popup.setMouseTracking(True)
        self.suggestions_popup.itemClicked.connect(self._apply_completion_from_click)
        self.textChanged.connect(self._check_danger_keywords)
    def focusOutEvent(self, event):
        self.suggestions_popup.hide()
        super().focusOutEvent(event)
    def _check_danger_keywords(self):
        text = self.toPlainText()
        modified = False
        new_text = text
        # Permitir consultas que crean datos temporales sin afectar tablas
        safe_temp_keywords = ['CREATE TEMPORARY TABLE', 'WITH', 'CREATE TABLE #']
        if any(re.search(re.escape(kw), new_text, re.IGNORECASE) for kw in safe_temp_keywords):
            return
        for keyword in DANGER_KEYWORDS:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                new_text = re.sub(pattern, '', new_text, flags=re.IGNORECASE)
                modified = True
                if self.app_window and hasattr(self.app_window, 'status_bar_widget'):
                    self.app_window.status_bar_widget.status_label.setText(f"Palabra clave '{keyword}' eliminada automáticamente.")

        if modified:
            self.blockSignals(True)
            self.setPlainText(new_text)
            self.blockSignals(False)
            self.highlighter.rehighlight()
    def _current_prefix_and_context(self):
        cursor = self.textCursor()
        pos = cursor.position()
        block = cursor.block()
        block_text = block.text()
        rel_pos = pos - block.position()
        left = block_text[:rel_pos]
        m = re.search(r"([A-Za-z0-9_\.]{1,64})$", left)
        prefix = m.group(1) if m else ""
        tokens = re.split(r"\s+", left.strip().upper())
        prev_kw = tokens[-2] if len(tokens) >= 2 else ""
        return prefix, prev_kw
        
    def _build_alias_map(self, text):
        alias = {}
        for m in re.finditer(r"\bFROM\s+([A-Za-z0-9_\.]+)(?:\s+(?:AS\s+)?([A-Za-z0-9_]+))?", text, re.IGNORECASE):
            tbl = m.group(1); al = m.group(2) or tbl
            alias[al] = tbl
        for m in re.finditer(r"\bJOIN\s+([A-Za-z0-9_\.]+)(?:\s+(?:AS\s+)?([A-Za-z0-9_]+))?", text, re.IGNORECASE):
            tbl = m.group(1); al = m.group(2) or tbl
            alias[al] = tbl
        return alias
        
    def _candidate_suggestions(self, prefix, prev_kw):
        s = set()
        if not prefix: return []
        p = prefix.lower()
        table_for_cols = None
        if '.' in prefix:
            left, _ = prefix.split('.', 1)
            alias_map = self._build_alias_map(self.toPlainText())
            table_for_cols = alias_map.get(left) or left
            p = p.split('.')[-1]
        if prev_kw in ("FROM", "JOIN") or p.startswith('jo'):
            if getattr(self.app_window, 'all_tables', None):
                for t in self.app_window.all_tables:
                    if str(t).lower().startswith(p.replace('.', '')): s.add(t)
        
        if table_for_cols and getattr(self.app_window, 'columns_cache', None):
            cols = self.app_window.columns_cache.get(table_for_cols, [])
            for c in cols:
                if c.lower().startswith(p): s.add(f"{table_for_cols}.{c}")
        s.update([kw for kw in SQL_KEYWORDS if kw.lower().startswith(p)])
        if getattr(self.app_window, 'all_tables', None): s.update([t for t in self.app_window.all_tables if str(t).lower().startswith(p)])
        if getattr(self.app_window, 'table_columns', None): s.update([c for c in self.app_window.table_columns if str(c).lower().startswith(p)])
        if getattr(self.app_window, 'variables_panel', None): s.update([v for v in self.app_window.variables_panel.get_variables().keys() if str(v).lower().startswith(p)])
        return sorted(list(s))
        
    def _show_suggestions(self):
        prefix, prev_kw = self._current_prefix_and_context()
        if len(prefix) < 2:
            self.suggestions_popup.hide()
            return
        items = self._candidate_suggestions(prefix, prev_kw)
        if not items:
            self.suggestions_popup.hide()
            return
        self.suggestions_popup.clear()
        self.suggestions_popup.addItems(items)
        self.suggestions_popup.setCurrentRow(0)
        cr = self.cursorRect()
        global_pos = self.mapToGlobal(cr.bottomRight())
        self.suggestions_popup.move(global_pos)
        self.suggestions_popup.resize(300, min(240, 18 * len(items) + 6))
        if self.hasFocus(): self.suggestions_popup.show()
    
    def _apply_completion(self, text):
        cursor = self.textCursor()
        pos = cursor.position()
        block = cursor.block()
        block_text = block.text()
        rel_pos = pos - block.position()
        left = block_text[:rel_pos]
        m = re.search(r"([A-Za-z0-9_\.]{1,64})$", left)
        if m:
            start = block.position() + (rel_pos - len(m.group(1)))
            cursor.setPosition(start)
            cursor.setPosition(pos, QTextCursor.KeepAnchor)
        cursor.insertText(text)
        self.setTextCursor(cursor)
        self.suggestions_popup.hide()
    
    def _apply_completion_from_click(self, item):
        self._apply_completion(item.text())
    
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter) and (mods & Qt.ControlModifier):
            if self.app_window: self.app_window.execute_query()
            return
        if self.suggestions_popup.isVisible() and key in (Qt.Key_Down, Qt.Key_Up):
            row = self.suggestions_popup.currentRow()
            row = min(row + 1, self.suggestions_popup.count() - 1) if key == Qt.Key_Down else max(row - 1, 0)
            self.suggestions_popup.setCurrentRow(row)
            return
        if self.suggestions_popup.isVisible() and key in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
            current = self.suggestions_popup.currentItem()
            if not current and self.suggestions_popup.count() > 0: current = self.suggestions_popup.item(0)
            if current:
                self._apply_completion(current.text())
                return
        if key == Qt.Key_Escape:
            if self.suggestions_popup.isVisible():
                self.suggestions_popup.hide()
                return
        text_char = event.text()
        is_text_input = bool(re.match(r"[A-Za-z0-9_\.]", text_char)) or key in (Qt.Key_Backspace, Qt.Key_Delete)
        super().keyPressEvent(event)
        if is_text_input and self.hasFocus():
            QTimer.singleShot(0, self._show_suggestions)
        else:
            self.suggestions_popup.hide()
    def validate_query(self, query):
        """
        Validates the SQL query for common syntax errors before execution.
        Returns a tuple: (bool is_valid, str error_message)
        """
        if not query.strip():
            return False, "La consulta está vacía."

        # Check for potential ambiguous Series issues in complex queries
        if re.search(r'\bFULL\s+JOIN\b|\bLEFT\s+JOIN\b|\bRIGHT\s+JOIN\b|\bINNER\s+JOIN\b|\bOUTER\s+JOIN\b', query, re.IGNORECASE):
            # Complex joins might return mixed data types that cause ambiguous Series errors
            pass  # Allow but log potential issues

        # Permitir consultas complejas con CREATE, INSERT, WITH, etc.
        if re.search(r'\bCREATE\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bWITH\b|\bDROP\b|\bALTER\b', query, re.IGNORECASE):
            # Para consultas complejas, solo verificar sintaxis básica
            if query.count("'") % 2 != 0:
                return False, "La consulta contiene comillas simples sin cerrar."
            if query.count('(') != query.count(')'):
                return False, "La consulta contiene paréntesis sin cerrar."
            return True, ""

        # Validación normal para consultas SELECT
        if query.count("'") % 2 != 0:
            return False, "La consulta contiene comillas simples sin cerrar."
        if query.count('(') != query.count(')'):
            return False, "La consulta contiene paréntesis sin cerrar."
        if re.search(r'^\s*SELECT\b', query, re.IGNORECASE) and not re.search(r'\bFROM\b', query, re.IGNORECASE) and not re.search(r'\bVALUES\b', query, re.IGNORECASE):
            return False, "Las consultas SELECT requieren una cláusula FROM."
        if re.search(r'\bWHERE\s*$', query, re.IGNORECASE) or re.search(r'\bAND\s*$', query, re.IGNORECASE):
            return False, "La consulta parece estar incompleta (termina con WHERE o AND)."
        return True, ""
# ==========================
# Variables
# ==========================
class VariableBox(QWidget):
    def __init__(self, name="Variable", value="", app_window=None):
        super().__init__()
        self.name = name
        self.value = str(value)
        self.app_window = app_window
        self.is_collapsed = False
        self._build_ui()
    
    def _build_ui(self):
        self.setObjectName("VariableBox")
        lay = QVBoxLayout(self); lay.setContentsMargins(2, 2, 2, 2); lay.setSpacing(2)
        top = QHBoxLayout(); top.setContentsMargins(0, 0, 0, 0); top.setSpacing(4)
        self.name_label = QLabel(self.name); self.name_label.setStyleSheet("font-weight:bold;color:#FFD700;")
        top.addWidget(self.name_label); top.addStretch(1)
        self.toggle_btn = QPushButton("−"); self.toggle_btn.setFixedSize(24, 24); self.toggle_btn.clicked.connect(self.toggle_collapse); top.addWidget(self.toggle_btn)
        edit_btn = QPushButton("✏️"); edit_btn.setFixedSize(24, 24); edit_btn.clicked.connect(self.edit_name); top.addWidget(edit_btn)
        copy_btn = QPushButton("📋"); copy_btn.setFixedSize(24, 24); copy_btn.setToolTip("Copiar el contenido de la variable"); copy_btn.clicked.connect(self.copy_value); top.addWidget(copy_btn)
        lay.addLayout(top)
        self.content_widget = QWidget()
        cont_lay = QVBoxLayout(self.content_widget); cont_lay.setContentsMargins(0, 0, 0, 0); cont_lay.setSpacing(2)
        self.value_display = QTextEdit(); self.value_display.setPlainText(self.value); self.value_display.setMaximumHeight(120); self.value_display.textChanged.connect(self._update_value); cont_lay.addWidget(self.value_display)
        btns = QHBoxLayout(); btns.setContentsMargins(0, 0, 0, 0); btns.setSpacing(2)
        self.btn_commas = QPushButton("Comas"); self.btn_commas.setToolTip("Unir con comas (sin duplicados)"); self.btn_commas.setObjectName("btn_commas"); self.btn_commas.clicked.connect(self._join_commas); btns.addWidget(self.btn_commas)
        self.btn_quotes = QPushButton("Comillas"); self.btn_quotes.setToolTip("Unir comillas simples y comas"); self.btn_quotes.setObjectName("btn_quotes"); self.btn_quotes.clicked.connect(self._join_quotes); btns.addWidget(self.btn_quotes)
        self.btn_parenthesis = QPushButton("Paréntesis"); self.btn_parenthesis.setToolTip("Unir con paréntesis, comillas y comas"); self.btn_parenthesis.setObjectName("btn_parenthesis"); self.btn_parenthesis.clicked.connect(self._join_parenthesis); btns.addWidget(self.btn_parenthesis)

        # Conectar señales para actualizar estado de botones
        self.value_display.textChanged.connect(self._update_buttons_state)
        self.value_display.textChanged.connect(self._validate_and_update_border)

        # Círculo indicador de validación (empieza rojo)
        self.validation_circle = QWidget()
        self.validation_circle.setFixedSize(16, 16)
        self.validation_circle.setStyleSheet("border-radius: 8px; background-color: green;")
        btns.addWidget(self.validation_circle)

        cont_lay.addLayout(btns)
        self._update_buttons_state()
        lay.addWidget(self.content_widget)
        self.setStyleSheet("QWidget#VariableBox{border:1px solid #FFD700;border-radius:4px;background:#000000;margin:1px;} QPushButton{background:#000000;border:1px solid #555;color:#ffffff;padding:4px;border-radius:3px;} QPushButton:hover{background:#333;} QTextEdit{background:#000000;color:#ffffff;border:1px solid #555;}")
        self.setMaximumHeight(200)
    def to_dict(self):
        return {"name": self.name, "value": self.value}
        
    def from_dict(self, d):
        self.name = d.get("name", "Variable"); self.value = d.get("value", "")
        self.name_label.setText(self.name); self.value_display.setPlainText(self.value)
        
    def _split_lines(self):
        txt = self.value_display.toPlainText().strip()
        if not txt: return []
        return [x.strip() for x in re.split(r"[\n\t,;]+", txt) if x.strip()]
    
    def _join_commas(self):
        current_text = self.value_display.toPlainText().strip()
        if current_text:  # Solo requiere que haya texto, no que sea diferente
            result = ", ".join(sorted(set(self._split_lines())))
            self.value_display.setPlainText(result)
            self.value = result
            self._update_buttons_state()
            self._check_format_after_transformation(result)
            if hasattr(self.app_window, 'status_bar_widget'):
                self.app_window.status_bar_widget.status_label.setText("Texto unido con comas")

    def _join_quotes(self):
        current_text = self.value_display.toPlainText().strip()
        if current_text:  # Solo requiere que haya texto, no que sea diferente
            result = "'" + "', '".join(sorted(set(self._split_lines()))) + "'"
            self.value_display.setPlainText(result)
            self.value = result
            self._update_buttons_state()
            self._check_format_after_transformation(result)
            if hasattr(self.app_window, 'status_bar_widget'):
                self.app_window.status_bar_widget.status_label.setText("Texto unido con comillas")

    def _join_parenthesis(self):
        current_text = self.value_display.toPlainText().strip()
        if current_text:  # Solo requiere que haya texto, no que sea diferente
            values = sorted(set(self._split_lines()))
            formatted_values = [f"('{value}')" for value in values]
            result = ", ".join(formatted_values)
            self.value_display.setPlainText(result)
            self.value = result
            self._update_buttons_state()
            self._check_format_after_transformation(result)
            if hasattr(self.app_window, 'status_bar_widget'):
                self.app_window.status_bar_widget.status_label.setText("Texto unido con paréntesis")

    def _check_format_after_transformation(self, result):
        # Verificar si el resultado tiene formato válido después de la transformación
        import re
        if not result or not re.match(r"^[\w\s,.\'\"()_-]*$", result):
            # Formato inválido, cambiar botones a rojo
            self.btn_commas.setStyleSheet("QPushButton { background-color: red; color: white; }")
            self.btn_quotes.setStyleSheet("QPushButton { background-color: red; color: white; }")
            self.btn_parenthesis.setStyleSheet("QPushButton { background-color: red; color: white; }")
        else:
            # Formato válido, restaurar colores normales
            self.btn_commas.setStyleSheet("")
            self.btn_quotes.setStyleSheet("")
            self.btn_parenthesis.setStyleSheet("")

    def _has_new_info(self):
        current_text = self.value_display.toPlainText().strip()
        return bool(current_text and current_text != self.value and current_text != "")

    def _update_buttons_state(self):
        current_text = self.value_display.toPlainText().strip()
        has_content = bool(current_text)  # Solo requiere que haya texto
        self.btn_commas.setEnabled(has_content)
        self.btn_quotes.setEnabled(has_content)
        self.btn_parenthesis.setEnabled(has_content)
        
    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.content_widget.hide(); self.toggle_btn.setText("+"); self.setMaximumHeight(40)
        else:
            self.content_widget.show(); self.toggle_btn.setText("−"); self.setMaximumHeight(200)
            
    def edit_name(self):
        text, ok = QInputDialog.getText(self, "Editar nombre", "Nombre de la variable:", text=self.name)
        if ok and text and text != self.name:
            self.name = text; self.name_label.setText(text)
            if self.app_window: self.app_window.get_editor().highlighter.rehighlight()
            
    def copy_value(self):
        QApplication.clipboard().setText(self.value_display.toPlainText())
        if self.app_window and hasattr(self.app_window, 'status_bar_widget'):
            self.app_window.status_bar_widget.status_label.setText(f"Variable '{self.name}' copiada")
        
    def _update_value(self):
        self.value = self.value_display.toPlainText()
        self._validate_and_update_border()

    def _validate_and_update_border(self):
        # Validar si el texto coincide con los 3 formatos específicos
        text = self.value

        # Verificar condiciones que hacen rojo: vacío, salto de página, espacios innecesarios
        is_invalid = (
            not text.strip() or  # Vacío
            '\n' in text or '\t' in text or  # Salto de página
            re.search(r'  +', text) or  # Espacios múltiples consecutivos
            text != text.strip()  # Espacios al inicio o final
        )

        if is_invalid:
            self.value_display.setStyleSheet("QTextEdit { border: 2px solid red; }")
            self.validation_circle.setStyleSheet("border-radius: 8px; background-color: red;")
            return

        # Detectar los 3 formatos específicos (solo verde para estos)
        is_comma_format = bool(re.match(r"^[^,]+(?:\s?,\s?[^,]+)*$", text))  # Separado por comas
        is_quote_format = bool(re.match(r"^'[^']+'(?:\s?,\s?'[^']+')*$", text))  # Separado por comillas
        is_parenthesis_format = bool(re.match(r"^\([^)]+\)(?:\s?,\s?\([^)]+\))*$", text))  # Separado por paréntesis

        if is_comma_format or is_quote_format or is_parenthesis_format:
            # Uno de los 3 formatos detectados, borde normal y círculo verde
            self.value_display.setStyleSheet("QTextEdit { border: 1px solid #333; }")
            self.validation_circle.setStyleSheet("border-radius: 8px; background-color: #004400;")
        else:
            # No coincide con ninguno de los 3 formatos, borde rojo y círculo rojo
            self.value_display.setStyleSheet("QTextEdit { border: 2px solid red; }")
            self.validation_circle.setStyleSheet("border-radius: 8px; background-color: red;")
        
    def validate_variable_content(self, text):
        # CORREGIDO: Se permite cualquier formato de variable según la solicitud del usuario.
        return True, ""
class VariablesPanel(QWidget):
    def __init__(self, app_window=None):
        super().__init__()
        self.app_window = app_window
        self.variable_boxes = []
        self._build_ui()
        
    def _build_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(2)
        add_btn = QPushButton("➕ Crear Variable"); add_btn.setToolTip("Crear una nueva variable (Alt+Shift+V)"); add_btn.clicked.connect(self.add_new_variable_dialog); lay.addWidget(add_btn)
        self.scroll_area = QScrollArea(); self.scroll_area.setWidgetResizable(True)
        container = QWidget()
        self.variables_layout = QVBoxLayout(container); self.variables_layout.setContentsMargins(2, 2, 2, 2); self.variables_layout.setSpacing(2); self.variables_layout.addStretch(1)
        self.scroll_area.setWidget(container)
        lay.addWidget(self.scroll_area)
    
    def add_new_variable_dialog(self):
        # Auto-generate numerical variable name
        existing_vars = [vb.name for vb in self.variable_boxes if vb.name.startswith('VAR')]
        numbers = []
        for var in existing_vars:
            try:
                num = int(var[3:])  # VAR1 -> 1
                numbers.append(num)
            except ValueError:
                pass
        next_num = max(numbers) + 1 if numbers else 4  # Start from VAR4 if VAR1-3 exist
        name = f"VAR{next_num}"
        self.add_variable_box(name)
    
    def add_variable_box(self, name, value=""):
        vb = VariableBox(name, value, self.app_window)
        self.variable_boxes.append(vb)
        self.variables_layout.insertWidget(self.variables_layout.count() - 1, vb)
        if self.app_window: self.app_window.get_editor().highlighter.rehighlight()
        
    def remove_variable_box(self, vb):
        if vb in self.variable_boxes:
            self.variable_boxes.remove(vb); self.variables_layout.removeWidget(vb); vb.deleteLater()
            if self.app_window: self.app_window.get_editor().highlighter.rehighlight()
            
    def clear_variables(self):
        for vb in self.variable_boxes: self.variables_layout.removeWidget(vb); vb.deleteLater()
        self.variable_boxes = []
        
    def get_variables(self):
        return {vb.name: vb.value for vb in self.variable_boxes}
        
    def load_variables(self, data):
        self.clear_variables()
        for d in data: self.add_variable_box(d.get('name', 'Variable'), d.get('value', ''))
        
    def to_json(self):
        return [vb.to_dict() for vb in self.variable_boxes]
        
    def find_variable_with_focus(self):
        for vb in self.variable_boxes:
            if vb.value_display.hasFocus():
                return vb
        return None
        
    def find_variable_with_name(self, name):
        for vb in self.variable_boxes:
            if vb.name == name:
                return vb
        return None
        
    def find_next_variable_text_box(self):
        focused_vb = self.find_variable_with_focus()
        if not focused_vb:
            if self.variable_boxes:
                return self.variable_boxes[0].value_display
            return None
        try:
            current_index = self.variable_boxes.index(focused_vb)
            next_index = (current_index + 1) % len(self.variable_boxes)
            return self.variable_boxes[next_index].value_display
        except ValueError:
            return None
# ==========================
# Conexión y perfiles
# ==========================
class ConnectionDialog(QDialog):
    def __init__(self, params=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración de Conexión"); self.setModal(True)
        self.params = params or {}
        self._build_ui()
        
    def _build_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(6)
        form = QFormLayout(); form.setContentsMargins(0, 0, 0, 0); form.setSpacing(6)
        self.driver_combo = QComboBox(); self.driver_combo.addItems(["{SQL Server}", "{ODBC Driver 17 for SQL Server}", "{MySQL ODBC 8.0 Driver}"]); self.driver_combo.setCurrentText(self.params.get('driver', '{SQL Server}')); form.addRow("Driver:", self.driver_combo)
        self.server_input = QLineEdit(self.params.get('server', '')); self.server_input.setPlaceholderText("localhost o IP del servidor"); form.addRow("Servidor:", self.server_input)
        self.database_input = QLineEdit(self.params.get('database', '')); self.database_input.setPlaceholderText("Nombre de la base de datos"); form.addRow("Base de Datos:", self.database_input)
        self.username_input = QLineEdit(self.params.get('uid', '')); self.username_input.setPlaceholderText("Usuario"); form.addRow("Usuario:", self.username_input)
        self.password_input = QLineEdit(self.params.get('pwd', '')); self.password_input.setEchoMode(QLineEdit.Password); self.password_input.setPlaceholderText("Contraseña"); form.addRow("Contraseña:", self.password_input)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); btns.accepted.connect(self.accept); btns.rejected.connect(self.reject); lay.addWidget(btns)
        
    def get_connection_params(self):
        return {'driver': self.driver_combo.currentText(), 'server': self.server_input.text(), 'database': self.database_input.text(), 'uid': self.username_input.text(), 'pwd': self.password_input.text()}
class ProfilesStore:
    def __init__(self, path):
        self.path = path
        self._data = load_json(self.path, {})
        
    def names(self): return sorted(self._data.keys())
    
    def get(self, name): return dict(self._data.get(name, {}))
    
    def set(self, name, params):
        self._data[name] = dict(params)
        save_json(self.path, self._data)
        
    def delete(self, name):
        if name in self._data:
            del self._data[name]
            save_json(self.path, self._data)
# ==========================
# Diálogo de atajos con captura
# ==========================
class ShortcutsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Atajos de Teclado"); self.setModal(True)
        self.parent = parent
        self.shortcuts = parent.shortcuts.copy()
        self.groups = {
            "Perfil y Conexión": ["Conectar", "Seleccionar Perfil Conexión (Combo)", "Guardar", "Eliminar"],
            "Consultas Guardadas": ["Guardar Consulta", "Foco Buscar Consultas", "Ver todas las consultas guardadas", "Editar Consulta Guardada", "Renombrar Consulta Guardada", "Eliminar Consulta Guardada"],
            "Tablas": ["Foco en Tablas", "Buscar Tablas", "Copiar Nombre de Tabla", "Seleccionar Primera Tabla", "Copiar Tablas Seleccionadas"],
            "Columnas": ["Foco en Columnas", "Foco Buscar Columnas", "Seleccionar Primera Columna", "Copiar Nombre de Columna", "Seleccionar Columna rut_codigo"],
            "Editor": ["Foco en Editor", "Generar SELECT", "Ejecutar Consulta", "Vista Previa Variables", "Pantalla Completa Editor", "Pantalla Completa Editor (Alternar)", "Ver primeros 100 datos"],
            "Resultados": ["Foco en Resultados", "Analizar Resultados", "Descargar Resultados", "Alternar Vista Resultados Completos", "Limpiar Filtros", "Cambiar Texto Buscar Resultados", "Foco Buscar Valor", "Foco Tipo Columna", "Filtrar columna", "Foco Número de Filas", "Foco Tipo Selección", "Cambiar Texto Filas Resultados", "Seleccionar Opción Resultados", "Cambiar Texto Valor Columnas", "Filas 100", "Filas 1000", "Filas 10000", "Filas 100000", "Filas 1000000", "Selección Celdas", "Selección Filas", "Selección Columnas", "Copiar Selección", "Copiar celdas y nombres de columnas seleccionadas", "Copiar Primera Fila con Headers", "Copiar Primera Columna con Headers", "Copiar Todas las Filas Visibles con Headers", "Copiar Todas las Columnas Visibles con Headers", "Copiar Celda Actual con Header", "Copiar Rango Seleccionado con Headers", "Copiar Filas Filtradas con Headers", "Copiar Columnas Filtradas con Headers"],
            "Variables": ["Crear Variable", "Guardar en Variable", "Foco Cuadro Texto Variables", "Foco Botones Variables", "Variables: Botón Comas", "Variables: Botón Comillas", "Variables: Botón Paréntesis", "Insertar Variable 1", "Insertar Variable 2", "Insertar Variable 3", "Insertar Variable 4", "Insertar Variable 5", "Insertar Variable 6", "Insertar Variable 7", "Insertar Variable 8", "Insertar Variable 9", "Insertar Contenido Variable 1", "Insertar Contenido Variable 2", "Insertar Contenido Variable 3", "Insertar Contenido Variable 4", "Insertar Contenido Variable 5", "Insertar Contenido Variable 6", "Insertar Contenido Variable 7", "Insertar Contenido Variable 8", "Insertar Contenido Variable 9", "Foco Variable 1", "Foco Variable 2", "Foco Variable 3", "Foco Variable 4", "Foco Variable 5", "Foco Variable 6", "Foco Variable 7", "Foco Variable 8", "Foco Variable 9"],
            "Consultas Frecuentes": ["Foco Historial", "Foco Lista Consultas Frecuentes", "Agregar a Historial", "Seleccionar Primera Consulta", "Historial: Agregar", "Historial: Usar", "Historial: Renombrar", "Historial: Editar SQL", "Historial: Eliminar", "Historial: Subir", "Historial: Bajar"],
            "Pestañas y Navegación": ["Nueva Pestaña", "Cerrar Pestaña", "Siguiente Pestaña", "Anterior Pestaña"],
            "General": ["Ver Atajos", "Ocultar/Mostrar Paneles Laterales", "Mostrar/Ocultar Barra Inferior y Menú", "Quitar Foco", "Ir al Escritorio", "Abrir Notas", "Guardar Sesión", "Cargar Sesión", "Limpiar Todo"]
        }
        self._build_ui()
        
    def _build_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(6)
        self.table = QTableWidget(); self.table.setColumnCount(3); self.table.setHorizontalHeaderLabels(["Acción", "Atajo Actual", "Nuevo Atajo"]); self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setSelectionMode(QTableWidget.SingleSelection); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        f = QFont(); f.setPointSize(11); self.table.setFont(f)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #000000; color: #FFFFFF; border: 1px solid #555555; gridline-color: #555555; }
            QHeaderView::section { background-color: #333333; color: #FFFFFF; border: 1px solid #555555; padding: 4px; }
            QTableWidget::item { border: none; padding: 4px; }
        """)
        lay.addWidget(self.table)
        self._populate()
        btns = QHBoxLayout()
        save_btn = QPushButton("Guardar Cambios"); save_btn.clicked.connect(self._save); btns.addWidget(save_btn)
        reset_btn = QPushButton("Restaurar Predeterminados"); reset_btn.clicked.connect(self._reset); btns.addWidget(reset_btn)
        cancel_btn = QPushButton("Cancelar"); cancel_btn.clicked.connect(self.reject); btns.addWidget(cancel_btn)
        lay.addLayout(btns)
        self.setMinimumWidth(1000)
        self.setMinimumHeight(600)
        
    def _populate(self):
        row = 0
        for group_name, actions in self.groups.items():
            # Add header row
            header_item = QTableWidgetItem(f"--- {group_name} ---")
            header_item.setFlags(header_item.flags() & ~Qt.ItemIsEditable)
            header_item.setBackground(QColor("#666666"))
            header_item.setForeground(QColor("#FFFFFF"))
            self.table.setItem(row, 0, header_item)
            self.table.setSpan(row, 0, 1, 3)  # span all columns
            self.table.setRowHeight(row, 24)
            row += 1
            for action in actions:
                if action in self.shortcuts:
                    act_item = QTableWidgetItem(action)
                    act_item.setFlags(act_item.flags() & ~Qt.ItemIsEditable)
                    cur_item = QTableWidgetItem(self.shortcuts[action])
                    cur_item.setFlags(cur_item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, 0, act_item)
                    self.table.setItem(row, 1, cur_item)
                    editor = QKeySequenceEdit()
                    if self.shortcuts[action]:
                        try: editor.setKeySequence(QKeySequence(self.shortcuts[action]))
                        except Exception: pass
                    self.table.setCellWidget(row, 2, editor)
                    self.table.setRowHeight(row, 32)
                    row += 1
        self.table.setRowCount(row)
            
    def _save(self):
        for i in range(self.table.rowCount()):
            action = self.table.item(i, 0).text()
            editor = self.table.cellWidget(i, 2)
            if isinstance(editor, QKeySequenceEdit): self.shortcuts[action] = editor.keySequence().toString()
        self.parent.shortcuts = self.shortcuts
        self.parent.setup_shortcuts()
        QMessageBox.information(self, "Guardado", "Atajos actualizados correctamente")
        self.accept()
        
    def _reset(self):
        self.shortcuts = DatabaseQueryApp.default_shortcuts()
        self._populate()
# ==========================
# ListWidget seguro
# ==========================
class SafeListWidget(QListWidget):
    activatedByEnter = pyqtSignal(QListWidgetItem)
    
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            item = self.currentItem()
            if item: self.activatedByEnter.emit(item)
            event.accept()
            return
        super().keyPressEvent(event)
# ==========================
# Tabla filtrable con selección flexible
# ==========================
class FilterableTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_window = parent
        self.original_df = pd.DataFrame()
        self.current_df = pd.DataFrame()
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSortingEnabled(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._install_header_context_menu()
        self._install_table_context_menu()
        self.column_filters = {}
        self.filter_widgets = {}
        
    def _install_header_context_menu(self):
        header = self.horizontalHeader(); header.setContextMenuPolicy(Qt.CustomContextMenu); header.customContextMenuRequested.connect(self._on_header_menu)
        
    def _on_header_menu(self, pos: QPoint):
        logical = self.horizontalHeader().logicalIndexAt(pos)
        if logical < 0 or logical >= self.columnCount(): return
        menu = QMenu(self)
        action_copy_name = QAction("Copiar nombre de columna", self); action_copy_name.triggered.connect(lambda: self.copy_column_name(logical)); menu.addAction(action_copy_name)
        action_filter = QAction("Filtrar columna...", self)
        action_filter.triggered.connect(lambda: self._show_column_filter_dialog(logical))
        menu.addAction(action_filter)
        menu.exec_(self.horizontalHeader().mapToGlobal(pos))
        
    def _show_column_filter_dialog(self, col_index):
        if self.original_df.empty:
            return

        col_name = self.horizontalHeaderItem(col_index).text().lstrip('▼ ').strip()
        # Get the base column name without space for filtering
        base_col_name = col_name.split(' ')[0] if ' ' in col_name and col_name.split(' ')[-1].isdigit() else col_name
        if base_col_name not in self.original_df.columns:
            return

        unique_values = sorted(self.original_df[base_col_name].dropna().astype(str).unique())
        
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Filtrar: {col_name}")
        dlg.resize(300, 400)
        layout = QVBoxLayout(dlg)
        
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Buscar valores...")
        layout.addWidget(search_edit)
        
        list_widget = QListWidget()
        list_widget.setSelectionMode(QListWidget.MultiSelection)
        
        for value in unique_values:
            item = QListWidgetItem(str(value))
            list_widget.addItem(item)
            
            if col_name in self.column_filters and str(value) in self.column_filters[col_name]:
                item.setSelected(True)
        
        layout.addWidget(list_widget)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dlg.accept)
        button_box.rejected.connect(dlg.reject)
        layout.addWidget(button_box)
        
        search_edit.textChanged.connect(lambda text: self._filter_list_items(list_widget, text))
        
        if dlg.exec_() == QDialog.Accepted:
            selected_values = [item.text() for item in list_widget.selectedItems()]
            if selected_values:
                self.column_filters[base_col_name] = selected_values
            elif base_col_name in self.column_filters:
                del self.column_filters[base_col_name]

            self._apply_column_filters()
            
    def _filter_list_items(self, list_widget, text):
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            item.setHidden(text.lower() not in item.text().lower())
            
    def _apply_column_filters(self):
        if self.original_df.empty:
            return
            
        df = self.original_df.copy()
        
        for col_name, values in self.column_filters.items():
            if col_name in df.columns:
                df = df[df[col_name].astype(str).isin(values)]
            else:
                # Try to find column with space if original doesn't exist
                matching_cols = [c for c in df.columns if c.startswith(col_name + ' ') and c[len(col_name) + 1:].isdigit()]
                if matching_cols:
                    df = df[df[matching_cols[0]].astype(str).isin(values)]
                
        self.current_df = df
        self._display(self.current_df)
        self.app_window._apply_filters_in_real_time()
        self._update_filter_indicators()
        
    def _update_filter_indicators(self):
        for i in range(self.columnCount()):
            col_name = self.horizontalHeaderItem(i).text().lstrip('▼ ').strip()
            # Remove space for filter checking
            base_col_name = col_name.split(' ')[0] if ' ' in col_name and col_name.split(' ')[-1].isdigit() else col_name
            if base_col_name in self.column_filters:
                self.horizontalHeaderItem(i).setText(f"▼ {col_name}")
            else:
                self.horizontalHeaderItem(i).setText(col_name)
    def _install_table_context_menu(self):
        self.setContextMenuPolicy(Qt.CustomContextMenu); self.customContextMenuRequested.connect(self._on_table_menu)
        
    def _on_table_menu(self, pos: QPoint):
        if self.rowCount() == 0: return
        menu = QMenu(self)
        a1 = QAction("Copiar selección (incl. cabecera)", self); a1.triggered.connect(self.copy_selection_with_header); menu.addAction(a1)
        a2 = QAction("Copiar solo celdas seleccionadas", self); a2.triggered.connect(self.copy_cells_only); menu.addAction(a2)
        a3 = QAction("Copiar resultados filtrados (incl. cabecera)", self); a3.triggered.connect(self.copy_filtered); menu.addAction(a3)
        menu.exec_(self.viewport().mapToGlobal(pos))
        
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        # Excel-like shortcuts
        if mods == Qt.ControlModifier:
            if key == Qt.Key_C:
                self.copy_cells_only()
                event.accept()
                return
            elif key == Qt.Key_A:  # Ctrl+A - Select all
                self.selectAll()
                event.accept()
                return
            elif key == Qt.Key_Home:  # Ctrl+Home - Go to top-left
                self.setCurrentCell(0, 0)
                event.accept()
                return
            elif key == Qt.Key_End:  # Ctrl+End - Go to bottom-right
                if self.rowCount() > 0 and self.columnCount() > 0:
                    self.setCurrentCell(self.rowCount() - 1, self.columnCount() - 1)
                event.accept()
                return
            elif key == Qt.Key_Left:  # Ctrl+Left - Go to first column
                current_row = self.currentRow()
                if current_row >= 0:
                    self.setCurrentCell(current_row, 0)
                event.accept()
                return
            elif key == Qt.Key_Right:  # Ctrl+Right - Go to last column
                current_row = self.currentRow()
                if current_row >= 0 and self.columnCount() > 0:
                    self.setCurrentCell(current_row, self.columnCount() - 1)
                event.accept()
                return
            elif key == Qt.Key_Up:  # Ctrl+Up - Go to first row
                current_col = self.currentColumn()
                if current_col >= 0:
                    self.setCurrentCell(0, current_col)
                event.accept()
                return
            elif key == Qt.Key_Down:  # Ctrl+Down - Go to last row
                current_col = self.currentColumn()
                if current_col >= 0 and self.rowCount() > 0:
                    self.setCurrentCell(self.rowCount() - 1, current_col)
                event.accept()
                return
            elif key == Qt.Key_Space:  # Ctrl+Space - Select entire column
                current_col = self.currentColumn()
                if current_col >= 0:
                    self.selectColumn(current_col)
                event.accept()
                return
        elif mods == Qt.ShiftModifier:
            if key == Qt.Key_Space:  # Shift+Space - Select entire row
                current_row = self.currentRow()
                if current_row >= 0:
                    self.selectRow(current_row)
                event.accept()
                return
        elif mods == (Qt.ControlModifier | Qt.ShiftModifier):
            if key == Qt.Key_C:  # Ctrl+Shift+C
                self.copy_selection_with_header()
                event.accept()
                return
            elif key == Qt.Key_Home:  # Ctrl+Shift+Home - Select from current to top-left
                current_row = self.currentRow()
                current_col = self.currentColumn()
                if current_row >= 0 and current_col >= 0:
                    self.setSelection(QRect(0, 0, current_col + 1, current_row + 1), QItemSelectionModel.Select)
                event.accept()
                return
            elif key == Qt.Key_End:  # Ctrl+Shift+End - Select from current to bottom-right
                current_row = self.currentRow()
                current_col = self.currentColumn()
                if current_row >= 0 and current_col >= 0 and self.rowCount() > 0 and self.columnCount() > 0:
                    self.setSelection(QRect(current_col, current_row, self.columnCount() - current_col, self.rowCount() - current_row), QItemSelectionModel.Select)
                event.accept()
                return

        # Handle arrow keys for navigation (without modifiers)
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and mods == Qt.NoModifier:
            super().keyPressEvent(event)
            event.accept()
            return

        super().keyPressEvent(event)
        
    def copy_selection_with_header(self):
        if self.current_df.empty: return
        indexes = self.selectedIndexes()
        if not indexes:
            self.copy_filtered()
            return

        rows = sorted(list(set(i.row() for i in indexes)))
        cols = sorted(list(set(i.column() for i in indexes)))

        if not cols: return

        df = self.current_df
        sel_df = df.iloc[rows, cols]

        column_names = [df.columns[c] for c in cols]

        # Copiar nombres de columnas
        header_text = '\t'.join(column_names)

        # Copiar datos con formato Excel-friendly
        data_text = sel_df.to_csv(sep='\t', index=False, header=False)

        clipboard_text = f"{header_text}\n{data_text}"
        QApplication.clipboard().setText(clipboard_text)
        self.app_window.status_bar_widget.status_label.setText(f"Columnas y celdas seleccionadas ({len(column_names)} columnas, {len(rows)} filas) copiadas para Excel.")
        
    def copy_cells_only(self):
        if self.current_df.empty: return
        indexes = self.selectedIndexes()
        if not indexes:
            return
        rows = sorted(set(i.row() for i in indexes))
        cols = sorted(set(i.column() for i in indexes))
        df = self.current_df
        sel_df = df.iloc[rows, cols] if cols else df.iloc[rows]
        QApplication.clipboard().setText(sel_df.to_csv(sep='\t', index=False, header=False))
        
    def copy_filtered(self):
        if self.current_df.empty: return
        QApplication.clipboard().setText(self.current_df.to_csv(sep='\t', index=False))
        
    def copy_column_name(self, col_index=None):
        if col_index is None:
            cols = sorted(set([i.column() for i in self.selectedIndexes()]))
            if not cols: return
            names = [self.horizontalHeaderItem(c).text().lstrip('▼ ').strip() for c in cols]
        else:
            names = [self.horizontalHeaderItem(col_index).text().lstrip('▼ ').strip()]
        # Remove spaces added for duplicate columns to get original names
        original_names = [name.split(' ')[0] if ' ' in name and name.split(' ')[-1].isdigit() else name for name in names]
        QApplication.clipboard().setText(', '.join(original_names))
        
    def set_data(self, df: pd.DataFrame):
        self.original_df = df.copy()
        self.current_df = df.copy()
        self.column_filters = {}
        self._display(self.current_df)
        self._update_filter_indicators()
        
    def _display(self, df: pd.DataFrame):
        self.setSortingEnabled(False)
        self.clear()
        self.setRowCount(len(df))
        self.setColumnCount(len(df.columns))
        # Display column names as they are, allowing duplicates
        self.setHorizontalHeaderLabels([str(c) for c in df.columns])
        # Handle unique columns detection safely for duplicate column names
        unique_cols = []
        for i, col in enumerate(df.columns):
            try:
                col_data = df.iloc[:, i]  # Get column by position to handle duplicates
                if col_data.nunique(dropna=False) == 1:
                    unique_cols.append(col)
            except Exception:
                # Skip if there's an issue with this column
                pass

        for r in range(len(df)):
            row_vals = df.iloc[r].tolist()
            for c, v in enumerate(row_vals):
                if isinstance(v, float) and v.is_integer():
                    v = int(v)
                it = QTableWidgetItem(str(v))
                if df.columns[c] in unique_cols:
                    it.setBackground(QColor("#004400"))  # Dark green background for unique value columns
                self.setItem(r, c, it)
        self.resizeColumnsToContents()
        self.setSortingEnabled(True)
        
    def get_filtered_data(self):
        return self.current_df.copy()

    def _copy_first_row_with_headers(self):
        if self.current_df.empty: return
        first_row = self.current_df.iloc[0:1]
        column_names = list(self.current_df.columns)
        header_text = '\t'.join(column_names)
        data_text = first_row.to_csv(sep='\t', index=False, header=False)
        clipboard_text = f"{header_text}\n{data_text}"
        QApplication.clipboard().setText(clipboard_text)
        self.app_window.status_bar_widget.status_label.setText("Primera fila con headers copiada")

    def _copy_first_column_with_headers(self):
        if self.current_df.empty: return
        first_col_name = self.current_df.columns[0]
        first_col = self.current_df[[first_col_name]]
        header_text = first_col_name
        data_text = first_col.to_csv(sep='\t', index=False, header=False)
        clipboard_text = f"{header_text}\n{data_text}"
        QApplication.clipboard().setText(clipboard_text)
        self.app_window.status_bar_widget.status_label.setText("Primera columna con header copiada")

    def _copy_all_visible_rows_with_headers(self):
        if self.current_df.empty: return
        column_names = list(self.current_df.columns)
        header_text = '\t'.join(column_names)
        data_text = self.current_df.to_csv(sep='\t', index=False, header=False)
        clipboard_text = f"{header_text}\n{data_text}"
        QApplication.clipboard().setText(clipboard_text)
        self.app_window.status_bar_widget.status_label.setText(f"Todas las filas visibles ({len(self.current_df)}) con headers copiadas")

    def _copy_all_visible_columns_with_headers(self):
        if self.current_df.empty: return
        column_names = list(self.current_df.columns)
        header_text = '\t'.join(column_names)
        data_text = self.current_df.to_csv(sep='\t', index=False, header=False)
        clipboard_text = f"{header_text}\n{data_text}"
        QApplication.clipboard().setText(clipboard_text)
        self.app_window.status_bar_widget.status_label.setText(f"Todas las columnas visibles ({len(column_names)}) con headers copiadas")

    def _copy_current_cell_with_header(self):
        current_row = self.currentRow()
        current_col = self.currentColumn()
        if current_row < 0 or current_col < 0 or self.current_df.empty: return

        col_name = self.current_df.columns[current_col]
        cell_value = str(self.current_df.iloc[current_row, current_col])
        clipboard_text = f"{col_name}\n{cell_value}"
        QApplication.clipboard().setText(clipboard_text)
        self.app_window.status_bar_widget.status_label.setText(f"Celda actual ({col_name}) con header copiada")

    def _copy_selected_range_with_headers(self):
        indexes = self.selectedIndexes()
        if not indexes:
            self.parent().status_bar_widget.status_label.setText("No hay selección para copiar")
            return

        rows = sorted(list(set(i.row() for i in indexes)))
        cols = sorted(list(set(i.column() for i in indexes)))

        if not cols: return

        df = self.current_df
        sel_df = df.iloc[rows, cols]

        column_names = [df.columns[c] for c in cols]
        header_text = '\t'.join(column_names)
        data_text = sel_df.to_csv(sep='\t', index=False, header=False)
        clipboard_text = f"{header_text}\n{data_text}"
        QApplication.clipboard().setText(clipboard_text)
        self.app_window.status_bar_widget.status_label.setText(f"Rango seleccionado ({len(rows)} filas, {len(cols)} columnas) con headers copiado")

    def _copy_filtered_rows_with_headers(self):
        if self.current_df.empty: return
        column_names = list(self.current_df.columns)
        header_text = '\t'.join(column_names)
        data_text = self.current_df.to_csv(sep='\t', index=False, header=False)
        clipboard_text = f"{header_text}\n{data_text}"
        QApplication.clipboard().setText(clipboard_text)
        self.app_window.status_bar_widget.status_label.setText(f"Filas filtradas ({len(self.current_df)}) con headers copiadas")

    def _copy_filtered_columns_with_headers(self):
        if self.current_df.empty: return
        # Si hay filtros de columna activos, copiar solo esas columnas
        if self.column_filters:
            filtered_cols = list(self.column_filters.keys())
            if filtered_cols:
                df_filtered = self.current_df[filtered_cols]
                column_names = filtered_cols
                header_text = '\t'.join(column_names)
                data_text = df_filtered.to_csv(sep='\t', index=False, header=False)
                clipboard_text = f"{header_text}\n{data_text}"
                QApplication.clipboard().setText(clipboard_text)
                self.app_window.status_bar_widget.status_label.setText(f"Columnas filtradas ({len(filtered_cols)}) con headers copiadas")
                return

        # Si no hay filtros activos, copiar todas las columnas
        self._copy_all_visible_columns_with_headers()

    def _make_columns_unique(self, columns):
        """Make column names unique by adding underscores when duplicates exist"""
        seen = {}
        result = []
        for col in columns:
            # Convert to string and handle None values
            col_str = str(col) if col is not None else ""
            if col_str in seen:
                seen[col_str] += 1
                result.append(f"{col_str}_{seen[col_str]}")
            else:
                seen[col_str] = 1
                result.append(col_str)
        return result
# ==========================
# Worker de consulta en hilo
# ==========================
class QueryWorker(QObject):
    finished = pyqtSignal(object, float, str)
    error = pyqtSignal(str)
    
    def __init__(self, engine, query_text, table_name=""):
        super().__init__()
        self.engine = engine
        self.query_text = query_text
        self.table_name = table_name
        
    def run(self):
        try:
            t0 = time.perf_counter()
            with self.engine.connect() as conn:
                # Verificar si es una consulta compleja con múltiples statements
                if self._is_multi_statement_query(self.query_text):
                    # Ejecutar múltiples statements y obtener el último resultado
                    df = self._execute_multi_statement_query(conn, self.query_text)
                else:
                    # Consulta normal
                    df = pd.read_sql(text(self.query_text), conn)
            t = time.perf_counter() - t0
            self.finished.emit(df, t, self.table_name)
        except Exception as e:
            self.error.emit(str(e))

    def _is_multi_statement_query(self, query):
        """Verificar si la consulta contiene múltiples statements"""
        # Contar statements SELECT, INSERT, UPDATE, DELETE, CREATE, DROP
        statements = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'WITH']
        count = 0
        for stmt in statements:
            if stmt in query.upper():
                count += 1
        return count > 1 or ';' in query

    def _execute_multi_statement_query(self, conn, query):
        """Ejecutar consulta con múltiples statements"""
        try:
            # Dividir la consulta en statements individuales
            statements = [stmt.strip() for stmt in query.split(';') if stmt.strip()]

            result_df = None
            for stmt in statements:
                if not stmt:
                    continue

                # Si es un SELECT o WITH (CTE), obtener el resultado
                if stmt.upper().strip().startswith('SELECT') or stmt.upper().strip().startswith('WITH'):
                    result_df = pd.read_sql(text(stmt), conn)
                else:
                    # Ejecutar otros statements (CREATE, INSERT, etc.)
                    conn.execute(text(stmt))
                    conn.commit()

            # Si no hay SELECT, devolver un DataFrame vacío
            if result_df is None:
                result_df = pd.DataFrame()

            return result_df

        except Exception as e:
            # Si hay error, intentar ejecutar como consulta normal
            return pd.read_sql(text(query), conn)
# ==========================
# Historial de consultas frecuentes (manual)
# ==========================
class QueryHistoryStore:
    def __init__(self, path):
        self.path = path
        self._data = load_json(self.path, {})
        
    def _key(self, table):
        return table or "__global__"
        
    def get_for_table(self, table):
        items = self._data.get(self._key(table), [])
        for it in items:
            if 'name' not in it:
                txt = it.get('text', ''); it['name'] = (txt.split('\n', 1)[0] or 'consulta').strip()[:50]
        return list(items)
        
    def set_for_table(self, table, items):
        self._data[self._key(table)] = list(items)
        save_json(self.path, self._data)
        
    def add_manual(self, table, name, text):
        key = self._key(table)
        items = self._data.setdefault(key, [])
        now = datetime.now().isoformat()
        items.append({'name': name, 'text': text, 'created_at': now, 'last_used': now})
        save_json(self.path, self._data)
        
    def rename(self, table, old_name, new_name):
        items = self._data.get(self._key(table), [])
        for it in items:
            if it.get('name') == old_name: it['name'] = new_name; break
        save_json(self.path, self._data)
        
    def delete(self, table, name):
        key = self._key(table)
        items = [it for it in self._data.get(key, []) if it.get('name') != name]
        self._data[key] = items
        save_json(self.path, self._data)
# ==========================
# Diálogo: Ordenación multi-columna
# ==========================
class MultiSortDialog(QDialog):
    def __init__(self, columns, existing=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ordenación Multi-columna")
        self.columns = list(columns); self.items = list(existing or [])
        self._build_ui()
        
    def _build_ui(self):
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(["Columna", "Asc", "Acciones"]); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); lay.addWidget(self.table)
        btns = QHBoxLayout()
        b_add = QPushButton("Agregar"); b_add.clicked.connect(self._add_row); btns.addWidget(b_add)
        b_up = QPushButton("↑"); b_up.clicked.connect(lambda: self._move(-1)); btns.addWidget(b_up)
        b_down = QPushButton("↓"); b_down.clicked.connect(lambda: self._move(1)); btns.addWidget(b_down)
        lay.addLayout(btns)
        okc = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); okc.accepted.connect(self.accept); okc.rejected.connect(self.reject); lay.addWidget(okc)
        for it in self.items: self._add_row(it)
        
    def _add_row(self, data=None):
        r = self.table.rowCount(); self.table.insertRow(r)
        cb = QComboBox(); cb.addItems(self.columns)
        if data and data.get('col') in self.columns: cb.setCurrentText(data['col'])
        self.table.setCellWidget(r, 0, cb)
        chk = QCheckBox(); chk.setChecked(True if not data else bool(data.get('asc', True))); self.table.setCellWidget(r, 1, chk)
        rm = QPushButton("Eliminar"); rm.clicked.connect(lambda: self.table.removeRow(r)); self.table.setCellWidget(r, 2, rm)
        
    def _move(self, direction):
        r = self.table.currentRow()
        if r < 0: return
        new_r = r + direction
        if not (0 <= new_r < self.table.rowCount()): return
        data = self.get_result(); data[r], data[new_r] = data[new_r], data[r]
        self.table.setRowCount(0)
        for it in data: self._add_row(it)
        self.table.setCurrentCell(new_r, 0)
        
    def get_result(self):
        res = []
        for r in range(self.table.rowCount()):
            cb = self.table.cellWidget(r, 0); chk = self.table.cellWidget(r, 1)
            if isinstance(cb, QComboBox) and isinstance(chk, QCheckBox): res.append({'col': cb.currentText(), 'asc': chk.isChecked()})
        return res
# ==========================
# Diálogo de notas
# ==========================
class NotesDialog(QDialog):
    def __init__(self, notes_store, parent=None):
        super().__init__(parent)
        self.notes_store = notes_store
        self.setWindowTitle("Notas")
        self.setModal(True)
        self.resize(600, 400)
        self._build_ui()
        self._load_notes()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Escribe tus notas aquí...")
        layout.addWidget(self.notes_edit)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._save_notes)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
    def _load_notes(self):
        notes = self.notes_store.get_notes()
        self.notes_edit.setPlainText(notes)
        
    def _save_notes(self):
        self.notes_store.save_notes(self.notes_edit.toPlainText())
        self.accept()
# ==========================
# Diálogo de errores
# ==========================
class ErrorLogDialog(QDialog):
    def __init__(self, error_log_store, parent=None):
        super().__init__(parent)
        self.error_log_store = error_log_store
        self.setWindowTitle("Registro de Errores")
        self.setModal(True)
        self.resize(800, 600)
        self._build_ui()
        self._load_errors()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.errors_edit = QPlainTextEdit()
        self.errors_edit.setReadOnly(True)
        layout.addWidget(self.errors_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _load_errors(self):
        errors = self.error_log_store.get_errors()
        error_text = ""
        for error in errors:
            error_text += f"[{error['timestamp']}] {error['type']}: {error['message']}\n\n"
        self.errors_edit.setPlainText(error_text)
# ==========================
# Diálogo de Información del Programa
# ==========================
class ProgramInfoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Información del Programa")
        self.setModal(True)
        self.resize(1000, 500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Agregar logo en la parte superior
        try:
            self.logo_widget = QSvgWidget("logo.svg")
            self.logo_widget.setFixedSize(100, 100)
            layout.addWidget(self.logo_widget, alignment=Qt.AlignCenter)
        except Exception:
            # Si no se puede cargar el logo, continuar sin él
            pass

        # Crear scroll area para el contenido
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)

        info_text = """
        <div style="text-align: center; font-family: Arial, sans-serif; color: #FFFFFF;">
            <h1 style="color: #004400; margin-bottom: 20px;">PROGRAMA: MAESTRO DE CONSULTAS SQL (MC-SQL)</h1>
            <p style="font-size: 16px; margin: 10px 0;"><b>CELULAR:</b> +57 3209820437</p>
            <p style="font-size: 16px; margin: 10px 0;"><b>CREADOR:</b> WILSON DANIEL MARTINEZ LOZANO</p>
            <p style="font-size: 16px; margin: 10px 0;"><b>CIUDAD:</b> BOGOTA</p>
            <p style="font-size: 16px; margin: 10px 0;"><b>PAIS:</b> COLOMBIA</p>
            <p style="font-size: 16px; margin: 10px 0;"><b>DESCRIPCIÓN:</b> El Programa Maestro de Consultas es una herramienta de escritorio segura y eficiente que permite a los usuarios conectarse a bases de datos SQL para realizar consultas de manera rápida y sin riesgos. Su principal función es facilitar la extracción y el análisis de datos (operaciones SELECT) a través de un editor inteligente con funciones como autocompletado y resaltado de sintaxis, mientras bloquea intencionalmente cualquier comando que pueda modificar o borrar información (UPDATE, DELETE), asegurando la integridad de la base de datos. Además, permite gestionar y organizar consultas, guardar perfiles de conexión y exportar los resultados para un análisis posterior.</p>
            <p style="font-size: 16px; margin: 10px 0;"><b>VENTAJAS:</b> Modo totalmente oscuro dark, consultas seguras en las que no puedes editar la base de datos, guarda histórico de todas las consultas realizadas, se crean variables que permiten la modificación de los valores para que estén los formatos que utiliza SQL, se guardan consultas, se guardan consultas frecuentes por tabla además de que puedes consultar y filtrar todas consultas hechas, atajos de teclado para todo para que el flujo de trabajo sea el mejor, puedes guardar perfiles, tiene una alerta de si la consulta llegó al límite de la consulta para que sepas que puede existir más información.</p>
            <p style="font-size: 16px; margin: 10px 0;"><b>PAGINA GITHUB - HOJA DE VIDA:</b><br>
                <a href="https://docs.google.com/document/d/12FXP8qEntlgTynDrCLoKpFXRrZXkiycFY1qcFUDelpc/edit?pli=1&tab=t.0" style="color: #2196F3; text-decoration: none; font-weight: bold;">📄 Ver Hoja de Vida</a>
            </p>
            <p style="font-size: 16px; margin: 10px 0;"><b>GITHUB:</b><br>
                <a href="https://github.com/wilsonads" style="color: #2196F3; text-decoration: none; font-weight: bold;">🐙 https://github.com/wilsonads</a>
            </p>
        </div>
        """

        self.info_label = QLabel(info_text)
        self.info_label.setOpenExternalLinks(True)
        self.info_label.setStyleSheet("QLabel { padding: 20px; }")
        self.info_label.setWordWrap(True)
        content_layout.addWidget(self.info_label)

        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)
# ==========================
# Aplicación principal
# ==========================
class DatabaseQueryApp(QMainWindow):
    def __init__(self):
        self.app_window = self  # Agregar referencia a sí mismo para compatibilidad
        super().__init__()
        self.engine = None
        self.connection_params = {}
        self.all_tables = []
        self.columns_cache = {}
        self.table_columns = []
        self.current_table_name = ""
        self.current_column_name = ""
        self.last_results_df = None
        self.row_limit = 1000
        self.data_directory = DATA_DIRECTORY
        self.active_filters = {}
        self.results_undocked = False
        self._tab_states = {}
        self.saved_queries_full_view = False
        self.variable_focus_index = -1
        self.is_fullscreen_editor = False
        self.original_editor_state = None
        self.f9_active = False
        self.shortcuts = DatabaseQueryApp.default_shortcuts()
        self.status_bar_widget = None  # Initialize to prevent AttributeError
        self.connection_check_timer = QTimer(self)
        self.connection_check_timer.timeout.connect(self._check_connection_status)
        self.connection_check_timer.start(5 * 60 * 1000)  # 5 minutes
        self.retry_connection_timer = QTimer(self)
        self.retry_connection_timer.timeout.connect(self._attempt_connection)
        self.retry_connection_timer.setSingleShot(False)
        self._build_ui()
        self._setup_dark_mode()
        self._setup_paths()
        self.setup_shortcuts()
        self._setup_menu()
        self._load_stores()

        self.setWindowTitle("MAESTRO DE CONSULTAS SQL (MC-SQL)")
        try:
            self.setWindowIcon(QIcon("logo.svg"))
        except Exception:
            # Si no se puede cargar el icono, continuar sin él
            pass
        self.setGeometry(50, 50, 1200, 800)
        self.showNormal()
        self.setMinimumSize(800, 600)

        # Crear 3 pestañas vacías al inicio
        self._create_editor_tab()
        self._create_editor_tab()
        self._create_editor_tab()

        # Seleccionar la primera pestaña
        self.editor_tabs.setCurrentIndex(0)

        self._apply_selection_mode("Celdas")

        # Configurar manejo de resize para botones de resultados
        self.result_buttons = [
            self.analyze_col_btn, self.copy_selection_btn, self.download_results_btn,
            self.view_full_results_btn, self.clear_filters_btn, self.filter_status_btn
        ]
        self.on_resize(None)  # Estado inicial

        # Auto-conectar al primer perfil si existe
        QTimer.singleShot(1000, self._auto_connect_first_profile)
    def _capture_initial_state(self):
        return {
            'connection_params': self.connection_params.copy(),
            'row_limit': self.row_limit,
            'variables': self.variables_panel.to_json(),
            'tabs': [{'query': self.get_editor().toPlainText()}],
            'selection_mode': "Celdas"
        }
    def _restore_initial_state(self):
        try:
            self.connection_params = self.initial_state['connection_params'].copy()
            self.row_limit = self.initial_state['row_limit']
            self.row_limit_combo.setCurrentText(str(self.row_limit))
            self.variables_panel.load_variables(self.initial_state['variables'])
            
            while self.editor_tabs.count() > 1:
                self._close_editor_tab(1)
                
            if self.editor_tabs.count() > 0:
                self.get_editor().setPlainText(self.initial_state['tabs'][0]['query'])
            
            self._apply_selection_mode(self.initial_state['selection_mode'])
            self.selection_mode_combo.setCurrentText(self.initial_state['selection_mode'])
            
            self.status_bar_widget.status_label.setText("Estado inicial restaurado")
            
        except Exception as e:
            error_msg = f"Error al restaurar estado inicial: {str(e)}"
            self.status_bar_widget.status_label.setText(error_msg)
            self.error_log_store.log_error("RestoreStateError", error_msg, datetime.now().isoformat())
    def _post_init_load(self):
        self.status_bar_widget.status_label.setText(f"Conectado a {self.connection_params['database']}@{self.connection_params['server']}")
        self.conn_group.setStyleSheet("QGroupBox#ConnectionGroup { border: 2px solid #4CAF50; background:#003300; } QGroupBox#ConnectionGroup::title { color: #4CAF50; }")
        self._load_tables()
        self.table_list.setFocus()

    def _auto_connect_first_profile(self):
        names = self.profile_store.names()
        if names:
            self._on_profile_selected(names[0])
            self._attempt_connection()

    def _check_connection_status(self):
        if self.engine is None:
            self._start_retry_connection()
            return
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            self._start_retry_connection()

    def _start_retry_connection(self):
        if not self.retry_connection_timer.isActive():
            self.retry_connection_timer.start(60 * 1000)  # 1 minute
            self.status_bar_widget.status_label.setText("Desconectado - Intentando reconectar cada minuto")
    def _setup_paths(self):
        self.query_directory = os.path.join(self.data_directory, "saved_queries")
        self.log_folder = os.path.join(self.data_directory, "query_logs")
        self.tab_results_dir = os.path.join(self.data_directory, "tab_results")
        self.profiles_file = os.path.join(self.data_directory, "connection_profiles.json")
        self.history_file = os.path.join(self.data_directory, "query_history.json")
        self.favorites_file = os.path.join(self.data_directory, "favorites_tags.json")
        self.sort_configs_file = os.path.join(self.data_directory, "sort_configs.json")
        self.notes_file = os.path.join(self.data_directory, "notes.json")
        self.error_log_file = os.path.join(self.data_directory, "error_log.json")
        os.makedirs(self.query_directory, exist_ok=True)
        os.makedirs(self.log_folder, exist_ok=True)
        os.makedirs(self.tab_results_dir, exist_ok=True)
    def _load_stores(self):
        self.profile_store = ProfilesStore(self.profiles_file)
        self.history_store = QueryHistoryStore(self.history_file)
        self.fav_store = FavoritesStore(self.favorites_file)
        self.sort_store = SortConfigStore(self.sort_configs_file)
        self.notes_store = NotesStore(self.notes_file)
        self.error_log_store = ErrorLogStore(self.error_log_file)
        self._reload_profiles_combo()
        self._load_saved_queries()
    @staticmethod
    def default_shortcuts():
        return {
            # Perfil y Conexión
            "Conectar": "F6",
            "Seleccionar Perfil Conexión (Combo)": "Ctrl+Shift+P",
            "Guardar": "Ctrl+Alt+S",
            "Eliminar": "Ctrl+Alt+D",

            # Consultas Guardadas
            "Guardar Consulta": "F10",
            "Foco Buscar Consultas": "Alt+S",
            "Ver todas las consultas guardadas": "Alt+Q",
            "Editar Consulta Guardada": "Ctrl+Alt+E",
            "Renombrar Consulta Guardada": "Ctrl+Alt+R",
            "Eliminar Consulta Guardada": "Ctrl+Alt+Del",

            # Tablas
            "Foco en Tablas": "Alt+T",
            "Buscar Tablas": "Alt+F",
            "Copiar Nombre de Tabla": "Alt+Ctrl+T",
            "Seleccionar Primera Tabla": "Alt+Shift+1",
            "Copiar Tablas Seleccionadas": "Ctrl+Alt+T",

            # Columnas
            "Foco en Columnas": "Alt+L",
            "Foco Buscar Columnas": "Alt+C",
            "Seleccionar Primera Columna": "Alt+Shift+2",
            "Copiar Nombre de Columna": "Ctrl+Shift+C",
            "Seleccionar Columna rut_codigo": "Alt+Shift+R",

            # Editor
            "Foco en Editor": "Alt+E",
            "Generar SELECT": "F1",
            "Ejecutar Consulta": "F5",
            "Vista Previa Variables": "F3",
            "Pantalla Completa Editor": "F2",
            "Pantalla Completa Editor (Alternar)": "Ctrl+F11",
            "Ver primeros 100 datos": "Ctrl+Shift+V",

            # Resultados
            "Foco en Resultados": "Alt+R",
            "Analizar Resultados": "F4",
            "Descargar Resultados": "F7",
            "Alternar Vista Resultados Completos": "F9",
            "Limpiar Filtros": "Alt+X",
            "Cambiar Texto Buscar Resultados": "Alt+B",
            "Foco Buscar Valor": "Ctrl+F",
            "Foco Tipo Columna": "Ctrl+Shift+F",
            "Filtrar columna": "Alt+I",
            "Foco Número de Filas": "Ctrl+L",
            "Foco Tipo Selección": "Ctrl+Shift+S",
            "Cambiar Texto Filas Resultados": "Ctrl+L",
            "Seleccionar Opción Resultados": "Alt+Shift+O",
            "Cambiar Texto Valor Columnas": "Alt+V",
            "Filas 100": "Ctrl+Shift+1",
            "Filas 1000": "Ctrl+Shift+2",
            "Filas 10000": "Ctrl+Shift+3",
            "Filas 100000": "Ctrl+Shift+4",
            "Filas 1000000": "Ctrl+Shift+5",
            "Selección Celdas": "Ctrl+Shift+8",
            "Selección Filas": "Ctrl+Shift+9",
            "Selección Columnas": "Ctrl+Shift+0",
            "Copiar Selección": "Ctrl+C",
            "Copiar celdas y nombres de columnas seleccionadas": "Ctrl+Shift+C",
            "Copiar Primera Fila con Headers": "Ctrl+Alt+4",
            "Copiar Primera Columna con Headers": "Ctrl+Alt+5",
            "Copiar Todas las Filas Visibles con Headers": "Ctrl+Alt+6",
            "Copiar Todas las Columnas Visibles con Headers": "Ctrl+Alt+7",
            "Copiar Celda Actual con Header": "Ctrl+Alt+8",
            "Copiar Rango Seleccionado con Headers": "Ctrl+Alt+9",
            "Copiar Filas Filtradas con Headers": "Ctrl+Shift+6",
            "Copiar Columnas Filtradas con Headers": "Ctrl+Shift+7",

            # Variables
            "Crear Variable": "Alt+Shift+V",
            "Guardar en Variable": "F2",
            "Foco Cuadro Texto Variables": "Alt+Shift+C",
            "Foco Botones Variables": "Alt+Shift+B",
            "Variables: Botón Comas": "Ctrl+Alt+C",
            "Variables: Botón Comillas": "Ctrl+Alt+Q",
            "Variables: Botón Paréntesis": "Ctrl+Alt+P",
            "Insertar Variable 1": "Ctrl+1",
            "Insertar Variable 2": "Ctrl+2",
            "Insertar Variable 3": "Ctrl+3",
            "Insertar Variable 4": "Ctrl+4",
            "Insertar Variable 5": "Ctrl+5",
            "Insertar Variable 6": "Ctrl+6",
            "Insertar Variable 7": "Ctrl+7",
            "Insertar Variable 8": "Ctrl+8",
            "Insertar Variable 9": "Ctrl+9",
            "Insertar Contenido Variable 1": "Ctrl+Alt+1",
            "Insertar Contenido Variable 2": "Ctrl+Alt+2",
            "Insertar Contenido Variable 3": "Ctrl+Alt+3",
            "Insertar Contenido Variable 4": "Ctrl+Alt+4",
            "Insertar Contenido Variable 5": "Ctrl+Alt+5",
            "Insertar Contenido Variable 6": "Ctrl+Alt+6",
            "Insertar Contenido Variable 7": "Ctrl+Alt+7",
            "Insertar Contenido Variable 8": "Ctrl+Alt+8",
            "Insertar Contenido Variable 9": "Ctrl+Alt+9",
            "Foco Variable 1": "Alt+1",
            "Foco Variable 2": "Alt+2",
            "Foco Variable 3": "Alt+3",
            "Foco Variable 4": "Alt+4",
            "Foco Variable 5": "Alt+5",
            "Foco Variable 6": "Alt+6",
            "Foco Variable 7": "Alt+7",
            "Foco Variable 8": "Alt+8",
            "Foco Variable 9": "Alt+9",

            # Consultas Frecuentes
            "Foco Historial": "Alt+H",
            "Foco Lista Consultas Frecuentes": "Alt+Shift+H",
            "Agregar a Historial": "Ctrl+H",
            "Seleccionar Primera Consulta": "Alt+Shift+3",
            "Historial: Agregar": "Ctrl+Shift+A",
            "Historial: Usar": "Ctrl+Shift+U",
            "Historial: Renombrar": "Ctrl+Shift+R",
            "Historial: Editar SQL": "Ctrl+Shift+E",
            "Historial: Eliminar": "Ctrl+Shift+D",
            "Historial: Subir": "Ctrl+Up",
            "Historial: Bajar": "Ctrl+Down",

            # Pestañas y Navegación
            "Nueva Pestaña": "Ctrl+T",
            "Cerrar Pestaña": "Ctrl+W",
            "Siguiente Pestaña": "Ctrl+PgDown",
            "Anterior Pestaña": "Ctrl+PgUp",

            # General
            "Ver Atajos": "F12",
            "Ocultar/Mostrar Paneles Laterales": "F8",
            "Mostrar/Ocultar Barra Inferior y Menú": "F11",
            "Quitar Foco": "Escape",
            "Ir al Escritorio": "Win+D",
            "Abrir Notas": "Ctrl+N",
            "Guardar Sesión": "Ctrl+S",
            "Cargar Sesión": "Alt+O",
            "Limpiar Todo": "Ctrl+Alt+L"
        }
    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        central.setFocusPolicy(Qt.StrongFocus)
        main_lay = QVBoxLayout(central); main_lay.setContentsMargins(0, 0, 0, 0); main_lay.setSpacing(0)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.left_panel = QWidget(); self.center_panel = QWidget(); self.right_panel = QWidget()
        
        self._build_left(); self._build_center(); self._build_right()
        
        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.center_panel)
        self.main_splitter.addWidget(self.right_panel)
        
        self.main_splitter.setSizes([320, 900, 320])
        main_lay.addWidget(self.main_splitter)
        
        # Se elimina la barra de estado de abajo
        self.status_bar_widget = StatusBarWidget()
        self.left_panel_layout.addWidget(self.status_bar_widget, alignment=Qt.AlignBottom)
    def _build_left(self):
        self.left_panel_layout = QVBoxLayout(self.left_panel); self.left_panel_layout.setContentsMargins(2, 2, 2, 2); self.left_panel_layout.setSpacing(0)

        self.conn_group = QGroupBox("Conexión"); self.conn_group.setObjectName("ConnectionGroup")
        self.conn_group.setStyleSheet("QGroupBox#ConnectionGroup { border: 2px solid #E53935; background:#000000; } QGroupBox#ConnectionGroup::title { color: #E53935; }")
        conn_lay = QVBoxLayout(self.conn_group); conn_lay.setContentsMargins(4, 10, 4, 4); conn_lay.setSpacing(4)
        # Add profile combo and logo sharing space
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox(); self.profile_combo.setPlaceholderText("Perfil de conexión…"); self.profile_combo.currentTextChanged.connect(self._on_profile_selected); self.profile_combo.setFixedHeight(30)
        profile_row.addWidget(self.profile_combo)
        try:
            self.logo_widget = QSvgWidget("logo.svg")
            self.logo_widget.setFixedSize(30, 30)
            profile_row.addWidget(self.logo_widget)
        except Exception:
            # Si no se puede cargar el logo, continuar sin él
            pass
        conn_lay.addLayout(profile_row)
        btns_prof = QHBoxLayout(); btns_prof.setContentsMargins(0, 0, 0, 0); btns_prof.setSpacing(4)
        self.save_profile_btn = QPushButton("Guardar"); self.save_profile_btn.setToolTip("Guardar los datos actuales como un perfil"); self.save_profile_btn.clicked.connect(self._save_profile); btns_prof.addWidget(self.save_profile_btn)
        self.delete_profile_btn = QPushButton("Eliminar"); self.delete_profile_btn.clicked.connect(self._delete_profile); btns_prof.addWidget(self.delete_profile_btn)
        # Nuevo botón para crear perfiles
        self.new_profile_btn = QPushButton("Nuevo"); self.new_profile_btn.setToolTip("Crear un nuevo perfil con 3 pestañas y 3 variables por defecto"); self.new_profile_btn.clicked.connect(self._create_new_profile); btns_prof.addWidget(self.new_profile_btn)
        conn_lay.addLayout(btns_prof)
        self.connect_btn = QPushButton("Conectar");
        self.connect_btn.clicked.connect(self._attempt_connection); self.connect_btn.setToolTip("Conectar (F6)")
        conn_lay.addWidget(self.connect_btn)
        self.left_panel_layout.addWidget(self.conn_group)

        saved_group = QGroupBox("Consultas Guardadas"); sg_lay = QVBoxLayout(saved_group); sg_lay.setContentsMargins(4, 10, 4, 4); sg_lay.setSpacing(2)
        search_lay_sq = QHBoxLayout()
        self.saved_queries_search = QLineEdit(); self.saved_queries_search.setPlaceholderText("Buscar consulta…"); self.saved_queries_search.textChanged.connect(self.filter_saved_queries)
        search_lay_sq.addWidget(self.saved_queries_search)
        edit_query_btn = QPushButton("✏️"); edit_query_btn.setFixedSize(24, 24); edit_query_btn.clicked.connect(self._edit_saved_query); edit_query_btn.setToolTip("Editar consulta seleccionada"); search_lay_sq.addWidget(edit_query_btn)
        rename_query_btn = QPushButton("✏️N"); rename_query_btn.setFixedSize(24, 24); rename_query_btn.clicked.connect(self._rename_saved_query); rename_query_btn.setToolTip("Renombrar consulta"); search_lay_sq.addWidget(rename_query_btn)
        self.toggle_saved_queries_btn = QPushButton("👁️"); self.toggle_saved_queries_btn.setFixedSize(24, 24); self.toggle_saved_queries_btn.setToolTip("Alternar vista completa (Alt+Q)"); self.toggle_saved_queries_btn.clicked.connect(self.toggle_full_query_view); search_lay_sq.addWidget(self.toggle_saved_queries_btn)
        sg_lay.addLayout(search_lay_sq)
        self.saved_queries_list = SafeListWidget(); self.saved_queries_list.itemDoubleClicked.connect(self._load_saved_query_item); self.saved_queries_list.activatedByEnter.connect(self._load_saved_query_item); sg_lay.addWidget(self.saved_queries_list)
        btns = QHBoxLayout(); btns.setContentsMargins(0, 0, 0, 0); btns.setSpacing(2)
        self.save_query_btn = QPushButton("💾 Guardar"); self.save_query_btn.setToolTip("Guardar consulta actual (F10)"); self.save_query_btn.clicked.connect(self.save_current_query); btns.addWidget(self.save_query_btn)
        self.delete_query_btn = QPushButton("🗑️ Eliminar"); self.delete_query_btn.setToolTip("Eliminar"); self.delete_query_btn.clicked.connect(self.delete_saved_query); btns.addWidget(self.delete_query_btn)
        self.fav_query_btn = QPushButton("⭐ Favorito"); self.fav_query_btn.setToolTip("Alternar favorito"); self.fav_query_btn.clicked.connect(self._toggle_query_favorite); btns.addWidget(self.fav_query_btn)
        sg_lay.addLayout(btns); self.left_panel_layout.addWidget(saved_group)

        tables_group = QGroupBox("Tablas"); tg_lay = QVBoxLayout(tables_group); tg_lay.setContentsMargins(4, 10, 4, 4); tg_lay.setSpacing(2)
        search_lay = QHBoxLayout(); search_lay.setContentsMargins(0,0,0,0); search_lay.setSpacing(2)
        self.search_input = QLineEdit(); self.search_input.setPlaceholderText("Buscar tabla…"); self.search_input.textChanged.connect(self.filter_tables); search_lay.addWidget(self.search_input)
        copy_table_btn = QPushButton("📋"); copy_table_btn.setToolTip("Copiar nombre de tabla"); copy_table_btn.clicked.connect(self.copy_table_name); search_lay.addWidget(copy_table_btn)
        self.fav_table_chk = QCheckBox("⭐"); self.fav_table_chk.setToolTip("Marcar tabla como favorita"); self.fav_table_chk.stateChanged.connect(self._toggle_table_fav); search_lay.addWidget(self.fav_table_chk)
        tg_lay.addLayout(search_lay)
        self.table_list = SafeListWidget(); self.table_list.setSelectionMode(QAbstractItemView.ExtendedSelection); self.table_list.setFocusPolicy(Qt.StrongFocus); self.table_list.itemClicked.connect(self.select_table_item); self.table_list.activatedByEnter.connect(self.select_table_item)
        # Agregar menú contextual para copiar selección
        self.table_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_list.customContextMenuRequested.connect(self._show_table_context_menu)
        tg_lay.addWidget(self.table_list); self.left_panel_layout.addWidget(tables_group)

        cols_group = QGroupBox("Columnas"); cg_lay = QVBoxLayout(cols_group); cg_lay.setContentsMargins(4, 10, 4, 4); cg_lay.setSpacing(2)
        self.columns_search = QLineEdit(); self.columns_search.setPlaceholderText("Buscar columna…"); self.columns_search.textChanged.connect(self.filter_columns); cg_lay.addWidget(self.columns_search)
        self.columns_list = SafeListWidget(); self.columns_list.itemClicked.connect(self.select_column_item); self.columns_list.itemDoubleClicked.connect(self.insert_column_name_item); self.columns_list.activatedByEnter.connect(self.insert_column_name_item); cg_lay.addWidget(self.columns_list)
        btn_cols = QHBoxLayout(); btn_cols.setContentsMargins(0, 0, 0, 0); btn_cols.setSpacing(2)
        copy_col_btn = QPushButton("Copiar Columna"); copy_col_btn.clicked.connect(self.copy_column_name); btn_cols.addWidget(copy_col_btn)
        copy_all_btn = QPushButton("Copiar Todas"); copy_all_btn.clicked.connect(self.copy_all_columns); btn_cols.addWidget(copy_all_btn)
        cg_lay.addLayout(btn_cols); self.left_panel_layout.addWidget(cols_group)

        # Bottom section with status
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(2, 2, 2, 2)
        bottom_layout.setSpacing(4)
        bottom_layout.addWidget(self.status_bar_widget)
        self.left_panel_layout.addLayout(bottom_layout)
    def _create_new_profile(self):
        # Ask for profile name first
        name, ok = QInputDialog.getText(self, "Nuevo", "Nombre del nuevo perfil:")
        if not ok or not name:
            return

        # Show connection dialog to get the parameters
        dlg = ConnectionDialog(self.connection_params, self)
        dlg.setWindowTitle(f"Configurar Perfil: {name}")
        if dlg.exec_() == QDialog.Accepted:
            params_to_save = dlg.get_connection_params()
            self.profile_store.set(name, params_to_save)
            self._reload_profiles_combo()
            self.profile_combo.setCurrentText(name)

            # Set the current connection params to the new profile
            self.connection_params = params_to_save
            self._on_profile_selected(name)

            # Clear existing tabs
            while self.editor_tabs.count() > 0:
                widget = self.editor_tabs.widget(0)
                self.editor_tabs.removeTab(0)
                widget.deleteLater()

            # Create 3 new tabs
            for i in range(3):
                self._create_editor_tab(query_text=f"SELECT TOP 100 * FROM sys.tables WHERE 1={i+1}")

            # Switch to first tab
            self.editor_tabs.setCurrentIndex(0)

            self.status_bar_widget.status_label.setText(f"Nuevo perfil '{name}' creado con 3 pestañas y 3 variables por defecto")
    
            
    def toggle_full_query_view(self):
        self.saved_queries_full_view = not self.saved_queries_full_view
        self._load_saved_queries()
    def _build_center(self):
        lay = QVBoxLayout(self.center_panel); lay.setContentsMargins(2, 2, 2, 2); lay.setSpacing(2)
        self.center_splitter = QSplitter(Qt.Vertical)
        self.query_group = QGroupBox("Editor"); 
        ql = QVBoxLayout(self.query_group); ql.setContentsMargins(4, 10, 4, 4); ql.setSpacing(4)
        self.editor_tabs = QTabWidget(); 
        self.editor_tabs.setTabsClosable(False); 
        self.editor_tabs.tabCloseRequested.connect(self._close_editor_tab); 
        self.editor_tabs.currentChanged.connect(self._on_tab_changed)
        self.editor_tabs.setStyleSheet("QTabBar::tab { border-bottom: none; } QTabBar::tab:selected { background-color: #FFFF00; color: #000000; }")
        buttons_widget = QWidget()
        top = QHBoxLayout(buttons_widget); top.setContentsMargins(0, 0, 0, 0); top.setSpacing(4)
        exec_btn = QPushButton("Ejecutar"); exec_btn.setToolTip("Ejecutar consulta (F5 o Ctrl+Enter)"); exec_btn.clicked.connect(self.execute_query); exec_btn.setStyleSheet("QPushButton { background-color: #004400; color: white; }"); top.addWidget(exec_btn)
        auto_btn = QPushButton("SELECT"); auto_btn.setToolTip("Generar SELECT (F1)"); auto_btn.clicked.connect(self.auto_generate_select); top.addWidget(auto_btn)
        preview_btn = QPushButton("Vista"); preview_btn.setToolTip("Ver consulta con variables (F3)"); preview_btn.clicked.connect(self.show_variable_preview); top.addWidget(preview_btn)
        sort_btn = QPushButton("Ordenar"); sort_btn.setToolTip("Ordenar resultados (Alt+O)"); sort_btn.clicked.connect(self.open_multi_sort); top.addWidget(sort_btn)
        fullscreen_btn = QPushButton("Pantalla"); fullscreen_btn.setToolTip("Pantalla completa editor (F2)"); fullscreen_btn.clicked.connect(self.toggle_fullscreen_editor); top.addWidget(fullscreen_btn)
        
        self.view_first_100_btn = QPushButton("100");
        self.view_first_100_btn.setToolTip("Ver solo los primeros 100 datos de la tabla (Ctrl+1)");
        self.view_first_100_btn.clicked.connect(self.view_first_100_data);
        top.addWidget(self.view_first_100_btn)

        self.clear_all_btn = QPushButton("Limpiar Todo");
        self.clear_all_btn.setToolTip("Limpiar pestañas, consultas frecuentes y lista de consultas");
        self.clear_all_btn.clicked.connect(self.clear_all_content);
        top.addWidget(self.clear_all_btn)
        
        self.editor_tabs.setCornerWidget(buttons_widget, Qt.TopRightCorner)
        ql.addWidget(self.editor_tabs)
        self.center_splitter.addWidget(self.query_group)
        self.results_group = QGroupBox("Resultados"); rl = QVBoxLayout(self.results_group); rl.setContentsMargins(4, 10, 4, 4); rl.setSpacing(4)
        controls = QHBoxLayout(); controls.setContentsMargins(0, 0, 0, 0); controls.setSpacing(4)
        controls.addWidget(QLabel("Filas:")); 
        self.row_limit_combo = QComboBox()
        self.row_limit_combo.addItems(["100", "1000", "10000", "100000", "1000000"])
        self.row_limit_combo.setCurrentText("1000")
        self.row_limit_combo.currentTextChanged.connect(self.update_row_limit)
        controls.addWidget(self.row_limit_combo)
        controls.addWidget(QLabel("Selección:")); self.selection_mode_combo = QComboBox(); self.selection_mode_combo.addItems(["Celdas", "Filas", "Columnas"]); self.selection_mode_combo.currentTextChanged.connect(self._apply_selection_mode); controls.addWidget(self.selection_mode_combo)
        self.estado_label = QLabel(""); self.estado_label.hide(); controls.addWidget(self.estado_label)
        controls.addStretch(1)
        self.analyze_col_btn = QPushButton("Analizar"); self.analyze_col_btn.setToolTip("Analizar columnas (F4)"); self.analyze_col_btn.clicked.connect(self._analyze_current_results); controls.addWidget(self.analyze_col_btn)
        self.copy_selection_btn = QPushButton("Copiar"); self.copy_selection_btn.setToolTip("Copiar selección (Ctrl+C)"); self.copy_selection_btn.clicked.connect(lambda: self.results_table.copy_cells_only()); controls.addWidget(self.copy_selection_btn)
        self.download_results_btn = QPushButton("Descargar"); self.download_results_btn.setToolTip("Descargar resultados (F7)"); self.download_results_btn.clicked.connect(self.download_results); controls.addWidget(self.download_results_btn)
        self.preview_results_btn = QPushButton("Vista"); self.preview_results_btn.setToolTip("Ver tabla de resultados como Excel (sin descargar)"); self.preview_results_btn.setStyleSheet("QPushButton { background-color: #00AA00; color: white; }"); self.preview_results_btn.clicked.connect(self.preview_results); controls.addWidget(self.preview_results_btn)
        self.view_full_results_btn = QPushButton("Ver Todo"); self.view_full_results_btn.setToolTip("Ver resultados completos (F9)"); self.view_full_results_btn.clicked.connect(self.toggle_f9_view); controls.addWidget(self.view_full_results_btn)
        self.clear_filters_btn = QPushButton("Limpiar"); self.clear_filters_btn.setToolTip("Limpiar filtros (Alt+X)"); self.clear_filters_btn.clicked.connect(self.clear_result_filters); controls.addWidget(self.clear_filters_btn)
        self.filter_status_btn = QPushButton("Estado"); self.filter_status_btn.setToolTip("Filtrar filas donde ESTADO es 1 o 0"); self.filter_status_btn.clicked.connect(self.filter_by_status); controls.addWidget(self.filter_status_btn)

        # Círculo indicador de límite de filas
        self.row_limit_circle = QWidget()
        self.row_limit_circle.setFixedSize(16, 16)
        self.row_limit_circle.setStyleSheet("border-radius: 8px; background-color: #004400;")
        self.row_limit_circle.setToolTip("Indicador de límite de filas alcanzado")
        controls.addWidget(self.row_limit_circle)

        # Botón que contiene todos los botones de resultados
        self.botones_btn = QToolButton()
        self.botones_btn.setText("Botones")
        self.botones_btn.setToolTip("Acceder a todos los botones de resultados")
        self.botones_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu()
        menu.addAction("Analizar", self._analyze_current_results)
        menu.addAction("Copiar", lambda: self.results_table.copy_cells_only())
        menu.addAction("Descargar", self.download_results)
        menu.addAction("Vista", self.preview_results)
        menu.addAction("Ver Todo", self.toggle_f9_view)
        menu.addAction("Limpiar", self.clear_result_filters)
        menu.addAction("Estado", self.filter_by_status)
        menu.addSeparator()
        menu.addAction("Mostrar Combo Filas", lambda: self.row_limit_combo.showPopup())
        menu.addAction("Mostrar Combo Selección", lambda: self.selection_mode_combo.showPopup())
        self.botones_btn.setMenu(menu)
        controls.addWidget(self.botones_btn)

        rl.addLayout(controls)
        filter_bar_layout = QHBoxLayout()
        filter_bar_layout.setContentsMargins(0, 2, 0, 2); filter_bar_layout.setSpacing(4)
        self.global_search_input = QLineEdit()
        self.global_search_input.setPlaceholderText("Buscar en resultados...")
        self.global_search_input.textChanged.connect(self._apply_filters_in_real_time)
        filter_bar_layout.addWidget(self.global_search_input, 1)
        column_filter_widget = QWidget()
        column_filter_layout = QHBoxLayout(column_filter_widget)
        column_filter_layout.setContentsMargins(0,0,0,0); column_filter_layout.setSpacing(4)
        column_filter_layout.addWidget(QLabel("Columna:"))
        self.filter_column_combo = QComboBox(); self.filter_column_combo.setMinimumWidth(120)
        column_filter_layout.addWidget(self.filter_column_combo)
        self.filter_value_input = QLineEdit(); self.filter_value_input.setPlaceholderText("Valor...")
        self.filter_value_input.returnPressed.connect(self._add_filter)
        column_filter_layout.addWidget(self.filter_value_input)
        filter_bar_layout.addWidget(column_filter_widget)
        
        rl.addLayout(filter_bar_layout)
        self.active_filters_scroll = QScrollArea()
        self.active_filters_scroll.setWidgetResizable(True)
        self.active_filters_scroll.setFixedHeight(38)
        self.active_filters_container = QWidget()
        self.active_filters_layout = QHBoxLayout(self.active_filters_container)
        self.active_filters_layout.setContentsMargins(0,0,0,0); self.active_filters_layout.setSpacing(4)
        self.active_filters_layout.setAlignment(Qt.AlignLeft)
        self.active_filters_scroll.setWidget(self.active_filters_container)
        rl.addWidget(self.active_filters_scroll)
        self.results_table = FilterableTableWidget(self); rl.addWidget(self.results_table)
        self.center_splitter.addWidget(self.results_group)
        self.center_splitter.setSizes([360, 680])
        lay.addWidget(self.center_splitter)
    def _build_right(self):
        lay = QVBoxLayout(self.right_panel); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        
        # Sección de Variables
        variables_group = QGroupBox("Variables"); 
        vl = QVBoxLayout(variables_group); vl.setContentsMargins(4, 10, 4, 4); vl.setSpacing(2)
        self.variables_panel = VariablesPanel(self); vl.addWidget(self.variables_panel)
        lay.addWidget(variables_group)
        
        # Sección de Consultas Frecuentes
        history_group = QGroupBox("Consultas Frecuentes"); 
        hl = QVBoxLayout(history_group); hl.setContentsMargins(4, 10, 4, 4); hl.setSpacing(2)
        search_lay_hist = QHBoxLayout()
        self.history_search = QLineEdit(); self.history_search.setPlaceholderText("Buscar por nombre, tabla o N°…"); self.history_search.textChanged.connect(self.filter_history)
        search_lay_hist.addWidget(self.history_search)
        
        # CORREGIDO: Botones para ver todas las consultas
        self.view_all_queries_btn = QPushButton("Ver Todo");
        self.view_all_queries_btn.setToolTip("Ver todas las consultas guardadas (sin filtrar por tabla)");
        self.view_all_queries_btn.clicked.connect(self._show_all_saved_queries);
        self.return_to_frequent_btn = QPushButton("Regresar a Frecuentes")
        self.return_to_frequent_btn.hide()
        self.return_to_frequent_btn.clicked.connect(self._return_to_frequent_queries)
        search_lay_hist.addWidget(self.view_all_queries_btn)
        search_lay_hist.addWidget(self.return_to_frequent_btn)
        hl.addLayout(search_lay_hist)
        
        self.history_list = SafeListWidget(); self.history_list.itemDoubleClicked.connect(self._load_history_query_item); self.history_list.activatedByEnter.connect(self._load_history_query_item); hl.addWidget(self.history_list)
        
        btns = QHBoxLayout(); btns.setContentsMargins(0, 0, 0, 0); btns.setSpacing(2)
        self.add_history_btn = QPushButton("Agregar"); self.add_history_btn.setToolTip("Agregar consulta actual a frecuentes"); self.add_history_btn.clicked.connect(self._add_history_item); btns.addWidget(self.add_history_btn)
        self.rename_history_btn = QPushButton("Renombrar"); self.rename_history_btn.setToolTip("Renombrar consulta seleccionada"); self.rename_history_btn.clicked.connect(self._rename_history_item); btns.addWidget(self.rename_history_btn)
        self.edit_history_btn = QPushButton("Editar"); self.edit_history_btn.setToolTip("Editar consulta seleccionada"); self.edit_history_btn.clicked.connect(self._edit_history_item); btns.addWidget(self.edit_history_btn)
        self.delete_history_btn = QPushButton("Eliminar"); self.delete_history_btn.setToolTip("Eliminar consulta seleccionada"); self.delete_history_btn.clicked.connect(self._delete_history_item); btns.addWidget(self.delete_history_btn)
        self.fav_history_btn = QPushButton("⭐ Favorito"); self.fav_history_btn.setToolTip("Marcar/desmarcar como favorito"); self.fav_history_btn.clicked.connect(self._toggle_history_favorite); btns.addWidget(self.fav_history_btn)
        hl.addLayout(btns)
        
        lay.addWidget(history_group)
        
    def _show_all_saved_queries(self):
        # Mostrar todas las consultas del archivo query_history.json
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
        except:
            history_data = {}

        self.history_list.clear()

        # Agregar filtros de búsqueda
        if not hasattr(self, 'table_filter_edit'):
            # Crear widgets de filtro si no existen
            self.table_filter_edit = QLineEdit()
            self.table_filter_edit.setPlaceholderText("Filtrar por tabla...")
            self.table_filter_edit.textChanged.connect(self._filter_all_queries_list)

            self.name_filter_edit = QLineEdit()
            self.name_filter_edit.setPlaceholderText("Filtrar por nombre...")
            self.name_filter_edit.textChanged.connect(self._filter_all_queries_list)

            # Insertar los filtros en el layout
            self.history_search.parent().layout().insertWidget(0, self.name_filter_edit)
            self.history_search.parent().layout().insertWidget(0, self.table_filter_edit)
        else:
            # Mostrar los filtros si ya existen
            self.table_filter_edit.show()
            self.name_filter_edit.show()

        row = 0
        self.all_queries_data = []  # Guardar datos para filtrado

        for table_key, queries in history_data.items():
            table_name = table_key if table_key != "__global__" else "Global"
            for i, query in enumerate(queries):
                fav = "⭐" if self.fav_store.is_query_fav(query.get('name', '')) else ""
                display_text = f"{row+1} {fav} {table_name}: {query.get('name', '')}"
                item = QListWidgetItem(display_text)
                item.setToolTip(query.get('text', ''))

                # Guardar información adicional en el item
                item.setData(Qt.UserRole, {
                    'name': query.get('name', ''),
                    'table': table_name,
                    'text': query.get('text', ''),
                    'row': row
                })

                self.history_list.addItem(item)
                self.all_queries_data.append({
                    'item': item,
                    'table': table_name.lower(),
                    'name': query.get('name', '').lower(),
                    'row': str(row + 1)
                })
                row += 1

        self.saved_queries_full_view = True
        self.view_all_queries_btn.hide()
        self.return_to_frequent_btn.show()

    def _populate_all_queries_list(self):
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
        except:
            history_data = {}

        self.all_queries_list.clear()
        row = 0
        for table_key, queries in history_data.items():
            table_name = table_key if table_key != "__global__" else "Global"
            for i, query in enumerate(queries):
                fav = "⭐" if self.fav_store.is_query_fav(query.get('name', '')) else ""
                display_text = f"{i+1} {fav} {table_name}: {query.get('name', '')}"
                item = QListWidgetItem(display_text)
                item.setToolTip(query.get('text', ''))
                item.setData(Qt.UserRole, query.get('name', ''))
                self.all_queries_list.addItem(item)
                row += 1

    def _filter_all_queries_list(self):
        table_filter = self.table_filter_edit.text().strip().lower()
        name_filter = self.name_filter_edit.text().strip().lower()

        for i in range(self.all_queries_list.count()):
            item = self.all_queries_list.item(i)
            text = item.text().lower()
            show = True
            if table_filter and table_filter not in text:
                show = False
            if name_filter and name_filter not in text:
                show = False
            item.setHidden(not show)

    def _load_from_all_queries_list(self, item):
        query_text = item.toolTip()
        if query_text:
            self.get_editor().setPlainText(query_text)
            self.status_bar_widget.status_label.setText("Consulta cargada desde lista de todas las consultas")

    def _toggle_fav_from_list(self):
        current_item = self.all_queries_list.currentItem()
        if not current_item: return
        name = current_item.data(Qt.UserRole)
        if name:
            current_fav = self.fav_store.is_query_fav(name)
            self.fav_store.set_query_fav(name, not current_fav)
            # Update display
            text = current_item.text()
            if current_fav:
                text = text.replace("⭐ ", "")
            else:
                text = "⭐ " + text
            current_item.setText(text)
        
    def _filter_all_queries_list(self):
        if not hasattr(self, 'all_queries_data'):
            return

        table_filter = self.table_filter_edit.text().strip().lower()
        name_filter = self.name_filter_edit.text().strip().lower()

        for data in self.all_queries_data:
            show = True
            if table_filter and table_filter not in data['table']:
                show = False
            if name_filter and name_filter not in data['name']:
                show = False
            data['item'].setHidden(not show)

    def _return_to_frequent_queries(self):
        self.saved_queries_full_view = False
        if hasattr(self, 'table_filter_edit'):
            self.table_filter_edit.hide()
            self.name_filter_edit.hide()
        self.history_search.clear()
        self.view_all_queries_btn.show()
        self.return_to_frequent_btn.hide()
        self._refresh_history_list()
    def _load_history_query_item(self, item):
        try:
            # Verificar que el item aún sea válido
            if not item or not hasattr(item, 'data'):
                return

            if self.saved_queries_full_view and item.data(Qt.UserRole):
                # Modo "Ver Todo" - usar datos del UserRole
                data = item.data(Qt.UserRole)
                if isinstance(data, dict) and 'text' in data:
                    query_text = data['text']
                    self.get_editor().setPlainText(query_text)
                    self.status_bar_widget.status_label.setText(f"Consulta '{data.get('name', '')}' cargada.")
                    return

            # Modo normal - usar tooltip
            query_text = item.toolTip()
            if query_text:
                self.get_editor().setPlainText(query_text)
                self.status_bar_widget.status_label.setText(f"Consulta '{item.text().split(' ', 1)[-1].strip()}' cargada.")
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
    def _setup_dark_mode(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color:#000000; color:#FFFFFF; }
            QGroupBox { font-weight:bold; border:1px solid #333333; border-radius:4px; margin-top:6px; padding-top:6px; background-color:#000000; }
            QGroupBox::title { subcontrol-origin: margin; left:6px; padding:0 4px; color:#FFFFFF; }
            QPushButton { background-color:#000000; border:1px solid #555555; padding:4px 8px; border-radius:3px; color:#FFFFFF; }
            QPushButton:hover { background-color:#333333; }
            QPushButton:pressed { background-color:#444444; }
            QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox { background-color:#000000; border:1px solid #555555; color:#FFFFFF; padding:4px; border-radius:3px; }
            QListWidget, QTableWidget { background-color:#000000; border:1px solid #555555; color:#FFFFFF; alternate-background-color:#111111; gridline-color: #333333; }
            QListWidget::item:selected, QTableWidget::item:selected { background-color:#00AA00; color:#FFFFFF; }
            QHeaderView::section { background-color:#222222; border:1px solid #555555; color:#FFFFFF; padding:4px; }
            QTableCornerButton::section { background-color: #000000; border: 1px solid #555555; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background-color: #000000; border: 1px solid #555555; selection-background-color: #00AA00; color: #FFFFFF; }
            QScrollBar:vertical, QScrollBar:horizontal { background:#000000; width:14px; height:14px; margin:0px; border: 1px solid #333333; border-radius: 7px; }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background:#444444; min-height:30px; min-width:30px; border-radius:7px; border: 1px solid #666666; }
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background:#666666; }
            QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed { background:#888888; }
            QScrollBar::add-line, QScrollBar::sub-line { height:0px; width:0px; }
            QScrollBar::add-page, QScrollBar::sub-page { background:#000000; }
            QScrollBar::up-arrow, QScrollBar::down-arrow, QScrollBar::left-arrow, QScrollBar::right-arrow { border: none; background: none; color: #FFFFFF; }
            QStatusBar { background:#000000; color:#FFFFFF; border-top: 1px solid #555555;}
            QStatusBar::item { border: none; }
            QTabWidget::pane { border-top: 1px solid #555555; background-color:#000000; }
            QTabBar::tab { background:#000000; color:#FFFFFF; border:1px solid #555555; padding:6px 10px; margin-right:2px; border-bottom: none; }
            QTabBar::tab:selected { background-color: #FFD700; color: #000000; }
            QTabBar::tab:!selected:hover { background:#333333; }
            QMenuBar { background-color: #000000; color: #FFFFFF; border-bottom: 1px solid #555555; }
            QMenu { background-color: #000000; border: 1px solid #555555; }
            QMenu::item:selected { background-color: #004400; color: #FFFFFF; }
            QMenuBar::item:selected { background-color: #004400; color: #FFFFFF; }
            QScrollArea { border: none; background-color:#000000; }
            QFrame { background-color:#000000; }
            QDialog { background-color:#000000; }
        """)
        
    def _setup_menu(self):
        bar = self.menuBar(); file_menu = bar.addMenu("Archivo")
        save_session = QAction("Guardar Sesión", self); save_session.setShortcut(QKeySequence("Ctrl+S")); save_session.triggered.connect(self.save_session); file_menu.addAction(save_session)
        load_session = QAction("Cargar Sesión", self); load_session.setShortcut(QKeySequence("Alt+O")); load_session.triggered.connect(self.load_session); file_menu.addAction(load_session)
        file_menu.addSeparator()
        exit_action = QAction("Salir", self); exit_action.setShortcut(QKeySequence("Alt+F4")); exit_action.triggered.connect(self.close); file_menu.addAction(exit_action)
        tools_menu = bar.addMenu("Herramientas")
        shortcuts_action = QAction("Atajos de Teclado", self); shortcuts_action.setShortcut(QKeySequence("F12")); shortcuts_action.triggered.connect(self.show_shortcuts_dialog); tools_menu.addAction(shortcuts_action)
        change_dir_action = QAction("Cambiar Carpeta de Datos", self); change_dir_action.triggered.connect(self._change_data_directory); tools_menu.addAction(change_dir_action)
        open_logs_action = QAction("Abrir Carpeta de Logs", self); open_logs_action.triggered.connect(lambda: safe_os_open(self.log_folder)); tools_menu.addAction(open_logs_action)
        
        notes_action = QAction("Notas", self); notes_action.setShortcut(QKeySequence("Ctrl+N")); notes_action.triggered.connect(self.open_notes); tools_menu.addAction(notes_action)
        
        error_log_action = QAction("Registro de Errores", self); error_log_action.triggered.connect(self.open_error_log); tools_menu.addAction(error_log_action)

        program_info_action = QAction("Información del Programa", self); program_info_action.triggered.connect(self.open_program_info); tools_menu.addAction(program_info_action)

        restore_state_action = QAction("Restaurar Estado Inicial", self); restore_state_action.triggered.connect(self._restore_initial_state); tools_menu.addAction(restore_state_action)
    def setup_shortcuts(self):
        for child in self.findChildren(QShortcut): child.setParent(None)
        m = self.shortcuts
        def add(sc, fn):
            if sc: QShortcut(QKeySequence(sc), self, activated=fn)
        add(m.get("Conectar"), self._attempt_connection)
        add(m.get("Foco en Tablas"), lambda: self.table_list.setFocus())
        add(m.get("Buscar Tablas"), lambda: self.search_input.setFocus())
        add(m.get("Foco en Columnas"), lambda: self.columns_list.setFocus())
        add(m.get("Foco en Editor"), lambda: self.get_editor().setFocus())
        add(m.get("Foco en Resultados"), lambda: self.results_table.setFocus())
        add(m.get("Generar SELECT"), self.auto_generate_select)
        add(m.get("Guardar en Variable"), self.save_results_to_variable)
        add(m.get("Ejecutar Consulta"), self.execute_query)
        add(m.get("Copiar Nombre de Tabla"), self.copy_table_name)
        add(m.get("Copiar Selección"), self.results_table.copy_cells_only)
        add(m.get("Copiar celdas y nombres de columnas seleccionadas"), self.results_table.copy_selection_with_header)
        add(m.get("Descargar Resultados"), self.download_results)
        add(m.get("Crear Variable"), self.variables_panel.add_new_variable_dialog)
        add(m.get("Ocultar/Mostrar Paneles Laterales"), self._toggle_side_panels)
        add(m.get("Alternar Vista Resultados Completos"), self.toggle_f9_view)
        add(m.get("Guardar Consulta"), self.save_current_query)
        add(m.get("Vista Previa Variables"), self.show_variable_preview)
        add(m.get("Ver Atajos"), self.show_shortcuts_dialog)
        add(m.get("Siguiente Pestaña"), self._next_tab)
        add(m.get("Anterior Pestaña"), self._prev_tab)
        add(m.get("Nueva Pestaña"), self._new_editor_tab_from_current_table)
        add(m.get("Cerrar Pestaña"), self._close_current_tab)
        add(m.get("Quitar Foco"), self.clear_focus)
        add(m.get("Analizar Resultados"), self._analyze_current_results)
        add(m.get("Limpiar Filtros"), self.clear_result_filters)
        add(m.get("Foco Buscar Consultas"), lambda: self.saved_queries_search.setFocus())
        add(m.get("Foco Buscar Columnas"), lambda: self.columns_search.setFocus())
        add(m.get("Foco Historial"), lambda: self.history_search.setFocus())
        add(m.get("Foco Lista Consultas Frecuentes"), lambda: self.history_list.setFocus())
        add(m.get("Agregar a Historial"), self._add_history_item)
        add(m.get("Mostrar/Ocultar Barra Inferior y Menú"), self._toggle_bottom_bar_and_menu)
        add(m.get("Ir al Escritorio"), self.minimize_to_desktop)
        add(m.get("Abrir Notas"), self.open_notes)
        add(m.get("Pantalla Completa Editor"), self.toggle_fullscreen_editor)
        
        add(m.get("Cambiar Texto Filas Resultados"), lambda: self.row_limit_combo.showPopup())
        add(m.get("Seleccionar Opción Resultados"), lambda: self.selection_mode_combo.showPopup())
        add(m.get("Seleccionar Columna rut_codigo"), self._select_rut_codigo_column)
        add(m.get("Cambiar Texto Valor Columnas"), lambda: self.filter_value_input.setFocus())
        add(m.get("Cambiar Texto Buscar Resultados"), lambda: self.global_search_input.setFocus())
        add(m.get("Foco Cuadro Texto Variables"), self._focus_variable_textbox)
        add(m.get("Foco Botones Variables"), self._focus_variable_buttons)
        add(m.get("Foco Botones Consultas Frecuentes"), self._focus_frequent_queries_buttons)
        
        add(m.get("Foco Número de Filas"), lambda: self.row_limit_combo.showPopup())
        add(m.get("Foco Tipo Selección"), lambda: self.selection_mode_combo.showPopup())
        add(m.get("Foco Buscar Valor"), lambda: self.filter_value_input.setFocus())
        add(m.get("Foco Tipo Columna"), lambda: self.filter_column_combo.showPopup())
        add(m.get("Pantalla Completa Editor (Alternar)"), self.toggle_fullscreen_editor)
        add(m.get("Seleccionar Perfil Conexión (Combo)"), lambda: self.profile_combo.showPopup())
        
        add(m.get("Variables: Botón Comas"), self._trigger_variable_button_commas)
        add(m.get("Variables: Botón Comillas"), self._trigger_variable_button_quotes)
        add(m.get("Variables: Botón Paréntesis"), self._trigger_variable_button_parenthesis)
        add(m.get("Historial: Agregar"), self._add_history_item)
        add(m.get("Historial: Usar"), lambda: self._use_history_item(self.history_list.currentItem()))
        add(m.get("Historial: Renombrar"), self._rename_history_item)
        add(m.get("Historial: Editar SQL"), self._edit_history_item)
        add(m.get("Historial: Eliminar"), self._delete_history_item)
        add(m.get("Historial: Subir"), lambda: self._move_history_item(-1))
        add(m.get("Historial: Bajar"), lambda: self._move_history_item(1))
        add(m.get("Guardar Sesión"), self.save_session)
        add(m.get("Cargar Sesión"), self.load_session)
        add(m.get("Limpiar Todo"), self.clear_all_content)
        add(m.get("Guardar Perfil"), self._save_profile)
        add(m.get("Eliminar Perfil"), self._delete_profile)
        add(m.get("Editar Consulta Guardada"), self._edit_saved_query)
        add(m.get("Renombrar Consulta Guardada"), self._rename_saved_query)
        add(m.get("Eliminar Consulta Guardada"), self.delete_saved_query)
        add(m.get("Ver primeros 100 datos"), self.view_first_100_data)
        add(m.get("Filtrar columna"), self._filter_current_column)
        add(m.get("Ver todas las consultas guardadas"), self.toggle_full_query_view)
        add(m.get("Seleccionar Primera Tabla"), lambda: self.table_list.setCurrentRow(0) if self.table_list.count() > 0 else None)
        add(m.get("Seleccionar Primera Columna"), lambda: self.columns_list.setCurrentRow(0) if self.columns_list.count() > 0 else None)
        add(m.get("Seleccionar Primera Consulta"), lambda: self.history_list.setCurrentRow(0) if self.history_list.count() > 0 else None)
        add(m.get("Foco Combo Filas"), lambda: self.row_limit_combo.showPopup())
        add(m.get("Foco Combo Selección"), lambda: self.selection_mode_combo.showPopup())
        add(m.get("Foco Combo Columna Filtro"), lambda: self.filter_column_combo.showPopup())
        add(m.get("Filas 100"), lambda: self.row_limit_combo.setCurrentText("100"))
        add(m.get("Filas 1000"), lambda: self.row_limit_combo.setCurrentText("1000"))
        add(m.get("Filas 10000"), lambda: self.row_limit_combo.setCurrentText("10000"))
        add(m.get("Filas 100000"), lambda: self.row_limit_combo.setCurrentText("100000"))
        add(m.get("Filas 1000000"), lambda: self.row_limit_combo.setCurrentText("1000000"))
        add(m.get("Selección Celdas"), lambda: self.selection_mode_combo.setCurrentText("Celdas"))
        add(m.get("Selección Filas"), lambda: self.selection_mode_combo.setCurrentText("Filas"))
        add(m.get("Selección Columnas"), lambda: self.selection_mode_combo.setCurrentText("Columnas"))
        add(m.get("Copiar Primera Fila con Headers"), self.results_table._copy_first_row_with_headers)
        add(m.get("Copiar Primera Columna con Headers"), self.results_table._copy_first_column_with_headers)
        add(m.get("Copiar Todas las Filas Visibles con Headers"), self.results_table._copy_all_visible_rows_with_headers)
        add(m.get("Copiar Todas las Columnas Visibles con Headers"), self.results_table._copy_all_visible_columns_with_headers)
        add(m.get("Copiar Celda Actual con Header"), self.results_table._copy_current_cell_with_header)
        add(m.get("Copiar Rango Seleccionado con Headers"), self.results_table._copy_selected_range_with_headers)
        add(m.get("Copiar Filas Filtradas con Headers"), self.results_table._copy_filtered_rows_with_headers)
        add(m.get("Copiar Columnas Filtradas con Headers"), self.results_table._copy_filtered_columns_with_headers)
        add(m.get("Copiar Tablas Seleccionadas"), self._copy_selected_tables)
        for i in range(1, 10):
            sc = m.get(f"Insertar Variable {i}")
            if sc:
                QShortcut(QKeySequence(sc), self, activated=lambda idx=i-1: self._insert_variable_name(idx))
        for i in range(1, 10):
            sc = m.get(f"Insertar Contenido Variable {i}")
            if sc:
                QShortcut(QKeySequence(sc), self, activated=lambda idx=i-1: self._insert_variable_content(idx))
        for i in range(1, 10):
            sc = m.get(f"Foco Variable {i}")
            if sc:
                QShortcut(QKeySequence(sc), self, activated=lambda idx=i-1: self._focus_variable_by_index(idx))
    def _trigger_variable_button_commas(self):
        vb = self.variables_panel.find_variable_with_focus()
        if vb: vb._join_commas()
        
    def _trigger_variable_button_quotes(self):
        vb = self.variables_panel.find_variable_with_focus()
        if vb: vb._join_quotes()
        
    def _trigger_variable_button_parenthesis(self):
        vb = self.variables_panel.find_variable_with_focus()
        if vb: vb._join_parenthesis()

    def _insert_variable_name(self, index):
        if index < len(self.variables_panel.variable_boxes):
            name = self.variables_panel.variable_boxes[index].name
            editor = self.get_editor()
            cursor = editor.textCursor()
            cursor.insertText(name)

    def _insert_variable_content(self, index):
        if index < len(self.variables_panel.variable_boxes):
            content = self.variables_panel.variable_boxes[index].value
            editor = self.get_editor()
            cursor = editor.textCursor()
            cursor.insertText(content)

    def _focus_variable_by_index(self, index):
        if index < len(self.variables_panel.variable_boxes):
            self.variables_panel.variable_boxes[index].value_display.setFocus()
    def _select_rut_codigo_column(self):
        if self.last_results_df is not None and 'rut_codigo' in self.last_results_df.columns:
            col_index = list(self.last_results_df.columns).index('rut_codigo')
            self.results_table.selectColumn(col_index)
    def _focus_variable_textbox(self):
        next_tb = self.variables_panel.find_next_variable_text_box()
        if next_tb:
            next_tb.setFocus()
    def _focus_variable_buttons(self):
        if self.variables_panel.variable_boxes:
            self.variables_panel.variable_boxes[0].findChild(QPushButton, "btn_commas").setFocus()
    def _focus_frequent_queries_buttons(self):
        self.add_history_btn.setFocus()
    
    def _filter_current_column(self):
        col_index = self.results_table.currentColumn()
        if col_index >= 0:
            self.results_table._show_column_filter_dialog(col_index)
    def _toggle_bottom_bar_and_menu(self):
        if self.menuBar().isVisible():
            self.menuBar().hide()
            self.status_bar_widget.hide()
        else:
            self.menuBar().show()
            self.status_bar_widget.show()
    def minimize_to_desktop(self):
        self.showMinimized()
    def open_notes(self):
        dlg = NotesDialog(self.notes_store, self)
        dlg.exec_()
    def open_error_log(self):
        dlg = ErrorLogDialog(self.error_log_store, self)
        dlg.exec_()

    def open_program_info(self):
        dlg = ProgramInfoDialog(self)
        dlg.exec_()
    def show_shortcuts_dialog(self):
        dlg = ShortcutsDialog(self)
        dlg.exec_()
    def _reload_profiles_combo(self):
        names = self.profile_store.names()
        self.profile_combo.clear(); self.profile_combo.addItems(names)
        if names:
            self.profile_combo.setCurrentText(names[0])
    def _on_profile_selected(self, name):
        if not name: return
        params = self.profile_store.get(name)
        if params:
            self.connection_params = params
            self.status_bar_widget.status_label.setText(f"Perfil '{name}' seleccionado. Presione 'Conectar' para establecer la conexión.")
            self.conn_group.setStyleSheet("QGroupBox#ConnectionGroup { border: 2px solid #FF0000; background:#000000; } QGroupBox#ConnectionGroup::title { color: #FF0000; }")
            self.engine = None
            self.all_tables = []
            self.columns_cache = {}
            self.table_columns = []
            self._populate_list(self.table_list, [])
            self.columns_list.clear()
    def _attempt_connection(self):
        # Mostrar indicador de conexión en el centro durante la conexión
        self.connection_logo_dialog = QDialog(self)
        self.connection_logo_dialog.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.connection_logo_dialog.setModal(True)
        self.connection_logo_dialog.setStyleSheet("""
            background-color: #000000;
            border: 3px solid #FFD700;
            border-radius: 20px;
        """)

        layout = QVBoxLayout(self.connection_logo_dialog)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Indicador circular animado
        self.connection_indicator = QWidget()
        self.connection_indicator.setFixedSize(120, 120)
        self.connection_indicator.setStyleSheet("""
            border: 4px solid #FFD700;
            border-radius: 60px;
            background-color: #000000;
        """)
        layout.addWidget(self.connection_indicator, alignment=Qt.AlignCenter)

        # Texto de conexión
        connecting_label = QLabel("Conectando a la base de datos...")
        connecting_label.setStyleSheet("color: #FFD700; font-size: 16px; font-weight: bold;")
        connecting_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(connecting_label, alignment=Qt.AlignCenter)

        # Centrar el diálogo en la pantalla
        screen = QApplication.primaryScreen().geometry()
        dialog_size = self.connection_logo_dialog.sizeHint()
        x = (screen.width() - dialog_size.width()) // 2
        y = (screen.height() - dialog_size.height()) // 2
        self.connection_logo_dialog.move(x, y)

        self.connection_logo_dialog.show()
        QApplication.processEvents()
        try:
            driver = self.connection_params['driver'].strip('{}')
            conn_str = f"mssql+pyodbc://{self.connection_params['uid']}:{self.connection_params['pwd']}@{self.connection_params['server']}/{self.connection_params['database']}?driver={driver}"

            self.engine = create_engine(conn_str, pool_pre_ping=True, pool_recycle=3600)
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self.conn_group.setStyleSheet("QGroupBox#ConnectionGroup { border: 2px solid #004400; background:#003300; } QGroupBox#ConnectionGroup::title { color: #004400; }")
            self.status_bar_widget.status_label.setStyleSheet("color: green;")
            self._post_init_load()
            # Cerrar el diálogo del logo
            if hasattr(self, 'connection_logo_dialog'):
                self.connection_logo_dialog.close()
            # Stop retry timer if running
            if self.retry_connection_timer.isActive():
                self.retry_connection_timer.stop()
        except Exception as e:
            # Cerrar el diálogo del logo
            if hasattr(self, 'connection_logo_dialog'):
                self.connection_logo_dialog.close()
            error_msg = f"No se pudo conectar a la base de datos: {str(e)}"
            QMessageBox.critical(self, "Error de Conexión", f"{error_msg}\n\nPor favor, verifique la configuración.")
            self.engine = None
            self.status_bar_widget.status_label.setText("Desconectado")
            self.conn_group.setStyleSheet("QGroupBox#ConnectionGroup { border: 2px solid #E53935; background:#000000; } QGroupBox#ConnectionGroup::title { color: #E53935; }")
            self.error_log_store.log_error("ConnectionError", error_msg, datetime.now().isoformat())
    def open_connection_dialog(self):
        dlg = ConnectionDialog(self.connection_params, self)
        if dlg.exec_() == QDialog.Accepted:
            self.connection_params = dlg.get_connection_params()
            self.status_bar_widget.status_label.setText("Configuración de conexión actualizada. Presione 'Conectar' para establecer la conexión.")
            self.conn_group.setStyleSheet("QGroupBox#ConnectionGroup { border: 1px solid #E53935; } QGroupBox#ConnectionGroup::title { color: #E53935; }")
            self.engine = None
    def _save_profile(self):
        # CORREGIDO: Mostrar diálogo con datos de conexión antes de guardar.
        name, ok = QInputDialog.getText(self, "Guardar Perfil", "Nombre del perfil:", text=self.profile_combo.currentText())
        if ok and name:
            # Pre-llenar el diálogo con los parámetros de conexión actuales.
            dlg = ConnectionDialog(self.connection_params, self)
            dlg.setWindowTitle(f"Guardar/Editar Perfil: {name}")
            if dlg.exec_() == QDialog.Accepted:
                params_to_save = dlg.get_connection_params()
                self.profile_store.set(name, params_to_save)
                self._reload_profiles_combo()
                self.profile_combo.setCurrentText(name)
                self.status_bar_widget.status_label.setText(f"Perfil '{name}' guardado")
    def _delete_profile(self):
        name = self.profile_combo.currentText()
        if not name: return
        if QMessageBox.question(self, "Confirmar", f"¿Eliminar el perfil '{name}'?") == QMessageBox.Yes:
            self.profile_store.delete(name); self._reload_profiles_combo()
            self.status_bar_widget.status_label.setText(f"Perfil '{name}' eliminado")
    def _load_tables(self):
        if not self.engine: return
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'"))
                self.all_tables = sorted([row[0] for row in result.fetchall()])
            self._populate_list(self.table_list, self.all_tables)
            self.columns_cache = {}
            for t in self.all_tables:
                self.columns_cache[t] = self._fetch_columns_for(t)
            self.get_editor().highlighter.rehighlight()
        except Exception as e:
            error_msg = f"Error al cargar tablas: {str(e)}"
            QMessageBox.warning(self, "Error", error_msg)
            self.error_log_store.log_error("LoadTablesError", error_msg, datetime.now().isoformat())
            
    def _fetch_columns_for(self, table_name):
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = :table_name ORDER BY ORDINAL_POSITION"),
                                     {'table_name': table_name})
                return [row[0] for row in result.fetchall()]
        except Exception as e:
            error_msg = f"Error al cargar columnas para {table_name}: {str(e)}"
            self.error_log_store.log_error("FetchColumnsError", error_msg, datetime.now().isoformat())
            return []
            
    def _load_columns(self, table_name):
        if not self.engine or not table_name:
            self.table_columns = []; self.columns_list.clear(); return
        try:
            self.table_columns = self.columns_cache.get(table_name) or self._fetch_columns_for(table_name)
            pk_cols = self._get_pk_columns(table_name)
            fk_cols = {fk['column'] for fk in self._get_fk_relations(table_name)}
            self.columns_list.clear()
            for col in self.table_columns:
                prefix = ""
                if col in pk_cols: prefix = "🔑 "
                elif col in fk_cols: prefix = "🔗 "
                self.columns_list.addItem(f"{prefix}{col}")
            self.get_editor().highlighter.rehighlight()
            
            self._refresh_history_list()
        except Exception as e:
            error_msg = f"Error al cargar columnas: {str(e)}"
            QMessageBox.warning(self, "Error", error_msg)
            self.error_log_store.log_error("LoadColumnsError", error_msg, datetime.now().isoformat())
            
    def _get_pk_columns(self, table_name):
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT c.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE c ON tc.CONSTRAINT_NAME = c.CONSTRAINT_NAME
                    WHERE tc.TABLE_NAME = :table_name AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                    ORDER BY c.ORDINAL_POSITION
                """), {'table_name': table_name})
                return {r[0] for r in result.fetchall()}
        except Exception as e:
            error_msg = f"Error al obtener PK para {table_name}: {str(e)}"
            self.error_log_store.log_error("GetPKError", error_msg, datetime.now().isoformat())
            return set()
            
    def _get_fk_relations(self, table_name):
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT cu.COLUMN_NAME, pk.TABLE_NAME AS REF_TABLE, pt.COLUMN_NAME AS REF_COLUMN
                    FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                    JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS fk ON rc.CONSTRAINT_NAME = fk.CONSTRAINT_NAME
                    JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS pk ON rc.UNIQUE_CONSTRAINT_NAME = pk.CONSTRAINT_NAME
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE cu ON rc.CONSTRAINT_NAME = cu.CONSTRAINT_NAME
                    JOIN (SELECT i1.TABLE_NAME, i2.COLUMN_NAME
                          FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS i1
                          JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE i2 ON i1.CONSTRAINT_NAME = i2.CONSTRAINT_NAME
                          WHERE i1.CONSTRAINT_TYPE = 'PRIMARY KEY') pt ON pk.TABLE_NAME = pt.TABLE_NAME
                    WHERE fk.TABLE_NAME = :table_name
                """), {'table_name': table_name})
                return [{"column": r[0], "ref_table": r[1], "ref_column": r[2]} for r in result.fetchall()]
        except Exception as e:
            error_msg = f"Error al obtener FK para {table_name}: {str(e)}"
            self.error_log_store.log_error("GetFKError", error_msg, datetime.now().isoformat())
            return []
            
    def _populate_list(self, list_widget: QListWidget, items):
        list_widget.clear()
        for i, it in enumerate(items):
            txt = str(it); lw = QListWidgetItem(f"{i+1} {txt}")
            if list_widget is self.table_list and self.fav_store.is_table_fav(txt):
                lw.setText(f"{i+1} ⭐ {txt}"); lw.setData(Qt.UserRole, txt)
            list_widget.addItem(lw)
            
    def filter_tables(self, text=None):
        name_txt = (self.search_input.text() if hasattr(self, 'search_input') else '').strip().lower()
        filtered = [t for t in self.all_tables if name_txt in str(t).lower() or name_txt.isdigit() and int(name_txt) > 0 and int(name_txt) <= len(self.all_tables) and self.all_tables[int(name_txt)-1] == t]
        self._populate_list(self.table_list, filtered)
    def select_table_item(self, item):
        try:
            if not item or not hasattr(item, 'data'):
                return
            name = item.data(Qt.UserRole) or item.text().split(' ', 1)[-1].lstrip('⭐ ').strip()
            self.current_table_name = name
            self._load_columns(self.current_table_name)
            self.fav_table_chk.setChecked(self.fav_store.is_table_fav(self.current_table_name))

            idx = self.editor_tabs.currentIndex()
            if idx >= 0:
                self._tab_states.setdefault(idx, {})['table'] = self.current_table_name
                self._rename_tab_with_table(idx)
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
    def filter_columns(self, text):
        t = text.strip().lower()
        for i in range(self.columns_list.count()):
            item = self.columns_list.item(i)
            # Buscar por nombre y por número de fila
            if t.isdigit() and int(t) > 0 and int(t) -1 == i:
                item.setHidden(False)
            elif t not in item.text().lower():
                item.setHidden(True)
            else:
                item.setHidden(False)
    def select_column_item(self, item):
        try:
            if not item or not hasattr(item, 'text'):
                return
            self.current_column_name = item.text().lstrip('🔑🔗 ').split(' ', 1)[-1].strip()
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
    def insert_column_name_item(self, item):
        try:
            if not item or not hasattr(item, 'text'):
                return
            name = item.text().lstrip('🔑🔗 ').split(' ', 1)[-1].strip()
            cur = self.get_editor().textCursor(); cur.insertText(name)
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
    def copy_table_name(self):
        if self.current_table_name:
            QApplication.clipboard().setText(self.current_table_name)
            self.status_bar_widget.status_label.setText(f"Tabla '{self.current_table_name}' copiada")

    def _show_table_context_menu(self, pos):
        """Mostrar menú contextual para la lista de tablas"""
        menu = QMenu(self)

        # Opción para copiar selección con cabecera
        copy_action = QAction("Copiar selección (incl. cabecera)", self)
        copy_action.setShortcut("Ctrl+Shift+C")
        copy_action.triggered.connect(self._copy_selected_tables)
        menu.addAction(copy_action)

        # Mostrar el menú en la posición del cursor
        menu.exec_(self.table_list.mapToGlobal(pos))

    def _copy_selected_tables(self):
        """Copiar las tablas seleccionadas con formato de lista"""
        selected_items = self.table_list.selectedItems()
        if not selected_items:
            self.status_bar_widget.status_label.setText("No hay tablas seleccionadas")
            return

        # Obtener los nombres de las tablas seleccionadas
        table_names = []
        for item in selected_items:
            try:
                if not item or not hasattr(item, 'text'):
                    continue
                table_name = item.text().split(' ', 1)[-1].lstrip('⭐ ').strip()
                table_names.append(table_name)
            except RuntimeError as e:
                if "has been deleted" in str(e):
                    # Item eliminado, continuar con el siguiente
                    continue
                else:
                    raise

        # Crear el texto para copiar
        if len(table_names) == 1:
            copy_text = table_names[0]
        else:
            # Formato: Tabla1, Tabla2, Tabla3
            copy_text = ", ".join(table_names)

        QApplication.clipboard().setText(copy_text)
        self.status_bar_widget.status_label.setText(f"{len(table_names)} tabla(s) copiada(s) con cabecera")
    def copy_column_name(self):
        it = self.columns_list.currentItem()
        try:
            if it and hasattr(it, 'text'):
                name = it.text().lstrip('🔑🔗 ').split(' ', 1)[-1].strip()
                QApplication.clipboard().setText(name)
                self.status_bar_widget.status_label.setText(f"Columna '{name}' copiada")
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
    def copy_all_columns(self):
        if self.table_columns:
            QApplication.clipboard().setText(", ".join(self.table_columns))
            self.status_bar_widget.status_label.setText("Todas las columnas copiadas")
    def _toggle_query_favorite(self):
        it = self.saved_queries_list.currentItem()
        try:
            if not it or not hasattr(it, 'data'): return
            name = it.data(Qt.UserRole); cur = self.fav_store.is_query_fav(name)
            self.fav_store.set_query_fav(name, not cur); self._load_saved_queries()
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
    def _toggle_table_fav(self):
        if not self.current_table_name: return
        self.fav_store.set_table_fav(self.current_table_name, self.fav_table_chk.isChecked())
        self.filter_tables()
    def get_editor(self) -> SQLEditor:
        w = self.editor_tabs.currentWidget()
        if w is None: return self._create_editor_tab()
        return w.findChild(SQLEditor)
        
    def _create_editor_tab(self, query_text=''):
        container = QWidget(); v = QVBoxLayout(container); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        editor = SQLEditor(self)
        editor.setPlainText(query_text)
        v.addWidget(editor)
        
        tab_count = self.editor_tabs.count()
        idx = self.editor_tabs.addTab(container, f"{tab_count + 1}")
        self.editor_tabs.setTabText(idx, str(idx+1))
        self.editor_tabs.setCurrentIndex(idx)
        
        # Guardar estado de la pestaña: variables inicialmente vacías
        self._tab_states[idx] = {
            'table': self.current_table_name,
            'query_text': query_text,
            'row_limit': self.row_limit,
            'selection_mode': self.selection_mode_combo.currentText(),
            'variables': []   # Vacío, se crearán 3 por defecto si no hay datos al cambiar
        }
        
        # Limpiar el panel de variables para la nueva pestaña
        self.variables_panel.clear_variables()
        
        # Crear 3 variables por defecto para la nueva pestaña
        self.variables_panel.add_variable_box('VAR1', '')
        self.variables_panel.add_variable_box('VAR2', '')
        self.variables_panel.add_variable_box('VAR3', '')
        
        return editor
        
    def _update_tab_colors(self):
        for i in range(self.editor_tabs.count()):
            if i == self.editor_tabs.currentIndex():
                self.editor_tabs.tabBar().setTabTextColor(i, QColor("#FFFF00"))
            else:
                self.editor_tabs.tabBar().setTabTextColor(i, QColor("#FFFFFF"))
                
    def _rename_tab_with_table(self, idx):
        self.editor_tabs.setTabText(idx, str(idx + 1))
        self._update_tab_colors()
        
    def _on_tab_changed(self, idx):
        if idx < 0: return
        previous_idx = self.editor_tabs.property("previousIndex")
        if previous_idx is not None and previous_idx >= 0 and previous_idx < self.editor_tabs.count():
            # Guardar el estado de la pestaña anterior
            self._tab_states[previous_idx]['query_text'] = self.editor_tabs.widget(previous_idx).findChild(SQLEditor).toPlainText()
            self._tab_states[previous_idx]['row_limit'] = self.row_limit
            self._tab_states[previous_idx]['selection_mode'] = self.selection_mode_combo.currentText()
            self._tab_states[previous_idx]['variables'] = self.variables_panel.to_json()
        self.editor_tabs.setProperty("previousIndex", idx)
        state = self._tab_states.get(idx, {})
        self.current_table_name = state.get('table', '')
        self._load_columns(self.current_table_name)
        
        self.row_limit = state.get('row_limit', 1000)
        self.row_limit_combo.setCurrentText(str(self.row_limit))
        self._apply_selection_mode(state.get('selection_mode', "Celdas"))
        
        # Cargar variables de la pestaña actual
        variables_data = state.get('variables', [])
        if variables_data:
            self.variables_panel.load_variables(variables_data)
        else:
            # Si no hay variables, crear las 3 por defecto
            self.variables_panel.clear_variables()
            self.variables_panel.add_variable_box('VAR1', '')
            self.variables_panel.add_variable_box('VAR2', '')
            self.variables_panel.add_variable_box('VAR3', '')
        
        self.get_editor().setPlainText(state.get('query_text', ''))
        self._refresh_history_list()
        self._update_tab_colors()
        self.status_bar_widget.status_label.setText(f"Cambiado a Pestaña {idx + 1}")
        self.clear_result_filters()
        # Cargar resultados de la pestaña actual si existen
        results_df = state.get('results_df')
        if results_df is not None:
            self.results_table.set_data(results_df)
            self.last_results_df = results_df
        else:
            self.results_table.set_data(pd.DataFrame())
            self.last_results_df = None
        # Actualizar barra de estado con info de la pestaña
        status_info = state.get('status', {})
        if status_info:
            self.status_bar_widget.elapsed_label.setText(f"Tiempo: {status_info.get('elapsed', 0):.2f}s")
            self.status_bar_widget.row_count_label.setText(f"Filas: {status_info.get('rows', 0)}")
            estado_data = status_info.get('estado')
            if estado_data:
                count_0 = estado_data['count_0']
                count_1 = estado_data['count_1']
                total = estado_data['total']
                self.status_bar_widget.estado_bar.setMaximum(total)
                self.status_bar_widget.estado_bar.setValue(count_1)
                self.status_bar_widget.estado_bar.setFormat(f"1: {count_1} | 0: {count_0}")
                self.status_bar_widget.estado_bar.show()
                self.status_bar_widget.estado_label.setText("Estado: ESTADO")
            else:
                self.status_bar_widget.estado_bar.hide()
                self.status_bar_widget.estado_label.setText("Estado: N/A")
        else:
            self.status_bar_widget.elapsed_label.setText("Tiempo: 0.0s")
            self.status_bar_widget.row_count_label.setText("Filas: 0")
            self.status_bar_widget.estado_bar.hide()
            self.status_bar_widget.estado_label.setText("Estado: N/A")
    def _close_editor_tab(self, idx):
        if self.editor_tabs.count() <= 1:
            return
        # Eliminar archivo de resultados si existe
        filename = os.path.join(self.tab_results_dir, f"tab_{idx}_results.xlsx")
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception as e:
                print(f"Error eliminando archivo de resultados: {e}")
        widget = self.editor_tabs.widget(idx)
        self.editor_tabs.removeTab(idx)
        widget.deleteLater()

        for key in list(self._tab_states.keys()):
            if key > idx:
                old_filename = os.path.join(self.tab_results_dir, f"tab_{key}_results.xlsx")
                new_filename = os.path.join(self.tab_results_dir, f"tab_{key-1}_results.xlsx")
                if os.path.exists(old_filename):
                    try:
                        os.rename(old_filename, new_filename)
                    except Exception as e:
                        print(f"Error renombrando archivo de resultados: {e}")
                self._tab_states[key - 1] = self._tab_states.pop(key)

        self._update_tab_colors()
        self.status_bar_widget.status_label.setText(f"Pestaña {idx + 1} cerrada")
        self._rename_tab_with_table(self.editor_tabs.currentIndex())
    def _close_current_tab(self):
        idx = self.editor_tabs.currentIndex()
        if idx >= 0: self._close_editor_tab(idx)
    def _new_editor_tab_from_current_table(self):
        self._create_editor_tab()
        self._rename_tab_with_table(self.editor_tabs.currentIndex())
    def _next_tab(self):
        c = self.editor_tabs.count()
        if c <= 1: return
        idx = (self.editor_tabs.currentIndex() + 1) % c
        self.editor_tabs.setCurrentIndex(idx)
    def _prev_tab(self):
        c = self.editor_tabs.count()
        if c <= 1: return
        idx = (self.editor_tabs.currentIndex() - 1) % c
        self.editor_tabs.setCurrentIndex(idx)
    def auto_generate_select(self):
        if self.current_table_name:
            where = f"{self.current_column_name} = " if self.current_column_name else ""
            q = f"SELECT * FROM {self.current_table_name} WHERE {where}"
            self.get_editor().setPlainText(q)
            cur = self.get_editor().textCursor(); cur.movePosition(QTextCursor.End); self.get_editor().setTextCursor(cur)
    def show_variable_preview(self):
        q = self.get_editor().toPlainText()
        if not q.strip():
            QMessageBox.information(self, "Sin consulta", "No hay consulta en el editor"); return
        variables = self.variables_panel.get_variables(); preview = q
        for k, v in variables.items(): preview = preview.replace(k, v)
        dlg = QDialog(self); dlg.setWindowTitle("Vista Previa de Consulta con Variables"); dlg.resize(800, 600)
        lay = QVBoxLayout(dlg)
        ed = QTextEdit(); ed.setPlainText(preview); ed.setReadOnly(True); lay.addWidget(ed)
        btn = QPushButton("Cerrar"); btn.clicked.connect(dlg.accept); lay.addWidget(btn)
        SQLHighlighter(ed.document()); dlg.exec_()
    def update_row_limit(self, v):
        self.row_limit = int(v)
        idx = self.editor_tabs.currentIndex()
        if idx >= 0:
            self._tab_states[idx]['row_limit'] = self.row_limit
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w: w.setParent(None)
    def _add_filter(self):
        column = self.filter_column_combo.currentText()
        value = self.filter_value_input.text().strip()
        if not column or not value:
            return
        self.active_filters[column] = value
        self.filter_value_input.clear()
        self._apply_filters_in_real_time()
        self._update_active_filters_display()
    def _remove_filter(self, column_name):
        if column_name in self.active_filters:
            del self.active_filters[column_name]
            self._apply_filters_in_real_time()
            self._update_active_filters_display()
    def _update_active_filters_display(self):
        while self.active_filters_layout.count():
            child = self.active_filters_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        if not self.active_filters:
            pass
        else:
            for column, value in self.active_filters.items():
                frame = QFrame()
                frame.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 8px; background-color: #111; } QLabel { border: none; }")
                layout = QHBoxLayout(frame)
                layout.setContentsMargins(6, 2, 4, 2)
                layout.setSpacing(4)
                label = QLabel(f"<b>{column}:</b> '{value}'")
                layout.addWidget(label)
                remove_btn = QPushButton("X")
                remove_btn.setFixedSize(18, 18)
                remove_btn.setStyleSheet("QPushButton { border-radius: 9px; font-weight: bold; }")
                remove_btn.clicked.connect(lambda _, c=column: self._remove_filter(c))
                layout.addWidget(remove_btn)
                self.active_filters_layout.addWidget(frame)
        self.active_filters_layout.addStretch(1)
    def _apply_filters_in_real_time(self):
        if self.last_results_df is None:
            return
        df = self.last_results_df.copy()
        if self.active_filters:
            df_cols = df.columns.tolist()
            for col, val in self.active_filters.items():
                if col in df_cols:
                    try:
                        # Manejar columnas duplicadas
                        col_data = df[col]
                        if isinstance(col_data, pd.DataFrame):
                            col_data = col_data.iloc[:, 0]  # Usar primera columna si duplicados
    
                        if val == '1' and col == 'ESTADO':
                            # Filtrar solo valores = 1
                            try:
                                numeric_col = pd.to_numeric(col_data, errors='coerce')
                                mask = numeric_col == 1
                                df = df[mask]
                            except Exception:
                                # Fallback: filtrar por string
                                mask = col_data.astype(str).str.strip() == '1'
                                df = df[mask]
                        elif val == '0|1' and col == 'ESTADO':
                            # Usar método más seguro para filtrar valores numéricos
                            try:
                                numeric_col = pd.to_numeric(col_data, errors='coerce')
                                mask = numeric_col.isin([0, 1])
                                df = df[mask]
                            except Exception:
                                # Fallback: filtrar por string
                                mask = col_data.astype(str).str.strip().isin(['0', '1'])
                                df = df[mask]
                        else:
                            mask = col_data.astype(str).str.contains(re.escape(val), case=False, na=False)
                            df = df[mask]
                    except Exception as e:
                        # Use safer boolean evaluation to avoid ambiguous Series errors
                        print(f"Error al aplicar filtro de columna: {e}")
        global_text = self.global_search_input.text().strip().lower()
        if global_text:
            try:
                mask = df.apply(lambda x: x.astype(str).str.lower().str.contains(re.escape(global_text), na=False)).any(axis=1)
                df = df[mask]
            except Exception as e:
                print(f"Error al aplicar filtro global: {e}")
        self.results_table._display(df)
    def clear_result_filters(self):
        self.active_filters.clear()
        self.global_search_input.clear()
        self.results_table.column_filters = {}
        self._update_active_filters_display()
        if self.last_results_df is not None:
            self.results_table.set_data(self.last_results_df)
    def _apply_selection_mode(self, mode):
        mode = mode.lower()
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        if mode == 'filas': self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        elif mode == 'columnas': self.results_table.setSelectionBehavior(QAbstractItemView.SelectColumns)
        else: self.results_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        
    def save_results_to_variable(self):
        if self.last_results_df is None or self.last_results_df.empty:
            QMessageBox.warning(self, "Sin resultados", "No hay resultados para guardar"); return
        name, ok = QInputDialog.getText(self, "Guardar en Variable", "Nombre de la variable:")
        if ok and name:
            df = self.results_table.get_filtered_data()
            text = df.iloc[:, 0].to_string(index=False) if df.shape[1] == 1 else df.to_csv(sep='\t', index=False)
            self.variables_panel.add_variable_box(name, text)
            self.status_bar_widget.status_label.setText(f"Resultados guardados en variable '{name}'")
    def preview_results(self):
        """Abrir vista previa de resultados en Excel sin descargar permanentemente"""
        if self.last_results_df is None or self.last_results_df.empty:
            QMessageBox.warning(self, "Sin resultados", "No hay resultados para mostrar")
            return

        df = self.results_table.get_filtered_data()
        if df.empty:
            QMessageBox.warning(self, "Sin resultados", "No hay resultados filtrados para mostrar")
            return

        # Sanitize column names for Excel compatibility
        def sanitize_column_name(name):
            # Replace invalid characters with underscores
            import re
            # Excel column names must start with letter and contain only letters, numbers, underscores
            sanitized = re.sub(r'[^A-Za-z0-9_]', '_', str(name))
            # Ensure it starts with a letter
            if sanitized and not sanitized[0].isalpha():
                sanitized = 'Col_' + sanitized
            return sanitized

        # Handle duplicate column names by making them unique for Excel export
        df.columns = self.app_window._make_columns_unique(df.columns)
        column_mapping = {col: sanitize_column_name(col) for col in df.columns}
        df_excel = df.rename(columns=column_mapping)

        # Get query name: first line or "consulta"
        query_text = self.get_editor().toPlainText().strip()
        query_name = query_text.split('\n', 1)[0].strip()[:50] if query_text else "consulta"

        # Sanitize query name for filename
        def sanitize_filename(name):
            import re
            sanitized = re.sub(r'[<>:"/\\|?*]', '_', str(name))
            sanitized = sanitized.strip('. ')
            if not sanitized:
                sanitized = "consulta"
            sanitized = sanitized[:100]
            return sanitized

        safe_query_name = sanitize_filename(query_name)

        # Create temporary filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_filename = os.path.join(self.log_folder, f"preview_{safe_query_name}_{timestamp}.xlsx")

        try:
            with pd.ExcelWriter(temp_filename, engine='openpyxl') as writer:
                df_excel.to_excel(writer, index=False, sheet_name='Vista_Previa')
                worksheet = writer.sheets['Vista_Previa']
                for idx, col in enumerate(df_excel):
                    series = df_excel[col]
                    max_len = max((series.astype(str).map(len).max(), len(str(series.name)))) + 2
                    col_letter = self._excel_column_name(idx)
                    worksheet.column_dimensions[col_letter].width = max_len

            # Abrir el archivo temporal en Excel
            safe_os_open(temp_filename)

            # Mostrar mensaje informativo
            self.status_bar_widget.status_label.setText(f"Vista previa abierta en Excel: {len(df)} filas, {len(df.columns)} columnas")

            # Programar eliminación del archivo temporal después de 5 minutos
            QTimer.singleShot(5 * 60 * 1000, lambda: self._cleanup_temp_file(temp_filename))

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Error al crear vista previa: {str(e)}")
            self.error_log_store.log_error("PreviewError", str(e), datetime.now().isoformat())

    def _cleanup_temp_file(self, filepath):
        """Eliminar archivo temporal de vista previa"""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass  # Silently ignore cleanup errors

    def download_results(self):
        if self.last_results_df is None or self.last_results_df.empty:
            QMessageBox.warning(self, "Sin resultados", "No hay resultados para descargar"); return
        df = self.results_table.get_filtered_data()

        # Sanitize column names for Excel compatibility
        def sanitize_column_name(name):
            # Replace invalid characters with underscores
            import re
            # Excel column names must start with letter and contain only letters, numbers, underscores
            sanitized = re.sub(r'[^A-Za-z0-9_]', '_', str(name))
            # Ensure it starts with a letter
            if sanitized and not sanitized[0].isalpha():
                sanitized = 'Col_' + sanitized
            return sanitized

        # Sanitize filename for Windows compatibility
        def sanitize_filename(name):
            # Remove or replace invalid characters for Windows filenames
            import re
            # Replace invalid chars with underscore, keep alphanumeric, spaces, dots, hyphens, underscores
            sanitized = re.sub(r'[<>:"/\\|?*]', '_', str(name))
            # Remove leading/trailing dots and spaces
            sanitized = sanitized.strip('. ')
            # Ensure it's not empty and not too long
            if not sanitized:
                sanitized = "consulta"
            # Limit length to avoid Windows path issues
            sanitized = sanitized[:100]
            return sanitized

        # Handle duplicate column names before creating Excel by making them unique
        df.columns = self.app_window._make_columns_unique(df.columns)
        # Create a mapping of original to sanitized names
        column_mapping = {col: sanitize_column_name(col) for col in df.columns}
        df_excel = df.rename(columns=column_mapping)

        # Get query name: first line or "consulta"
        query_text = self.get_editor().toPlainText().strip()
        query_name = query_text.split('\n', 1)[0].strip()[:50] if query_text else "consulta"

        # Sanitize query name for filename
        safe_query_name = sanitize_filename(query_name)

        # Add timestamp to ensure uniqueness
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create filename with timestamp for guaranteed uniqueness
        filename = os.path.join(self.log_folder, f"{safe_query_name}_{timestamp}.xlsx")

        try:
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                df_excel.to_excel(writer, index=False, sheet_name='Resultados')
                worksheet = writer.sheets['Resultados']
                for idx, col in enumerate(df_excel):
                    series = df_excel[col]
                    max_len = max((series.astype(str).map(len).max(), len(str(series.name)))) + 2
                    col_letter = self._excel_column_name(idx)
                    worksheet.column_dimensions[col_letter].width = max_len
            safe_os_open(filename)
            self.status_bar_widget.status_label.setText(f"Archivo guardado y abierto: {os.path.basename(filename)}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Error al guardar: {str(e)}")
            self.error_log_store.log_error("DownloadError", str(e), datetime.now().isoformat())
            
    def toggle_f9_view(self):
        if not self.f9_active:
            self.original_splitter_sizes = self.main_splitter.sizes()
            self.original_left_panel_visibility = self.left_panel.isVisible()
            self.original_right_panel_visibility = self.right_panel.isVisible()
            self.original_center_splitter_sizes = self.center_splitter.sizes()
            self.original_query_group_visibility = self.query_group.isVisible()
            self.left_panel.hide()
            self.right_panel.hide()
            self.query_group.hide()
            self.main_splitter.setSizes([0, self.width(), 0])
            self.center_splitter.setSizes([0, self.height()])
            self.f9_active = True
            self.view_full_results_btn.setText("Restaurar Vista")
        else:
            self.left_panel.setVisible(self.original_left_panel_visibility)
            self.right_panel.setVisible(self.original_right_panel_visibility)
            self.query_group.setVisible(self.original_query_group_visibility)
            if self.original_splitter_sizes:
                self.main_splitter.setSizes(self.original_splitter_sizes)
            if self.original_center_splitter_sizes:
                self.center_splitter.setSizes(self.original_center_splitter_sizes)
            self.f9_active = False
            self.view_full_results_btn.setText("Ver Todo")
    def toggle_fullscreen_editor(self):
        if not self.is_fullscreen_editor:
            self.original_editor_state = {
                'splitter_sizes': self.center_splitter.sizes(),
                'results_visible': self.results_group.isVisible()
            }
            
            self.results_group.hide()
            self.center_splitter.setSizes([self.height(), 0])
            
            self.is_fullscreen_editor = True
        else:
            if self.original_editor_state:
                self.results_group.setVisible(self.original_editor_state['results_visible'])
                self.center_splitter.setSizes(self.original_editor_state['splitter_sizes'])
            
            self.is_fullscreen_editor = False
    def view_first_100_data(self):
        if not self.current_table_name:
            QMessageBox.information(self, "Sin tabla seleccionada", "Selecciona una tabla primero")
            return
            
        # Guardamos la consulta actual
        current_query = self.get_editor().toPlainText()
        
        # Creamos y ejecutamos la consulta sin modificar el editor
        query = f"SELECT TOP 100 * FROM {self.current_table_name}"
        
        # Ejecutar directamente sin modificar el editor
        self._execute_direct_query(query)
    def _execute_direct_query(self, query_text):
        if not self.engine:
            QMessageBox.warning(self, "Sin conexión", "Conecta a una base de datos primero"); return
        
        q = query_text.strip()
        
        is_valid, error_msg = self.get_editor().validate_query(q)
        if not is_valid:
            self.status_bar_widget.status_label.setText(f"Error de validación: {error_msg}")
            QMessageBox.warning(self, "Error de Validación", error_msg)
            return
            
        # CORREGIDO: Se elimina la validación de variables y se sustituyen directamente.
        variables = self.variables_panel.get_variables()
        for k, v in variables.items():
            q = q.replace(k, v)
                    
        self.status_bar_widget.elapsed_label.setText("Tiempo: 0.0 s")
        self.status_bar_widget.status_label.setText("Ejecutando consulta...")
        self.status_bar_widget.row_count_label.setText("Filas: 0")

        self._elapsed_start = time.perf_counter()
        # Inicializar el timer correctamente
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._elapsed_timer.start(100)  # Actualizar cada 100 ms
        
        self._thread = QThread(); self._worker = QueryWorker(self.engine, q, self.current_table_name)
        self._worker.moveToThread(self._thread); self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_query_finished); self._worker.error.connect(self._on_query_error)
        self._worker.finished.connect(self._thread.quit); self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater); self._thread.start()
    def _load_saved_queries(self):
        self.saved_queries_list.clear()
        try:
            files = [f[:-4] for f in os.listdir(self.query_directory) if f.lower().endswith('.sql')]
            files = sorted(files, key=lambda n: (0 if self.fav_store.is_query_fav(n) else 1, n.lower()))
            for i, name in enumerate(files):
                disp_name = f"{i+1} {name}"
                if self.saved_queries_full_view:
                    try:
                        filename = os.path.join(self.query_directory, f"{name}.sql")
                        with open(filename, 'r', encoding='utf-8') as f:
                            query_text = f.read()
                            match = re.search(r'FROM\s+([a-zA-Z0-9_\.]+)', query_text, re.IGNORECASE)
                            table_name = match.group(1) if match else "N/A"
                            disp_name = f"{name} ({table_name})"
                    except Exception as e:
                        disp_name = f"{i+1} Error al cargar-{name}"
                
                lw = QListWidgetItem(disp_name)
                lw.setData(Qt.UserRole, name)
                self.saved_queries_list.addItem(lw)
        except Exception as e:
            error_msg = f"Error al cargar consultas guardadas: {str(e)}"
            self.error_log_store.log_error("LoadSavedQueriesError", error_msg, datetime.now().isoformat())
    def filter_saved_queries(self, text):
        t = self.saved_queries_search.text().strip().lower()
        for i in range(self.saved_queries_list.count()):
            item = self.saved_queries_list.item(i)
            if t.isdigit() and int(t) > 0 and int(t) -1 == i:
                item.setHidden(False)
            elif t not in item.text().lower():
                item.setHidden(True)
            else:
                item.setHidden(False)
    def _load_saved_query_item(self, item):
        try:
            # Verificar que el item aún sea válido
            if not item or not hasattr(item, 'data') or item.data(Qt.UserRole) is None:
                return
            name = item.data(Qt.UserRole)
            filename = os.path.join(self.query_directory, f"{name}.sql")
            with open(filename, 'r', encoding='utf-8') as f: self.get_editor().setPlainText(f.read())
            self.status_bar_widget.status_label.setText(f"Consulta '{name}' cargada")
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
        except Exception as e:
            error_msg = f"Error al cargar consulta: {str(e)}"
            QMessageBox.warning(self, "Error", error_msg)
            self.error_log_store.log_error("LoadQueryError", error_msg, datetime.now().isoformat())
    def save_current_query(self):
        text = self.get_editor().toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Sin consulta", "No hay consulta para guardar"); return
        name, ok = QInputDialog.getText(self, "Guardar Consulta", "Nombre de la consulta:")
        if ok and name:
            filename = os.path.join(self.query_directory, f"{name}.sql")
            try:
                with open(filename, 'w', encoding='utf-8') as f: f.write(text)
                self._load_saved_queries()
                self.status_bar_widget.status_label.setText(f"Consulta guardada como '{name}'")
            except Exception as e:
                error_msg = f"Error al guardar: {str(e)}"
                QMessageBox.warning(self, "Error", error_msg)
                self.error_log_store.log_error("SaveQueryError", error_msg, datetime.now().isoformat())
    def _edit_saved_query(self):
        item = self.saved_queries_list.currentItem()
        try:
            if not item or not hasattr(item, 'data'):
                QMessageBox.warning(self, "Sin selección", "Seleccione una consulta para editar.")
                return
            name = item.data(Qt.UserRole)
            filename = os.path.join(self.query_directory, f"{name}.sql")
            with open(filename, 'r', encoding='utf-8') as f:
                current_text = f.read()
            new_text, ok = QInputDialog.getMultiLineText(self, f"Editar Consulta: {name}", "Contenido SQL:", current_text)
            if ok and new_text != current_text:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(new_text)
                self.status_bar_widget.status_label.setText(f"Consulta '{name}' actualizada.")
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
        except Exception as e:
            error_msg = f"No se pudo editar la consulta: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg)
            self.error_log_store.log_error("EditQueryError", error_msg, datetime.now().isoformat())

    def _rename_saved_query(self):
        item = self.saved_queries_list.currentItem()
        try:
            if not item or not hasattr(item, 'data'):
                QMessageBox.warning(self, "Sin selección", "Seleccione una consulta para renombrar.")
                return
            old_name = item.data(Qt.UserRole)
            new_name, ok = QInputDialog.getText(self, "Renombrar Consulta", "Nuevo nombre:", text=old_name)
            if ok and new_name and new_name != old_name:
                old_filename = os.path.join(self.query_directory, f"{old_name}.sql")
                new_filename = os.path.join(self.query_directory, f"{new_name}.sql")
                try:
                    os.rename(old_filename, new_filename)
                    self._load_saved_queries()
                    self.status_bar_widget.status_label.setText(f"Consulta renombrada de '{old_name}' a '{new_name}'.")
                except Exception as e:
                    error_msg = f"No se pudo renombrar la consulta: {str(e)}"
                    QMessageBox.critical(self, "Error", error_msg)
                    self.error_log_store.log_error("RenameQueryError", error_msg, datetime.now().isoformat())
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
    def delete_saved_query(self):
        item = self.saved_queries_list.currentItem()
        try:
            if not item or not hasattr(item, 'data'): return
            name = item.data(Qt.UserRole)
            if QMessageBox.question(self, "Confirmar", f"¿Eliminar la consulta '{name}'?") == QMessageBox.Yes:
                try:
                    os.remove(os.path.join(self.query_directory, f"{name}.sql"))
                    self._load_saved_queries()
                    self.status_bar_widget.status_label.setText(f"Consulta '{name}' eliminada")
                except Exception as e:
                    error_msg = f"Error al eliminar: {str(e)}"
                    QMessageBox.warning(self, "Error", error_msg)
                    self.error_log_store.log_error("DeleteQueryError", error_msg, datetime.now().isoformat())
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
    def save_session(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Guardar Sesión", "", "Archivos JSON (*.json)")
        if not filename: return
        data = {
            'active_tab': self.editor_tabs.currentIndex(),
            'tabs': [{'title': self.editor_tabs.tabText(i), 'table': self._tab_states.get(i, {}).get('table', ''), 'query': self.editor_tabs.widget(i).findChild(SQLEditor).toPlainText()} for i in range(self.editor_tabs.count())],
            'variables': self.variables_panel.to_json(), 'connection_params': self.connection_params,
            'current_table': self.current_table_name, 'row_limit': self.row_limit, 'data_directory': self.data_directory
        }
        save_json(filename, data)
        self.status_bar_widget.status_label.setText(f"Sesión guardada: {filename}")
        
    def load_session(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Cargar Sesión", "", "Archivos JSON (*.json)")
        if not filename: return
        try:
            data = load_json(filename, {})
            self.editor_tabs.clear(); self._tab_states = {}
            for tab in data.get('tabs', []):
                self._create_editor_tab(query_text=tab.get('query', ''))
                tab_index = self.editor_tabs.count() - 1
                self._tab_states[tab_index]['table'] = tab.get('table', '')
                self._tab_states[tab_index]['variables'] = tab.get('variables', [])
            self.editor_tabs.setCurrentIndex(int(data.get('active_tab', 0)))
            if 'connection_params' in data: self.connection_params = data['connection_params']
            if 'current_table' in data:
                self.current_table_name = data['current_table']; self._load_columns(self.current_table_name)
            if 'row_limit' in data:
                self.row_limit = int(data['row_limit']); self.row_limit_combo.setCurrentText(str(self.row_limit))
            if 'data_directory' in data:
                self.data_directory = data['data_directory']; self._setup_paths(); self._load_stores()
            self.status_bar_widget.status_label.setText(f"Sesión cargada: {filename}")
            self._on_tab_changed(self.editor_tabs.currentIndex())
        except Exception as e:
            error_msg = f"Error al cargar sesión: {str(e)}"
            QMessageBox.warning(self, "Error", error_msg)
            self.error_log_store.log_error("LoadSessionError", error_msg, datetime.now().isoformat())
    def execute_query(self):
        try:
            if not self.engine:
                QMessageBox.warning(self, "Sin conexión", "Conecta a una base de datos primero"); return

            q = self.get_editor().toPlainText().strip()

            is_valid, error_msg = self.get_editor().validate_query(q)
            if not is_valid:
                self.status_bar_widget.status_label.setText(f"Error de validación: {error_msg}")
                QMessageBox.warning(self, "Error de Validación", error_msg)
                return

            # CORREGIDO: Se elimina la validación de variables y se sustituyen directamente.
            variables = self.variables_panel.get_variables()
            for k, v in variables.items():
                q = q.replace(k, v)

            if re.match(r'\s*SELECT', q, re.IGNORECASE) and not re.search(r'\bTOP\b|\bLIMIT\b', q, re.IGNORECASE):
                q = re.sub(r'(\s*SELECT\s+(?:DISTINCT\s+)?)', rf'\1TOP {self.row_limit} ', q, count=1, flags=re.IGNORECASE)
            self.status_bar_widget.elapsed_label.setText("Tiempo: 0.0 s")
            self.status_bar_widget.status_label.setText("Ejecutando consulta...")
            self.status_bar_widget.row_count_label.setText("Filas: 0")

            self._elapsed_start = time.perf_counter()
            # Inicializar el timer correctamente
            self._elapsed_timer = QTimer(self)
            self._elapsed_timer.timeout.connect(self._update_elapsed)
            self._elapsed_timer.start(100)  # Actualizar cada 100 ms

            self._thread = QThread(); self._worker = QueryWorker(self.engine, q, self.current_table_name)
            self._worker.moveToThread(self._thread); self._thread.started.connect(self._worker.run)
            self._worker.finished.connect(self._on_query_finished); self._worker.error.connect(self._on_query_error)
            self._worker.finished.connect(self._thread.quit); self._worker.finished.connect(self._worker.deleteLater)
            self._thread.finished.connect(self._thread.deleteLater); self._thread.start()
        except Exception as e:
            error_msg = f"Error inesperado en ejecución de consulta: {str(e)}"
            self.status_bar_widget.status_label.setText(error_msg)
            self.error_log_store.log_error("ExecuteQueryError", error_msg, datetime.now().isoformat())
            QMessageBox.warning(self, "Error", error_msg)
            
    def _update_elapsed(self):
        if hasattr(self, '_elapsed_start'):
            dt = time.perf_counter() - self._elapsed_start
            self.status_bar_widget.elapsed_label.setText(f"Tiempo: {dt:.1f} s")
            

    def _on_query_finished(self, df, elapsed, table_for_history):
        try:
            # Detener el timer correctamente
            if hasattr(self, '_elapsed_timer'):
                self._elapsed_timer.stop()

            if df.empty:
                QMessageBox.information(self, "Sin resultados", "La consulta no devolvió datos.")
                self.status_bar_widget.status_label.setText("0 filas - Consulta sin resultados")
                self.status_bar_widget.elapsed_label.setText(f"Tiempo: {elapsed:.2f}s")
                self.status_bar_widget.estado_bar.hide()
                self.results_table.set_data(pd.DataFrame())
                return

            self.last_results_df = df
            idx = self.editor_tabs.currentIndex()
            if idx >= 0:
                self._tab_states.setdefault(idx, {})['results_df'] = df
                self._tab_states[idx]['variables'] = self.variables_panel.to_json()
                # Guardar resultados persistentemente
                filename = os.path.join(self.tab_results_dir, f"tab_{idx}_results.xlsx")
                try:
                    df.to_excel(filename, index=False)
                except Exception as e:
                    print(f"Error guardando resultados de pestaña {idx}: {e}")
                # Guardar estado de la barra de estado
                status_info = {
                    'elapsed': elapsed,
                    'rows': len(df),
                    'estado': None
                }
                # Procesar columna ESTADO de manera más versátil para el estado de pestaña
                try:
                    if 'ESTADO' in df.columns:
                        estado_col = df['ESTADO']
                        if isinstance(estado_col, pd.DataFrame):
                            estado_col = estado_col.iloc[:, 0]  # Usar primera columna si duplicados
                        estado_str = estado_col.astype(str).str.strip()
                        estado_numeric = pd.to_numeric(estado_str, errors='coerce')
                        valid_mask = estado_numeric.notna() & estado_numeric.isin([0, 1])
                        if valid_mask.any():
                            valid_estado = estado_numeric[valid_mask]
                            counts = valid_estado.value_counts()
                            count_0 = counts.get(0, 0)
                            count_1 = counts.get(1, 0)
                            total = count_0 + count_1
                            if total > 0:
                                status_info['estado'] = {'count_0': count_0, 'count_1': count_1, 'total': total}
                except Exception as e:
                    # Log error but don't crash - use safer boolean evaluation
                    print(f"Error procesando columna ESTADO: {e}")
                    pass
                self._tab_states[idx]['status'] = status_info

            self.clear_result_filters()
            self.filter_column_combo.clear()
            if not df.empty:
                self.filter_column_combo.addItems(df.columns)
                # Log successful processing of complex queries with duplicate columns
                self.status_bar_widget.status_label.setText(f"Consulta compleja procesada: {len(df)} filas, {len(df.columns)} columnas")
            self.results_table.set_data(df)

            self.status_bar_widget.status_label.setText(f"{len(df)} filas")
            self.status_bar_widget.elapsed_label.setText(f"Tiempo: {elapsed:.2f}s")
            self._append_text_log(table_for_history, self.get_editor().toPlainText().strip(), elapsed, len(df))

            # Color del borde de resultados si hay mas de 1000 filas o llegó al límite
            if len(df) > 1000 or len(df) >= self.row_limit:
                self.results_group.setStyleSheet("QGroupBox#ResultsGroup { border: 2px solid red; }")
                self.row_limit_circle.setStyleSheet("border-radius: 8px; background-color: red;")
            else:
                self.results_group.setStyleSheet("") # Restablecer
                self.row_limit_circle.setStyleSheet("border-radius: 8px; background-color: #004400;")

            # Procesar columna ESTADO de manera más versátil
            try:
                if 'ESTADO' in df.columns:
                    # Manejar columnas duplicadas: usar la primera si hay múltiples
                    estado_col = df['ESTADO']
                    if isinstance(estado_col, pd.DataFrame):
                        estado_col = estado_col.iloc[:, 0]  # Usar primera columna si duplicados
                    # Convertir a string primero para manejar diferentes tipos de datos
                    estado_str = estado_col.astype(str).str.strip()
                    # Intentar convertir a numérico, pero permitir valores no numéricos
                    estado_numeric = pd.to_numeric(estado_str, errors='coerce')
                    # Filtrar valores válidos (0, 1) y no nulos
                    valid_mask = estado_numeric.notna() & estado_numeric.isin([0, 1])
                    if valid_mask.any():
                        valid_estado = estado_numeric[valid_mask]
                        counts = valid_estado.value_counts()
                        count_0 = counts.get(0, 0)
                        count_1 = counts.get(1, 0)
                        total = count_0 + count_1
                        if total > 0:
                            self.status_bar_widget.estado_bar.setMaximum(total)
                            self.status_bar_widget.estado_bar.setValue(count_1)
                            self.status_bar_widget.estado_bar.setFormat(f"1: {count_1} | 0: {count_0}")
                            self.status_bar_widget.estado_bar.show()
                        else:
                            self.status_bar_widget.estado_bar.hide()
                    else:
                        self.status_bar_widget.estado_bar.hide()
                else:
                    self.status_bar_widget.estado_bar.hide()
            except Exception as e:
                # Log error but don't crash - use safer boolean evaluation
                print(f"Error procesando columna ESTADO en barra de estado: {e}")
                self.status_bar_widget.estado_bar.hide()

            if len(df) > 1000:
                QMessageBox.warning(self, "Demasiadas filas", f"La consulta devolvió {len(df)} filas, que es más de 1000.")
        except Exception as e:
            # Enhanced error handling to catch ambiguous Series errors
            error_msg = f"Error al procesar resultados: {str(e)}"
            if "ambiguous" in str(e).lower() or "truth value" in str(e).lower():
                error_msg += "\n\nSugerencia: Verifique que las consultas no devuelvan datos mixtos en columnas críticas."
            self.status_bar_widget.status_label.setText(error_msg)
            self.error_log_store.log_error("ResultProcessingError", error_msg, datetime.now().isoformat())
            QMessageBox.warning(self, "Error", error_msg)
    def _append_text_log(self, table, query_text, elapsed, rows):
        try:
            log_file = os.path.join(self.log_folder, 'query_log.txt')
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] table={table} elapsed={elapsed:.2f}s rows={rows} sql={query_text}\n")
        except Exception as e:
            error_msg = f"Error al guardar log: {str(e)}"
            self.error_log_store.log_error("SaveLogError", error_msg, datetime.now().isoformat())
            
    def _on_query_error(self, msg):
        try:
            # Detener el timer correctamente si está corriendo
            if hasattr(self, '_elapsed_timer') and self._elapsed_timer.isActive():
                self._elapsed_timer.stop()

            # Detener el hilo si está corriendo
            if hasattr(self, '_thread') and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(1000)  # Esperar hasta 1 segundo

            error_msg = f"Error al ejecutar consulta: {msg}"
            # Enhanced error message for ambiguous Series errors
            if "ambiguous" in str(msg).lower() or "truth value" in str(msg).lower():
                error_msg += "\n\nPosible causa: La consulta devuelve datos mixtos que pandas no puede evaluar como verdadero/falso."
            self.status_bar_widget.status_label.setText(error_msg)
            self.error_log_store.log_error("QueryError", error_msg, datetime.now().isoformat())

            # Mostrar alerta de fallo y continuar normalmente
            QMessageBox.warning(self, "Error de Consulta", f"No se pudo ejecutar la consulta: {msg}")

            # Reset UI state
            self.status_bar_widget.elapsed_label.setText("Tiempo: 0.0s")
            self.status_bar_widget.row_count_label.setText("Filas: 0")
            self.status_bar_widget.estado_bar.hide()
            self.status_bar_widget.estado_label.setText("Estado: N/A")
        except Exception as e:
            print(f"Error handling query error: {e}")
        
    def _toggle_side_panels(self):
        self.left_panel.setVisible(not self.left_panel.isVisible())
        self.right_panel.setVisible(not self.right_panel.isVisible())
        
    def _refresh_history_list(self):
        self.history_list.clear()
        search = (self.history_search.text() if hasattr(self, 'history_search') else '').strip().lower()
        
        items_to_display = []
        if self.saved_queries_full_view:
            # CORREGIDO: Mostrar todas las consultas guardadas
            files = [f[:-4] for f in os.listdir(self.query_directory) if f.lower().endswith('.sql')]
            files = sorted(files, key=lambda n: (0 if self.fav_store.is_query_fav(n) else 1, n.lower()))
            for name in files:
                try:
                    filename = os.path.join(self.query_directory, f"{name}.sql")
                    with open(filename, 'r', encoding='utf-8') as f:
                        query_text = f.read()
                        match = re.search(r'FROM\s+([a-zA-Z0-9_\.]+)', query_text, re.IGNORECASE)
                        table_name = match.group(1) if match else "N/A"
                        disp_name = f"{name} ({table_name})"
                    items_to_display.append({'name': name, 'disp_name': disp_name, 'text': query_text})
                except Exception:
                    items_to_display.append({'name': name, 'disp_name': f"Error al cargar-{name}", 'text': ""})
        else:
            # Lógica original: mostrar consultas frecuentes de la tabla actual
            items = self.history_store.get_for_table(self.current_table_name)
            items_to_display = [{'name': d['name'], 'disp_name': d['name'], 'text': d['text']} for d in items]
            
        for i, item in enumerate(items_to_display):
            # El filtro ahora busca en el nombre de la consulta y de la tabla
            if search and search not in item['disp_name'].lower() and not (search.isdigit() and int(search) - 1 == i):
                continue
            fav_indicator = "⭐ " if item.get('favorite', False) else ""
            lw = QListWidgetItem(f"{i+1} {fav_indicator}{item['disp_name']}")
            lw.setToolTip(item['text'])
            lw.setData(Qt.UserRole, item['name'])
            self.history_list.addItem(lw)
            
    def filter_history(self, text):
        self._refresh_history_list()
        
    def _use_history_item(self, item: QListWidgetItem):
        try:
            if not item or not hasattr(item, 'data'): return
            name = item.data(Qt.UserRole)
            items = self.history_store.get_for_table(self.current_table_name)
            for d in items:
                if d.get('name') == name:
                    self.get_editor().setPlainText(str(d.get('text', ''))); self.get_editor().setFocus(); break
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
                
    def _add_history_item(self):
        text = self.get_editor().toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Frecuentes", "No hay consulta en el editor para agregar"); return
        name, ok = QInputDialog.getText(self, "Agregar a Frecuentes", "Nombre a mostrar:")
        if ok and name:
            self.history_store.add_manual(self.current_table_name, name, text); self._refresh_history_list()
            
    def _rename_history_item(self):
        it = self.history_list.currentItem()
        try:
            if not it or not hasattr(it, 'text'): return
            old = it.text().split(' ', 1)[-1].strip()
            new_name, ok = QInputDialog.getText(self, "Renombrar", "Nuevo nombre:", text=old)
            if ok and new_name and new_name != old:
                self.history_store.rename(self.current_table_name, old, new_name); self._refresh_history_list()
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
            
    def _edit_history_item(self):
        it = self.history_list.currentItem()
        try:
            if not it or not hasattr(it, 'data'): return
            name = it.data(Qt.UserRole)
            items = self.history_store.get_for_table(self.current_table_name)
            cur_text = next((d.get('text','') for d in items if d.get('name') == name), '')
            new_text, ok = QInputDialog.getMultiLineText(self, "Editar consulta", "Consulta:", cur_text)
            if ok:
                for d in items:
                    if d.get('name') == name: d['text'] = new_text
                self.history_store.set_for_table(self.current_table_name, items); self._refresh_history_list()
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
            
    def _delete_history_item(self):
        it = self.history_list.currentItem()
        try:
            if not it or not hasattr(it, 'data'): return
            name = it.data(Qt.UserRole)
            if QMessageBox.question(self, "Confirmar", f"¿Eliminar '{name}'?") == QMessageBox.Yes:
                self.history_store.delete(self.current_table_name, name); self._refresh_history_list()
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
            
    def _move_history_item(self, direction):
        row = self.history_list.currentRow()
        try:
            if row < 0: return
            items = self.history_store.get_for_table(self.current_table_name)
            if not (0 <= row < len(items)): return
            new_row = row + direction
            if not (0 <= new_row < len(items)): return
            items[row], items[new_row] = items[new_row], items[row]
            self.history_store.set_for_table(self.current_table_name, items)
            self._refresh_history_list(); self.history_list.setCurrentRow(new_row)
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise

    def _toggle_history_favorite(self):
        it = self.history_list.currentItem()
        try:
            if not it or not hasattr(it, 'data'): return
            name = it.data(Qt.UserRole)
            items = self.history_store.get_for_table(self.current_table_name)
            for d in items:
                if d.get('name') == name:
                    d['favorite'] = not d.get('favorite', False)
                    break
            self.history_store.set_for_table(self.current_table_name, items)
            self._refresh_history_list()
        except RuntimeError as e:
            if "has been deleted" in str(e):
                # Item eliminado, ignorar silenciosamente
                return
            else:
                raise
        
    def open_multi_sort(self):
        if self.last_results_df is None or self.last_results_df.empty:
            QMessageBox.information(self, "Ordenar", "No hay resultados"); return
        df = self.results_table.get_filtered_data()
        key = str(hash(self.get_editor().toPlainText()))
        existing = self.sort_store.get(key)
        dlg = MultiSortDialog(list(df.columns), existing, self)
        if dlg.exec_() == QDialog.Accepted:
            config = dlg.get_result(); self.sort_store.set(key, config)
            if config:
                by = [c['col'] for c in config]; asc = [c['asc'] for c in config]
                try:
                    df2 = df.sort_values(by=by, ascending=asc); self.results_table.set_data(df2)
                except Exception as e:
                    error_msg = f"No se pudo ordenar: {e}"
                    QMessageBox.warning(self, "Orden", error_msg)
                    self.error_log_store.log_error("SortError", error_msg, datetime.now().isoformat())
                    
    def _change_data_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta de Datos", self.data_directory)
        if folder:
            self.data_directory = folder; self._setup_paths(); self._load_stores()
            QMessageBox.information(self, "Carpeta Cambiada", f"La carpeta de datos se ha establecido en:\n{folder}\n\nLa aplicación debe reiniciarse para que todos los cambios surtan efecto.")
            
    def clear_focus(self):
        try: self.get_editor().suggestions_popup.hide()
        except Exception: pass
        self.table_list.clearSelection(); self.columns_list.clearSelection(); self.results_table.clearSelection()
        fw = QApplication.focusWidget()
        if fw: fw.clearFocus()
        self.centralWidget().setFocus(Qt.OtherFocusReason)
        
    def _analyze_current_results(self):
        df = self.results_table.get_filtered_data()
        if df.empty:
            QMessageBox.information(self, "Análisis", "No hay datos para analizar."); return
        report = ""
        for col_name in df.columns:
            col_data = df[col_name]
            report += f"### Análisis de la Columna: '{col_name}'\n\n"
            report += f"- **Tipo de Dato:** {col_data.dtype}\n"
            null_count = col_data.isnull().sum()
            report += f"- **Valores Nulos:** {null_count} ({null_count / len(df):.2%})\n"
            report += f"- **Valores Únicos:** {col_data.nunique()}\n"
            if pd.api.types.is_numeric_dtype(col_data.dtype) and not col_data.isnull().all():
                report += f"- **Varianza:** {col_data.var():.4f}\n"
                report += f"- **Rango:** De {col_data.min()} a {col_data.max()}\n"
                report += f"- **Media:** {col_data.mean():.4f}\n"
                report += f"- **Desv. Estándar:** {col_data.std():.4f}\n"
            report += "\n" + ("-"*20) + "\n\n"
        dlg = QDialog(self)
        dlg.setWindowTitle("Reporte de Análisis")
        dlg.resize(500, 400)
        layout = QVBoxLayout(dlg)
        text_edit = QTextEdit()
        text_edit.setMarkdown(report)
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dlg.accept)
        layout.addWidget(button_box)
        dlg.exec_()
    def clear_all_content(self):
        try:
            # Block signals to prevent errors during cleaning
            self.editor_tabs.blockSignals(True)
            self.variables_panel.blockSignals(True)
            self.results_table.blockSignals(True)

            # Clear all tabs directly
            while self.editor_tabs.count() > 0:
                widget = self.editor_tabs.widget(0)
                self.editor_tabs.removeTab(0)
                widget.deleteLater()

            # Reset application state to initial
            self.last_results_df = None
            self.current_table_name = ""
            self.table_columns = []
            self.columns_cache = {}
            self.active_filters = {}
            self.results_table.set_data(pd.DataFrame())
            self.filter_column_combo.clear()
            self.global_search_input.clear()
            self._update_active_filters_display()
            self.status_bar_widget.status_label.setText("")
            self.status_bar_widget.elapsed_label.setText("Tiempo: 0.0s")
            self.status_bar_widget.row_count_label.setText("Filas: 0")
            self.status_bar_widget.estado_bar.hide()
            self.status_bar_widget.estado_label.setText("Estado: N/A")
            self.row_limit = 1000
            self.row_limit_combo.setCurrentText("1000")
            self.selection_mode_combo.setCurrentText("Celdas")
            self._apply_selection_mode("Celdas")
            self.variables_panel.clear_variables()
            self.variables_panel.add_variable_box('VAR1', '')
            self.variables_panel.add_variable_box('VAR2', '')
            self.variables_panel.add_variable_box('VAR3', '')

            # Create exactly 3 new tabs like initial startup
            self._create_editor_tab()
            self._create_editor_tab()
            self._create_editor_tab()

            # Select the first tab
            self.editor_tabs.setCurrentIndex(0)

            self._tab_states = {}

            # Clear frequent queries
            self.history_store._data = {}
            self.history_store.save()
            self._refresh_history_list()

            # Clear saved queries
            import os
            for f in os.listdir(self.query_directory):
                if f.lower().endswith('.sql'):
                    os.remove(os.path.join(self.query_directory, f))
            self._load_saved_queries()

            # Unblock signals
            self.editor_tabs.blockSignals(False)
            self.variables_panel.blockSignals(False)
            self.results_table.blockSignals(False)

        except Exception as e:
            # Silently handle any errors to prevent alerts
            pass

    def filter_by_status(self):
        if self.last_results_df is None or self.last_results_df.empty:
            QMessageBox.information(self, "Sin resultados", "No hay resultados para filtrar")
            return
        if 'ESTADO' not in self.last_results_df.columns:
            QMessageBox.information(self, "Sin columna ESTADO", "La columna 'ESTADO' no existe en los resultados")
            return
        # Toggle filter for ESTADO = 1 only
        estado_col_name = None
        for col in self.last_results_df.columns:
            if col == 'ESTADO':
                estado_col_name = col
                break
        if estado_col_name is None:
            QMessageBox.information(self, "Sin columna ESTADO", "La columna 'ESTADO' no existe en los resultados")
            return

        if estado_col_name in self.active_filters and self.active_filters[estado_col_name] == '1':
            # Remove filter
            del self.active_filters[estado_col_name]
        else:
            # Add filter for ESTADO = 1
            self.active_filters[estado_col_name] = '1'
        self._apply_filters_in_real_time()
        self._update_active_filters_display()

    def _excel_column_name(self, n):
        """Convert column index to Excel column name (A, B, ..., Z, AA, AB, etc.)"""
        name = ''
        while n >= 0:
            name = chr(65 + (n % 26)) + name
            n = n // 26 - 1
        return name

    def _make_columns_unique(self, columns):
        """Make column names unique by adding underscores when duplicates exist"""
        seen = {}
        result = []
        for col in columns:
            if col in seen:
                seen[col] += 1
                result.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 1
                result.append(col)
        return result

    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Salir',
                                     '¿Estás seguro de que quieres salir?',
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        if reply == QMessageBox.Yes:
            event.accept()
        else:
            event.ignore()

    def resizeEvent(self, event):
        self.on_resize(event)
        super().resizeEvent(event)

    def on_resize(self, event):
        # Mostrar botones individuales si ancho >= 1200, sino mostrar solo el botón de menú
        if hasattr(self, 'result_buttons') and hasattr(self, 'botones_btn'):
            show_individual = self.width() >= 1200
            for btn in self.result_buttons:
                btn.setVisible(show_individual)
            self.botones_btn.setVisible(not show_individual)
def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 9))
    def excepthook(type, value, traceback):
        QMessageBox.critical(None, "Error", f"Se produjo un error:\n\n{type.__name__}: {value}\n\nLa aplicación continuará ejecutándose.")
    sys.excepthook = excepthook
    win1 = DatabaseQueryApp()
    win1.show()
    sys.exit(app.exec_())
if __name__ == "__main__":
    main()
