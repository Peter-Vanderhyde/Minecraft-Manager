import socket
import threading
import datetime
import os
import pyautogui as pag
import pygetwindow as pgw
import time
import json
from mcstatus import JavaServer

import sys
import socket
import queue
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QStackedLayout, QGridLayout, QWidget, QTextBrowser
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter, QPaintEvent
from PyQt6.QtCore import Qt, QRect, QTimer, QThread, pyqtSignal

class BackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.background_image = QPixmap("block_background.png")

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.drawPixmap(QRect(0, 0, self.width(), self.height()), self.background_image)

class ServerManagerApp(QMainWindow):
    def __init__(self):
        super().__init__()

        # Default IP
        #self.host_ip = "25.6.72.126"
        self.host_ip = "127.0.0.1"
        self.port = 5555
        self.server_port = "25565"
        self.server = None
        self.receive_thread = None
        self.message_thread = None
        self.ips = {}
        self.clients = {}
        self.player_list = []
        self.status = ""
        self.server_world = ""
        self.path_list = {}
        self.log_queue = queue.Queue()

        self.stop_threads = threading.Event()

        self.init_ui()
        self.load_ips()
        self.load_worlds()
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
        self.stacked_layout.addWidget(server_manager_page)

        # Set the main layout to the stacked layout
        main_layout.addLayout(self.stacked_layout)

        # Set window title and initial size
        self.setWindowTitle("Server Manager")

        # Set the window icon
        icon = QIcon("block_icon.png")
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
                background-color: #a0a0a0; /* Slightly lighter gray for disabled */
                color: #d0d0d0; /* Lighter text color for disabled */
            }

            #stopButton:disabled,
            #restartButton:disabled {
                background-color: #a0a0a0; /* Slightly lighter gray for disabled */
                color: #d0d0d0; /* Lighter text color for disabled */
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

            QLineEdit, QTextEdit {
                border: 4px solid #4CAF50;
                border-radius: 8px;
                padding: 0px;
            }

            QLabel {
                color: white;
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

    def load_ips(self):
        try:
            with open("server_names.json", 'r') as f:
                self.ips = json.load(f)
            
        except:
            with open("server_names.json", 'w') as f:
                json.dump(self.ips, f)
            self.log_queue.put("Names file not found.")
            self.log_queue.put("Created new server_names.json file.")
    
    def update_names(self):
        with open("names.json", 'w') as f:
            json.dump(self.ips, f)
    
    def load_worlds(self):
        try:
            with open("server_worlds.json", 'r') as f:
                self.path_list = json.load(f)
        
        except:
            with open("server_worlds.json", 'w') as f:
                json.dump(self.path_list, f)
            self.log_queue.put("Worlds file not found.")
            self.log_queue.put("Created new server_worlds.json file")
            return

        def check_properties(path):
            try:
                with open(path, 'r') as f:
                    lines = f.readlines()
                
                edited = False
                found_query = False
                found_port = False
                for i, line in enumerate(lines):
                    if line.startswith("enable-query="):
                        found_query = True
                        compare = "enable-query=true\n"
                        if line != compare:
                            lines[i] = compare
                            edited = True
                    elif line.startswith("query.port="):
                        found_port = True
                        compare = "query.port=25565\n"
                        if line != compare:
                            lines[i] = compare
                            edited = True
                
                if not found_query:
                    lines.append("\nenable-query=true")
                    edited = True
                if not found_port:
                    lines.append("\nquery.port=25565")
                    edited = True
                
                if edited:
                    with open(path, 'w') as f:
                        f.writelines(lines)
            except IOError:
                self.log_queue.put(f"<font color='orange'>WARNING: Was unable to check if '{path}' has query enabled \
                                    while server.properties is being accessed.</font>")
        
        for world, path in self.path_list.items():
            directory = os.path.dirname(path)
            check_path = f"{directory}\\server.properties"
            if os.path.exists(check_path):
                check_properties(check_path)
            else:
                self.log_queue.put(f"<font color='orange'>WARNING: Unable to find 'server.properties' in folder at '{directory}'. \
                                   Make sure the server's .bat file is placed in the server folder.</font>")


    def start_manager_server(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind((self.host_ip, self.port))
        self.server.listen()
        self.server.setblocking(False)
        self.receive_thread = threading.Thread(target=self.receive)
        self.receive_thread.start()
        self.message_thread = threading.Thread(target=self.check_messages)
        self.message_thread.start()
        self.log_queue.put("Manager waiting for connections...")
    
    def receive(self):
        handlers = []
        while not self.stop_threads.is_set():
            try:
                client, address = self.server.accept()
                intention = client.recv(1024).decode("ascii")
                if intention == "connection request":
                    client_thread = threading.Thread(target=self.handle_client, args=(client, address))
                    handlers.append(client_thread)
                    client_thread.start()
            except socket.error as e:
                if e.errno == 10035: # Non blocking socket error
                    time.sleep(0.1) # Avoid CPU usage
                else:
                    print(f"Socket error {e}")
                    break
        
        for thread in handlers:
            thread.join()
    
    def handle_client(self, client, address):
        ip, port = address
        if self.ips.get(ip) is not None:
            self.clients[client] = self.ips.get(ip)
            self.tell(client, "accept")
        else:
            # Get display name
            self.tell(client, "identify")
            stop = False
            while not stop and not self.stop_threads.is_set():
                try:
                    identity = client.recv(1024)
                    if not identity:
                        client.close()
                        return
                    
                    self.clients[client] = identity.decode("ascii")
                    self.ips[ip] = self.clients[client]
                    print(self.ips.items())
                    self.update_names()
                    stop = True
                except socket.error as e:
                    if e.errno == 10035: # Non blocking socket error
                        time.sleep(0.1)
                    else:
                        print(f"Socket error (handler during indentify) {e}")
                        client.close()
                        return
        
        self.log_queue.put(f"{self.clients[client]} has joined the room!")
        self.tell(client, "You have joined the room!")
        for send_client, _ in self.clients.items():
            if send_client is not client:
                self.tell(send_client, f"{self.clients[client]} has joined the room!")
        
        while not self.stop_threads.is_set():
            try:
                message = client.recv(1024)
                if not message:
                    break

                message = message.decode('ascii')
                if not message.startswith("MANAGER-REQUEST"):
                    self.log_queue.put(f'<font color="blue">{self.clients[client]}: {message}</font>')
                    self.broadcast(message, client)
                else:
                    data = message.split(':')[-1].split(',')
                    request, args = data[0], data[1:]
                    if request == "get-status":
                        self.log_queue.put(f"{self.clients[client]} queried the server status.")
                        result = self.query_status()
                        self.log_queue.put(f"Server status is: {result[0]}.")
                        self.tell(client, f"DATA-RETURN(status):{','.join(result)}")
                    elif request == "get-players":
                        self.log_queue.put(f"{self.clients[client]} queried the active players.")
                        self.tell(client, f"DATA-RETURN(players):{self.query_players()}")
                    elif request == "start-server":
                        self.log_queue.put(f"{self.clients[client]} requested to start the server.")
                        self.tell(client, "Starting server...")
                        error = self.start_server(args[0])
                        if error:
                            self.tell(client, f"DATA-RETURN(start):{error}")
                        else:
                            self.tell(client, "DATA-RETURN(start):success")

            except socket.error as e:
                if e.errno == 10035: # Non blocking socket error
                    time.sleep(0.1)
                else:
                    print(f"Socket error (handler) {e}")
                    break
            except Exception as e:
                print(f"Error receiving message from a client: {e}")
                break
        
        client.close()
        self.log_queue.put(f"{self.clients[client]} has left the room.")
        self.broadcast(f"{self.clients[client]} has left the room.")
        self.clients.pop(client)
    
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
                print(f"Error sending message to a client: {e}")
    
    def tell(self, client, message):
        client.sendall(message.encode("ascii"))
    
    def check_messages(self):
        while not self.stop_threads.is_set():
            while not self.log_queue.empty():
                message = self.log_queue.get()
                self.log_box.append(message)
                self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())
    
    def first_load(self):
        self.get_status()
    
    def message_entered(self):
        message = self.message_entry.text()
        if message != "":
            self.message_entry.clear()
            self.log_queue.put(f'<font color="green">You: {message}</font>')
            self.broadcast(f'<font color="blue">Admin: {message}</font>')
    
    def start_server(self, world):
        path = self.path_list.get(world)
        if not path:
            self.log_queue.put(f"<font color='red'>ERROR: world '{world}' is not recognized.</font>")
            return f"<font color='red'>Manager doesn't recognize that world.</font>"
        elif not os.path.exists(path):
            error = f"<font color='red'>Uh oh. Path to world '{world}' no longer exists.</font>"
            self.log_queue.put(f"<font color='red'>ERROR: Unable to find '{world}' at path '{path}'!</font>")
            return error
        else:
            try:
                os.system(path)
                return None
            except:
                error = f"<font color='red'>Uh oh. There was a problem running the server world.</font>"
                self.log_queue.put(f"<font color='red'>ERROR: Problem running world '{world}' at path '{path}'!</font>")
                return error
    
    def stop_server(self):
        pass

    def restart_server(self):
        self.stop_server()
        
    
    def query_status(self):
        try:
            query = JavaServer.lookup(f"25.6.72.126:{self.server_port}", 1).query()
            return "online", f"{query.software.brand} {query.software.version}", query.map
        except TimeoutError:
            return "offline", "", ""
    
    def query_players(self):
        try:
            query = JavaServer.lookup(f"25.6.72.126:{self.server_port}", 1).query()
            return query.players.names
        except TimeoutError:
            return []

    def get_status(self):
        self.set_status("pinging")
        status, version, world = self.query_status()
        if status == "offline":
            self.set_status("offline")
            self.players_info_box.clear()
            self.set_world_list()
        elif status == "online":
            self.set_status("online", version, world)
            self.get_players()
            self.set_world_list()

    def get_players(self):
        self.player_list = self.query_players()
        self.set_players(self.player_list)
    
    def set_status(self, status, version=None, world=None):
        if status == "online":
            self.status = "online"
            self.server_status_label.hide()
            self.server_status_offline_label.hide()
            self.server_status_online_label.show()
            self.version_label.setText(f"Version: {version}")
            self.world_label.setText(f"World: {world}")
            self.refresh_button.setEnabled(True)
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
    
    def set_world_list(self):
        self.dropdown.clear()
        self.dropdown.addItems(self.path_list.keys())
    
    def closeEvent(self, event):
        self.stop_threads.set()
        if self.receive_thread:
            self.receive_thread.join()
        if self.message_thread:
            self.message_thread.join()
        if self.server:
            self.server.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    server_manager_app = ServerManagerApp()

    server_manager_app.show()
    sys.exit(app.exec())