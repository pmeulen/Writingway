from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QApplication
from PyQt5.QtGui import QTextCursor
from PyQt5.QtCore import Qt

class ProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Summary Progress"))
        self.setMinimumSize(800, 300)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlaceholderText(_("Summary generation progress will appear here..."))
        layout.addWidget(self.text_edit)
        self.close_button = QPushButton(_("Close"))
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.close_button)
        self.setLayout(layout)

    def append_message(self, message):
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.insertPlainText(message + "\n")
        self.text_edit.ensureCursorVisible()
        self.text_edit.repaint()  # Force immediate redraw of the text edit
        QApplication.processEvents()  # Process pending events to update GUI
