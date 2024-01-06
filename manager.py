import sys
import socket
import queue
import time
import threading
import json
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QStackedLayout, QGridLayout, QWidget, QTextBrowser
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter, QPaintEvent
from PyQt6.QtCore import Qt, QRect, QThread, pyqtSignal, QObject

class BackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.background_image = QPixmap("Images\\block_background.png")

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

    def __init__(self):
        super().__init__()

        # Default IP
        self.host_ip = "25.6.72.126"
        self.port = 5555
        self.client = None
        self.close_threads = threading.Event()
        self.receive_thread = None
        self.message_thread = None
        self.connection_thread = None
        self.status = ""
        self.server_version = ""
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
        
        self.init_ui()
        self.connect_button.clicked.connect(self.start_connection_thread)

    def init_ui(self):

        # Central widget to hold everything
        central_widget = BackgroundWidget(self)
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout(central_widget)

        # Stacked layout to manage pages
        self.stacked_layout = QStackedLayout()

        # Page 1: Connect to Server
        connect_layout = QVBoxLayout()
        input_layout = QVBoxLayout()
        input_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        host_ip_label = QLabel("Host IP:")
        host_ip_label.setObjectName("mediumText")
        host_ip_label.setFont(QFont(host_ip_label.font().family(), int(host_ip_label.font().pointSize() * 1.5)))
        host_ip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.host_ip_entry = QLineEdit(self.host_ip)  # Set default IP
        self.host_ip_entry.setMaximumWidth(self.width() // 2)
        self.host_ip_entry.setFont(QFont(self.host_ip_entry.font().family(), int(self.host_ip_entry.font().pointSize() * 1.5)))
        self.host_ip_entry.setPlaceholderText("IP Address")
        self.connect_button = QPushButton("Connect")

        input_layout.addWidget(host_ip_label)
        input_layout.addWidget(self.host_ip_entry)
        input_layout.addWidget(self.connect_button)

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

        connect_layout.addLayout(input_layout)
        connect_layout.addLayout(message_layout)

        connect_page = QWidget()
        connect_page.setLayout(connect_layout)

        # Page 2: Name Prompt
        name_prompt_layout = QVBoxLayout()
        name_prompt_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_entry = QLineEdit()
        self.name_entry.setMaximumWidth(self.width() // 2)
        self.name_entry.setFont(QFont(self.name_entry.font().family(), int(self.name_entry.font().pointSize() * 1.5)))
        self.name_entry.setPlaceholderText("Display Name")
        self.name_entry.returnPressed.connect(self.send_name)

        name_prompt_layout.addWidget(self.name_entry)

        name_prompt_page = QWidget()
        name_prompt_page.setLayout(name_prompt_layout)

        # Page 3: Server Manager
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
        self.log_box.setReadOnly(True)
        self.message_entry = QLineEdit()
        self.message_entry.setPlaceholderText("Send Message")
        self.message_entry.returnPressed.connect(self.on_message_entered)

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
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setObjectName("stopButton")
        self.restart_button = QPushButton("Restart")
        self.restart_button.clicked.connect(self.restart_server)
        self.restart_button.setObjectName("restartButton")

        functions_layout = QGridLayout()
        functions_layout.addWidget(self.functions_label, 0, 0, 1, 2)  # Label spanning two columns
        functions_layout.addWidget(self.start_button, 1, 0)

        # Create a horizontal layout for the dropdown and add it to the grid
        dropdown_layout = QHBoxLayout()
        self.dropdown = QComboBox()
        dropdown_layout.addWidget(self.dropdown)  # Dropdown for start options
        functions_layout.addLayout(dropdown_layout, 1, 1)

        functions_layout.addWidget(self.stop_button, 2, 0, 1, 2)  # Spanning two columns
        functions_layout.addWidget(self.restart_button, 3, 0, 1, 2)  # Spanning two columns
        functions_layout.setColumnStretch(1, 1)  # Stretch the second column

        right_column_layout.addLayout(functions_layout)
        right_column_layout.addStretch(1)  # Add empty space at the bottom

        server_manager_layout.addLayout(left_column_layout, 2)  # Make the left column twice as wide
        server_manager_layout.addLayout(center_column_layout, 5)  # Keep the center column as it is
        server_manager_layout.addLayout(right_column_layout, 2)  # Make the right column twice as wide

        server_manager_page = QWidget()
        server_manager_page.setLayout(server_manager_layout)

        # Add pages to the stacked layout
        self.stacked_layout.addWidget(connect_page)
        self.stacked_layout.addWidget(name_prompt_page)
        self.stacked_layout.addWidget(server_manager_page)

        # Set the main layout to the stacked layout
        main_layout.addLayout(self.stacked_layout)

        # Set window title and initial size
        self.setWindowTitle("Server Manager")

        # Set the window icon
        icon = QIcon("Images\\block_icon.png")
        self.setWindowIcon(icon)

        # Apply styles for a colorful appearance
        self.setStyleSheet(
            """
            text {
                color: white;
            }
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 5px 15px;
                text-align: center;
                text-decoration: none;
                font-size: 16px;
                margin: 4px 2px;
                border-radius: 8px;
            }
                           
            QPushButton:hover {
                background-color: #45a049; /* Change background color on hover */
            }

            QPushButton:pressed {
                background-color: #3c9039; /* Change background color when pressed */
            }
                           
            QPushButton:disabled {
                background-color: #d3d3d3; /* Light gray */
            }

            #stopButton {
                color: lightcoral; /* Text color */
                background-color: darkred; /* Background color of the text outline */
            }

            #stopButton:hover {
                background-color: #780000; /* Darker red on hover */
            }

            #stopButton:pressed {
                background-color: #660000; /* Even darker red when pressed */
            }

            #restartButton {
                background-color: #3b5998; /* Blue variant */
                color: #4285f4;
            }

            #restartButton:hover {
                background-color: #2d4278; /* Darker blue on hover */
            }

            #restartButton:pressed {
                background-color: #1d2951; /* Even darker blue when pressed */
            }

            #stopButton:disabled,
            #restartButton:disabled {
                background-color: #a0a0a0; /* Slightly lighter gray for disabled */
                color: #d0d0d0; /* Lighter text color for disabled */
            }

            QLineEdit, QTextEdit {
                border: 4px solid #4CAF50;
                border-radius: 8px;
                padding: 0px;
            }

            QLabel {
                color: white;
            }

            #mediumText {
                font-size: 27px;
            }
                           
            #connectingText {
                color: #4285f4;
                font-size: 28px;
            }

            #messageText {
                color: white;
                font-size: 18px;
            }

            #details {
                font-size: 16px;
            }
                           
            #statusOnline {
                color: lightgreen; /* Text color */
                background-color: darkgreen; /* Background color of the text outline */
                padding: 3px; /* Adjust padding as needed */
                border-radius: 5px;
                text-align: center;
            }
            
            #statusOffline {
                color: lightcoral; /* Text color */
                background-color: darkred; /* Background color of the text outline */
                padding: 3px; /* Adjust padding as needed */
                border-radius: 5px;
                text-align: center;
            }
        """)
    
    def delay(self, delay_amount):
        end_time = time.time() + delay_amount
        while time.time() < end_time:
            QApplication.processEvents()
    
    def start_connection_thread(self):
        if self.host_ip_entry.text() == "":
            return
        
        self.host_ip = self.host_ip_entry.text()
        
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
        messages = []
        while not self.close_threads.is_set():
            try:
                message = self.client.recv(1024).decode("utf-8")
                if not message:
                    self.close_threads.set()
                    break

                messages += message.split("SERVER-MESSAGE:")[1:]
                if "CLOSING" in messages:
                    break

                while len(messages) != 0:
                    message = messages.pop(0)
                    if not message.startswith("DATA-RETURN"):
                        self.log_queue.put(message)
                    else:
                        data = message.split(':')
                        key, args = data[0][data[0].find('(')+1:data[0].find(')')], json.loads(data[1])
                        if key == "status":
                            self.set_status_signal.emit(args)
                        elif key == "players":
                            self.set_players_signal.emit(args)
                        elif key == "worlds-list":
                            self.set_worlds_list_signal.emit(args)
                        elif key in ["start", "stop"] and args == ["refresh"]:
                            self.get_status_signal.emit()
            except socket.error as e:
                if e.errno == 10035:
                    time.sleep(0.1)
                else:
                    self.close_threads.set()
                    break
        
        self.switch_to_connect_signal.emit()

    def display_delay_messages(self):
        for i, label in enumerate(self.connection_delabels):
            label.setText(self.connection_delay_messages[i])
    
    def send(self, message):
        self.client.sendall(f"CLIENT-MESSAGE:{message}".encode("utf-8"))

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
    
    def switch_to_connect_page(self):
        self.close_threads.set()
        self.close_connection_thread()
        if self.receive_thread:
            self.receive_thread.join()
        if self.message_thread:
            self.message_thread.join()
        if self.client:
            self.client.close()
        self.stacked_layout.setCurrentIndex(0)
        self.connecting_label.setText("Lost Connection")
        self.close_threads.clear()
        self.log_box.clear()
        self.set_status(["pinging", "", ""])

    def check_messages(self):
        while not self.close_threads.is_set():
            while not self.log_queue.empty():
                message = self.log_queue.get()
                self.update_log_signal.emit(message)

    def first_connect(self):
        self.get_worlds_list()
        self.get_status()

    def get_status(self):
        self.set_status(["pinging",None,None])
        self.send("MANAGER-REQUEST:get-status")

    def get_players(self):
        self.send("MANAGER-REQUEST:get-players")

    def get_worlds_list(self):
        self.send("MANAGER-REQUEST:get-worlds-list")
    
    def start_server(self, world):
        self.send(f"MANAGER-REQUEST:start-server,{world}")
    
    def stop_server(self):
        self.send("MANAGER-REQUEST:stop-server")
    
    def restart_server(self):
        self.send("MANAGER-REQUEST:restart-server")
    
    def set_status(self, info):
        status, version, world = info
        if status == "online":
            self.status = "online"
            self.server_status_label.hide()
            self.server_status_offline_label.hide()
            self.server_status_online_label.show()
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
    
    def set_worlds_list(self, worlds):
        self.dropdown.clear()
        self.dropdown.addItems(worlds)
    
    def update_log(self, message):
        self.log_box.append(message)
        scrollbar = self.log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def closeEvent(self, event):
        self.send("CLOSING")
        self.close_threads.set()
        self.close_connection_thread()
        if self.receive_thread:
            self.receive_thread.join()
        if self.message_thread:
            self.message_thread.join()
        if self.client:
            self.client.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    server_manager_app = ServerManagerApp()

    server_manager_app.show()
    sys.exit(app.exec())