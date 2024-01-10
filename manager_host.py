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
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QStackedLayout, QGridLayout, QWidget, QTextBrowser
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter, QPaintEvent
from PyQt6.QtCore import Qt, QRect, pyqtSignal, QTimer, pyqtSlot

import queries
import file_funcs

TESTING = False
VERSION = "v2.3"

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
        self.default_ip = "127.0.0.1"
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
        self.host_ip, self.ips, self.server_path, self.worlds = file_funcs.load_settings(self.default_ip, self.log_queue, self.file_lock)
        if self.server_path == "" or not os.path.isdir(self.server_path):
            self.message_timer.stop()
            self.show_server_entry_page()
            # self.show_error_page("Server Path is Invalid", "Set the path in 'manager_settings.json'")
        else:
            self.start_manager_server()
            self.first_load()

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
        self.current_players_label = QLabel("Current Players")
        self.current_players_label.setFont(QFont(self.current_players_label.font().family(), int(self.current_players_label.font().pointSize() * 1.5)))
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.get_players)
        self.players_info_box = QTextBrowser()

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
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accepted_eula)
        bot_box.addWidget(self.ok_button)

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

        # Page 3: Connect to Server
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
        self.browse_button.clicked.connect(lambda: self.server_folder_path_entry.setText(file_funcs.show_folder_dialog(self) or
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

        # Add pages to the stacked layout
        self.stacked_layout.addWidget(server_manager_page)
        self.stacked_layout.addWidget(error_page)
        self.stacked_layout.addWidget(server_path_page)

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
        file_funcs.open_folder(self.server_path)
    
    def delay(self, delay_amount):
        end_time = time.time() + delay_amount
        while time.time() < end_time:
            QApplication.processEvents()
    
    def show_main_page(self):
        self.host_ip, self.ips, self.server_path, self.worlds = file_funcs.load_settings(self.default_ip, self.log_queue, self.file_lock)
        self.stacked_layout.setCurrentIndex(0)
    
    def show_error_page(self, error, info, ok_button=False):
        self.error_label.setText(error)
        self.info_label.setText(info)
        if ok_button:
            self.ok_button.show()
            self.folder_button.show()
        else:
            self.ok_button.hide()
            self.folder_button.hide()
        self.stacked_layout.setCurrentIndex(1)
    
    def show_server_entry_page(self):
        self.stacked_layout.setCurrentIndex(2)
    
    def check_server_path(self, new_text):
        self.existing_server_button.setEnabled(os.path.isdir(new_text))
        self.create_server_button.setEnabled(new_text != "")


    def start_manager_server(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.server.bind((self.host_ip, self.port))
            self.server.listen()
            self.server.setblocking(False)
        except:
            self.show_error_page("Unable to Start Manager", "Is Hamachi open?")
            return
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
                    file_funcs.update_settings(self.file_lock, self.host_ip, self.ips, self.server_path, self.worlds)
                    stop = True
                except socket.error as e:
                    if e.errno == 10035: # Non blocking socket error
                        pass
                    else:
                        client.close()
                        return
                
                time.sleep(1)
        
        self.log_queue.put(f"{self.clients[client]} has joined the room!")
        self.tell(client, "You have joined the room!")
        for send_client, _ in self.clients.items():
            if send_client is not client:
                self.tell(send_client, f"{self.clients[client]} has joined the room!")
        
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
                                        self.send_data("status", ["offline", "", ""])
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
                                        self.send_data("start", "refresh")
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
        self.log_queue.put(f"{self.clients[client]} has left the room.")
        self.broadcast(f"{self.clients[client]} has left the room.")
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
                        self.tell(client, f'<font color="blue">{name}: {message}</font>')
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
        elif not os.path.exists(path):
            error = f"<font color='red'>Uh oh. Path to world '{world}' no longer exists.</font>"
            self.log_queue.put(f"<font color='red'>ERROR: Unable to find '{world}' at path '{path}'!</font>")
            return error
        else:
            try:
                if not restart:
                    self.log_queue.put(f"Preparing for version {version}.")
                    self.delay(1)
                    if not file_funcs.prepare_server_settings(world, version, fabric, self.server_path, self.log_queue):
                        raise RuntimeError("Failed to prepare settings.")
                
                os.system(f'start /min cmd /C "title Server Ignition && cd /d {self.server_path} && run.bat"')
                loop = True
                window = None
                ignition_window = None
                end_time = time.time() + 30
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

                self.delay(8)

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
            self.version_label.setText(f"Version: {version} {'Fabric' * self.worlds[world]['fabric']}")
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
            file_funcs.update_settings(self.file_lock, self.host_ip, self.ips, path, self.worlds)
            self.show_main_page()
            self.start_manager_server()
            self.first_load()
    
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
        self.message_timer.start(1000)
            
        file_funcs.update_settings(self.file_lock, self.host_ip, self.ips, path, self.worlds)
        
        self.log_queue.put("Downloading latest server.jar file...")
        self.delay(0.5)
        version = queries.download_latest_server_jar(path, self.log_queue)
        if version:
            self.log_queue.put("Generating server files...")
            self.delay(0.5)
            subprocess.run(["java", "-jar", f"server-{version}.jar"], cwd=path)
            self.server_path = path
            self.accepted_eula()
    
    def accepted_eula(self):
        with open(os.path.join(self.server_path, "eula.txt")) as f:
            content = f.read()
        if "eula=false" in content:
            self.show_error_page("You must agree to the EULA in order to run the server.",
                                    "Please open 'eula.txt' in the server folder.", True)
        elif "eula=true" in content:
            self.show_main_page()
            self.start_manager_server()
            self.first_load()
    
    @pyqtSlot()
    def onWindowStateChanged(self):
        if self.windowState() == Qt.WindowMinimized:
            self.message_timer.stop()
        else:
            self.message_timer.start(1000)
    
    def closeEvent(self, event):
        try:
            self.broadcast("CLOSING")
        except:
            pass
        self.stop_threads.set()
        if self.receive_thread.is_alive():
            self.receive_thread.join()
        if self.server:
            self.server.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    server_manager_app = ServerManagerApp()

    server_manager_app.show()
    sys.exit(app.exec())