import sys
import socket
import queue
import time
import threading
import json
import os
import winreg
import subprocess
import manager_host
from queries import latest_app_info
from pathlib import Path
from file_funcs import pick_folder
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QStackedLayout, QGridLayout, QWidget, QTextBrowser, QProgressBar, QSizePolicy, QCheckBox
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter, QPaintEvent, QDesktopServices
from PyQt6.QtCore import Qt, QRect, QThread, pyqtSignal, QObject, QUrl

TESTING = False
VERSION = "v2.10.1"

KEY_PATH = "Software\\MinecraftManager"

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent

STYLE_PATH = BASE_DIR / "Styles" / "manager_style.css"
IMAGE_PATH = BASE_DIR / "Images"

class BackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.background_image = QPixmap(os.path.join(IMAGE_PATH, "block_background.png"))

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.drawPixmap(QRect(0, 0, self.width(), self.height()), self.background_image)

class ConnectionWorker(QObject):
    connection_success = pyqtSignal(object)
    connection_failure = pyqtSignal()

    def __init__(self, ip, port):
        super().__init__()
        self.ip = ip
        self.port = port
    
    def attempt_connection(self):
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.setblocking(False)
            client.settimeout(5)
            client.connect((self.ip, self.port))
            client.sendall("connection test".encode("utf-8"))
            self.connection_success.emit(client)
        except socket.error as e:
            if e.errno == 10035:
                time.sleep(0.1)
            else:
                self.connection_failure.emit()

