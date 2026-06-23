#!/usr/bin/env python3
"""PyQt5 full-resolution image viewer launched from the terminal browser."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QFileDialog, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget


class ImageViewerWindow(QMainWindow):
    def __init__(self, image_path: Path):
        super().__init__()
        self.image_path = image_path.resolve()
        self.pixmap = QPixmap(str(self.image_path))

        central = QWidget()
        layout = QVBoxLayout(central)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        if self.pixmap.isNull():
            self.image_label.setText(f"Could not load image:\n{self.image_path}")
        else:
            self.image_label.setPixmap(self.pixmap)
        layout.addWidget(self.image_label)

        save_button = QPushButton("Save As…")
        save_button.clicked.connect(self.save_image)
        layout.addWidget(save_button)

        self.setCentralWidget(central)
        title = self.image_path.name
        if not self.pixmap.isNull():
            title = f"{title} ({self.pixmap.width()}×{self.pixmap.height()})"
        self.setWindowTitle(title)
        self.resize(min(960, max(420, self.pixmap.width() + 40)), min(720, self.pixmap.height() + 80))

    def save_image(self):
        if self.pixmap.isNull():
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Save Image As",
            str(self.image_path),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if destination:
            self.pixmap.save(destination)


def show_image(image_path: str | Path) -> int:
    path = Path(image_path)
    app = QApplication.instance() or QApplication(sys.argv)
    window = ImageViewerWindow(path)
    window.show()
    return app.exec_()


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: qt_image_viewer.py <image-path>", file=sys.stderr)
        return 1
    return show_image(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
