"""Проверочное приложение Qt for Android: доказывает, что сборка, QtMultimedia и QtNetwork работают на телефоне."""

import sys

from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtNetwork import QNetworkInterface
from PySide6.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv)
cameras = [device.description() for device in QMediaDevices.videoInputs()]
label = QLabel(f"GMAGC Qt\ncameras: {cameras}\nnet: {len(QNetworkInterface.allInterfaces())}")
label.show()
sys.exit(app.exec())