class ServerManagerApp(QMainWindow):
    set_status_signal = pyqtSignal(list)
    set_players_signal = pyqtSignal(list)
    set_worlds_list_signal = pyqtSignal(list)
    get_status_signal = pyqtSignal()
    update_log_signal = pyqtSignal(str)
    switch_to_connect_signal = pyqtSignal()
    progress_set_signal = pyqtSignal(int)
    progress_range_signal = pyqtSignal(int, int)
    download_message_signal = pyqtSignal(str)
    enable_mods_button_signal = pyqtSignal()
    download_complete_signal = pyqtSignal()
    log_message_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # Default IP
        self.host_ip = self.load_ip()
        self.port = 5555
        self.client = None
        self.close_threads = threading.Event()
        self.receive_thread = None
        self.message_thread = None
        self.connection_thread = None
        self.selected_dropdown_text = ""
        self.status = ""
        self.server_version = ""
        self.worlds = {}
        self.mods_download_path: Path | None = None
        self.last_page_index = 0
        self.log_queue = queue.Queue()
        self.connection_delay_messages = ["Having trouble connecting? Either",
                                     "1. Your Hamachi is not open",
                                     "2. The host's Hamachi is not open",
                                     "3. The host is not running their manager application"]

        # Signals
        self.set_status_signal.connect(self.set_status)
        self.set_players_signal.connect(self.set_players)
        self.set_worlds_list_signal.connect(self.set_worlds_list)
        self.get_status_signal.connect(self.get_status)
        self.update_log_signal.connect(self.update_log)
        self.switch_to_connect_signal.connect(self.switch_to_connect_page)
        self.progress_set_signal.connect(self.set_progress_value)
        self.progress_range_signal.connect(self.set_progress_range)
        self.download_message_signal.connect(self.set_download_message_text)
        self.enable_mods_button_signal.connect(self.enable_mods_button)
        self.download_complete_signal.connect(self.download_complete)
        self.log_message_signal.connect(self.log_queue.put)
        
        self.init_ui()
        self.connect_button.clicked.connect(self.start_connection_thread)
        self.host_ip_entry.returnPressed.connect(self.start_connection_thread)
        self.switch_to_mode_page()

    def init_ui(self):

        # Central widget to hold everything
        central_widget = BackgroundWidget(self)
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout(central_widget)

        # Stacked layout to manage pages
        self.stacked_layout = QStackedLayout()

        # Page 1: Connect to Server
        connect_layout = QGridLayout()
        center_column_layout = QVBoxLayout()
        input_layout = QVBoxLayout()
        input_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        host_ip_label = QLabel("Host IP:")
        host_ip_label.setObjectName("mediumText")
        host_ip_label.setFont(QFont(host_ip_label.font().family(), int(host_ip_label.font().pointSize() * 1.5)))
        host_ip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.host_ip_entry = QLineEdit(self.host_ip)  # Set default IP
        self.host_ip_entry.setMinimumWidth(self.width() // 2)
        self.host_ip_entry.setMaximumWidth(self.width() // 2)
        self.host_ip_entry.setFont(QFont(self.host_ip_entry.font().family(), int(self.host_ip_entry.font().pointSize() * 1.5)))
        self.host_ip_entry.setPlaceholderText("IP Address")

        self.default_ip_checkbox = QCheckBox("Set as default IP")
        self.default_ip_checkbox.setChecked(False)

        self.connect_button = QPushButton("Connect")

        input_layout.addWidget(host_ip_label)
        input_layout.addWidget(self.host_ip_entry)
        input_layout.addWidget(self.connect_button)
        input_layout.addWidget(self.default_ip_checkbox)

        # Shown when connection failure
        message_layout = QVBoxLayout()
        message_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.connecting_label = QLabel("Connection Failed")
        self.connecting_label.setObjectName("connectingText")
        self.connecting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_layout.addWidget(self.connecting_label)
        self.connecting_label.setText("") # Gets set after failure
        self.connecting_label.setFont(QFont("Tahoma", self.connecting_label.font().pointSize()))

        self.connection_delabels = [QLabel("") for _ in self.connection_delay_messages]
        for label in self.connection_delabels:
            label.setObjectName("messageText")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            message_layout.addWidget(label)

        center_column_layout.addLayout(input_layout)
        center_column_layout.addLayout(message_layout)


        right_column_layout = QVBoxLayout()

        version = QPushButton(VERSION)
        version.setObjectName("version_num")
        version.setCursor(Qt.CursorShape.PointingHandCursor)
        version.clicked.connect(self.switch_to_update_page)
        right_column_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        connect_layout.setColumnStretch(0, 1)
        connect_layout.addLayout(center_column_layout, 0, 1, 0, 8, Qt.AlignmentFlag.AlignCenter)
        connect_layout.addLayout(right_column_layout, 0, 9)
        connect_layout.setColumnStretch(9, 1)

        connect_page = QWidget()
        connect_page.setLayout(connect_layout)

        # Page 2: Name Prompt
        name_prompt_layout = QGridLayout()
        center_column_layout = QVBoxLayout()
        center_column_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_entry = QLineEdit()
        self.name_entry.setMinimumWidth(self.width() // 2)
        self.name_entry.setMaximumWidth(self.width() // 2)
        self.name_entry.setFont(QFont(self.name_entry.font().family(), int(self.name_entry.font().pointSize() * 1.5)))
        self.name_entry.setPlaceholderText("Display Name")
        self.name_entry.returnPressed.connect(self.send_name)

        center_column_layout.addWidget(self.name_entry, Qt.AlignmentFlag.AlignHCenter)

        right_column_layout = QVBoxLayout()
        version = QPushButton(VERSION)
        version.setObjectName("version_num")
        version.setCursor(Qt.CursorShape.PointingHandCursor)
        version.clicked.connect(self.switch_to_update_page)

        right_column_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        name_prompt_layout.setColumnStretch(0, 1)
        name_prompt_layout.addLayout(center_column_layout, 0, 1, 0, 8, Qt.AlignmentFlag.AlignCenter)
        name_prompt_layout.addLayout(right_column_layout, 0, 9)
        name_prompt_layout.setColumnStretch(9, 1)

        name_prompt_page = QWidget()
        name_prompt_page.setLayout(name_prompt_layout)

        # Page 3: Server Manager
        server_manager_layout = QHBoxLayout()

        # Left column
        left_column_layout = QVBoxLayout()
        self.change_ip = QPushButton("Change IP")
        self.change_ip.pressed.connect(self.switch_to_connect_page)
        self.refresh_button = QPushButton("\u21BB")
        self.refresh_button.setObjectName("smallGreenButton")
        self.refresh_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.refresh_button.setToolTip("Refresh Players")
        self.refresh_button.clicked.connect(self.get_players)
        self.current_players_label = QLabel("Current Players")
        self.current_players_label.setFont(QFont(self.current_players_label.font().family(), int(self.current_players_label.font().pointSize() * 1.5)))
        self.players_info_box = QTextBrowser()

        players_label_layout = QHBoxLayout()
        players_label_layout.addWidget(self.refresh_button)
        players_label_layout.addWidget(self.current_players_label)
        left_column_layout.addWidget(self.change_ip)
        left_column_layout.addLayout(players_label_layout)
        left_column_layout.addWidget(self.players_info_box)

        # Center column
        center_column_layout = QVBoxLayout()
        self.title_label = QLabel("Server Manager")
        self.title_font = self.title_label.font()
        self.title_font.setFamily("Courier New")
        self.title_font.setPointSize(int(self.title_font.pointSize() * 2.5))
        self.title_font.setBold(True)
        self.title_label.setFont(self.title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        
        self.world_label = QLabel("Server World: ")
        self.world_label.setObjectName("world_details")
        self.world_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.version_label = QLabel("Server Version: ")
        self.version_label.setObjectName("world_details")
        self.version_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        status_layout = QGridLayout()
        self.refresh_status_button = QPushButton("\u21BB")
        self.refresh_status_button.setObjectName("smallGreenButton")
        self.refresh_status_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.refresh_status_button.setToolTip("Refresh Status")
        self.refresh_status_button.clicked.connect(self.get_status)
        status_layout.addWidget(self.refresh_status_button, 0, 0)
        self.server_status_label = QLabel("Status: Pinging...")  # Replace with dynamic status
        self.server_status_label.setFont(QFont("Verdana", int(self.server_status_label.font().pointSize() * 1.5)))
        status_layout.addWidget(self.server_status_label, 0, 1)
        self.server_status_label.hide()
        self.server_status_online_label = QLabel("Status: Online")  # Replace with dynamic status
        self.server_status_online_label.setObjectName("statusOnline")
        self.server_status_online_label.setFont(QFont("Verdana", int(self.server_status_online_label.font().pointSize() * 1.5)))
        status_layout.addWidget(self.server_status_online_label, 0, 1)
        self.server_status_online_label.hide()
        self.server_status_offline_label = QLabel("Status: Offline")  # Replace with dynamic status
        self.server_status_offline_label.setObjectName("statusOffline")
        self.server_status_offline_label.setFont(QFont("Verdana", int(self.server_status_offline_label.font().pointSize() * 1.5)))
        status_layout.addWidget(self.server_status_offline_label, 0, 1)
        self.server_status_offline_label.show()
        status_layout.setColumnStretch(2, 1)

        self.log_box = QTextBrowser()
        self.log_box.setOpenExternalLinks(True)
        self.log_box.setReadOnly(True)
        self.message_entry = QLineEdit()
        self.message_entry.setPlaceholderText("Send Message")
        self.message_entry.returnPressed.connect(self.on_message_entered)

        center_column_layout.addWidget(self.title_label)
        center_column_layout.addWidget(self.world_label)
        center_column_layout.addWidget(self.version_label)
        center_column_layout.addLayout(status_layout)
        center_column_layout.addWidget(self.log_box)
        center_column_layout.addWidget(self.message_entry)

        # Right column
        right_column_layout = QVBoxLayout()
        self.functions_label = QLabel("Functions")
        self.functions_label.setFont(QFont(self.functions_label.font().family(), int(self.functions_label.font().pointSize() * 1.5)))
        self.dropdown = QComboBox()
        self.dropdown.currentTextChanged.connect(self.set_current_world_version)
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(lambda: self.start_server(self.dropdown.currentText()))
        self.world_version_label = QLabel("")
        self.world_version_label.setObjectName("world_version")
        self.world_version_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setObjectName("stopButton")

        self.mods_download_button = QPushButton("Download\nMods")
        self.mods_download_button.setObjectName("blueButton")
        self.mods_download_button.clicked.connect(self.switch_to_download_page)
        self.mods_download_button.hide()
        self.mods_download_button.setDisabled(True)

        functions_layout = QGridLayout()
        functions_layout.addWidget(self.functions_label, 0, 0, 1, 2)  # Label spanning two columns
        functions_layout.addWidget(self.dropdown, 1, 0, 1, 2)
        functions_layout.addWidget(self.world_version_label, 2, 0, 1, 2)
        functions_layout.addWidget(self.start_button, 3, 0, 1, 2)
        functions_layout.addWidget(self.stop_button, 4, 0, 1, 2)
        functions_layout.addWidget(self.mods_download_button, 5, 0, 1, 2)

        functions_layout.setColumnStretch(1, 1)  # Stretch the second column

        right_column_layout.addLayout(functions_layout)
        right_column_layout.addStretch(1)  # Add empty space at the bottom
        version = QPushButton(VERSION)
        version.setObjectName("version_num")
        version.setCursor(Qt.CursorShape.PointingHandCursor)
        version.clicked.connect(self.switch_to_update_page)
        right_column_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        server_manager_layout.addLayout(left_column_layout, 2)  # Make the left column twice as wide
        server_manager_layout.addLayout(center_column_layout, 5)  # Keep the center column as it is
        server_manager_layout.addLayout(right_column_layout, 2)  # Make the right column twice as wide

        server_manager_page = QWidget()
        server_manager_page.setLayout(server_manager_layout)

        # Page 4: Download mods page

        page_layout = QHBoxLayout()

        center_layout = QVBoxLayout()
        center_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.downloads_message = QLabel("")
        self.downloads_message.setObjectName("mediumText")
        self.downloads_message.setWordWrap(True)
        self.downloads_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.download_progress = QProgressBar()
        self.download_progress.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.download_progress.hide()
        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self.download_mods)
        self.finish_button = QPushButton("Finish")
        self.finish_button.clicked.connect(self.switch_to_server_manager)
        self.open_downloads_button = QPushButton("View Download Folder")
        self.open_downloads_button.setObjectName("blueButton")
        self.open_downloads_button.clicked.connect(lambda: self.open_folder_explorer(self.mods_download_path or Path.home() / "Downloads"))
        self.cancel_download_button = QPushButton("Cancel")
        self.cancel_download_button.setObjectName("stopButton")
        self.cancel_download_button.clicked.connect(self.switch_to_server_manager)

        center_layout.addWidget(self.downloads_message, alignment=Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.download_progress, alignment=Qt.AlignmentFlag.AlignCenter)
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.download_button, alignment=Qt.AlignmentFlag.AlignCenter)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.finish_button, alignment=Qt.AlignmentFlag.AlignCenter)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.open_downloads_button, alignment=Qt.AlignmentFlag.AlignCenter)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.cancel_download_button, alignment=Qt.AlignmentFlag.AlignCenter)
        buttons_layout.addStretch(1)
        center_layout.addLayout(buttons_layout)

        right_layout = QVBoxLayout()
        version = QPushButton(VERSION)
        version.setObjectName("version_num")
        version.setCursor(Qt.CursorShape.PointingHandCursor)
        version.clicked.connect(self.switch_to_update_page)
        right_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        page_layout.addStretch(1)
        page_layout.addLayout(center_layout)
        page_layout.addLayout(right_layout)
        page_layout.setStretch(2, 1)

        download_page = QWidget()
        download_page.setLayout(page_layout)

        # Page 5: Select Manager Mode
        mode_layout = QGridLayout()
        center_column_layout = QVBoxLayout()
        buttons_layout = QVBoxLayout()
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        mode_label = QLabel("Select Manager Mode")
        mode_label.setObjectName("mediumText")
        mode_label.setFont(QFont(mode_label.font().family(), int(mode_label.font().pointSize() * 1.5)))
        mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        client_button = QPushButton("Client")
        client_button.clicked.connect(self.show_connect_page)
        host_button = QPushButton("Host")
        host_button.clicked.connect(self.open_host_app)

        buttons_layout.addWidget(mode_label)
        buttons_layout.addWidget(client_button)
        buttons_layout.addWidget(host_button)
        center_column_layout.addLayout(buttons_layout)

        right_column_layout = QVBoxLayout()

        version = QPushButton(VERSION)
        version.setObjectName("version_num")
        version.setCursor(Qt.CursorShape.PointingHandCursor)
        version.clicked.connect(self.switch_to_update_page)
        right_column_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        mode_layout.setColumnStretch(0, 1)
        mode_layout.addLayout(center_column_layout, 0, 1, 0, 8, Qt.AlignmentFlag.AlignCenter)
        mode_layout.addLayout(right_column_layout, 0, 9)
        mode_layout.setColumnStretch(9, 1)

        mode_page = QWidget()
        mode_page.setLayout(mode_layout)

        # Page 6: Download Update Page
        update_layout = QGridLayout()
        center_column_layout = QVBoxLayout()
        buttons_layout = QVBoxLayout()
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        download_button = QPushButton("Download Latest Version")
        download_button.setObjectName("blueButton")
        download_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(latest_app_info()[2])))
        open_url_button = QPushButton("View Github Releases Page")
        open_url_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.github.com/Peter-Vanderhyde/Minecraft-Manager/releases/")))
        back_button = QPushButton("Back")
        back_button.setObjectName("stopButton")
        back_button.clicked.connect(lambda: self.stacked_layout.setCurrentIndex(self.last_page_index))

        buttons_layout.addWidget(download_button)
        buttons_layout.addWidget(open_url_button)
        buttons_layout.addWidget(back_button)
        center_column_layout.addLayout(buttons_layout)

        right_column_layout = QVBoxLayout()

        version = QPushButton(VERSION)
        version.setObjectName("version_num")
        version.setCursor(Qt.CursorShape.PointingHandCursor)
        version.clicked.connect(self.switch_to_update_page)
        right_column_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        update_layout.setColumnStretch(0, 1)
        update_layout.addLayout(center_column_layout, 0, 1, 0, 8, Qt.AlignmentFlag.AlignCenter)
        update_layout.addLayout(right_column_layout, 0, 9)
        update_layout.setColumnStretch(9, 1)

        update_page = QWidget()
        update_page.setLayout(update_layout)

        #----------------------------------------------------

        # Add pages to the stacked layout
        self.stacked_layout.addWidget(connect_page)
        self.stacked_layout.addWidget(name_prompt_page)
        self.stacked_layout.addWidget(server_manager_page)
        self.stacked_layout.addWidget(download_page)
        self.stacked_layout.addWidget(mode_page)
        self.stacked_layout.addWidget(update_page)

        # Set the main layout to the stacked layout
        main_layout.addLayout(self.stacked_layout)

        # Set window title and initial size
        self.setWindowTitle("Server Manager")

        # Set the window icon
        icon = QIcon(os.path.join(IMAGE_PATH, "app_icon.ico"))
        self.setWindowIcon(icon)

        # Apply styles for a colorful appearance
        with open(STYLE_PATH, 'r') as stylesheet:
            style_str = stylesheet.read()
        
        self.setStyleSheet(style_str)
    
    def delay(self, delay_amount):
        end_time = time.time() + delay_amount
        while time.time() < end_time:
            QApplication.processEvents()
    
    def save_ip(self):
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY_PATH)
            winreg.SetValueEx(key, "DefaultIP", 0, winreg.REG_SZ, self.host_ip)
            winreg.CloseKey(key)
        except:
            return
    
    def load_ip(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH)
            value, _ = winreg.QueryValueEx(key, "DefaultIP")
            winreg.CloseKey(key)
            return value
        except:
            return ""
    
    def start_connection_thread(self):
        if self.host_ip_entry.text() == "":
            return
        
        self.host_ip = self.host_ip_entry.text()
        if self.default_ip_checkbox.isChecked():
            self.save_ip()
        
        self.connecting_label.setText("Connecting...")
        delay = 0.5
        end = time.time() + delay
        while time.time() < end:
            QApplication.processEvents()
        
        self.connection_thread = QThread(self)
        connection_worker = ConnectionWorker(self.host_ip, self.port)
        connection_worker.moveToThread(self.connection_thread)

        connection_worker.connection_success.connect(self.on_connection_success)
        connection_worker.connection_failure.connect(self.on_connection_failure)

        self.connection_thread.start()
        connection_worker.attempt_connection()
    
    def close_connection_thread(self):
        if self.connection_thread and self.connection_thread.isRunning():
            self.connection_thread.quit()
            self.connection_thread.wait()

    def on_connection_success(self):
        self.close_connection_thread()
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.connect((self.host_ip, self.port))
        self.client.sendall("connection request".encode("utf-8"))
        accepted = self.client.recv(1024).decode("utf-8")
        if accepted == "accept" or accepted == "identify":
            self.client.setblocking(False)
            self.receive_thread = threading.Thread(target=self.receive)
            self.receive_thread.start()
            self.message_thread = threading.Thread(target=self.check_messages)
            self.message_thread.start()
            if accepted == "accept":
                self.switch_to_server_manager()
                self.first_connect()
            elif accepted == "identify":
                self.switch_to_name_prompt()
    
    def on_connection_failure(self):
        self.close_connection_thread()
        self.connecting_label.setText("Connection Failure")
        self.display_delay_messages()
    
    def on_message_entered(self):
        message = self.message_entry.text()
        if message != "":
            self.message_entry.clear()
            self.send(message)
    
    def receive(self):
        buf = bytearray()
        total_file_sizes = 0
        size_so_far = 0
        expecting_file = False
        self.file = None
        self.file_name = None
        self.file_size = 0
        file_bytes_needed = 0
        last_time = time.time()
        while not self.close_threads.is_set():
            try:
                if expecting_file:
                    chunk = self.client.recv(65536)
                else:
                    chunk = self.client.recv(4096)
                if not chunk:
                    self.close_threads.set()
                    break
                buf.extend(chunk)

                if expecting_file:
                    to_write = buf[:file_bytes_needed]
                    if to_write:
                        self.file.write(to_write)
                        self.file.flush()
                        del buf[:len(to_write)]
                        file_bytes_needed -= len(to_write)
                        size_so_far += len(to_write)
                        if time.time() - last_time >= 0.1:
                            self.progress_set_signal.emit(min(size_so_far, total_file_sizes))
                            last_time = time.time()

                    if file_bytes_needed == 0:
                        self.file.close()
                        self.file = None
                        expecting_file = False
                        self.log_queue.put(f"Downloaded '{self.file_name}'.")
                    else:
                        continue

                while True:
                    marker = b"SERVER-MESSAGE~~>"
                    idx = buf.find(marker)
                    if idx == -1:
                        # Keep accumulating
                        break

                    nl = buf.find(b"\n", idx)
                    if nl == -1:
                        break
                    raw_msg = bytes(buf[idx + len(marker):nl])
                    del buf[:nl + 1]
                    try:
                        text = raw_msg.decode("utf-8")
                    except UnicodeDecodeError:
                        continue

                    if text.startswith("DATA-RETURN"):
                        data = text.split('~~>')
                        key, args = data[0][data[0].find('(')+1:data[0].find(')')], json.loads(data[1])
                        
                        if key == "sending-file":
                            filename, filesize, current_index, num_of_mods, total_file_sizes = args
                            self.progress_range_signal.emit(0, total_file_sizes)
                            self.file_name = filename
                            file_bytes_needed = int(filesize)
                            self.download_message_signal.emit(f"Downloading mod {current_index}/{num_of_mods}\n{filename}")
                            self.file = open(self.mods_download_path / self.file_name, "wb")
                            to_take = min(len(buf), file_bytes_needed)
                            if to_take:
                                self.file.write(buf[:to_take])
                                self.file.flush()
                                del buf[:to_take]
                                file_bytes_needed -= to_take
                                size_so_far += to_take
                            
                            if file_bytes_needed == 0:
                                self.file.close()
                                self.file = None
                                self.log_message_signal.emit(f"Downloaded '{self.file_name}'.")
                                expecting_file = False
                            else:
                                expecting_file = True
                        else:
                            if key == "status":
                                self.set_status_signal.emit(args)
                            elif key == "players":
                                self.set_players_signal.emit(args)
                            elif key == "worlds-list":
                                self.set_worlds_list_signal.emit(args)
                            elif key in ["start", "stop"] and args == ["refresh"]:
                                self.get_status_signal.emit()
                            elif key == "available-mods":
                                if args[0] == self.selected_dropdown_text and args[1] == True:
                                    self.enable_mods_button_signal.emit()
                            elif key == "file-transfer-complete":
                                self.download_complete_signal.emit()
                                total_file_sizes = 0
                                size_so_far = 0
                    else:
                        self.log_message_signal.emit(text)
                        
            except socket.error as e:
                if e.errno == 10035:
                    time.sleep(0.1)
                else:
                    self.close_threads.set()
                    break
            except Exception:
                if self.file:
                    try:
                        self.file.close()
                    except Exception:
                        pass
                    self.file = None
                self.close_threads.set()
                break
        
        if expecting_file and self.file:
            self.file.close()
        self.switch_to_connect_signal.emit()

    def display_delay_messages(self):
        for i, label in enumerate(self.connection_delabels):
            label.setText(self.connection_delay_messages[i])
    
    def send(self, message):
        self.client.sendall(f"CLIENT-MESSAGE~~>{message}".encode("utf-8"))

    def switch_to_name_prompt(self):
        self.stacked_layout.setCurrentIndex(1) # Show the second page (Name Prompt)
    
    def send_name(self):
        name = self.name_entry.text()
        if name != "":
            self.send(name)
            self.delay(1)
            self.switch_to_server_manager()
            self.first_connect()

    def switch_to_server_manager(self):
        self.stacked_layout.setCurrentIndex(2)  # Show the third page (Server Manager)
    
    def show_connect_page(self):
        self.stacked_layout.setCurrentIndex(0)
    
    def switch_to_connect_page(self):
        self.close_threads.set()
        self.close_connection_thread()
        if self.receive_thread:
            self.receive_thread.join()
        if self.message_thread:
            self.message_thread.join()
        if self.client:
            self.client.close()
        self.set_worlds_list([{}, []])
        self.stacked_layout.setCurrentIndex(0)
        self.connecting_label.setText("Lost Connection")
        self.close_threads.clear()
        self.log_box.clear()
        self.set_status(["pinging", "", ""])
    
    def switch_to_download_page(self):
        self.downloads_message.setText(f"Are you sure you want to download recommended client mods for '{self.selected_dropdown_text}'?")
        self.download_button.show()
        self.cancel_download_button.show()
        self.finish_button.hide()
        self.open_downloads_button.hide()
        self.stacked_layout.setCurrentIndex(3)
    
    def switch_to_mode_page(self):
        self.stacked_layout.setCurrentIndex(4)
    
    def switch_to_update_page(self):
        if self.stacked_layout.currentIndex() != 5:
            self.last_page_index = self.stacked_layout.currentIndex()
        self.stacked_layout.setCurrentIndex(5)

    def check_messages(self):
        while not self.close_threads.is_set():
            while not self.log_queue.empty():
                message = self.log_queue.get()
                if message == "CLOSING":
                    continue

                self.update_log_signal.emit(message)

    def first_connect(self):
        self.get_worlds_list()
        self.get_status()

        version_name, tag_version, link = latest_app_info()
        if version_name:
            if tag_version != VERSION:
                self.log_queue.put(f"<br>{version_name} is available!")
                self.log_queue.put("Click the version number in the corner to update.<br>")

    def get_status(self):
        self.set_status(["pinging",None,None])
        self.send("MANAGER-REQUEST~~>get-status")

    def get_players(self):
        self.send("MANAGER-REQUEST~~>get-players")

    def get_worlds_list(self):
        self.send("MANAGER-REQUEST~~>get-worlds-list")
    
    def start_server(self, world):
        self.send(f"MANAGER-REQUEST~~>start-server,{world}")
        self.start_button.setEnabled(False)
    
    def stop_server(self):
        self.send("MANAGER-REQUEST~~>stop-server")
        self.stop_button.setEnabled(False)
    
    def check_available_mods(self, world):
        self.send(f"MANAGER-REQUEST~~>check-mods,{world}")
    
    def set_status(self, info):
        status, version, world = info
        if version and version.startswith("vanilla "):
            version = version.removeprefix("vanilla ")
        if status == "online":
            self.status = "online"
            self.server_status_label.hide()
            self.server_status_offline_label.hide()
            self.server_status_online_label.show()
            self.version_label.setText(f"Version: {version} {'Fabric' * self.worlds[world]['fabric']}")
            self.world_label.setText(f"World: {world}")
            self.refresh_button.setEnabled(True)
            self.get_players()
            self.refresh_status_button.setEnabled(True)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
        elif status == "offline":
            self.status = "offline"
            self.server_status_label.hide()
            self.server_status_offline_label.show()
            self.server_status_online_label.hide()
            self.version_label.setText("")
            self.world_label.setText("")
            self.refresh_button.setEnabled(False)
            self.players_info_box.clear()
            self.refresh_status_button.setEnabled(True)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
        elif status == "pinging":
            self.status = "pinging"
            self.server_status_label.show()
            self.server_status_offline_label.hide()
            self.server_status_online_label.hide()
            self.version_label.setText("")
            self.world_label.setText("")
            self.refresh_button.setEnabled(False)
            self.players_info_box.clear()
            self.refresh_status_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(False)

    def set_players(self, players):
        self.players_info_box.clear()
        if len(players) == 0:
            self.players_info_box.append("<font color='red'>No players online</font>")
            return
        
        for player in players:
            self.players_info_box.append(f"<font color='purple'>{player}</font>")
    
    def set_worlds_list(self, worlds_data):
        self.worlds.clear()
        self.worlds.update(worlds_data[0])
        prev = self.dropdown.currentText()
        self.dropdown.clear()
        self.dropdown.addItems(worlds_data[1])
        if prev in self.worlds.keys():
            self.dropdown.setCurrentText(prev)
        self.set_current_world_version(self.dropdown.currentText())

    def set_current_world_version(self, world):
        if world:
            self.selected_dropdown_text = world
            self.world_version_label.setText(f'v{self.worlds[world]["version"]} {"Fabric" * self.worlds[world]["fabric"]}')
            if self.worlds[world]["fabric"]:
                self.mods_download_button.show()
                self.mods_download_button.setDisabled(True)
                self.check_available_mods(world)
            else:
                self.mods_download_button.hide()
        else:
            self.world_version_label.setText("")
    
    def download_mods(self):
        downloads_folder = Path.home() / "Downloads"
        self.mods_download_path = Path(pick_folder(self, downloads_folder, "Select Download Location"))
        if self.mods_download_path is None:
            return
        
        if self.dropdown.currentText():
            self.download_button.hide()
            self.cancel_download_button.hide()
            self.download_progress.show()
            self.send(f"MANAGER-REQUEST~~>download-mods,{self.dropdown.currentText()}")
    
    def download_complete(self):
        self.downloads_message.setText("Download complete!")
        self.finish_button.show()
        self.open_downloads_button.show()
        self.download_progress.hide()
    
    def set_progress_value(self, value):
        self.download_progress.setValue(value)
    
    def set_progress_range(self, minimum, maximum):
        self.download_progress.setRange(minimum, maximum)
    
    def set_download_message_text(self, msg):
        self.downloads_message.setText(msg)
    
    def enable_mods_button(self):
        self.mods_download_button.setEnabled(True)
    
    def update_log(self, message):
        self.log_box.append(message)
        scrollbar = self.log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def open_folder_explorer(self, folder_path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))
    
    def open_host_app(self):
        curr_script = os.path.abspath(sys.argv[0])
        if TESTING:
            parsed = curr_script.split("\\")
            parsed.pop()
            parsed.append("manager_host.py")
            curr_script = "\\".join(parsed)
        if not os.path.isfile(curr_script):
            self.connecting_label.setText("Unable to find the host program.")
            self.display_delay_messages()
            self.show_connect_page()
        else:
            subprocess.Popen(
                [sys.executable, curr_script, "--host"],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True
            )
            self.close()
    
    def closeEvent(self, event):
        try:
            self.send("CLOSING")
            self.close_connection_thread()
        except:
            pass
        self.close_threads.set()
        if self.receive_thread:
            self.receive_thread.join()
        if self.message_thread:
            self.message_thread.join()
        if self.client:
            self.client.close()
        event.accept()

if __name__ == "__main__":
    if "--host" in sys.argv:
        manager_host.main()
    elif "--supervisor" in sys.argv:
        manager_host.main(create_supervisor=True)
    else:
        app = QApplication(sys.argv)
        server_manager_app = ServerManagerApp()

        server_manager_app.show()
        sys.exit(app.exec())