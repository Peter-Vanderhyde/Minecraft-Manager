import socket
import threading
import os
import pyautogui as pag
import pygetwindow as pgw
import time
import json
import sys
import queue
import subprocess
import glob
import shutil
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QStackedLayout, QGridLayout, QWidget, QTextBrowser, QCheckBox, QFrame
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter, QPaintEvent
from PyQt6.QtCore import Qt, QRect, pyqtSignal, QTimer, pyqtSlot

import queries
import file_funcs

TESTING = False
VERSION = "v2.3.1"

if TESTING:
    STYLE_PATH = "Styles"
    IMAGE_PATH = "Images"
else:
    STYLE_PATH = sys._MEIPASS
    IMAGE_PATH = sys._MEIPASS

class BackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.background_image = QPixmap(os.path.join(IMAGE_PATH, "block_background.png"))

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
    set_players_signal = pyqtSignal(list)

    def __init__(self):
        super().__init__()

        # Default IP
        self.default_ip = "25.6.72.126"
        self.saved_ip = ""
        self.host_ip = ""
        self.port = 5555
        self.server_port = "25565"
        self.server = None
        self.receive_thread = threading.Thread(target=self.receive)
        self.message_timer = QTimer(self)
        self.message_timer.timeout.connect(self.check_messages)
        self.ips = {}
        self.clients = {}
        self.status = ""
        self.server_path = ""
        self.previous_world = ""
        self.worlds = {}
        self.log_queue = queue.Queue()

        self.no_clients = True
        self.stop_threads = threading.Event()
        self.file_lock = threading.Lock()

        # Signals
        self.get_status_signal.connect(self.get_status)
        self.set_status_signal.connect(self.set_status)
        self.set_players_signal.connect(self.set_players)

        self.init_ui()
        self.host_ip, self.ips, self.server_path, self.worlds = file_funcs.load_settings(self.log_queue, self.file_lock)
        self.saved_ip = self.host_ip
        self.clear_log_queue()
        
        if self.server_path == "" or not os.path.isdir(self.server_path):
            self.message_timer.stop()
            self.show_server_entry_page()
            # self.show_error_page("Server Path is Invalid", "Set the path in 'manager_settings.json'")
        else:
            self.start_manager_server()

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
        self.players_info_box = QTextBrowser()

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
        self.version_label.setObjectName("details")
        self.world_label = QLabel("Server World: ")
        self.world_label.setObjectName("details")
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
        self.restart_button = QPushButton("Restart")
        self.restart_button.clicked.connect(self.restart_server)
        self.restart_button.setObjectName("blueButton")

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Raised)

        self.world_options = QPushButton("World Options")
        self.world_options.clicked.connect(self.show_world_options_page)
        self.open_folder_button = QPushButton("Server Folder")
        self.open_folder_button.clicked.connect(self.open_server_folder)
        self.open_properties_button = QPushButton("Server Properties")
        self.open_properties_button.clicked.connect(self.open_properties)

        functions_layout = QGridLayout()
        functions_layout.addWidget(self.functions_label, 0, 0, 1, 2)  # Label spanning two columns
        functions_layout.addWidget(self.start_button, 1, 0, 2, 1)

        # Create a horizontal layout for the dropdown and add it to the grid
        dropdown_layout = QHBoxLayout()
        self.dropdown = QComboBox()
        self.dropdown.currentTextChanged.connect(self.set_selected_world_version)
        dropdown_layout.addWidget(self.dropdown)  # Dropdown for start options
        functions_layout.addLayout(dropdown_layout, 1, 1)
        functions_layout.addWidget(self.world_version_label, 2, 1)

        functions_layout.addWidget(self.stop_button, 3, 0, 1, 2)  # Spanning two columns
        functions_layout.addWidget(self.restart_button, 4, 0, 1, 2)  # Spanning two columns
        functions_layout.addWidget(separator, 5, 0, 1, 2)
        functions_layout.addWidget(self.world_options, 6, 0, 1, 2)
        functions_layout.addWidget(self.open_folder_button, 7, 0, 1, 2)
        functions_layout.addWidget(self.open_properties_button, 8, 0, 1, 2)
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
        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self.error_label.setObjectName("error")
        top_box.addWidget(self.error_label)
        bot_box = QVBoxLayout()
        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.info_label.setObjectName("details")
        bot_box.addWidget(self.info_label)
        self.folder_button = QPushButton("Open Server Folder")
        self.folder_button.clicked.connect(self.open_server_folder)
        bot_box.addWidget(self.folder_button)
        self.eula_ok_button = QPushButton("OK")
        self.eula_ok_button.clicked.connect(self.accepted_eula)
        bot_box.addWidget(self.eula_ok_button)

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

        self.hosting_ip_entry = QLineEdit(self.default_ip)  # Set default IP
        self.hosting_ip_entry.setMinimumWidth(self.width() // 2)
        self.hosting_ip_entry.setMaximumWidth(self.width() // 2)
        self.hosting_ip_entry.setFont(QFont(self.hosting_ip_entry.font().family(), int(self.hosting_ip_entry.font().pointSize() * 1.5)))
        self.hosting_ip_entry.setPlaceholderText(self.host_ip or self.default_ip)
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

        create_new_button = QPushButton("Create New World")
        create_new_button.clicked.connect(self.add_new_world)
        select_existing_button = QPushButton("Add Existing World")
        select_existing_button.clicked.connect(self.add_existing_world)
        remove_world_button = QPushButton("Remove World")
        remove_world_button.clicked.connect(self.prepare_remove_world_page)
        remove_world_button.setObjectName("redButton")
        backup_button = QPushButton("Save Backup")
        backup_button.clicked.connect(self.backup_world)
        backup_button.setObjectName("yellowButton")
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("smallRedButton")
        cancel_button.clicked.connect(self.show_main_page)

        top_box.addWidget(create_new_button)
        top_box.addWidget(select_existing_button)
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
        self.new_world_seed_edit = QLineEdit("")
        self.new_world_seed_edit.setObjectName("lineEdit")
        self.new_world_seed_edit.setPlaceholderText("(Optional) World Seed")
        self.new_world_seed_edit.hide()
        temp_box = QHBoxLayout()
        self.mc_version_label = QLabel("Version: ")
        self.mc_version_label.setObjectName("details")
        self.mc_version_dropdown = QComboBox()
        versions = queries.get_mc_versions()
        if versions:
            self.mc_version_dropdown.addItems(versions)
        self.is_fabric_check = QCheckBox("Fabric")
        self.is_fabric_check.setObjectName("checkbox")
        self.add_existing_world_button = QPushButton("Add World")
        self.add_existing_world_button.hide()
        self.add_existing_world_button.clicked.connect(self.confirm_add_world)
        self.create_new_world_button = QPushButton("Create World")
        self.create_new_world_button.hide()
        self.create_new_world_button.clicked.connect(self.confirm_create_world)
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("redButton")
        cancel_button.clicked.connect(self.show_world_options_page)
        self.add_world_error = QLabel("")
        self.add_world_error.setObjectName("messageText")

        top_box.addWidget(self.add_world_label)
        top_box.addWidget(self.new_world_name_edit)
        temp_box.addWidget(self.mc_version_label)
        temp_box.addWidget(self.mc_version_dropdown, 1)
        top_box.addLayout(temp_box)
        top_box.addWidget(self.new_world_seed_edit)
        temp = QHBoxLayout()
        temp.addWidget(self.is_fabric_check, 1, Qt.AlignmentFlag.AlignCenter)
        top_box.addLayout(temp)
        bot_box.addWidget(self.add_existing_world_button)
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
        remove_world_cancel_button.clicked.connect(self.show_world_options_page)
        remove_world_confirm_button = QPushButton("Remove")
        remove_world_confirm_button.clicked.connect(self.remove_world)

        temp_box1.addWidget(world_label)
        temp_box1.addWidget(self.worlds_dropdown, 1)

        temp_box2.addWidget(remove_world_cancel_button)
        temp_box2.addWidget(remove_world_confirm_button)

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

        # Add pages to the stacked layout
        self.stacked_layout.addWidget(server_manager_page)
        self.stacked_layout.addWidget(error_page)
        self.stacked_layout.addWidget(server_path_page)
        self.stacked_layout.addWidget(connect_page)
        self.stacked_layout.addWidget(worlds_page)
        self.stacked_layout.addWidget(add_world_page)
        self.stacked_layout.addWidget(remove_world_page)

        # Set the main layout to the stacked layout
        main_layout.addLayout(self.stacked_layout)

        # Set window title and initial size
        self.setWindowTitle("Server Manager")

        # Set the window icon
        icon = QIcon(os.path.join(IMAGE_PATH, "block_icon.png"))
        self.setWindowIcon(icon)

        # Apply styles for a colorful appearance
        with open(os.path.join(STYLE_PATH, "manager_host_style.css"), 'r') as stylesheet:
            style_str = stylesheet.read()
        
        self.setStyleSheet(style_str)
    
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
            saved_ip, self.ips, self.server_path, self.worlds = file_funcs.load_settings(self.log_queue, self.file_lock)
        
        self.stacked_layout.setCurrentIndex(0)
    
    def show_error_page(self, error, info, eula_ok_button=False):
        self.error_label.setText(error)
        self.info_label.setText(info)
        if eula_ok_button:
            self.eula_ok_button.show()
            self.folder_button.show()
        else:
            self.eula_ok_button.hide()
            self.folder_button.hide()
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
    
    def show_world_options_page(self):
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
                    file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.saved_ip)
                    stop = True
                except socket.error as e:
                    if e.errno == 10035: # Non blocking socket error
                        pass
                    else:
                        client.close()
                        return
                
                time.sleep(1)
        
        self.log_queue.put(f"<font color='blue'>{self.clients[client]} has joined the room!</font>")
        self.tell(client, "You have joined the room!")
        for send_client, _ in self.clients.items():
            if send_client is not client:
                self.tell(send_client, f"<font color='blue'>{self.clients[client]} has joined the room!</font>")
        
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
                        self.log_queue.put(f'<font color="blue">{self.clients[client]}: {message}</font>')
                        self.broadcast(message, client)
                    else:
                        data = message.split('~~>')[-1].split(',')
                        request, args = data[0], data[1:]
                        if request == "get-status":
                            # self.log_queue.put(f"{self.clients[client]} queried the server status.")
                            result = self.query_status()
                            # self.log_queue.put(f"Server status is: {result[0]}.")
                            self.set_status_signal.emit(result)
                            self.send_data("status", result)
                        elif request == "get-players":
                            status = self.query_status()
                            # self.log_queue.put(f"{self.clients[client]} queried the active players.")
                            if status[0] == "online":
                                players = self.query_players()
                                self.set_players_signal.emit(players)
                                self.send_data("players", players)
                            else:
                                self.set_status_signal.emit(status)
                                self.tell(client, "The server has closed.")
                                self.send_data("status", status)
                        elif request == "get-worlds-list":
                            self.send_data("worlds-list", self.query_worlds(), client)
                        elif request in ["start-server", "stop-server", "restart-server"]:
                            self.log_queue.put(f"{self.clients[client]} requested to {request[:request.find('-')]} the server.")
                            if request in ["stop-server", "restart-server"]:
                                error = self.stop_server()
                                if error:
                                    if error == "already offline":
                                        self.tell(client, "Server already stopped.")
                                        updated_status = self.query_status()
                                        self.set_status_signal.emit(updated_status)
                                        self.send_data("status", updated_status)
                                    else:
                                        self.tell(client, error)
                            if request in ["start-server", "restart-server"]:
                                error = None
                                if request == "start-server":
                                    error = self.start_server(args[0])
                                else:
                                    error = self.start_server(self.previous_world)
                                if error:
                                    if error == "already online":
                                        self.tell(client, "Server already running.")
                                        updated_status = self.query_status()
                                        self.set_status_signal.emit(updated_status)
                                        self.send_data("status", updated_status)
                                    else:
                                        self.tell(client, error)

            except socket.error as e:
                if e.errno == 10035: # Non blocking socket error
                    pass
                else:
                    break
            except Exception as e:
                break

            time.sleep(0.5)
        
        client.close()
        self.log_queue.put(f"<font color='blue'>{self.clients[client]} has left the room.</font>")
        self.broadcast(f"<font color='blue'>{self.clients[client]} has left the room.</font>")
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
        client.sendall(f"SERVER-MESSAGE~~>{message}".encode("utf-8"))
    
    def check_messages(self):
        while not self.log_queue.empty():
            message = self.log_queue.get()
            self.log_box.append(message)
            scrollbar = self.log_box.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
    
    def first_load(self):
        self.set_worlds_list()
        self.get_status()
    
    def message_entered(self):
        message = self.message_entry.text()
        if message != "":
            self.message_entry.clear()
            self.log_queue.put(f'<font color="green">You: {message}</font>')
            self.broadcast(f'<font color="blue">Admin: {message}</font>')
    
    def start_server(self, world, restart=False):
        if world == "":
            self.log_queue.put(f"<font color='red'>There is no world selected.</font>")
            return f"<font color='red'>There is no world selected.</font>"
        
        status, _, _ = self.query_status()
        if status == "online":
            self.log_queue.put("Server is already online.")
            return "already online"
        
        version, fabric = None, None
        if self.worlds.get(world):
            version = self.worlds[world].get("version")
            fabric = self.worlds[world].get("fabric")
            seed = self.worlds[world].get("seed", None)
        if not version:
            self.log_queue.put(f"<font color='red'>The version is not specified for {world}.</font>")
            return f"<font color='red'>ERROR: World {world} is missing version.</font>"
        
        self.broadcast("Starting server...")
        self.log_queue.put("Starting server...")
        QApplication.processEvents()
        data = self.worlds.get(world)
        path = os.path.join(os.path.join(self.server_path, "worlds"), world)
        if not data:
            self.log_queue.put(f"<font color='red'>ERROR: world '{world}' is not recognized.</font>")
            return f"<font color='red'>Manager doesn't recognize that world.</font>"
        elif not os.path.exists(path) and self.worlds[world].get("seed") is None:
            error = f"<font color='red'>Uh oh. Path to world '{world}' no longer exists.</font>"
            self.log_queue.put(f"<font color='red'>ERROR: Unable to find '{world}' at path '{path}'!</font>")
            return error
        else:
            try:
                if not restart:
                    self.log_queue.put(f"Preparing for {'fabric ' if fabric else ''} version {version}.")
                    if seed is not None:
                        if seed != "":
                            self.log_queue.put(f"Generating world with seed '{seed}'...")
                        else:
                            self.log_queue.put(f"Generating world with random seed...")
                    self.delay(1)
                    if not file_funcs.prepare_server_settings(world, version, fabric, self.server_path, self.log_queue, seed):
                        raise RuntimeError("Failed to prepare settings.")
                    else:
                        if seed is not None:
                            self.worlds[world].pop("seed")
                            file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.saved_ip)
                
                os.system(f'start /min cmd /C "title Server Ignition && cd /d {self.server_path} && run.bat"')
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

                self.get_status_signal.emit()
                self.log_queue.put(f"Server world '{world}' has been started.")
                self.broadcast(f"Server world '{world}' has been started.")
                self.send_data("start", "refresh")
            except:
                error = f"<font color='red'>Uh oh. There was a problem running the server world.</font>"
                self.log_queue.put(f"<font color='red'>ERROR: Problem running world '{world}'!</font>")
                return error
    
    def stop_server(self):
        status, _, _ = self.query_status()
        if status == "offline":
            self.log_queue.put("Server is already offline.")
            return "already offline"

        self.broadcast("Stopping server...")
        self.log_queue.put("Stopping server...")
        windows = pgw.getWindowsWithTitle("Minecraft server")
        window = None
        for w in windows:
            if w.title == "Minecraft server":
                window = w
        
        pgw.getActiveWindow().title
        window.restore()
        window.activate()
        target_pos = pag.Point(window.bottomright.x - 30, window.bottomright.y - 30)
        while pag.position() != target_pos:
            pag.moveTo(target_pos.x, target_pos.y)

        pag.click()
        pag.typewrite("stop")
        pag.keyDown("enter")

        self.delay(3)

        self.get_status_signal.emit()
        self.log_queue.put("Server has been stopped.")
        self.broadcast("Server has been stopped.")
        self.send_data("stop", "refresh")
        return None

    def restart_server(self):
        self.stop_server()
        self.delay(5)
        self.start_server(self.previous_world, True)

    def query_status(self):
        status, brand, version, world = queries.status(self.host_ip, self.server_port)
        if status == "offline":
            return status, "", ""
        else:
            if world:
                world = world.removeprefix("worlds/")
            
            self.previous_world = world or self.previous_world
            return status, f"{brand} {version}", world
    
    def query_players(self):
        return queries.players(self.host_ip, self.server_port)
    
    def query_worlds(self):
        return self.worlds

    def get_status(self):
        self.set_status(["pinging",None,None])
        status = self.query_status()
        self.set_status(status)
        self.send_data("status", status)

    def get_players(self):
        status = self.query_status()
        if status[0] == "online":
            players = self.query_players()
            self.set_players(players)
            self.send_data("players", players)
        else:
            self.set_status(status)
            self.send_data("status", status)
    
    def set_status(self, info):
        status, version, world = info
        if status == "online":
            self.status = "online"
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
            self.restart_button.setEnabled(True)
        elif status == "offline":
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
            self.restart_button.setEnabled(False)
        elif status == "pinging":
            self.status = "pinging"
            self.server_status_label.show()
            self.server_status_offline_label.hide()
            self.server_status_online_label.hide()
            self.version_label.setText("Version:")
            self.world_label.setText("World:")
            self.refresh_button.setEnabled(False)
            self.players_info_box.clear()
            self.refresh_status_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.restart_button.setEnabled(False)

    def set_players(self, players):
        self.players_info_box.clear()
        if len(players) == 0:
            self.players_info_box.append("<font color='red'>No players online</font>")
            return
        
        for player in players:
            self.players_info_box.append(f"<font color='blue'>{player}</font>")
    
    def set_worlds_list(self):
        self.dropdown.clear()
        self.dropdown.addItems(self.worlds.keys())
        self.set_selected_world_version(self.dropdown.currentText())
    
    def set_selected_world_version(self, world):
        if world:
            self.world_version_label.setText(f'v{self.worlds[world]["version"]} {self.worlds[world]["fabric"] * "Fabric"}')
        else:
            self.world_version_label.setText("")
    
    def set_server_path(self):
        path = self.server_folder_path_entry.text()
        if os.path.isdir(path):
            while not self.log_queue.empty():
                self.log_queue.get()
            self.message_timer.start(1000)
            if self.server_path:
                file_funcs.update_settings(self.file_lock, self.ips, path, self.worlds, self.saved_ip)
                saved_ip, self.ips, self.server_path, self.worlds = file_funcs.load_settings(self.log_queue, self.file_lock)
                self.clear_log_queue()
            else:
                self.server_path = path
                file_funcs.update_settings(self.file_lock, self.ips, path, self.worlds, self.saved_ip)
            self.start_manager_server()
    
    def create_server_folder(self):
        path = self.server_folder_path_entry.text()
        def create_path(path):
            if path == "" or os.path.exists(path):
                return
            
            parent = os.path.join(path, os.path.pardir)
            create_path(parent)
            os.mkdir(path)

        if not os.path.isdir(path):
            # Build up directories to the requested one
            create_path(path)
        
        while not self.log_queue.empty():
            self.log_queue.get()
        self.message_timer.start(200)
            
        file_funcs.update_settings(self.file_lock, self.ips, path, self.worlds, self.saved_ip)
        
        self.change_ip_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.refresh_status_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.restart_button.setEnabled(False)
        self.world_options.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.open_properties_button.setEnabled(False)

        self.show_main_page(ignore_load=True)
        self.log_queue.put("Downloading latest server.jar file...")
        self.delay(0.5)
        version = queries.download_latest_server_jar(path, self.log_queue)
        if version:
            self.log_queue.put("Generating server files...")
            self.delay(0.5)
            subprocess.run(["java", "-jar", f"server-{version}.jar"], cwd=path)
            self.server_path = path
            self.message_timer.start(1000)

            self.change_ip_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.refresh_status_button.setEnabled(True)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(True)
            self.restart_button.setEnabled(True)
            self.world_options.setEnabled(True)
            self.open_folder_button.setEnabled(True)
            self.open_properties_button.setEnabled(True)
            
            self.accepted_eula()
    
    def accepted_eula(self):
        with open(os.path.join(self.server_path, "eula.txt")) as f:
            content = f.read()
        if "eula=false" in content:
            self.show_error_page("You must agree to the EULA in order to run the server.",
                                    "Please open 'eula.txt' in the server folder.", True)
        elif "eula=true" in content:
            self.start_manager_server()
    
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
                file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, ip=self.host_ip)
            self.start_manager_server()
    
    def backup_world(self):
        world_path = file_funcs.pick_folder(self, os.path.join(self.server_path, "worlds"))
        if world_path is None:
            return
        
        world_path = os.path.normpath(world_path)
        world_folders = glob.glob(os.path.normpath(os.path.join(self.server_path, "worlds", "*/")))
        if world_path in world_folders:
            try:
                if self.previous_world == os.path.basename(world_path) and self.query_status()[0] == "online":
                    self.log_queue.put(f"<font color='red'>ERROR: Unable to backup world folder while world is being run.</font>")
                    self.show_main_page()
                    return
                
                current_date = datetime.now().strftime("%m-%d-%y")
                new_path = f"{os.path.join(self.server_path, 'backups', os.path.basename(world_path))}_{current_date}"
                if os.path.exists(new_path):
                    index = 1
                    while os.path.exists(f"{new_path}({str(index)})"):
                        index += 1
                    shutil.copytree(world_path, f"{new_path}({str(index)})")
                else:
                    shutil.copytree(world_path, new_path)
                self.log_queue.put(f"<font color='green'>Saved backup of '{os.path.basename(world_path)}'.</font>")
                self.show_main_page()
            except:
                self.log_queue.put(f"<font color='red'>ERROR: Unable to backup world folder.</font>")
                try:
                    new_path = f"{os.path.join(self.server_path, 'backups', os.path.basename(world_path))}_{current_date}"
                    shutil.rmtree(new_path)
                except:
                    pass
                self.show_main_page()
        elif world_path:
            self.log_queue.put(f"<font color='red'>ERROR: Invalid world folder.</font>")
            self.show_main_page()
    
    def add_existing_world(self):
        world_path = file_funcs.pick_folder(self, os.path.join(self.server_path, "worlds"))
        if world_path is None:
            return
        
        world_path = os.path.normpath(world_path)
        world_folders = glob.glob(os.path.normpath(os.path.join(self.server_path, "worlds", "*/")))
        if world_path in world_folders:
            try:
                if os.path.basename(world_path) in self.worlds.keys():
                    self.log_queue.put(f"<font color='red'>ERROR: World '{os.path.basename(world_path)}' already in worlds list.</font>")
                    self.show_main_page()
                    return
                self.mc_version_dropdown.setCurrentIndex(0)
                version = file_funcs.load_version(world_path)
                if version:
                    self.mc_version_dropdown.setCurrentText(version)
                self.add_world(world=os.path.basename(world_path), new=False)
            except:
                self.log_queue.put(f"<font color='red'>ERROR: Unable to add world folder.</font>")
        elif world_path:
            self.log_queue.put(f"<font color='red'>ERROR: Invalid world folder.</font>")
    
    def add_new_world(self):
        self.add_world(new=True)
    
    def add_world(self, world="", new=False):
        if new:
            self.add_existing_world_button.hide()
            self.create_new_world_button.show()
            self.new_world_name_edit.show()
            self.new_world_seed_edit.show()
            self.add_world_label.setText("Create World")

            self.mc_version_dropdown.setCurrentIndex(0)
            self.new_world_seed_edit.setText("")
            self.new_world_name_edit.setText("")
            self.is_fabric_check.setChecked(False)
        else:
            self.add_existing_world_button.show()
            self.create_new_world_button.hide()
            self.new_world_name_edit.hide()
            self.new_world_seed_edit.hide()
            self.add_world_label.setText(world)

            self.is_fabric_check.setChecked(False)
        
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

    def confirm_add_world(self):
        result = self.verify_version(self.mc_version_dropdown.currentText(), self.is_fabric_check.isChecked())
        if result is True:
            self.worlds[self.add_world_label.text()] = {"version": self.mc_version_dropdown.currentText(), "fabric": self.is_fabric_check.isChecked()}
            file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.saved_ip)
            self.set_worlds_list()
            self.send_data("worlds-list", self.query_worlds())
            self.log_queue.put(f"<font color='green'>Successfully added world.</font>")
            self.show_main_page()
        elif result is False:
            self.add_world_error.setText(f"Invalid {'Fabric ' * self.is_fabric_check.isChecked()}Minecraft version.")
        elif result is None:
            self.log_queue.put(f"<font color='red'>ERROR: Unable to download from {'Fabric' if self.is_fabric_check.isChecked() else 'MCVersions'}.</font>")
            self.show_main_page()

    def confirm_create_world(self):
        if self.new_world_name_edit.text() == "" or self.new_world_name_edit.text() in self.worlds.keys():
            self.add_world_error.setText(f"Name invalid or already exists.")
            return
        
        result = self.verify_version(self.mc_version_dropdown.currentText(), self.is_fabric_check.isChecked())
        if result is True:
            self.worlds[self.new_world_name_edit.text()] = {
                "version": self.mc_version_dropdown.currentText(),
                "fabric": self.is_fabric_check.isChecked(),
                "seed": self.new_world_seed_edit.text()
            }
            file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.saved_ip)
            self.set_worlds_list()
            self.send_data("worlds-list", self.query_worlds())
            self.log_queue.put(f"<font color='green'>Successfully added world.</font>")
            self.show_main_page()
        elif result is False:
            self.add_world_error.setText(f"Invalid {'Fabric' * self.is_fabric_check.isChecked()} Minecraft version.")
        elif result is None:
            self.log_queue.put(f"<font color='red'>ERROR: Unable to download from {'Fabric' if self.is_fabric_check.isChecked() else 'MCVersions'}.</font>")
            self.show_main_page()
    
    def remove_world(self):
        world = self.worlds_dropdown.currentText()
        if not world:
            return
        
        if self.delete_world_checkbox.isChecked():
            try:
                folder_path = os.path.join(self.server_path, "worlds", world)
                shutil.rmtree(folder_path)
            except:
                pass
        
        self.worlds.pop(world)
        file_funcs.update_settings(self.file_lock, self.ips, self.server_path, self.worlds, self.saved_ip)
        self.set_worlds_list()
        self.send_data("worlds-list", self.query_worlds())
        self.log_queue.put(f"<font color='green'>Successfully removed world.</font>")
        self.show_main_page()
    
    def open_properties(self):
        file_funcs.open_file(os.path.join(self.server_path, "server.properties"))

    @pyqtSlot()
    def onWindowStateChanged(self):
        if self.windowState() == Qt.WindowMinimized:
            self.message_timer.stop()
        else:
            self.message_timer.start(1000)
    
    def stop_server_threads(self):
        self.stop_threads.set()
        if self.receive_thread.is_alive():
            self.receive_thread.join()
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