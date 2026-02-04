import sys
import os
import time
import subprocess
import pytesseract
import re
import tempfile
import numpy as np
import random
from PIL import Image
import cv2

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QSpinBox, QTextEdit
)
from PyQt5.QtCore import QThread, pyqtSignal

# ===== 경로 설정 =====
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
ADB_PATH = os.path.join(BASE_DIR, "adb.exe")
SCREENSHOT_FILE = os.path.join(tempfile.gettempdir(), "screen.png")
LOG_FILE = os.path.join(BASE_DIR, "macro.log")

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
KEYWORDS = ["저", "주", "받", "물", "상", "자", "보물", "상자", "저주", "받은"]

# ===== 로그 함수 =====
def write_log(msg):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f"{timestamp} {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line

# ===== 랜덤 좌표 함수 =====
def random_tap(x, y, min_offset=3, max_offset=8):
    dx = random.randint(-max_offset, max_offset)
    dy = random.randint(-max_offset, max_offset)

    # 너무 작은 움직임 방지
    if abs(dx) < min_offset:
        dx = min_offset if dx >= 0 else -min_offset
    if abs(dy) < min_offset:
        dy = min_offset if dy >= 0 else -min_offset

    return x + dx, y + dy

# ===== 디바이스 자동 탐색 =====
def get_device_id():
    try:
        result = subprocess.run(
            [ADB_PATH, "devices"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        lines = result.stdout.strip().splitlines()
        for line in lines[1:]:
            if "\tdevice" in line:
                return line.split("\t")[0]
        return None
    except:
        return None

# ===== 스크린샷 =====
def take_screenshot(device_id):
    try:
        subprocess.run([ADB_PATH, "-s", device_id, "shell", "screencap", "-p", "/sdcard/screen.png"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run([ADB_PATH, "-s", device_id, "pull", "/sdcard/screen.png", SCREENSHOT_FILE],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, creationflags=subprocess.CREATE_NO_WINDOW)

        # 파일 생성 확인
        timeout = 5
        while timeout > 0:
            if os.path.exists(SCREENSHOT_FILE) and os.path.getsize(SCREENSHOT_FILE) > 0:
                return True
            time.sleep(0.1)
            timeout -= 0.1
        return False
    except Exception as e:
        return False

# ===== 매크로 스레드 =====
class MacroThread(QThread):
    log = pyqtSignal(str)
    ocr_text = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, wait_seconds):
        super().__init__()
        self.wait_seconds = wait_seconds
        self.running = True
        self.device_id = None

    def stop(self):
        self.running = False

    def run(self):
        self.device_id = get_device_id()
        if not self.device_id:
            msg = write_log("❌ 연결된 디바이스 없음")
            self.log.emit(msg)
            self.finished.emit()
            return

        msg = write_log(f"📱 디바이스 연결됨: {self.device_id}")
        self.log.emit(msg)

        while self.running:
            msg = write_log("스크린샷 촬영")
            self.log.emit(msg)
            if not take_screenshot(self.device_id):
                msg = write_log("❌ 스크린샷 실패 → 재시도")
                self.log.emit(msg)
                time.sleep(2)
                continue

            try:
                img = Image.open(SCREENSHOT_FILE)
                img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            except Exception as e:
                msg = write_log(f"❌ 이미지 로드 실패: {e}")
                self.log.emit(msg)
                time.sleep(2)
                continue

            roi = img[360:470, 60:650]
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

            # OCR
            text = pytesseract.image_to_string(gray, lang="kor", config="--psm 6")
            hangul_text = re.sub(r"[^가-힣]", "", text)
            self.ocr_text.emit(f"📄 인식 텍스트: {hangul_text}")

            msg = write_log(f"OCR 원문: {text}")
            self.log.emit(msg)

            found = [k for k in KEYWORDS if k in hangul_text]
            if found:
                msg = write_log(f"🎯 키워드 발견: {found}")
                self.log.emit(msg)
                break

            msg = write_log("키워드 없음 → 매크로 실행")
            self.log.emit(msg)

            # 매크로 액션 (랜덤 클릭 포함)
            taps = [(60,1240),(478,800),(60,1240),(360,1200)]
            delays = [1.5,2,2,0]

            for (x,y), delay in zip(taps, delays):
                tx, ty = random_tap(x, y)
                subprocess.run(
                    [ADB_PATH, "-s", self.device_id, "shell", "input", "tap", str(tx), str(ty)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    shell=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                time.sleep(delay)

            msg = write_log(f"{self.wait_seconds}초 대기")
            self.log.emit(msg)
            for _ in range(self.wait_seconds):
                if not self.running:
                    break
                time.sleep(1)

        msg = write_log("매크로 종료")
        self.log.emit(msg)
        self.finished.emit()

# ===== UI =====
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OCR 매크로")
        self.thread = None

        self.label = QLabel("대기 시간 (초)")
        self.spin = QSpinBox()
        self.spin.setRange(1, 9999)
        self.spin.setValue(15)

        self.button = QPushButton("실행")
        self.button.clicked.connect(self.toggle)

        self.ocr_label = QTextEdit()
        self.ocr_label.setReadOnly(True)

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.spin)
        layout.addWidget(self.button)
        layout.addWidget(QLabel("📄 OCR 인식 한글"))
        layout.addWidget(self.ocr_label)
        layout.addWidget(QLabel("📝 로그"))
        layout.addWidget(self.log)
        self.setLayout(layout)

    def toggle(self):
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.button.setEnabled(False)
        else:
            self.start_macro()

    def start_macro(self):
        self.thread = MacroThread(self.spin.value())
        self.thread.log.connect(self.append_log)
        self.thread.ocr_text.connect(self.set_ocr_text)
        self.thread.finished.connect(self.on_finished)
        self.thread.start()
        self.button.setText("중지")

    def append_log(self, msg):
        self.log.append(msg)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def set_ocr_text(self, text):
        self.ocr_label.setPlainText(text)

    def on_finished(self):
        self.button.setText("실행")
        self.button.setEnabled(True)
        self.thread = None

# ===== 실행 =====
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(400, 500)
    win.show()
    sys.exit(app.exec_())
