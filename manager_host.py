import socket
import threading
import os
import pyautogui as pag
import pygetwindow as pgw
import ctypes
import time
import json
import sys
import queue
import subprocess
import glob
import shutil
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QStackedLayout, QGridLayout, QWidget, QTextBrowser, QCheckBox, QFrame, QSizePolicy, QPlainTextEdit, QListWidget, QMenu, QListWidgetItem
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter, QPaintEvent, QDesktopServices, QColor
from PyQt6.QtCore import Qt, QRect, pyqtSignal, QTimer, pyqtSlot, QUrl

import queries
import file_funcs
import websock_mgmt
import html

TESTING = False
VERSION = "v2.4.3"

if TESTING:
    STYLE_PATH = "Styles"
    IMAGE_PATH = "Images"
else:
    STYLE_PATH = sys._MEIPASS
    IMAGE_PATH = sys._MEIPASS

def check_java_installed():
    """Checks if Java is installed and returns the version."""
    try:
        # Run 'java -version' and capture output
        result = subprocess.run(["java", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output = result.stderr if result.stderr else result.stdout  # Java version is printed to stderr

        # Extract Java version
        segments = output.split('"')
        if len(segments) == 3:
            ver_sub = segments[1]
            if ver_sub.startswith("1."):
                # Oracle formatting "1.x.__"
                return int(ver_sub.split(".")[1])
            else:
                # Latest formatting "xx.___"
                return int(ver_sub.split(".")[0])
        else:
            return False
    
    except FileNotFoundError:
        return False

class BackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.background_image = QPixmap(os.path.normpath(os.path.join(IMAGE_PATH, "block_background.png")))

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.drawPixmap(QRect(0, 0, self.width(), self.height()), self.background_image)

class HoverButton(QPushButton):
    changeHovering = pyqtSignal(bool)
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setMouseTracking(True)  # Enable mouse tracking to receive enter and leave events

    def enterEvent(self, event):
        # This is triggered when the mouse enters the button
        self.changeHovering.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        # This is triggered when the mouse leaves the button
        self.changeHovering.emit(False)
        super().leaveEvent(event)

class ServerManagerApp(QMainWindow):
    get_status_signal = pyqtSignal()
    set_status_signal = pyqtSignal(list)
    update_players_list_signal = pyqtSignal(list)
    start_server_signal = pyqtSignal(list) # [client, world_name]
    stop_server_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()

        # Default IP
        self.ip_placeholder_msg = "Hosting IP"
        self.saved_ip = ""
        self.host_ip = ""
        self.port = 5555
        self.server_port = "25565"
        self.server = None # server socket
        self.java_version = ""
        self.receive_thread = threading.Thread(target=self.receive)
        self.message_timer = QTimer(self)
        self.message_timer.timeout.connect(self.check_messages)
        self.ips = {}
        self.clients = {}
        self.status = ""
        self.server_path = ""
        self.world = ""
        self.world_version = ""
        self.worlds = {}
        self.world_order = []
        self.universal_settings = {}
        self.curr_players = []
        self.log_queue = queue.Queue()
        self.result_queue = queue.Queue()

        self.no_clients = True
        self.stop_threads = threading.Event()
        self.file_lock = threading.Lock()

        # Signals
        self.get_status_signal.connect(self.get_status)
        self.set_status_signal.connect(self.set_status)
        self.update_players_list_signal.connect(self.update_players_list)
        self.start_server_signal.connect(self.client_start_server)
        self.stop_server_signal.connect(self.client_stop_server)

        # Minecraft Server Management Protocol Listener
        self.bus = None
        self.bus_shutdown_complete = threading.Event()
        self.bus_shutdown_complete.set()

        self.init_ui()

        # Check if Java is installed before anything else
        version = check_java_installed()
        if not version:
            self.show_error_page(
                "Java Runtime Not Found",
                "Minecraft servers require a Java Runtime Environment (JRE) to run.<br>"
                "Download it from:<br>"
                "Adoptium Temurin JRE (www.adoptium.net/temurin/releases/)<br><br>"
                "The latest versions of Minecraft will require the latest version of Java.",
                eula=False
            )

            return
        else:
            self.java_version = version
        
        latest_mc_version = queries.get_latest_release(self.log_queue)
        required_java_version = queries.get_required_java_version(latest_mc_version, self.log_queue)
        if required_java_version:
            if required_java_version > self.java_version:
                self.show_error_page("Your Java version is out of date!",
                                    f"Minecraft version {latest_mc_version} requires Java version {required_java_version}.<br>"
                                    f"You are currently running version {self.java_version}.<br>"
                                    "Download an updated version from www.adoptium.net/temurin/releases/",
                                    eula=False)
                
                return


        self.host_ip, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings = file_funcs.load_settings(self.log_queue, self.file_lock)
        self.saved_ip = self.host_ip
        self.clear_log_queue()
        
        if self.server_path == "" or not os.path.isdir(self.server_path):
            self.message_timer.stop()
            self.show_server_entry_page()
        else:
            eula_result = self.check_eula()
            if eula_result == False:
                self.show_error_page("By accepting, you are indicating your agreement<br> to Minecraft's EULA.",
                                    "(https://aka.ms/MinecraftEULA)", eula=True)
            elif eula_result:
                self.start_manager_server()
            elif eula_result is None:
                return

    def init_ui(self):
        # Central widget to hold everything
        central_widget = BackgroundWidget(self)
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout(central_widget)

        # Stacked layout to manage pages
        self.stacked_layout = QStackedLayout()

        # Page 1: Server Manager
        server_manager_layout = QHBoxLayout()

        # Left column
        left_column_layout = QVBoxLayout()
        temp_box = QHBoxLayout()
        self.change_ip_button = QPushButton("Change IP")
        self.change_ip_button.setObjectName("smallYellowButton")
        self.change_ip_button.clicked.connect(self.prepare_ip_page)
        self.host_ip_label = QLabel(f"IP: {self.host_ip}")
        self.current_players_label = QLabel("Current Players")
        self.current_players_label.setFont(QFont(self.current_players_label.font().family(), int(self.current_players_label.font().pointSize() * 1.5)))
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.get_players)
        self.players_info_box = QListWidget()
        self.players_info_box.setUniformItemSizes(True)
        self.players_info_box.itemClicked.connect(
            lambda it: self.open_player_context_menu(self.players_info_box.visualItemRect(it).center())
        )

        temp_box.addWidget(self.change_ip_button)
        temp_box.addWidget(self.host_ip_label)
        left_column_layout.addLayout(temp_box)
        left_column_layout.addWidget(self.current_players_label)
        left_column_layout.addWidget(self.refresh_button)
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

        status_layout = QGridLayout()
        self.server_status_label = QLabel("Status: Pinging...")  # Replace with dynamic status
        self.server_status_label.setFont(QFont("Verdana", int(self.server_status_label.font().pointSize() * 1.5)))
        status_layout.addWidget(self.server_status_label, 0, 0)
        self.server_status_label.hide()
        self.server_status_online_label = QLabel("Status: Online")  # Replace with dynamic status
        self.server_status_online_label.setObjectName("statusOnline")
        self.server_status_online_label.setFont(QFont("Verdana", int(self.server_status_online_label.font().pointSize() * 1.5)))
        status_layout.addWidget(self.server_status_online_label, 0, 0)
        self.server_status_online_label.hide()
        self.server_status_offline_label = QLabel("Status: Offline")  # Replace with dynamic status
        self.server_status_offline_label.setObjectName("statusOffline")
        self.server_status_offline_label.setFont(QFont("Verdana", int(self.server_status_offline_label.font().pointSize() * 1.5)))
        status_layout.addWidget(self.server_status_offline_label, 0, 0)
        self.server_status_offline_label.show()
        status_layout.setColumnStretch(1, 1)
        
        self.version_label = QLabel("Server Version: ")
        self.version_label.setObjectName("world_details")
        self.version_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.world_label = QLabel("Server World: ")
        self.world_label.setObjectName("world_details")
        self.world_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.refresh_status_button = QPushButton("Refresh Status")
        self.refresh_status_button.clicked.connect(self.get_status)
        self.log_box = QTextBrowser()
        self.message_entry = QLineEdit()
        self.message_entry.setPlaceholderText("Send Message")
        self.message_entry.returnPressed.connect(self.message_entered)

        center_column_layout.addWidget(self.title_label)
        center_column_layout.addLayout(status_layout)
        center_column_layout.addWidget(self.version_label)
        center_column_layout.addWidget(self.world_label)
        center_column_layout.addWidget(self.refresh_status_button)
        center_column_layout.addWidget(self.log_box)
        center_column_layout.addWidget(self.message_entry)

        # Right column
        right_column_layout = QVBoxLayout()
        self.functions_label = QLabel("Functions")
        self.functions_label.setFont(QFont(self.functions_label.font().family(), int(self.functions_label.font().pointSize() * 1.5)))
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(lambda: self.start_server(self.dropdown.currentText()))
        self.world_version_label = QLabel("")
        self.world_version_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.world_version_label.setObjectName("world_version")
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setObjectName("redButton")

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Raised)

        self.world_properties_button = QPushButton("Properties")
        self.world_properties_button.clicked.connect(self.show_edit_properties_page)
        self.world_mods_button = QPushButton("Mods")
        self.world_mods_button.clicked.connect(self.show_mods_page)
        self.modrinth_button = QPushButton("Modrinth")
        self.modrinth_button.setObjectName("blueButton")
        self.modrinth_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.modrinth.com")))

        separator2 = QFrame(self)
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setFrameShadow(QFrame.Shadow.Raised)

        self.world_manager_button = QPushButton("World Manager")
        self.world_manager_button.clicked.connect(self.show_world_manager_page)
        self.commands_button = QPushButton("Admin Settings")
        self.commands_button.clicked.connect(self.show_commands_page)
        self.open_folder_button = QPushButton("Server Folder")
        self.open_folder_button.clicked.connect(self.open_server_folder)
    

        functions_layout = QGridLayout()
        functions_layout.addWidget(self.functions_label, 0, 0, 1, 2)  # Label spanning two columns

        dropdown_layout = QVBoxLayout()
        box = QHBoxLayout()
        self.dropdown = QComboBox()
        self.dropdown.currentTextChanged.connect(self.set_selected_world_version)
        box.addWidget(self.dropdown, 1)
        dropdown_layout.addLayout(box)  # Dropdown for world options
        dropdown_layout.addWidget(self.world_version_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        functions_layout.addLayout(dropdown_layout, 1, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        functions_layout.addWidget(self.start_button, 2, 0, 1, 1)
        functions_layout.addWidget(self.stop_button, 2, 1, 1, 1)
        functions_layout.addWidget(separator, 3, 0, 1, 2)
        functions_layout.addWidget(self.world_properties_button, 4, 0, 1, 1)
        functions_layout.addWidget(self.world_mods_button, 4, 1, 1, 1)
        functions_layout.addWidget(self.modrinth_button, 5, 0, 1, 2)
        functions_layout.addWidget(separator2, 6, 0, 1, 2)
        functions_layout.addWidget(self.world_manager_button, 7, 0, 1, 2)
        functions_layout.addWidget(self.commands_button, 8, 0, 1, 2)
        functions_layout.addWidget(self.open_folder_button, 9, 0, 1, 2)
        functions_layout.setColumnStretch(1, 1)  # Stretch the second column

        right_column_layout.addLayout(functions_layout)
        right_column_layout.addStretch(1)  # Add empty space at the bottom
        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_column_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        server_manager_layout.addLayout(left_column_layout, 2)  # Make the left column twice as wide
        server_manager_layout.addLayout(center_column_layout, 5)  # Keep the center column as it is
        server_manager_layout.addLayout(right_column_layout, 2)  # Make the right column twice as wide

        # Page 2: Startup error
        error_layout = QGridLayout()
        center_column_layout = QVBoxLayout()

        top_box = QVBoxLayout()

        top_box.addStretch(1)
        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self.error_label.setObjectName("error")
        top_box.addWidget(self.error_label)
        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.info_label.setObjectName("details")
        top_box.addWidget(self.info_label)

        bot_box = QVBoxLayout()
        bot_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link_row = QHBoxLayout()
        buttons_row = QHBoxLayout()

        link_row.addStretch(1)
        self.eula_link_button = QPushButton("Open EULA Link")
        self.eula_link_button.setObjectName("smallBlueButton")
        self.eula_link_button.clicked.connect(self.open_eula_link)
        link_row.addWidget(self.eula_link_button)
        link_row.addStretch(1)
        bot_box.addLayout(link_row)
        bot_box.addStretch(1)

        buttons_row.addStretch(1)
        self.eula_accept_button = QPushButton("Accept")
        self.eula_accept_button.clicked.connect(self.accepted_eula)
        buttons_row.addWidget(self.eula_accept_button)
        buttons_row.addStretch(1)
        self.eula_decline_button = QPushButton("Decline")
        self.eula_decline_button.setObjectName("redButton")
        self.eula_decline_button.clicked.connect(self.declined_eula)
        buttons_row.addWidget(self.eula_decline_button)
        buttons_row.addStretch(1)
        bot_box.addLayout(buttons_row)
        bot_box.addStretch(1)

        center_column_layout.addLayout(top_box)
        center_column_layout.addLayout(bot_box)

        right_column_layout = QVBoxLayout()
        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_column_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        error_layout.setColumnStretch(0, 1)
        error_layout.addLayout(center_column_layout, 0, 1, 0, 8)
        error_layout.addLayout(right_column_layout, 0, 9)
        error_layout.setColumnStretch(9, 1)

        server_manager_page = QWidget()
        server_manager_page.setLayout(server_manager_layout)

        error_page = QWidget()
        error_page.setLayout(error_layout)

        # Page 3: Server Path Prompt
        server_path_layout = QGridLayout()
        center_column_layout = QVBoxLayout()
        input_layout = QVBoxLayout()
        input_layout.setAlignment(Qt.AlignmentFlag.AlignBottom)

        server_folder_label = QLabel("Server Folder Path:")
        server_folder_label.setObjectName("mediumText")
        server_folder_label.setFont(QFont(server_folder_label.font().family(), int(server_folder_label.font().pointSize() * 1.5)))
        server_folder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        side_by_side = QHBoxLayout()
        side_by_side.setContentsMargins(0, 0, 0, 0)

        self.server_folder_path_entry = QLineEdit("")
        self.server_folder_path_entry.setObjectName("serverEntry")
        self.server_folder_path_entry.setMinimumWidth(self.width() // 2)
        self.server_folder_path_entry.setMaximumWidth(self.width() // 2)
        self.server_folder_path_entry.setFont(QFont(self.server_folder_path_entry.font().family(), int(self.server_folder_path_entry.font().pointSize() * 1.5)))
        self.server_folder_path_entry.setPlaceholderText("Server Path")
        self.server_folder_path_entry.textChanged.connect(self.check_server_path)
        self.browse_button = QPushButton("Browse")
        self.browse_button.setObjectName("browseButton")
        self.browse_button.clicked.connect(lambda: self.server_folder_path_entry.setText(file_funcs.pick_folder(self) or
                                                                                         self.server_folder_path_entry.text()))

        side_by_side.addWidget(self.server_folder_path_entry, 8)
        side_by_side.addWidget(self.browse_button, 2)

        input_layout.addWidget(server_folder_label)
        input_layout.addLayout(side_by_side)

        self.server_path_hover_label = QLabel("")
        self.server_path_hover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.server_path_hover_label.setObjectName("smallText")

        options_layout = QHBoxLayout()
        options_layout.setAlignment(Qt.AlignmentFlag.AlignBottom)
        self.create_server_button = HoverButton("Create New")
        self.create_server_button.setEnabled(False)
        self.create_server_button.changeHovering.connect(lambda hovering: self.server_path_hover_label.setText(
            "Automatically download and set up a server in the specified empty folder." if hovering else ""
        ))
        self.create_server_button.clicked.connect(self.create_server_folder)
        self.existing_server_button = HoverButton("Use Existing")
        self.existing_server_button.setObjectName("yellowButton")
        self.existing_server_button.setEnabled(False)
        self.existing_server_button.changeHovering.connect(lambda hovering: self.server_path_hover_label.setText(
            "Use the specified path of a previously created server folder." if hovering else ""
        ))
        self.existing_server_button.clicked.connect(self.set_server_path)
        options_layout.addWidget(self.create_server_button)
        options_layout.addWidget(self.existing_server_button)

        center_column_layout.addLayout(input_layout)
        center_column_layout.addLayout(options_layout)

        center_column_layout.addWidget(self.server_path_hover_label)

        right_column_layout = QVBoxLayout()

        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_column_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        server_path_layout.setColumnStretch(0, 1)
        server_path_layout.addLayout(center_column_layout, 0, 1, 0, 8, Qt.AlignmentFlag.AlignCenter)
        server_path_layout.addLayout(right_column_layout, 0, 9)
        server_path_layout.setColumnStretch(9, 1)

        server_path_page = QWidget()
        server_path_page.setLayout(server_path_layout)

        # Page 4: IP Prompt Page
        connect_layout = QGridLayout()
        center_column_layout = QVBoxLayout()
        input_layout = QVBoxLayout()
        input_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        host_ip_label = QLabel("Hosting IP:")
        host_ip_label.setObjectName("mediumText")
        host_ip_label.setFont(QFont(host_ip_label.font().family(), int(host_ip_label.font().pointSize() * 1.5)))
        host_ip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.hosting_ip_entry = QLineEdit("")  # Set default IP
        self.hosting_ip_entry.setMinimumWidth(self.width() // 2)
        self.hosting_ip_entry.setMaximumWidth(self.width() // 2)
        self.hosting_ip_entry.setFont(QFont(self.hosting_ip_entry.font().family(), int(self.hosting_ip_entry.font().pointSize() * 1.5)))
        self.hosting_ip_entry.setPlaceholderText(self.host_ip or self.ip_placeholder_msg)
        self.default_ip_check = QCheckBox("Set as default")
        self.default_ip_check.setObjectName("checkbox")
        self.default_ip_check.setChecked(False)
        self.host_button = QPushButton("Host")
        self.host_button.clicked.connect(self.set_ip)
        self.hosting_ip_entry.returnPressed.connect(self.set_ip)

        input_layout.addWidget(host_ip_label)
        input_layout.addWidget(self.hosting_ip_entry)
        input_layout.addWidget(self.host_button)
        input_layout.addWidget(self.default_ip_check)

        # Shown when attempting to host
        message_layout = QVBoxLayout()
        message_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.connecting_label = QLabel("Connecting")
        self.connecting_label.setObjectName("connectingText")
        self.connecting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_layout.addWidget(self.connecting_label)
        self.connecting_label.setText("")
        self.connecting_label.setFont(QFont("Tahoma", self.connecting_label.font().pointSize()))

        self.connection_delabel = QLabel("Is Hamachi Offline?")
        self.connection_delabel.setObjectName("messageText")
        self.connection_delabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connection_delabel.setText("")
        message_layout.addWidget(self.connection_delabel)

        center_column_layout.addLayout(input_layout)
        center_column_layout.addLayout(message_layout)

        right_column_layout = QVBoxLayout()

        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_column_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        connect_layout.setColumnStretch(0, 1)
        connect_layout.addLayout(center_column_layout, 0, 1, 0, 8, Qt.AlignmentFlag.AlignCenter)
        connect_layout.addLayout(right_column_layout, 0, 9)
        connect_layout.setColumnStretch(9, 1)

        connect_page = QWidget()
        connect_page.setLayout(connect_layout)

        # Page 5: Worlds page
        world_layout = QGridLayout()

        center_layout = QVBoxLayout()
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_box = QVBoxLayout()
        top_box.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        bot_box = QHBoxLayout()
        bot_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        add_world_button = QPushButton("Add World")
        add_world_button.clicked.connect(self.show_new_world_type_page)
        update_world_button = QPushButton("Update World")
        update_world_button.clicked.connect(lambda: self.add_existing_world(update=True))
        remove_world_button = QPushButton("Remove World")
        remove_world_button.clicked.connect(self.prepare_remove_world_page)
        remove_world_button.setObjectName("redButton")
        backup_button = QPushButton("Save Backup")
        backup_button.clicked.connect(self.backup_world)
        backup_button.setObjectName("yellowButton")
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("smallRedButton")
        cancel_button.clicked.connect(self.show_main_page)

        top_box.addWidget(add_world_button)
        top_box.addWidget(update_world_button)
        top_box.addWidget(remove_world_button)
        top_box.addWidget(backup_button)
        bot_box.addWidget(cancel_button)

        center_layout.addLayout(top_box)
        center_layout.addLayout(bot_box)

        right_layout = QVBoxLayout()

        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        world_layout.setColumnStretch(0, 1)
        world_layout.addLayout(center_layout, 0, 1, 0, 8, Qt.AlignmentFlag.AlignCenter)
        world_layout.addLayout(right_layout, 0, 9)
        world_layout.setColumnStretch(9, 1)

        worlds_page = QWidget()
        worlds_page.setLayout(world_layout)

        # Page 6: Add world page
        add_world_layout = QGridLayout()

        center_layout = QVBoxLayout()
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_box = QVBoxLayout()
        top_box.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        bot_box = QHBoxLayout()
        bot_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.add_world_label = QLabel("")
        self.add_world_label.setObjectName("largeText")
        self.new_world_name_edit = QLineEdit("")
        self.new_world_name_edit.setObjectName("lineEdit")
        self.new_world_name_edit.setPlaceholderText("World Name")
        self.new_world_name_edit.hide()
        self.new_world_name_edit.setMaxLength(32)
        self.new_world_seed_edit = QLineEdit("")
        self.new_world_seed_edit.setObjectName("lineEdit")
        self.new_world_seed_edit.setPlaceholderText("(Optional) World Seed")
        self.new_world_seed_edit.hide()
        self.mc_version_label = QLabel("Version: ")
        self.mc_version_label.setObjectName("details")
        self.mc_version_dropdown = QComboBox()
        versions = queries.get_mc_versions(include_snapshots=False)
        if versions:
            self.mc_version_dropdown.addItems(versions)
        self.mc_version_dropdown.currentTextChanged.connect(self.version_dropdown_changed)
        self.include_snapshots_check = QCheckBox("Include Snapshots")
        self.include_snapshots_check.setObjectName("checkbox")
        self.include_snapshots_check.checkStateChanged.connect(self.change_snapshot_state)

        self.gamemode_label = QLabel("Gamemode: ")
        self.gamemode_label.setObjectName("details")
        self.gamemode_dropdown = QComboBox()
        modes = ["Survival", "Creative", "Hardcore"]
        self.gamemode_dropdown.addItems(modes)
        self.gamemode_dropdown.currentTextChanged.connect(self.check_for_hardcore)

        self.diff_label = QLabel("Difficulty: ")
        self.diff_label.setObjectName("details")
        self.difficulty_dropdown = QComboBox()
        diffs = ["Peaceful", "Easy", "Normal", "Hard"]
        self.difficulty_dropdown.addItems(diffs)
        self.difficulty_dropdown.setCurrentText("Normal")

        self.is_fabric_check = QCheckBox("Fabric")
        self.is_fabric_check.setObjectName("checkbox")
        self.is_fabric_check.hide()
        self.fabric_label = QLabel("Fabric Mods")
        self.fabric_label.setObjectName("details")
        self.fabric_dropdown = QComboBox()
        self.fabric_dropdown.addItems(["Enabled", "Disabled"])
        self.fabric_dropdown.currentTextChanged.connect(lambda: self.is_fabric_check.setChecked(self.fabric_dropdown.currentText() == "Enabled"))
        self.fabric_dropdown.setCurrentText("Disabled")
        self.is_fabric_check.setChecked(False)

        self.level_type_label = QLabel("World Type")
        self.level_type_label.setObjectName("details")
        self.level_type_dropdown = QComboBox()
        self.level_type_dropdown.addItems(["Normal", "Flat", "Large biomes", "Amplified"])

        self.add_existing_world_button = QPushButton("Add World")
        self.add_existing_world_button.hide()
        self.add_existing_world_button.clicked.connect(self.confirm_add_world)
        self.update_existing_world_button = QPushButton("Update World")
        self.update_existing_world_button.hide()
        self.update_existing_world_button.clicked.connect(lambda: self.confirm_add_world(update=True))
        self.create_new_world_button = QPushButton("Create World")
        self.create_new_world_button.hide()
        self.create_new_world_button.clicked.connect(self.confirm_create_world)
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("redButton")
        cancel_button.clicked.connect(self.show_new_world_type_page)
        self.add_world_error = QLabel("")
        self.add_world_error.setObjectName("messageText")

        top_box.addWidget(self.add_world_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        top_box.addWidget(self.new_world_name_edit)
        top_box.addWidget(self.new_world_seed_edit)
        temp = QHBoxLayout()
        left = QHBoxLayout()
        left.addWidget(self.mc_version_label, 1, alignment=Qt.AlignmentFlag.AlignRight)
        right = QHBoxLayout()
        self.mc_version_dropdown.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.mc_version_dropdown.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        right.addWidget(self.mc_version_dropdown, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        temp.addLayout(left)
        temp.addLayout(right)
        top_box.addLayout(temp)
        top_box.addWidget(self.include_snapshots_check, alignment=Qt.AlignmentFlag.AlignHCenter)
        temp = QHBoxLayout()
        temp.addWidget(self.is_fabric_check, 1, Qt.AlignmentFlag.AlignCenter)
        top_box.addLayout(temp)
        temp = QHBoxLayout()
        left = QHBoxLayout()
        left.addWidget(self.gamemode_label, 1, alignment=Qt.AlignmentFlag.AlignRight)
        right = QHBoxLayout()
        self.gamemode_dropdown.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.gamemode_dropdown.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        right.addWidget(self.gamemode_dropdown, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        temp.addLayout(left)
        temp.addLayout(right)
        top_box.addLayout(temp)
        temp = QHBoxLayout()
        left = QHBoxLayout()
        left.addWidget(self.diff_label, 1, alignment=Qt.AlignmentFlag.AlignRight)
        right = QHBoxLayout()
        self.difficulty_dropdown.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.difficulty_dropdown.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        right.addWidget(self.difficulty_dropdown, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        temp.addLayout(left)
        temp.addLayout(right)
        top_box.addLayout(temp)
        temp = QHBoxLayout()
        left = QHBoxLayout()
        left.addWidget(self.fabric_label, 1, alignment=Qt.AlignmentFlag.AlignRight)
        right = QHBoxLayout()
        self.fabric_dropdown.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.fabric_dropdown.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        right.addWidget(self.fabric_dropdown, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        temp.addLayout(left)
        temp.addLayout(right)
        top_box.addLayout(temp)
        temp = QHBoxLayout()
        left = QHBoxLayout()
        left.addWidget(self.level_type_label, 1, alignment=Qt.AlignmentFlag.AlignRight)
        right = QHBoxLayout()
        self.level_type_dropdown.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.level_type_dropdown.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        right.addWidget(self.level_type_dropdown, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        temp.addLayout(left)
        temp.addLayout(right)
        top_box.addLayout(temp)
        bot_box.addWidget(self.add_existing_world_button)
        bot_box.addWidget(self.update_existing_world_button)
        bot_box.addWidget(self.create_new_world_button)
        bot_box.addWidget(cancel_button)

        center_layout.addLayout(top_box)
        center_layout.addLayout(bot_box)
        center_layout.addWidget(self.add_world_error)
        center_layout.setStretch(0, 1)
        center_layout.setStretch(2, 1)

        right_layout = QVBoxLayout()

        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        add_world_layout.setColumnStretch(0, 1)
        add_world_layout.addLayout(center_layout, 0, 1, 0, 8, Qt.AlignmentFlag.AlignCenter)
        add_world_layout.addLayout(right_layout, 0, 9)
        add_world_layout.setColumnStretch(9, 1)

        add_world_page = QWidget()
        add_world_page.setLayout(add_world_layout)

        # Page 7: Remove World Page

        remove_world_layout = QGridLayout()

        center_layout = QVBoxLayout()
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        remove_world_label = QLabel("Remove World")
        remove_world_label.setObjectName("largeText")
        temp_box1 = QHBoxLayout()
        world_label = QLabel("World Name: ")
        world_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        world_label.setObjectName("details")
        self.worlds_dropdown = QComboBox()
        self.delete_world_checkbox = QCheckBox("Delete world folder")
        self.delete_world_checkbox.setObjectName("cautionCheckbox")
        self.delete_world_checkbox.setChecked(False)
        temp_box2 = QHBoxLayout()
        remove_world_cancel_button = QPushButton("Cancel")
        remove_world_cancel_button.setObjectName("redButton")
        remove_world_cancel_button.clicked.connect(self.show_world_manager_page)
        remove_world_confirm_button = QPushButton("Remove")
        remove_world_confirm_button.clicked.connect(self.remove_world)

        temp_box1.addWidget(world_label)
        temp_box1.addWidget(self.worlds_dropdown, 1)

        temp_box2.addWidget(remove_world_confirm_button)
        temp_box2.addWidget(remove_world_cancel_button)

        center_layout.addWidget(remove_world_label)
        center_layout.addLayout(temp_box1)
        center_layout.addWidget(self.delete_world_checkbox)
        center_layout.addLayout(temp_box2)

        right_layout = QVBoxLayout()

        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        remove_world_layout.setColumnStretch(0, 1)
        remove_world_layout.addLayout(center_layout, 0, 1, 0, 8, Qt.AlignmentFlag.AlignCenter)
        remove_world_layout.addLayout(right_layout, 0, 9)
        remove_world_layout.setColumnStretch(9, 1)

        remove_world_page = QWidget()
        remove_world_page.setLayout(remove_world_layout)

        # Page 8: Edit Properties

        center_layout = QVBoxLayout()
        center_layout.setContentsMargins(12, 12, 12, 12)
        center_layout.setSpacing(8)

        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.title_label = QLabel("Example Properties")
        self.title_label.setObjectName("largeText")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.edit_box = QPlainTextEdit("This is placeholder.")
        font = self.edit_box.font()
        font.setPointSize(11)
        self.edit_box.setFont(font)
        self.edit_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        buttons_box = QHBoxLayout()
        self.save_button = QPushButton()
        self.save_button.setText("Save")
        self.save_button.clicked.connect(self.save_properties_edit)
        self.cancel_button = QPushButton()
        self.cancel_button.setText("Cancel")
        self.cancel_button.setObjectName("redButton")
        self.cancel_button.clicked.connect(lambda: self.show_main_page(True))

        buttons_box.addStretch(1)
        buttons_box.addWidget(self.save_button)
        buttons_box.addWidget(self.cancel_button)

        center_layout.addWidget(self.title_label)
        center_layout.addWidget(self.edit_box, 1)
        center_layout.addLayout(buttons_box)

        right_layout = QVBoxLayout()

        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        edit_properties_layout = QGridLayout()
        edit_properties_layout.setRowStretch(0, 1)
        edit_properties_layout.setColumnStretch(0, 1)
        edit_properties_layout.addLayout(center_layout, 0, 1, 1, 8)
        edit_properties_layout.setColumnStretch(1, 10)
        edit_properties_layout.addLayout(right_layout, 0, 9)
        edit_properties_layout.setColumnStretch(9, 1)

        edit_properties_page = QWidget()
        edit_properties_page.setLayout(edit_properties_layout)

        # Page 9: Add world type page

        page_layout = QHBoxLayout()

        center_layout = QVBoxLayout()
        center_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        create_new_button = QPushButton("Create New World")
        create_new_button.clicked.connect(self.add_new_world)
        select_existing_button = QPushButton("Add Existing World")
        select_existing_button.clicked.connect(lambda: self.add_existing_world(update=False))
        cancel_add_world_button = QPushButton("Back")
        cancel_add_world_button.setObjectName("smallRedButton")
        cancel_add_world_button.clicked.connect(self.show_world_manager_page)

        center_layout.addWidget(create_new_button)
        center_layout.addWidget(select_existing_button)
        back_layout = QHBoxLayout()
        back_layout.addStretch(1)
        back_layout.addWidget(cancel_add_world_button)
        back_layout.addStretch(1)
        center_layout.addLayout(back_layout)

        right_layout = QVBoxLayout()
        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        page_layout.addStretch(1)
        page_layout.addLayout(center_layout)
        page_layout.addLayout(right_layout)
        page_layout.setStretch(2, 1)

        new_world_type_page = QWidget()
        new_world_type_page.setLayout(page_layout)

        # Page 10: Running Commands

        page_layout = QHBoxLayout()

        center_layout = QVBoxLayout()
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.commands_label = QLabel("Admin Settings")
        self.commands_label.setObjectName("largeText")
        # stretch here
        self.commands_warning_label = QLabel("Any changes will require a<br>server restart to take effect.")
        self.commands_warning_label.setObjectName("details")
        self.commands_warning_label.hide()
        self.whitelist_toggle_label = QLabel("Whitelist: ")
        self.whitelist_toggle_label.setObjectName("optionText")
        self.whitelist_toggle_button = QPushButton("Disabled")
        self.whitelist_toggle_button.setProperty("variant", "red")
        self.whitelist_toggle_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.whitelist_toggle_button.adjustSize()
        self.whitelist_toggle_button.clicked.connect(self.toggle_whitelist)
        self.whitelist_add_label = QLabel("Add to whitelist:")
        self.whitelist_add_label.setObjectName("optionText")
        self.whitelist_add_button = QPushButton("Add")
        self.whitelist_add_button.setObjectName("smallYellowButton")
        self.whitelist_add_button.clicked.connect(self.add_player_to_whitelist)
        self.whitelist_add_button.setEnabled(False)
        self.whitelist_add_textbox = QLineEdit("")
        self.whitelist_add_textbox.setPlaceholderText("Username")
        self.whitelist_add_textbox.returnPressed.connect(self.add_player_to_whitelist)
        self.whitelist_add_textbox.textChanged.connect(lambda: self.whitelist_add_button.setEnabled(self.whitelist_add_textbox.text() != ""))
        self.view_distance_label = QLabel("View Distance: ")
        self.view_distance_label.setObjectName("optionText")
        self.view_distance_textbox = QLineEdit("")
        self.view_distance_textbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view_distance_textbox.setPlaceholderText("3-32")
        self.view_distance_textbox.setMaxLength(2)
        self.view_distance_textbox.setMaximumWidth(100)
        self.view_distance_textbox.setObjectName("optionText")
        self.view_distance_textbox.editingFinished.connect(lambda: self.view_distance_textbox.setText(
                                                                                str(min(32, max(3, int(self.view_distance_textbox.text()))))))
        self.view_distance_textbox.textChanged.connect(lambda: self.view_distance_textbox.setText(
            self.view_distance_textbox.text() if self.view_distance_textbox.text().isdigit() else self.view_distance_textbox.text()[:-1]
        ))
        self.simulation_distance_label = QLabel("Simulation Distance: ")
        self.simulation_distance_label.setObjectName("optionText")
        self.simulation_distance_textbox = QLineEdit("")
        self.simulation_distance_textbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.simulation_distance_textbox.setPlaceholderText("3-32")
        self.simulation_distance_textbox.setMaxLength(2)
        self.simulation_distance_textbox.setMaximumWidth(100)
        self.simulation_distance_textbox.setObjectName("optionText")
        self.simulation_distance_textbox.editingFinished.connect(lambda: self.simulation_distance_textbox.setText(
                                                                                str(min(32, max(3, int(self.simulation_distance_textbox.text()))))))
        self.simulation_distance_textbox.textChanged.connect(lambda: self.simulation_distance_textbox.setText(
            self.simulation_distance_textbox.text() if self.simulation_distance_textbox.text().isdigit() else self.simulation_distance_textbox.text()[:-1]
        ))
        self.commands_back_button = QPushButton("Save")
        self.commands_back_button.clicked.connect(self.leave_commands_page)

        center_layout.addWidget(self.commands_label, 1, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        hor_box = QHBoxLayout()
        hor_box.addWidget(self.whitelist_toggle_label)
        hor_box.addWidget(self.whitelist_toggle_button)
        center_layout.addLayout(hor_box)
        hor_box = QHBoxLayout()
        hor_box.addWidget(self.whitelist_add_label)
        hor_box.addWidget(self.whitelist_add_textbox, 1)
        hor_box.addWidget(self.whitelist_add_button)
        center_layout.addLayout(hor_box)
        hor_box = QHBoxLayout()
        hor_box.addWidget(self.view_distance_label)
        hor_box.addWidget(self.view_distance_textbox)
        center_layout.addLayout(hor_box)
        hor_box = QHBoxLayout()
        hor_box.addWidget(self.simulation_distance_label)
        hor_box.addWidget(self.simulation_distance_textbox)
        center_layout.addLayout(hor_box)
        center_layout.addWidget(self.commands_warning_label, alignment=Qt.AlignmentFlag.AlignCenter)
        hor_box = QHBoxLayout()
        hor_box.addStretch(1)
        hor_box.addWidget(self.commands_back_button)
        hor_box.addStretch(1)
        center_layout.addLayout(hor_box)
        center_layout.addStretch(1)

        right_layout = QVBoxLayout()
        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_layout.addWidget(version, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        page_layout.addStretch(1)
        page_layout.addLayout(center_layout)
        page_layout.addLayout(right_layout, 1)

        commands_page_layout = QWidget()
        commands_page_layout.setLayout(page_layout)

        # Page 11: Mods page

        page_layout = QHBoxLayout()

        center_layout = QVBoxLayout()
        center_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        server_mods_button = HoverButton("Server Mods")
        server_mods_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        server_mods_button.clicked.connect(self.open_mods_folder)
        server_mods_button.changeHovering.connect(lambda hovering: hover_label.setText("Server-side mods being run by the server" if hovering else ""))
        client_mods_button = HoverButton("Client Mods")
        client_mods_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        client_mods_button.clicked.connect(lambda: self.open_mods_folder(client_folder=True))
        client_mods_button.changeHovering.connect(lambda hovering: hover_label.setText("Mods in this folder can be downloaded by clients to use" if hovering else ""))
        cancel_mods_button = QPushButton("Back")
        cancel_mods_button.setObjectName("smallRedButton")
        cancel_mods_button.clicked.connect(self.show_main_page)

        hover_label = QLabel("")
        hover_label.setObjectName("smallText")
        hover_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        center_layout.addWidget(server_mods_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        center_layout.addWidget(client_mods_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        center_layout.addWidget(hover_label)
        back_layout = QHBoxLayout()
        back_layout.addStretch(1)
        back_layout.addWidget(cancel_mods_button)
        back_layout.addStretch(1)
        center_layout.addLayout(back_layout)

        right_layout = QVBoxLayout()
        version = QLabel(VERSION)
        version.setObjectName("version_num")
        right_layout.addWidget(version, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        page_layout.addStretch(1)
        page_layout.addLayout(center_layout)
        page_layout.addLayout(right_layout)
        page_layout.setStretch(2, 1)

        mods_page = QWidget()
        mods_page.setLayout(page_layout)

        #----------------------------------------------------

        self.stacked_layout.addWidget(server_manager_page)
        self.stacked_layout.addWidget(error_page)
        self.stacked_layout.addWidget(server_path_page)
        self.stacked_layout.addWidget(connect_page)
        self.stacked_layout.addWidget(worlds_page)
        self.stacked_layout.addWidget(add_world_page)
        self.stacked_layout.addWidget(remove_world_page)
        self.stacked_layout.addWidget(edit_properties_page)
        self.stacked_layout.addWidget(new_world_type_page)
        self.stacked_layout.addWidget(commands_page_layout)
        self.stacked_layout.addWidget(mods_page)

        # Set the main layout to the stacked layout
        main_layout.addLayout(self.stacked_layout)

        # Set window title and initial size
        self.setWindowTitle("Server Manager")

        # Set the window icon
        icon = QIcon(self.path(IMAGE_PATH, "app_icon.png"))
        self.setWindowIcon(icon)

        # Apply styles for a colorful appearance
        with open(self.path(STYLE_PATH, "manager_host_style.css"), 'r') as stylesheet:
            style_str = stylesheet.read()
        
        self.setStyleSheet(style_str)
    
    def path(self, *args):
        return os.path.normpath(os.path.join(*args))
    
    def create_bus(self, api_version):
        self.bus = websock_mgmt.MgmtBus(api_version)
        self.bus.log.connect(self.log_queue.put)
        self.bus.recvd_result.connect(self.result_queue.put)
        self.bus.connected.connect(self.api_connection)
        self.bus.server_closing.connect(self.bus_shutdown_complete.clear)
        self.bus.server_closed.connect(self.api_closed)
        self.bus.set_players.connect(self.set_players)
        self.bus.update_status.connect(self.update_status)
        self.bus.player_join.connect(self.add_player)
        self.bus.player_leave.connect(self.remove_player)
        self.bus.refresh_players.connect(self.update_players_list)

        # This version will start the threads attempting to connect to the api.
        # A signal is used to broadcast whether the threads successfully connected (i.e. the server is up)
        api_settings = file_funcs.get_api_settings(self.server_path, api_version)
        self.mgmt_listener_thread = threading.Thread(target=self.bus.run_mgmt_listener_client, args=api_settings, daemon=True)
        self.mgmt_listener_thread.start()
        self.mgmt_sender_thread = threading.Thread(target=self.bus.run_mgmt_sender_client, args=api_settings, daemon=True)
        self.mgmt_sender_thread.start()

    def disconnect_bus(self):
        try:
            self.bus.log.disconnect(self.log_queue.put)
        except:
            pass
        try:
            self.bus.recvd_result.disconnect(self.result_queue.put)
        except:
            pass
        try:
            self.bus.connected.disconnect(self.api_connection)
        except:
            pass
        try:
            self.bus.server_closing.disconnect(self.bus_shutdown_complete.clear)
        except:
            pass
        try:
            self.bus.server_closed.disconnect(self.api_closed)
        except:
            pass
        try:
            self.bus.set_players.disconnect(self.set_players)
        except:
            pass
        try:
            self.bus.update_status.disconnect(self.update_status)
        except:
            pass
        try:
            self.bus.player_join.disconnect(self.add_player)
        except:
            pass
        try:
            self.bus.player_leave.disconnect(self.remove_player)
        except:
            pass
    
    def shutdown_bus(self):
        if self.bus is not None:
            self.bus.shutdown()
            if self.mgmt_listener_thread.is_alive():
                self.mgmt_listener_thread.join(timeout=2.0)
            if self.mgmt_sender_thread.is_alive():
                self.mgmt_sender_thread.join(timeout=2.0)
        self.disconnect_bus()
        self.bus = None
        self.bus_shutdown_complete.set()
    
    def open_server_folder(self):
        file_funcs.open_folder_explorer(self.server_path)
    
    def delay(self, delay_amount):
        end_time = time.time() + delay_amount
        while time.time() < end_time:
            QApplication.processEvents()
    
    def clear_log_queue(self):
        while not self.log_queue.empty():
            self.log_queue.get()
    
    def clear_log(self):
        self.log_box.clear()
    
    def show_main_page(self, ignore_load=False):
        if not ignore_load:
            saved_ip, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings = file_funcs.load_settings(self.log_queue, self.file_lock)
        
        self.check_messages()
        self.stacked_layout.setCurrentIndex(0)
    
    def show_error_page(self, error, info, eula=False):
        self.error_label.setText(error)
        self.info_label.setText(info)
        if eula:
            self.eula_link_button.show()
            self.eula_accept_button.show()
            self.eula_decline_button.show()
        else:
            self.eula_link_button.hide()
            self.eula_accept_button.hide()
            self.eula_decline_button.hide()
        self.stacked_layout.setCurrentIndex(1)
    
    def show_server_entry_page(self):
        self.stacked_layout.setCurrentIndex(2)
    
    def prepare_ip_page(self, failed=False):
        if failed:
            self.connecting_label.setText("Unable to Bind to IP")
            self.connection_delabel.setText("Is Hamachi offline?")
        else:
            self.connecting_label.setText("")
            self.connection_delabel.setText("")
        self.default_ip_check.setChecked(False)
        self.hosting_ip_entry.setText(self.host_ip)
        self.show_ip_entry_page()
    
    def show_ip_entry_page(self):
        self.stacked_layout.setCurrentIndex(3)
    
    def show_world_manager_page(self):
        self.stacked_layout.setCurrentIndex(4)
    
    def show_add_world_page(self):
        self.stacked_layout.setCurrentIndex(5)
    
    def prepare_remove_world_page(self):
        worlds = self.worlds.keys()
        self.worlds_dropdown.clear()
        self.worlds_dropdown.addItems(worlds)
        self.delete_world_checkbox.setChecked(False)
        self.show_remove_world_page()

    def show_remove_world_page(self):
        self.stacked_layout.setCurrentIndex(6)
    
    def show_edit_properties_page(self):
        world = self.dropdown.currentText()
        file_path = self.path(self.server_path, "worlds", world, "saved_properties.properties")
        with open(file_path, 'r') as props:
            curr_properties = props.read()
        
        self.edit_box.setPlainText(curr_properties)
        self.title_label.setText(f"{world} Properties")
        
        self.stacked_layout.setCurrentIndex(7)
    
    def show_new_world_type_page(self):
        if self.update_existing_world_button.isHidden():
            self.stacked_layout.setCurrentIndex(8)
        else:
            self.update_existing_world_button.hide()
            self.include_snapshots_check.setDisabled(False)
            self.mc_version_dropdown.clear()
            self.mc_version_dropdown.addItems(queries.get_mc_versions(include_snapshots=False))
            self.show_world_manager_page()
    
    def show_commands_page(self):
        if self.status == "online" and not self.is_api_compatible(self.worlds[self.world]["version"]):
            self.commands_warning_label.show()
        else:
            self.commands_warning_label.hide()
        if self.universal_settings.get("whitelist enabled"):
            self.whitelist_toggle_button.setProperty("variant", "")
            self.whitelist_toggle_button.setText("Enabled")
        else:
            self.whitelist_toggle_button.setProperty("variant", "red")
            self.whitelist_toggle_button.setText("Disabled")
        
        st = self.whitelist_toggle_button.style()
        st.unpolish(self.whitelist_toggle_button)
        st.polish(self.whitelist_toggle_button)

        self.whitelist_add_textbox.clear()

        self.view_distance_textbox.setText(str(self.universal_settings.get("view distance")))
        self.simulation_distance_textbox.setText(str(self.universal_settings.get("simulation distance")))
        self.stacked_layout.setCurrentIndex(9)
    
    def show_mods_page(self):
        self.stacked_layout.setCurrentIndex(10)
    
    def save_properties_edit(self):
        world = self.dropdown.currentText()
        file_path = self.path(self.server_path, "worlds", world, "saved_properties.properties")
        new_contents = self.edit_box.toPlainText()
        with open(file_path, 'w') as props:
            props.write(new_contents)
        
        self.universal_settings = file_funcs.check_for_property_updates(self.server_path, world, self.file_lock, self.ips, self.host_ip)
        self.log_queue.put(f"<font color='green'>Properties have been saved.</font>")

        self.show_main_page(True)
    
    def check_server_path(self, new_text):
        self.existing_server_button.setEnabled(os.path.isdir(new_text))
        self.create_server_button.setEnabled(new_text != "")

    def start_manager_server(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if self.host_ip == "":
            self.show_ip_entry_page()
            self.default_ip_check.setChecked(False)
            return
        try:
            self.server.bind((self.host_ip, self.port))
            self.server.listen()
            self.server.setblocking(False)
        except:
            self.prepare_ip_page(failed=True)
            return
        self.host_ip_label.setText(f"IP: {self.host_ip}")
        self.show_main_page()
        self.first_load()
        self.receive_thread = threading.Thread(target=self.receive)
        self.receive_thread.start()
        self.message_timer.start(1000)
        self.log_queue.put("Waiting for connections...")
        if not self.dropdown.currentText():
            self.log_queue.put("<br>You do not currently have any worlds added to your list.")
            self.log_queue.put("Click 'World Manager' to add a new world.")
    
    def receive(self):
        handlers = []
        while not self.stop_threads.is_set():
            try:
                client, address = self.server.accept()
                intention = client.recv(1024).decode("utf-8")
                if intention == "connection request":
                    client_thread = threading.Thread(target=self.handle_client, args=(client, address))
                    handlers.append(client_thread)
                    client_thread.start()
            except socket.error as e:
                if e.errno == 10035: # Non blocking socket error
                    pass
                else:
                    break
            time.sleep(3) # Avoid CPU usage
        
        for thread in handlers:
            thread.join()
    
    def handle_client(self, client, address):
        skip_receive = False
        messages = []
        ip, port = address
        if self.ips.get(ip) is not None:
            self.clients[client] = self.ips.get(ip)
            client.sendall("accept".encode("utf-8"))
        else:
            # Get display name
            client.sendall("identify".encode("utf-8"))
            stop = False
            while not stop and not self.stop_threads.is_set():
                try:
                    message = client.recv(1024).decode('utf-8')
                    if not message:
                        client.close()
                        return

                    messages += message.split("CLIENT-MESSAGE~~>")[1:]
                    if "CLOSING" in messages:
                        client.close()
                        return

                    self.clients[client] = messages.pop(0)
                    self.ips[ip] = self.clients[client]
                    file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
                    stop = True
                except socket.error as e:
                    if e.errno == 10035: # Non blocking socket error
                        pass
                    else:
                        client.close()
                        return
                
                time.sleep(1)
        
        self.log_queue.put(f"<font color='blue'>{html.escape(self.clients[client])} has joined the room!</font>")
        self.tell(client, "You have joined the room!")
        for send_client, _ in self.clients.items():
            if send_client is not client:
                self.tell(send_client, f"<font color='blue'>{html.escape(self.clients[client])} has joined the room!</font>")
        
        self.delay(1)

        while not self.stop_threads.is_set() and not skip_receive:
            try:
                new_message = client.recv(1024).decode('utf-8')
                if not new_message:
                    break

                messages += new_message.split("CLIENT-MESSAGE~~>")[1:]

                if "CLOSING" in messages:
                    break
                while len(messages) != 0:
                    message = messages.pop(0)
                    if message == "":
                        continue

                    if not message.startswith("MANAGER-REQUEST"):
                        self.log_queue.put(f'<font color="blue">{html.escape(self.clients[client])}: {message}</font>')
                        self.broadcast(message, client)
                    else:
                        data = message.split('~~>')[-1].split(',')
                        request, args = data[0], data[1:]
                        if request == "get-status":
                            # self.log_queue.put(f"{html.escape(self.clients[client])} queried the server status.")
                            result = self.query_status()
                            # self.log_queue.put(f"Server status is: {result[0]}.")
                            self.set_status_signal.emit(result)
                            self.send_data("status", result)
                        elif request == "get-players":
                            status = self.query_status()
                            # self.log_queue.put(f"{html.escape(self.clients[client])} queried the active players.")
                            if status[0] == "online":
                                players = self.query_players()
                                self.update_players_list_signal.emit(players)
                            else:
                                self.set_status_signal.emit(status)
                                self.tell(client, "The server has closed.")
                                self.send_data("status", status)
                        elif request == "get-worlds-list":
                            self.send_data("worlds-list", self.query_worlds(), client)
                        elif request in ["start-server", "stop-server"]:
                            self.log_queue.put(f"{html.escape(self.clients[client])} requested to {request[:request.find('-')]} the server.")
                            if request == "stop-server":
                                self.stop_server_signal.emit(client)
                            elif request == "start-server":
                                self.start_server_signal.emit([client, args[0]])
                        elif request == "restart-server":
                            self.tell(client, "<font color='red'>The host manager no longer supports restarting worlds in the current version.</font>")
                            self.tell(client, "You are using an outdated client version. You can find the latest release at https://www.github.com/Peter-Vanderhyde/Minecraft-Manager/releases.")
                        elif request == "check-mods":
                            folder_path = self.path(self.server_path, "worlds", args[0], "client mods")
                            if os.path.isdir(folder_path) and len(glob.glob(self.path(folder_path, "*.jar"))) > 0:
                                    self.send_data("available-mods", [args[0], True], client)
                            else:
                                self.send_data("available-mods", [args[0], False], client)
                        elif request == "download-mods":
                            world = args[0]
                            folder_path = self.path(self.server_path, "worlds", world, "client mods")
                            if os.path.isdir(folder_path):
                                files = glob.glob(self.path(folder_path, "*.jar"))
                                total_size = 0
                                for file in files:
                                    total_size += os.path.getsize(file)
                                for i, file in enumerate(files):
                                    filesize = os.path.getsize(file)
                                    filename = os.path.basename(file)
                                    header = [filename, filesize, i + 1, len(files), total_size]
                                    self.send_data("sending-file", header, client)
                                    with open(file, "rb") as f:
                                        client.sendfile(f)
                                self.send_data("file-transfer-complete", "", client)

            except socket.error as e:
                if e.errno == 10035: # Non blocking socket error
                    pass
                else:
                    break
            except Exception as e:
                break

            time.sleep(0.5)
        
        client.close()
        self.log_queue.put(f"<font color='blue'>{html.escape(self.clients[client])} has left the room.</font>")
        self.broadcast(f"<font color='blue'>{html.escape(self.clients[client])} has left the room.</font>")
        self.clients.pop(client)

    def send_data(self, topic, data, client=None):
        if not isinstance(data, (list, tuple, dict)):
            data = [data]
        if client:
            self.tell(client, f"DATA-RETURN({topic})~~>{json.dumps(data)}")
        else:
            self.broadcast(f"DATA-RETURN({topic})~~>{json.dumps(data)}")
    
    def broadcast(self, message, owner=None):
        for client, name in self.clients.items():
            try:
                if owner:
                    if client is owner:
                        self.tell(client, f'<font color="green">You: {message}</font>')
                    else:
                        self.tell(client, f'<font color="blue">{self.clients[owner]}: {message}</font>')
                else:
                    self.tell(client, message)
            except Exception as e:
                pass
    
    def tell(self, client, message):
        client.sendall(f"SERVER-MESSAGE~~>{message}\n".encode("utf-8"))
    
    def check_messages(self):
        while not self.log_queue.empty():
            message = self.log_queue.get()
            self.log_box.append(message)
            scrollbar = self.log_box.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
    
    def first_load(self):
        self.verify_world_formatting() # Update oudated formatting from previous versions
        self.set_worlds_list()
        self.get_status()
        if self.status == "online" and self.is_api_compatible(self.worlds[self.world]["version"]):
            self.create_bus(self.get_api_version(self.worlds[self.world]["version"]))
    
    def verify_world_formatting(self):
        outdated = False
        for name, data in self.worlds.items():
            if not data.get("gamemode"):
                # Older manager version
                outdated = True
                new_data = {
                    "version": data["version"],
                    "seed": data.get("seed", ""),
                    "gamemode": data.get("gamemode", "Survival"),
                    "difficulty": data.get("difficulty", "Easy"),
                    "fabric": data.get("fabric", False),
                    "level-type": data.get("level-type", "Normal")
                }
                self.worlds[name] = new_data
                if os.path.exists(self.path(self.server_path, "worlds", name)):
                    file_funcs.save_world_properties(self.path(self.server_path, "worlds", name), new_data)
                
                if os.path.isfile(self.path(self.server_path, "worlds", name, "version.txt")):
                    os.remove(self.path(self.server_path, "worlds", name, "version.txt"))
        
        if self.world_order == [] and len(self.worlds.keys()) > 0:
            outdated = True
            for world in self.worlds.keys():
                self.world_order.append(world)
        
        if self.universal_settings in [{}, None]:
            self.universal_settings = {
                "whitelist enabled": False,
                "view distance": 10,
                "simulation distance": 10
            }
            outdated = True
        
        if outdated:
            file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
        
    
    def message_entered(self):
        message = self.message_entry.text()
        if message != "":
            self.message_entry.clear()
            self.log_queue.put(f'<font color="green">You: {message}</font>')
            self.broadcast(f'<font color="blue">Admin: {message}</font>')
    
    def get_api_version(self, version):
        game_versions = queries.get_mc_versions(include_snapshots=True)
        # Check what API syntax/systems to handle based on updates to the game in certain versions
        version_index = game_versions.index(version)
        api_version = 0
        updated_versions = ["25w35a", "25w37a", "1.21.9-pre1", "1.21.9-pre4"]
        for v in updated_versions:
            if version_index <= game_versions.index(v):
                api_version += 1
        
        return api_version
    
    def is_api_compatible(self, version):
        return self.get_api_version(version) > 0

    def api_connection(self, success):
        if success:
            waited = 0
            while waited < 10 and self.query_status()[0] != "online":
                self.delay(1)
                waited += 1
            self.get_status_signal.emit()
            self.log_queue.put(f"Server world '{self.world}' has been started.")
            self.broadcast(f"Server world '{self.world}' has been started.")
            self.send_data("start", "refresh")
        else:
            self.shutdown_bus()
            error = f"<font color='red'>Uh oh. There was a problem running the server world.</font>"
            self.log_queue.put(f"<font color='red'>ERROR: Problem running world '{self.world}'!</font>")
            self.broadcast(error)
    
    def api_closed(self):
        self.shutdown_bus()
        self.get_status_signal.emit()
        self.log_queue.put("Server has been stopped.")
        self.broadcast("Server has been stopped.")
        self.send_data("stop", "refresh")
        if os.path.exists(self.path(self.server_path, "mods")) and self.status == "offline":
            try:
                shutil.rmtree(self.path(self.server_path, "mods"))
            except:
                pass
    
    def client_start_server(self, args):
        client, world = args
        error = self.start_server(world)
        if error:
            if error == "already online":
                self.tell(client, "Server already running.")
                updated_status = self.query_status()
                self.set_status_signal.emit(updated_status)
                self.send_data("status", updated_status)
            else:
                self.tell(client, error)
    
    def client_stop_server(self, client):
        error = self.stop_server()
        if error:
            if error == "already offline":
                self.tell(client, "Server already stopped.")
                updated_status = self.query_status()
                self.set_status_signal.emit(updated_status)
                self.send_data("status", updated_status)
            else:
                self.tell(client, error)
    
    def start_server(self, world):
        if world == "":
            self.log_queue.put(f"<font color='red'>There is no world selected.</font>")
            return f"<font color='red'>There is no world selected.</font>"
        
        if not self.bus_shutdown_complete.is_set():
            self.bus_shutdown_complete.wait(timeout=5.0)
            if not self.bus_shutdown_complete.is_set():
                self.shutdown_bus()
        
        status, _, _ = self.query_status()
        if status == "online":
            self.log_queue.put("Server is already online.")
            return "already online"
        
        version, gamemode, difficulty, fabric, level_type = None, None, None, None, None
        if self.worlds.get(world):
            version = self.worlds[world].get("version")
            fabric = self.worlds[world].get("fabric")
            seed = self.worlds[world].get("seed", None)
            difficulty = self.worlds[world].setdefault("difficulty", "Easy")
            gamemode = self.worlds[world].setdefault("gamemode", "Survival")
            level_type = self.worlds[world].setdefault("level-type", "Normal")
        if not version:
            self.log_queue.put(f"<font color='red'>The version is not specified for {world}.</font>")
            return f"<font color='red'>ERROR: World {world} is missing version.</font>"
        
        required_java_version = queries.get_required_java_version(version, self.log_queue)
        if required_java_version:
            if required_java_version > self.java_version:
                self.log_queue.put(f"<font color='red'>Your Java version is out of date!<br>"
                                    f"Minecraft version {queries.get_latest_release(self.log_queue)} requires Java version {required_java_version}.<br>"
                                    f"You are currently running version {self.java_version}.<br>"
                                    "Download an updated version from www.adoptium.net/temurin/releases/</font>",
                                    eula=False)
                
                return f"<font color='red'>ERROR: Host is running an older version of Java that does not support version {version}.</font>"

        self.broadcast("Starting server...")
        self.log_queue.put("Starting server...")
        QApplication.processEvents()
        old_jars = glob.glob(self.path(self.server_path, "*.jar"))
        for path in old_jars:
            os.remove(path)
        data = self.worlds.get(world)
        path = self.path(self.server_path, "worlds", world)
        if not data:
            self.log_queue.put(f"<font color='red'>ERROR: world '{world}' is not recognized.</font>")
            return f"<font color='red'>Manager doesn't recognize that world.</font>"
        elif not os.path.exists(path) and self.worlds[world].get("seed") is None:
            error = f"<font color='red'>Uh oh. Path to world '{world}' no longer exists.</font>"
            self.log_queue.put(f"<font color='red'>ERROR: Unable to find '{world}' at path '{path}'!</font>")
            return error
        else:
            try:
                self.log_queue.put(f"Preparing for {'fabric ' if fabric else ''} version {version}.")
                if seed is not None:
                    if seed != "":
                        self.log_queue.put(f"Generating {level_type} world with seed '{seed}'...")
                    else:
                        self.log_queue.put(f"Generating {level_type} world with random seed...")
                self.delay(1)

                # Erase old properties for fresh start each time
                with open(self.path(self.server_path, "server.properties"), 'w') as props:
                    props.write("")
                
                # Copy world properties to the server properties
                if os.path.isfile(self.path(path, "saved_properties.properties")):
                    lines = []
                    with open(self.path(path, "saved_properties.properties"), 'r') as world_props:
                        lines = world_props.readlines()
                    for i in range(len(lines)):
                        if lines[i].startswith("management-server-secret="):
                            lines[i] = ""
                    with open(self.path(self.server_path, "server.properties"), 'w') as props:
                        props.writelines(lines)
                elif not os.path.isdir(path):
                    os.mkdir(path)
                
                # Apply settings such as whitelist etc.
                file_funcs.apply_universal_settings(self.server_path)
                
                world_mods_folder = self.path(path, "mods")
                server_mods_folder = self.path(self.server_path, "mods")
                if fabric and os.path.exists(world_mods_folder):
                    if os.path.exists(server_mods_folder):
                        shutil.rmtree(server_mods_folder)
                    shutil.copytree(world_mods_folder, server_mods_folder)
                elif fabric:
                    if os.path.exists(server_mods_folder):
                        shutil.rmtree(server_mods_folder)
                        os.mkdir(server_mods_folder)
                else:
                    if os.path.exists(server_mods_folder):
                        shutil.rmtree(server_mods_folder)

                if self.is_api_compatible(version):
                    api_version = self.get_api_version(version)
                    file_funcs.get_api_settings(self.server_path, api_version)
                if not file_funcs.prepare_server_settings(world, version, gamemode, difficulty, fabric, level_type, self.server_path, self.log_queue, seed):
                    raise RuntimeError("Failed to prepare settings.")
                else:
                    if seed is not None:
                        self.worlds[world].pop("seed")
                        file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
            
                os.system(f'start "" /min cmd /C "title Server Ignition && cd /d "{self.server_path}" && run.bat"')
                loop = True
                window = None
                ignition_window = None
                timer_amount = 60
                end_time = time.time() + timer_amount
                while loop and not self.stop_threads.is_set():
                    QApplication.processEvents()
                    windows = pgw.getAllTitles()
                    for w in windows:
                        if w == "Minecraft server":
                            loop = False
                            window = pgw.getWindowsWithTitle(w)[0]
                        elif ignition_window is None and "Server Ignition" in w:
                            ignition_window = pgw.getWindowsWithTitle(w)[0]
                    
                    if time.time() > end_time:
                        self.log_queue.put("<font color='red'>Timed out waiting for the server to start up.</font>")
                        return "<font color='red'>Timed out waiting for the server to start.</font>"
                
                if self.stop_threads.is_set():
                    return

                window.minimize()
                if ignition_window:
                    ignition_window.close()
                
                self.world = world
                self.world_version = version
                self.move_world_to_top(world)

                if not os.path.isfile(self.path(path, "saved_properties.properties")):
                    lines = []
                    with open(self.path(self.server_path, "server.properties"), 'r') as props:
                        lines = props.readlines()
                    with open(self.path(path, "saved_properties.properties"), 'w') as world_props:
                        world_props.writelines(lines)
                else:
                    with open(self.path(self.server_path, "server.properties"), 'r') as serv:
                        serv_lines = serv.readlines()
                    
                    with open(self.path(path, "saved_properties.properties"), 'r') as saved:
                        saved_lines = saved.readlines()
                    
                    if len(serv_lines) > len(saved_lines):
                        with open(self.path(path, "saved_properties.properties"), 'w') as saved:
                            saved.writelines(serv_lines)
                    
                    if world == self.dropdown.currentText():
                        self.world_properties_button.setEnabled(True)
                        if fabric:
                            self.world_mods_button.setEnabled(True)
                            self.modrinth_button.show()
                
                if fabric and not os.path.exists(world_mods_folder):
                    try:
                        os.mkdir(world_mods_folder)
                    except:
                        pass
                
                self.log_queue.put("Waiting for chunks to generate...")
                if self.is_api_compatible(version):
                    # The bus is the asynchronous threads that listen to the api
                    self.create_bus(self.get_api_version(version))
                else:
                    if seed:
                        # Wait longer
                        check_status = 5
                    else:
                        check_status = 10
                    
                    while check_status != 0:
                        self.delay(5)
                        if self.query_status()[0] == "online":
                            check_status = 0
                        else:
                            check_status -= 1

                    # Older versions assume the world will start soon, even if the wait timer was exhausted
                    self.get_status_signal.emit()
                    self.log_queue.put(f"Server world '{world}' has been started.")
                    self.broadcast(f"Server world '{world}' has been started.")
                    self.send_data("start", "refresh")
            except Exception as e:
                error = f"<font color='red'>Uh oh. There was a problem running the server world.</font>"
                self.log_queue.put(f"<font color='red'>ERROR: Problem running world '{world}'! {e}</font>")
                return error
    
    def stop_server(self):
        status, _, world = self.query_status()
        if status == "offline":
            self.log_queue.put("Server is already offline.")
            return "already offline"

        self.broadcast("Stopping server...")
        self.log_queue.put("Stopping server...")
        if self.is_api_compatible(self.worlds[world]["version"]):
            self.bus.close_server.emit()
        else:
            windows = pgw.getWindowsWithTitle("Minecraft server")
            window = None
            for w in windows:
                if w.title == "Minecraft server":
                    window = w
            
            pgw.getActiveWindow().title
            window.restore()
            window.activate()

            # Check if caps lock is on
            user32 = ctypes.WinDLL("user32")
            caps_lock_state = user32.GetKeyState(0x14)
            if bool(caps_lock_state):
                pag.keyDown("capslock")
                pag.keyUp("capslock")

            target_pos = pag.Point(window.bottomright.x - 30, window.bottomright.y - 30)
            while pag.position() != target_pos:
                pag.moveTo(target_pos.x, target_pos.y)

            pag.click()
            pag.typewrite("stop")
            pag.keyDown("enter")

            if bool(caps_lock_state):
                pag.keyDown("capslock")
                pag.keyUp("capslock")

            self.delay(3)

            self.get_status_signal.emit()
            self.log_queue.put("Server has been stopped.")
            self.broadcast("Server has been stopped.")
            self.send_data("stop", "refresh")

            # Hacky way to delete the mods folder after closing for old version
            if os.path.exists(self.path(self.server_path, "mods")) and self.status == "offline":
                try:
                    shutil.rmtree(self.path(self.server_path, "mods"))
                except:
                    pass
            return None

    def query_status(self):
        status, brand, version, world = queries.status(self.host_ip, self.server_port)
        if status == "offline":
            return status, "", ""
        else:
            if world:
                world = world.removeprefix("worlds/")
            
            self.world = world or self.world
            return status, f"{brand} {version}", world
    
    def query_players(self):
        return queries.players(self.host_ip, self.server_port)
    
    def query_worlds(self):
        return (self.worlds, self.world_order)

    def get_status(self):
        self.set_status(["pinging",None,None])
        status = self.query_status()
        self.set_status(status)
        self.send_data("status", status)
        if status == "online" and self.is_api_compatible(self.worlds[self.world]["version"]) and not self.bus and self.bus_shutdown_complete.is_set():
            self.create_bus(self.worlds[self.world]["version"])

    def get_players(self):
        # Used with the player refresh button
        status = self.query_status()
        if status[0] == "online":
            self.curr_players = self.query_players()
            self.update_players_list()
        else:
            self.set_status(status)
            self.send_data("status", status)
    
    def update_status(self, info):
        # Updates through API heartbeat
        status, version = info
        if status:
            self.status = "online"
            self.server_status_label.hide()
            self.server_status_offline_label.hide()
            self.server_status_online_label.show()
            self.version_label.setText(f"Version: {version} {'Fabric' * self.worlds[self.world]['fabric']}")
            self.world_label.setText(f"World: {self.world}")
            self.refresh_button.setEnabled(True)
            self.refresh_status_button.setEnabled(True)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
        else:
            self.status = "offline"
            self.server_status_label.hide()
            self.server_status_offline_label.show()
            self.server_status_online_label.hide()
            self.version_label.setText("Version:")
            self.world_label.setText("World:")
            self.refresh_button.setEnabled(False)
            self.players_info_box.clear()
            self.refresh_status_button.setEnabled(True)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
    
    def set_status(self, info):
        # Used to update through refresh buttons
        status, version, world = info
        if version and version.startswith("vanilla "):
            version = version.removeprefix("vanilla ")
        if status == "online":
            self.status = "online"
            self.world = world
            self.world_version = version
            self.server_status_label.hide()
            self.server_status_offline_label.hide()
            self.server_status_online_label.show()
            if world in self.worlds:
                self.version_label.setText(f"Version: {version} {'Fabric' * self.worlds[world]['fabric']}")
            else:
                self.version_label.setText(f"Version: {version}")
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
    
    def set_players(self, new_player_list):
        # Sets the players through the API heartbeat
        self.curr_players = [player["name"] for player in new_player_list]
        self.update_players_list()

    def update_players_list(self):
        self.send_data("players", self.curr_players)
        self.players_info_box.clear()
        if len(self.curr_players) == 0:
            item = QListWidgetItem("No players online")
            item.setForeground(QColor("red"))
            self.players_info_box.addItem(item)
            return

        opped_players = []
        if os.path.isfile(self.path(self.server_path, "ops.json")):
            with open(self.path(self.server_path, "ops.json"), 'r') as f:
                opped_players = [p["name"] for p in json.loads(f.read())]
        for player in self.curr_players:
            if player in opped_players:
                player = f"{player} [op]"
            item = QListWidgetItem(html.escape(player))
            item.setForeground(QColor("purple"))
            self.players_info_box.addItem(item)
    
    def color_segments(self, segs, colors):
        msg = ""
        for segment, color in zip(segs, colors):
            safe = html.escape(segment).replace("\n", "<br>")
        
            if color:
                msg += f"<span style=\"color:{color}\">{safe}</span>"
            else:
                msg += safe
        return msg
    
    def remove_player(self, player_obj):
        self.curr_players.remove(player_obj["name"])
        self.update_players_list()
        formatted_text = self.color_segments([player_obj['name'], " disconnected ", "from the server."], ["purple", "red", None])
        self.log_queue.put(formatted_text)
        self.broadcast(formatted_text)
    
    def add_player(self, player_obj):
        self.curr_players.append(player_obj["name"])
        self.update_players_list()
        formatted_text = self.color_segments([player_obj['name'], " joined ", "the server."], ["purple", "green", None])
        self.log_queue.put(formatted_text)
        self.broadcast(formatted_text)
    
    def set_worlds_list(self):
        self.dropdown.clear()
        self.dropdown.addItems(self.world_order)
        self.set_selected_world_version(self.dropdown.currentText())
    
    def set_selected_world_version(self, world):
        if world:
            self.world_version_label.setText(f'v{self.worlds[world]["version"]} {self.worlds[world]["fabric"] * "Fabric"}')
            if os.path.isfile(self.path(self.server_path, "worlds", world, "saved_properties.properties")):
                self.world_properties_button.setEnabled(True)
            else:
                self.world_properties_button.setEnabled(False)
            
            if self.worlds[world].get("fabric"):
                self.world_mods_button.setEnabled(True)
                self.modrinth_button.show()
            else:
                self.world_mods_button.setEnabled(False)
                self.modrinth_button.hide()
        else:
            self.world_version_label.setText("")
            self.world_properties_button.setEnabled(False)
            self.world_mods_button.setEnabled(False)
            self.modrinth_button.hide()
    
    def set_server_path(self):
        path = self.server_folder_path_entry.text()
        if os.path.isdir(path):
            while not self.log_queue.empty():
                self.log_queue.get()
            self.message_timer.start(1000)
            if self.server_path:
                file_funcs.update_settings(self.file_lock, self.ips, path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
                saved_ip, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings = file_funcs.load_settings(self.log_queue, self.file_lock)
                self.clear_log_queue()
            else:
                self.server_path = path
                file_funcs.update_settings(self.file_lock, self.ips, path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
            self.start_manager_server()
    
    def create_server_folder(self):
        path = self.server_folder_path_entry.text()
        def create_path(path):
            if path == "" or os.path.exists(path):
                return
            
            parent = self.path(path, os.path.pardir)
            create_path(parent)
            os.mkdir(path)

        if not os.path.isdir(path):
            # Build up directories to the requested one
            create_path(path)
        
        while not self.log_queue.empty():
            self.log_queue.get()
        self.message_timer.start(200)
            
        file_funcs.update_settings(self.file_lock, self.ips, path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
        
        self.change_ip_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.refresh_status_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.world_manager_button.setEnabled(False)
        self.commands_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.world_properties_button.setEnabled(False)
        self.world_mods_button.setEnabled(False)
        self.modrinth_button.hide()

        self.log_queue.put("Downloading latest server.jar file...")
        self.show_main_page(ignore_load=True)
        self.delay(0.5)
        version = queries.download_latest_server_jar(path, self.log_queue)
        if version:
            self.log_queue.put("Generating server files...")
            self.log_queue.put("Please wait...")
            self.delay(0.5)
            subprocess.run(["java", "-jar", f"server-{version}.jar"], cwd=path)
            self.server_path = path
            self.message_timer.start(1000)

            self.change_ip_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.refresh_status_button.setEnabled(True)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(True)
            self.world_manager_button.setEnabled(True)
            self.commands_button.setEnabled(True)
            self.open_folder_button.setEnabled(True)
            
            if not self.check_eula():
                self.show_error_page("By accepting, you are indicating your agreement<br> to Minecraft's EULA.",
                                    "(https://aka.ms/MinecraftEULA)", eula=True)
            else:
                self.start_manager_server()
    
    def open_eula_link(self):
        QDesktopServices.openUrl(QUrl("https://aka.ms/MinecraftEULA"))

    def check_eula(self):
        try:
            with open(self.path(self.server_path, "eula.txt"), 'r') as f:
                content = f.read()
            if "eula=false" in content:
                return False
            elif "eula=true" in content:
                return True
        except FileNotFoundError:
            self.show_error_page("Unable to find server eula.txt file.", "", eula=False)
            return None
    
    def accepted_eula(self):
        with open(self.path(self.server_path, "eula.txt"), 'r') as f:
            content = f.readlines()
        for i, line in enumerate(content):
            if line.strip() == "eula=false":
                content[i] = "eula=true"
        with open(self.path(self.server_path, "eula.txt"), 'w') as f:
            f.writelines(content)
        
        self.start_manager_server()

    def declined_eula(self):
        self.close()
    
    def set_ip(self):
        ip = self.hosting_ip_entry.text()
        if ip:
            if ip == self.host_ip and self.receive_thread.is_alive():
                self.show_main_page(ignore_load=True)
                return
            elif self.receive_thread.is_alive():
                self.stop_server_threads()
                self.stop_threads.clear()
                self.clear_log_queue()
                self.clear_log()
            else:
                self.clear_log_queue()
                self.clear_log()
            self.connecting_label.setText("Connecting...")
            self.host_ip = ip
            self.delay(0.5)
            if self.default_ip_check.isChecked():
                file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings, ip=self.host_ip)
                self.saved_ip = self.host_ip
            self.start_manager_server()
    
    def backup_world(self):
        world_path = file_funcs.pick_folder(self, self.path(self.server_path, "worlds"))
        if world_path is None:
            return
        
        world_path = os.path.normpath(world_path)
        world_folders = glob.glob(self.path(self.server_path, "worlds", "*/"))
        if world_path in world_folders:
            try:
                if self.world == os.path.basename(world_path) and self.query_status()[0] == "online":
                    self.log_queue.put(f"<font color='red'>ERROR: Unable to backup world folder while world is being run.</font>")
                    self.show_main_page()
                    return
                
                current_date = datetime.now().strftime("%m-%d-%y")
                new_path = f"{self.path(self.server_path, 'backups', os.path.basename(world_path))}_{current_date}"
                if os.path.exists(new_path):
                    index = 1
                    while os.path.exists(f"{new_path}({str(index)})"):
                        index += 1
                    
                    self.log_queue.put(f"<font color='green'>Copying files. Please wait...</font>")
                    self.show_main_page()
                    self.delay(0.5)
                    shutil.copytree(world_path, f"{new_path}({str(index)})")
                else:
                    self.log_queue.put(f"<font color='green'>Copying files. Please wait...</font>")
                    self.show_main_page()
                    self.delay(0.5)
                    shutil.copytree(world_path, new_path)
                self.log_queue.put(f"<font color='green'>Saved backup of '{os.path.basename(world_path)}'.</font>")
            except:
                self.log_queue.put(f"<font color='red'>ERROR: Unable to backup world folder.</font>")
                try:
                    new_path = f"{self.path(self.server_path, 'backups', os.path.basename(world_path))}_{current_date}"
                    shutil.rmtree(new_path)
                except:
                    pass
                self.show_main_page()
        elif world_path:
            self.log_queue.put(f"<font color='red'>ERROR: Invalid world folder.</font>")
            self.show_main_page()
    
    def add_existing_world(self, update=False):
        world_path = file_funcs.pick_folder(self, self.path(self.server_path, "worlds"))
        if world_path is None:
            return
        
        world_path = self.path(world_path)
        world_folders = glob.glob(self.path(self.server_path, "worlds", "*/"))
        if not update:
            if world_path in world_folders:
                try:
                    if os.path.basename(world_path) in self.worlds.keys():
                        self.log_queue.put(f"<font color='red'>ERROR: World '{os.path.basename(world_path)}' already in worlds list.</font>")
                        self.show_main_page()
                        return
                    self.add_world(world=os.path.basename(world_path), new=False)
                    self.mc_version_dropdown.setCurrentIndex(0)
                    old_properties = file_funcs.load_world_properties(world_path)
                    version = old_properties["version"]
                    if version:
                        if version not in queries.get_mc_versions(include_snapshots=False):
                            self.include_snapshots_check.setChecked(True)
                        try:
                            self.mc_version_dropdown.setCurrentText(version)
                        except:
                            pass
                    self.gamemode_dropdown.setCurrentText(old_properties["gamemode"])
                    self.difficulty_dropdown.setCurrentText(old_properties["difficulty"])
                    self.fabric_dropdown.setCurrentText("Enabled" if old_properties["fabric"] else "Disabled")
                    self.level_type_dropdown.setCurrentText(old_properties["level-type"])
                except:
                    self.log_queue.put(f"<font color='red'>ERROR: Unable to add world folder.</font>")
            elif world_path:
                self.log_queue.put(f"<font color='red'>ERROR: Invalid world folder.</font>")
        else:
            if world_path in world_folders:
                try:
                    if os.path.basename(world_path) not in self.worlds.keys():
                        self.log_queue.put(f"<font color='red'>ERROR: World '{os.path.basename(world_path)}' not found in worlds list.</font>")
                        self.show_main_page()
                        return
                    world = os.path.basename(world_path)
                    if world == self.world and self.query_status()[0] == "online":
                        self.log_queue.put(f"<font color='red'>ERROR: Cannot update while {world} is online.</font>")
                        self.show_main_page()
                        return
                    self.add_world(world=world, new=False, update=True)
                    self.mc_version_dropdown.setCurrentIndex(0)
                    old_properties = file_funcs.load_world_properties(world_path)
                    version = old_properties["version"]
                    if not version:
                        self.log_queue.put(f"<font color='red'>ERROR: Unable to find current version for '{world}'.</font>")
                        self.show_main_page()
                        return
                    if not self.set_version_range(version):
                        self.log_queue.put(f"<font color='red'>ERROR: '{world}' already at latest version.</font>")
                        self.show_main_page()
                        return
                    
                    self.mc_version_dropdown.setCurrentIndex(0)
                    self.gamemode_dropdown.setCurrentText(old_properties["gamemode"])
                    self.difficulty_dropdown.setCurrentText(old_properties["difficulty"])
                    self.fabric_dropdown.setCurrentText("Enabled" if old_properties["fabric"] else "Disabled")
                    self.level_type_dropdown.setCurrentText(old_properties["level-type"])
                except:
                    self.log_queue.put(f"<font color='red'>ERROR: Unable to {'update' if update else 'add'} world folder.</font>")
            elif world_path:
                self.log_queue.put(f"<font color='red'>ERROR: Invalid world folder.</font>")
    
    def add_new_world(self):
        self.add_world(new=True)
    
    def add_world(self, world="", new=False, update=False):
        if new:
            self.add_existing_world_button.hide()
            self.update_existing_world_button.hide()
            self.create_new_world_button.show()
            self.new_world_name_edit.show()
            self.new_world_seed_edit.show()
            self.add_world_label.setText("Create World")

            self.mc_version_dropdown.setCurrentIndex(0)
            self.include_snapshots_check.setChecked(False)
            self.new_world_seed_edit.setText("")
            self.new_world_name_edit.setText("")
            self.fabric_dropdown.setCurrentText("Disabled")
            self.is_fabric_check.setChecked(False)
            self.gamemode_dropdown.setCurrentText("Survival")
            self.difficulty_dropdown.setCurrentText("Normal")
            self.level_type_dropdown.show()
            self.level_type_dropdown.setCurrentText("Normal")
            self.level_type_label.show()
        elif update:
            self.update_existing_world_button.show()
            self.add_existing_world_button.hide()
            self.create_new_world_button.hide()
            self.new_world_name_edit.hide()
            self.new_world_seed_edit.hide()
            self.add_world_label.setText(world)

            self.include_snapshots_check.setChecked(False)
            self.fabric_dropdown.setCurrentText("Disabled")
            self.is_fabric_check.setChecked(False)
            self.gamemode_dropdown.setCurrentText("Survival")
            self.difficulty_dropdown.setCurrentText("Normal")
            self.level_type_dropdown.hide()
            self.level_type_label.hide()
        else:
            self.add_existing_world_button.show()
            self.update_existing_world_button.hide()
            self.create_new_world_button.hide()
            self.new_world_name_edit.hide()
            self.new_world_seed_edit.hide()
            self.add_world_label.setText(world)

            self.include_snapshots_check.setChecked(False)
            self.fabric_dropdown.setCurrentText("Disabled")
            self.is_fabric_check.setChecked(False)
            self.gamemode_dropdown.setCurrentText("Survival")
            self.difficulty_dropdown.setCurrentText("Normal")
            self.level_type_dropdown.hide()
            self.level_type_label.hide()
        
        self.add_world_error.setText("")
        self.show_add_world_page()
    
    def verify_version(self, version, fabric):
        if version != "":
            if fabric:
                return queries.verify_fabric_version(version)
            else:
                # The version dropdown already uses verified versions
                return True
        else:
            return False

    def confirm_add_world(self, update=False):
        result = self.verify_version(self.mc_version_dropdown.currentText(), self.is_fabric_check.isChecked())
        if result:
            name = self.add_world_label.text()
            if update:
                self.remove_world(updating=name)
            self.worlds[name] = {
                "version": self.mc_version_dropdown.currentText(),
                "gamemode": self.gamemode_dropdown.currentText(),
                "difficulty": self.difficulty_dropdown.currentText(),
                "fabric": self.is_fabric_check.isChecked(),
                "level-type": self.level_type_dropdown.currentText()
            }
            self.world_order.insert(0, name)
            file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
            file_funcs.save_world_properties(self.path(os.path.join(self.server_path, "worlds", name)), self.worlds[name])
            self.set_worlds_list()
            self.send_data("worlds-list", self.query_worlds())
            self.log_queue.put(f"<font color='green'>Successfully {'updated' if update else 'added'} world.</font>")
            self.dropdown.setCurrentText(self.add_world_label.text())
            self.show_main_page()
        elif result is False:
            self.add_world_error.setText(f"Invalid {'Fabric ' * self.is_fabric_check.isChecked()}Minecraft version.")
        elif result is None:
            self.log_queue.put(f"<font color='red'>ERROR: Unable to download from {'Fabric' if self.is_fabric_check.isChecked() else 'MCVersions'}.</font>")
            self.show_main_page()
        
        self.include_snapshots_check.setDisabled(False)
        self.update_existing_world_button.hide()
        self.mc_version_dropdown.clear()
        self.mc_version_dropdown.addItems(queries.get_mc_versions(include_snapshots=False))

    def confirm_create_world(self):
        if self.new_world_name_edit.text() == "" or self.new_world_name_edit.text() in self.worlds.keys():
            self.add_world_error.setText(f"Name invalid or already exists.")
            return
        
        result = self.verify_version(self.mc_version_dropdown.currentText(), self.is_fabric_check.isChecked())
        if result:
            self.worlds[self.new_world_name_edit.text()] = {
                "seed": self.new_world_seed_edit.text(),
                "version": self.mc_version_dropdown.currentText(),
                "gamemode": self.gamemode_dropdown.currentText(),
                "difficulty": self.difficulty_dropdown.currentText(),
                "fabric": self.is_fabric_check.isChecked(),
                "level-type": self.level_type_dropdown.currentText()
            }
            self.world_order.insert(0, self.new_world_name_edit.text())
            file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
            self.set_worlds_list()
            self.send_data("worlds-list", self.query_worlds())
            self.log_queue.put(f"<font color='green'>Successfully added world.</font>")
            self.log_queue.put("The world and its folder will be generated when the world is run for the first time.")
            self.dropdown.setCurrentText(self.new_world_name_edit.text())
            self.show_main_page()
        elif result is False:
            self.add_world_error.setText(f"Invalid {'Fabric' * self.is_fabric_check.isChecked()} Minecraft version.")
        elif result is None:
            self.log_queue.put(f"<font color='red'>ERROR: Unable to download from {'Fabric' if self.is_fabric_check.isChecked() else 'MCVersions'}.</font>")
            self.show_main_page()
    
    def version_dropdown_changed(self):
        old_version = file_funcs.load_world_properties(self.path(self.server_path, "worlds", self.add_world_label.text()))["version"]
        if not old_version:
            if os.path.isfile(self.path(self.server_path, "worlds", self.add_world_label.text(), "version.txt")):
                with open(self.path(self.server_path, "worlds", self.add_world_label.text(), "version.txt"), 'r') as f:
                    old_version = f.readline()
        
        if old_version:
            new_version = self.mc_version_dropdown.currentText()
            found_old = False
            for version in queries.get_mc_versions(True):
                if version == new_version:
                    if found_old:
                        self.add_world_error.setText(f"Warning! The existing world was generated in {old_version}!<br>Selecting this older version could break the world.")
                    else:
                        self.add_world_error.setText("")
                    return
                elif version == old_version:
                    found_old = True
    
    def remove_world(self, updating=""):
        if not updating:
            world = self.worlds_dropdown.currentText()
        else:
            world = updating
        if not world:
            return
        
        if self.world == world and self.query_status()[0] == "online":
            self.log_queue.put(f"<font color='red'>ERROR: Unable to {'update' if updating else 'remove'} {world} while the world is being run.</font>")
            self.show_main_page()
            return
        
        if not updating and self.delete_world_checkbox.isChecked():
            try:
                folder_path = self.path(self.server_path, "worlds", world)
                shutil.rmtree(folder_path)
                self.log_queue.put(f"<font color='green'>Successfully deleted the world folder.</font>")
            except:
                pass
        
        self.worlds.pop(world)
        self.world_order.remove(world)
        file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
        self.set_worlds_list()
        self.send_data("worlds-list", self.query_worlds())
        if not updating:
            self.log_queue.put(f"<font color='green'>Successfully removed world.</font>")
            self.show_main_page()
    
    def open_properties(self):
        world = self.dropdown.currentText()
        if world == "" or world is None:
            self.log_queue.put(f"<font color='red'>There is no world selected.</font>")
            return
        
        if not os.path.isfile(self.path(self.server_path, "worlds", world, "saved_properties.properties")):
            self.log_queue.put(f"<font color='red'>The world has not been generated yet.")
            self.log_queue.put(f"<font color='red'>Start world once to generate the world properties.</font>")
            return
        
        file_funcs.open_file(self.path(self.server_path, "worlds", world, "saved_properties.properties"))
    
    def open_mods_folder(self, client_folder=False):
        world = self.dropdown.currentText()
        if world and self.worlds[world].get("fabric"):
            world_folder = self.path(self.server_path, "worlds", world)
            if os.path.exists(world_folder):
                if client_folder:
                    if not os.path.exists(self.path(world_folder, "client mods")):
                        os.mkdir(self.path(world_folder, "client mods"))
                else:
                    if not os.path.exists(self.path(world_folder, "mods")):
                        os.mkdir(self.path(world_folder, "mods"))
            else:
                os.mkdir(world_folder)
                if client_folder:
                    os.mkdir(self.path(world_folder, "client mods"))
                else:
                    os.mkdir(self.path(world_folder, "mods"))

            file_funcs.open_folder_explorer(self.path(world_folder, "client mods" if client_folder else "mods"))
            self.show_main_page(ignore_load=True)
    
    def toggle_whitelist(self):
        enabled = not self.whitelist_toggle_button.text() == "Enabled"
        self.whitelist_toggle_button.setProperty("variant", "red" * (not enabled))
        self.whitelist_toggle_button.setText("Enabled" if enabled else "Disabled")
        
        st = self.whitelist_toggle_button.style()
        st.unpolish(self.whitelist_toggle_button)
        st.polish(self.whitelist_toggle_button)
    
    def set_whitelist(self):
        enabled = self.whitelist_toggle_button.text() == "Enabled"
        self.universal_settings["whitelist enabled"] = enabled

        if self.status == "online" and self.bus is not None:
            self.bus.enable_whitelist.emit(enabled)

    def add_player_to_whitelist(self):
        player = self.whitelist_add_textbox.text()
        if player:
            player_obj = queries.get_player_uuid(player)
            if player_obj:
                try:
                    with open(self.path(self.server_path, "whitelist.json"), 'r') as f:
                        curr_whitelists = json.loads(f.read())
                except FileNotFoundError:
                    with open(self.path(self.server_path, "whitelist.json"), 'w') as f:
                        json.dump([player_obj], f, indent=2)
                    self.whitelist_add_textbox.clear()
                    return
                
                already_whitelisted = False
                for obj in curr_whitelists:
                    if obj["name"] == player:
                        already_whitelisted = True
                        break
                
                if not already_whitelisted:
                    curr_whitelists.append(player_obj)
                    with open(self.path(self.server_path, "whitelist.json"), 'w') as f:
                        json.dump(curr_whitelists, f, indent=2)
            if self.status == "online" and self.bus is not None:
                self.bus.whitelist_player.emit(player, False)
            
            self.whitelist_add_textbox.clear()
    
    def update_view_distance(self):
        distance = self.view_distance_textbox.text()
        if distance and distance.isdigit():
            distance = min(32, max(3, int(distance)))
            self.universal_settings["view distance"] = int(distance)

    def update_simulation_distance(self):
        distance = self.simulation_distance_textbox.text()
        if distance and distance.isdigit():
            distance = min(32, max(3, int(distance)))
            self.universal_settings["simulation distance"] = int(distance)
    
    def leave_commands_page(self):
        self.set_whitelist()
        self.update_view_distance()
        self.update_simulation_distance()
        file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
        file_funcs.update_all_universal_settings(self.server_path)
        if self.status == "online" and self.bus is not None:
            self.bus.view_distance.emit(int(self.universal_settings["view distance"]))
            self.bus.simulation_distance.emit(int(self.universal_settings["simulation distance"]))
        self.show_main_page()
    
    def move_world_to_top(self, world):
        self.world_order.remove(world)
        self.world_order.insert(0, world)
        current_selected = self.dropdown.currentText()
        self.dropdown.clear()
        self.dropdown.addItems(self.world_order)
        self.dropdown.setCurrentText(current_selected)
        file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.world_order, self.universal_settings, self.saved_ip)
    
    def open_player_context_menu(self, pos):
        item = self.players_info_box.itemAt(pos)
        if not item or not self.is_api_compatible(self.worlds[self.world]["version"]) or item.text() == "No players online":
            return
        
        name = item.text().removesuffix(" [op]")
        menu = QMenu(self)
        options = [
            {
                "file": "ops.json",
                "default": "Op",
                "remove": "De-Op",
                "func": self.op_player
            },
            {
                "file": "whitelist.json",
                "default": "Whitelist",
                "remove": "Remove Whitelist",
                "func": self.whitelist_player
            },
            {
                "file": None,
                "default": "Kick",
                "func": self.kick_player
            },
            {
                "file": None,
                "default": "Ban",
                "func": self.ban_player
            }
        ]

        for option in options:
            label = option.get("default")
            func = option.get("func")
            if not option.get("file"):
                menu.addAction(label, lambda n=name, f=func: f(n))
                continue
            
            with open(self.path(self.server_path, option.get("file")), 'r') as f:
                players = json.loads(f.read())
            
            remove = False
            for player in players:
                if player.get("name") == name:
                    label = option.get("remove")
                    remove = True
            
            menu.addAction(label, lambda n=name, r=remove, f=func: f(n, r))
        
        menu.exec(self.players_info_box.viewport().mapToGlobal(pos))
    
    def op_player(self, player, remove):
        self.bus.op_player.emit(player, remove)
        if remove:
            self.notify_player(player, "Your operator status has been removed.")
            self.msg_player(player, "Server: Your operator status has been removed.")
        else:
            self.notify_player(player, "You have been given operator status.")
            self.msg_player(player, "Server: You have been given operator status.")
    
    def whitelist_player(self, player, remove):
        self.bus.whitelist_player.emit(player, remove)
    
    def kick_player(self, player):
        self.bus.kick_player.emit(player)
    
    def ban_player(self, player):
        self.bus.ban_player.emit(player)
    
    def notify_player(self, player, msg):
        self.bus.notify_player.emit(player, msg)
    
    def msg_player(self, player, msg):
        self.bus.msg_player.emit(player, msg)
    
    def change_snapshot_state(self, state: Qt.CheckState):
        if self.update_existing_world_button.isHidden():
            new_versions = queries.get_mc_versions(state == Qt.CheckState.Checked)
            self.mc_version_dropdown.clear()
            self.mc_version_dropdown.addItems(new_versions)
        else:
            # In updating page, so limit versions available
            version = self.worlds[self.add_world_label.text()]["version"]
            new_versions = []
            if state == Qt.CheckState.Checked:
                new_versions = queries.get_mc_versions(include_snapshots=True)
                new_versions = new_versions[:new_versions.index(version)]
            else:
                release_versions = queries.get_mc_versions(include_snapshots=False)
                if version in release_versions:
                    new_versions = release_versions[:release_versions.index(version)]
                else:
                    snapshot_versions = queries.get_mc_versions(include_snapshots=True)
                    index = snapshot_versions.index(version)
                    for i in range(index):
                        if snapshot_versions[i] in release_versions:
                            new_versions.append(snapshot_versions[i])
            
            self.mc_version_dropdown.clear()
            self.mc_version_dropdown.addItems(new_versions)
    
    def set_version_range(self, version):
        release_versions = queries.get_mc_versions(include_snapshots=False)
        snapshot_versions = queries.get_mc_versions(include_snapshots=True)
        new_versions = []
        if snapshot_versions[0] == version:
            return False
        elif release_versions[0] == version:
            self.include_snapshots_check.setChecked(True)
            self.include_snapshots_check.setDisabled(True)
            new_versions = snapshot_versions[:snapshot_versions.index(version)]
        else:
            check_index = snapshot_versions.index(version) - 1
            while check_index >= 0:
                check_version = snapshot_versions[check_index]
                if check_version in release_versions:
                    break
                check_index -= 1
            if check_index < 0:
                self.include_snapshots_check.setDisabled(True)
                self.include_snapshots_check.setChecked(True)
                new_versions = snapshot_versions[:snapshot_versions.index(version)]
            else:
                self.include_snapshots_check.setChecked(False)
                self.include_snapshots_check.setDisabled(False)
                new_versions = release_versions[:release_versions.index(snapshot_versions[check_index]) + 1]
        
        self.mc_version_dropdown.clear()
        self.mc_version_dropdown.addItems(new_versions)
        return True
    
    def check_for_hardcore(self):
        if self.gamemode_dropdown.currentText() == "Hardcore":
            self.difficulty_dropdown.clear()
            self.difficulty_dropdown.addItem("Hard")
        else:
            curr_diff = self.difficulty_dropdown.currentText()
            self.difficulty_dropdown.clear()
            self.difficulty_dropdown.addItems(["Peaceful", "Easy", "Normal", "Hard"])
            self.difficulty_dropdown.setCurrentText(curr_diff)

    @pyqtSlot()
    def onWindowStateChanged(self):
        if self.windowState() == Qt.WindowMinimized:
            self.message_timer.stop()
        else:
            self.message_timer.start(1000)
    
    def stop_server_threads(self):
        self.stop_threads.set()
        self.shutdown_bus()
        if self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2.0)
        if self.server:
            self.server.close()

    def closeEvent(self, event):
        try:
            self.broadcast("CLOSING")
        except:
            pass
        self.stop_server_threads()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    server_manager_app = ServerManagerApp()

    server_manager_app.show()
    sys.exit(app.exec())