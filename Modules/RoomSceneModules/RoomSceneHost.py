import json
import os

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt6.QtWidgets import QLabel, QMenu, QInputDialog

from Modules.RoomSceneModules.SceneEditor.SceneEditorFlyout import SceneEditorFlyout
from Modules.RoomSceneModules.SceneWidget import SceneWidget
from Utils.ScrollableMenu import ScrollableMenu
from loguru import logger as logging

from Utils.UtilMethods import get_host, get_auth


class RoomSceneHost(ScrollableMenu):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.focus_lock = False
        self.current_top_folder = None
        self.setFixedSize(parent.width(), parent.height() - self.y())

        self.setStyleSheet("border: 2px solid #ffcd00; border-radius: 10px")

        self.menu = QMenu(self)
        self.menu.setStyleSheet("color: white")
        folder_action = self.menu.addAction("Create Folder")
        folder_action.triggered.connect(self.create_folder)
        new_scene_action = self.menu.addAction("Create New Scene")
        new_scene_action.triggered.connect(
            lambda: SceneEditorFlyout(self, None, None).show()
        )

        self.back_widget = SceneWidget(self, -1, None, is_back_widget=True)
        self.scene_data = None
        self.scene_widgets = []

        self.network_manager = QNetworkAccessManager()
        self.network_manager.finished.connect(self.handle_network_response)

        self.folder_level_label = QLabel(self)
        self.folder_level_label.setFont(self.parent.get_font("JetBrainsMono-Regular"))
        self.folder_level_label.setFixedSize(self.width(), 20)
        self.folder_level_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignCenter
        )
        self.folder_level_label.setStyleSheet(
            "color: white; font-size: 15px; font-weight: bold; border: none; background-color: transparent"
        )
        self.folder_level_label.move(0, 2)
        self.folder_level_label.setText("Loading Scene Data...")
        self.folder_path_names = []
        self.folder_path_ids = []

        self.retry_timer = QTimer(self)
        self.retry_timer.timeout.connect(self.make_request)
        self.retry_timer.start(5000)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.make_request)

        self.hide()

        self.make_request()

    def make_request(self):
        logging.info("Requesting routine data")
        request = QNetworkRequest(QUrl(f"{get_host()}/scene_get/scenes/null"))
        request.setRawHeader(b"Cookie", bytes("auth=" + get_auth(), "utf-8"))
        self.network_manager.get(request)

    def handle_network_response(self, reply):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                logging.error(f"Error: {reply.error()}")
                self.retry_timer.start(5000)
                return
            data = reply.readAll()
            data = data.data().decode("utf-8")
            data = json.loads(data)
            # logging.debug(f"Data: {data}")
            self.retry_timer.stop()
            if "error" in data:
                logging.error(f"Error: {data['error']}")
                self.retry_timer.start(5000)
                return
            self.scene_data = data["result"]
            self.handle_scene_data(self.scene_data)
            self.refresh_timer.start(60000)
        except Exception as e:
            logging.error(f"Error handling network response: {e}")
            logging.exception(e)
            self.retry_timer.start(5000)
        finally:
            reply.deleteLater()

    def hideEvent(self, a0):
        self.refresh_timer.start(60000)
        self.current_top_folder = None
        self.folder_path_names = ["Routines"]
        self.folder_path_ids = [None]
        self.back_widget.set_name("Routines")

    def showEvent(self, a0):
        try:
            self.refresh_timer.stop()
        except Exception as e:
            logging.error(f"Error showing host: {e}")
            logging.exception(e)

    def lock_focus(self, lock):
        self.focus_lock = lock

    def reload(self):
        for widget in self.scene_widgets:
            if widget.is_back_widget:
                continue
            widget.hide()
            widget.deleteLater()
        self.scene_widgets = []
        self.make_request()

    def handle_scene_data(self, data):
        for widget in self.scene_widgets:
            if widget.is_back_widget:
                continue
            widget.hide()
            widget.deleteLater()
        self.scene_widgets.clear()
        self.folder_path_names = ["Routines"]
        self.folder_path_ids = [None]
        self.current_top_folder = None
        self.back_widget.set_name("Routines")
        for scene_id, scene in data.items():
            self.scene_widgets.append(SceneWidget(self, scene_id, scene))
        self.scene_widgets.append(self.back_widget)
        self.layout_widgets()

    def update_path_text(self):
        self.folder_level_label.setText(" -> ".join(self.folder_path_names))

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        self.setFixedSize(self.parent.width(), self.height())
        self.folder_level_label.setFixedSize(self.width(), 20)
        self.layout_widgets()

    def move_widgets(self, offset):
        offset = round(offset)
        for widget in self.scene_widgets:
            widget.move(widget.x(), widget.y() + offset)
        self.scroll_offset = 0

    def create_folder(self):
        """
        Create a popup asking for the folder name and then create a folder scene
        :return:
        """
        try:
            diag = QInputDialog()
            diag.setWindowFlags(Qt.WindowType.FramelessWindowHint)
            diag.setLabelText("Enter the folder name:")
            diag.setOkButtonText("Create")
            diag.setCancelButtonText("Cancel")
            diag.exec()
            folder_name = diag.textValue()
            if folder_name == "":
                return
            SceneEditorFlyout(
                self,
                None,
                {
                    "name": folder_name,
                    "data": '{"folder":""}',
                    "parent": self.current_top_folder,
                },
            ).show()
        except Exception as e:
            logging.error(f"Error creating folder: {e}")
            logging.exception(e)

    def get_available_folders(self):
        """
        Returns the folders in the currently viewed folder that a scene could be moved to
        :return: List of folder scene ids and names
        """
        available_folders = []
        for widget in self.scene_widgets:
            if (
                widget.is_folder
                and widget.parent_scene == self.current_top_folder
                and not widget.is_back_widget
            ):
                available_folders.append((widget.scene_id, widget.data["name"]))
        # Additionally look one level up to allow moving scenes out from a parent folder
        if self.current_top_folder is not None:
            outer_folder = self.folder_path_ids[-2]
            if outer_folder is None:
                available_folders.append((None, "Routines"))
            else:
                for widget in self.scene_widgets:
                    if (
                        widget.is_folder
                        and widget.scene_id == outer_folder
                        and not widget.is_back_widget
                    ):
                        available_folders.append((widget.scene_id, widget.data["name"]))
        return available_folders

    def contextMenuEvent(self, ev):
        try:
            self.menu.exec(ev.globalPos())
        except Exception as e:
            logging.error(f"Error in contextMenuEvent: {e}")
            logging.exception(e)

    def open_folder(self, folder_id):
        folder_name = [
            widget.data["name"]
            for widget in self.scene_widgets
            if widget.scene_id == folder_id
        ][0]
        if folder_id == -1:
            if len(self.folder_path_names) == 1:
                return
            self.back_widget.set_name(self.folder_path_names[-1])
            self.folder_path_names.pop()
            self.folder_path_ids.pop()
            self.current_top_folder = self.folder_path_ids[-1]
        else:
            self.back_widget.set_name(self.folder_path_names[-1])
            self.folder_path_names.append(folder_name)
            self.folder_path_ids.append(folder_id)
            self.current_top_folder = folder_id
        self.layout_widgets()

    def find_orphans(self):
        for widget in self.scene_widgets:
            if widget.parent_scene is not None:
                if not any(
                    [
                        scene.scene_id == widget.parent_scene
                        for scene in self.scene_widgets
                    ]
                ):
                    logging.warning(
                        f"Scene {widget.scene_id} has a parent that does not exist"
                    )
                    widget.orphaned()

    def layout_widgets(self):
        # Hide all the widgets
        for widget in self.scene_widgets:
            widget.hide()

        self.update_path_text()

        self.find_orphans()
        current_widgets = [
            widget
            for widget in self.scene_widgets
            if (
                widget.parent_scene == self.current_top_folder
                and not widget.is_back_widget
            )
            or (widget.is_back_widget and self.current_top_folder is not None)
        ]
        # Sort the scenes by number of triggers (lowest to highest, excluding the new scene widget)
        current_widgets.sort(
            key=lambda x: (
                x.is_back_widget,
                x.is_folder,
                len(x.data["triggers"]) if not x.is_folder else 0,
            )
        )

        # Lay the widgets out row by row with a 10 pixel margin
        y_offset = 22
        x_offset = 5
        center_offset = []
        row_num = 0
        widget_num = 0
        has_back_widget = self.current_top_folder is not None
        # Start a new row when the widgets won't fit on the current row
        for widget in current_widgets:
            widget.move(x_offset, y_offset)
            widget.row_num = row_num
            widget.show()
            x_offset += widget.width() + 7
            widget_num += 1
            # Wrap around to the next row if the widget won't fit on the current row
            if x_offset + widget.width() > self.width() or (
                widget_num == len(current_widgets) - 1 and has_back_widget
            ):
                center_offset.append(round((self.width() - x_offset - 5) / 2))
                row_num += 1
                x_offset = 5
                y_offset += widget.height() + 10

        center_offset.append(round((self.width() - x_offset - 5) / 2))
        row_num += 1

        # Center the widgets
        for widget in current_widgets:
            widget.move(widget.x() + center_offset[widget.row_num], widget.y())
