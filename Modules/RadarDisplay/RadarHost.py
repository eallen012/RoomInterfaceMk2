import datetime
import json
import os
import queue
import random
import time

from PyQt6.QtCore import QUrl, QTimer, Qt
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import QLabel, QPushButton
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from loguru import logger as logging

from Modules.RadarDisplay.RadarTile import RadarTile
from Utils.UtilMethods import get_host


class RadarHost(QLabel):
    max_frames = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setFixedSize(parent.width(), parent.height() - self.y())
        self.maptile_surface = QLabel(self)

        # Look into the MapTiles folder and determine the range of available map tiles
        self.min_x, self.max_x, self.min_y, self.max_y = self.determine_map_size()
        self.range_x = self.max_x - self.min_x + 1
        self.range_y = self.max_y - self.min_y + 1
        logging.info(
            f"Map Tile Range: {self.min_x}-{self.max_x}, {self.min_y}-{self.max_y} : {self.range_x}x{self.range_y}"
        )
        self.map_tiles = []
        self.maptile_surface.setFixedSize(256 * self.range_x, 256 * self.range_y)

        self.focused = False
        self.playing = False

        # Map drag variables
        self.dragging = False
        self.drag_start = (0, 0)

        self.network_manager = QNetworkAccessManager()
        self.network_manager.finished.connect(self.handle_response)

        self.timestamp_label = QLabel(self)
        self.timestamp_label.setFixedSize(212, 20)
        self.timestamp_label.move(0, 0)
        self.timestamp_label.setStyleSheet(
            "background-color: black; color: #ffcd00; font-size: 14px;"
        )
        self.timestamp_label.setFont(self.parent.get_font("JetBrainsMono-Regular"))
        self.timestamp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timestamp_label.setText("Loading...")

        self.now_button = QPushButton(self)
        self.now_button.setFixedSize(53, 20)
        self.now_button.move(0, 20)
        self.now_button.setText("Now")
        self.now_button.setStyleSheet(
            "background-color: grey; color: white; font-size: 14px;"
        )
        self.now_button.setFont(self.parent.get_font("JetBrainsMono-Regular"))
        self.now_button.clicked.connect(self.now_button_clicked)

        self.play_pause_button = QPushButton(self)
        self.play_pause_button.setFixedSize(53, 20)
        self.play_pause_button.move(53, 20)
        self.play_pause_button.setText("Play")
        self.play_pause_button.setStyleSheet(
            "background-color: grey; color: white; font-size: 14px;"
        )
        self.play_pause_button.setFont(self.parent.get_font("JetBrainsMono-Regular"))
        self.play_pause_button.clicked.connect(self.play_button_clicked)

        self.back_button = QPushButton(self)
        self.back_button.setFixedSize(53, 20)
        self.back_button.move(106, 20)
        self.back_button.setText("Back")
        self.back_button.setStyleSheet(
            "background-color: grey; color: white; font-size: 14px;"
        )
        self.back_button.setFont(self.parent.get_font("JetBrainsMono-Regular"))
        self.back_button.clicked.connect(self.last_frame)

        self.next_frame_button = QPushButton(self)
        self.next_frame_button.setFixedSize(53, 20)
        self.next_frame_button.move(159, 20)
        self.next_frame_button.setText("Next")
        self.next_frame_button.setStyleSheet(
            "background-color: grey; color: white; font-size: 14px;"
        )
        self.next_frame_button.setFont(self.parent.get_font("JetBrainsMono-Regular"))
        self.next_frame_button.clicked.connect(self.next_frame)

        self.loading_label = QLabel(self)
        self.loading_label.setFont(self.parent.get_font("JetBrainsMono-Regular"))
        self.loading_label.setFixedSize(300, 45)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setStyleSheet(
            "color: #ffcd00; font-size: 15px; font-weight: bold; border: none;"
            " background-color: black"
        )
        self.loading_label.setText("Loading Radar Frames [??/??]")
        self.loading_label.move(
            round((self.width() - self.loading_label.width()) / 2), 0
        )
        self.loading_label.hide()

        self.timestamp_list = []
        self.current_frame = 0
        self.zoom_level = 1

        self.playback_timer = QTimer(self)
        self.playback_timer.timeout.connect(self.next_frame)

        self.loading_check_timer = QTimer(self)
        self.loading_check_timer.timeout.connect(self.check_loading)

        self.activity_timer_callback = None

    @staticmethod
    def determine_map_size():
        # Look into the MapTiles folder and determine the range of available map tiles
        min_x, max_x, min_y, max_y = 1000, 0, 1000, 0
        for file in os.listdir("Assets/MapTiles"):
            x, y = map(int, file.split(".")[0].split("-"))
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
        return min_x, max_x, min_y, max_y

    def set_activity_timer_callback(self, callback):
        self.activity_timer_callback = callback

    def check_loading(self):
        # Compare the number of frames still loading to the total number of frames to be loaded
        if all(
            [
                map_tile.outstanding_requests == 0 and map_tile.outstanding_parses == 0
                for map_tile in self.map_tiles
            ]
        ):
            # self.loading_check_timer.stop()
            self.loading_label.hide()
        else:
            self.loading_label.show()
        total_tiles = sum([map_tile.total_frames for map_tile in self.map_tiles])
        downloaded_frames = total_tiles - sum(
            [map_tile.outstanding_requests for map_tile in self.map_tiles]
        )
        loaded_frames = sum([len(map_tile.radar_images) for map_tile in self.map_tiles])
        self.loading_label.setText(
            f"Loading Radar Data [{downloaded_frames}/{total_tiles}]\n"
            f"Parsing Radar Data [{loaded_frames}/{total_tiles}]"
        )

    def last_frame(self):
        self.current_frame -= 2
        if self.current_frame < 0:
            self.current_frame = len(self.timestamp_list) - 2
        self.next_frame()

    def now_button_clicked(self):
        for i, timestamp in enumerate(self.timestamp_list.__reversed__()):
            if timestamp < time.time():
                self.current_frame = len(self.timestamp_list) - i - 2
                break
        self.next_frame()

    def play_button_clicked(self):
        self.playing = not self.playing
        if self.playing:
            self.play_pause_button.setText("Pause")
            self.playback_timer.start(500)
        else:
            self.play_pause_button.setText("Play")
            self.playback_timer.stop()

    def set_focus(self, focus) -> None:
        self.focused = focus
        if focus:
            self.load_maptiles()
            self.playing = False
            self.play_pause_button.setText("Play")
            self.show()
        else:
            self.unload_maptiles()
            self.playback_timer.stop()
            self.hide()

    def unload_maptiles(self):
        for map_tile in self.map_tiles:
            map_tile.deleteLater()
        self.map_tiles.clear()

    def wheelEvent(self, a0) -> None:
        # return
        current_x, current_y = self.maptile_surface.x(), self.maptile_surface.y()
        if a0.angleDelta().y() > 0 and self.zoom_level < 2:
            self.zoom_level += 1
            self.maptile_surface.setFixedSize(
                self.maptile_surface.width() * 2, self.maptile_surface.height() * 2
            )
            for map_tile in self.map_tiles:
                map_tile.change_size(2)
            # Re layout the map tiles
            for i, map_tile in enumerate(self.map_tiles):
                map_tile.move(
                    (i % 4) * self.map_tiles[0].width(),
                    (i // 4) * self.map_tiles[0].height(),
                )
                map_tile.position(
                    (i % 4) * self.map_tiles[0].width(),
                    (i // 4) * self.map_tiles[0].height(),
                )
            self.load_radartiles()
            # Adjust the position of the map tiles to keep the same point in the center
            self.maptile_surface.move(current_x * 2, current_y * 2)
        elif a0.angleDelta().y() < 0 and self.zoom_level > 1:
            self.zoom_level -= 1
            self.maptile_surface.setFixedSize(
                self.maptile_surface.width() // 2, self.maptile_surface.height() // 2
            )
            for map_tile in self.map_tiles:
                map_tile.change_size(0.5)
            # Re layout the map tiles
            for i, map_tile in enumerate(self.map_tiles):
                map_tile.move(
                    (i % 4) * self.map_tiles[0].width(),
                    (i // 4) * self.map_tiles[0].height(),
                )
            self.load_radartiles()
            self.maptile_surface.move(current_x // 2, current_y // 2)

    # Setup mouse events to allow the user to drag the radar map around
    def mousePressEvent(self, event):
        try:
            self.dragging = True
            if self.activity_timer_callback is not None:
                self.activity_timer_callback()
            self.drag_start = (event.pos().x(), event.pos().y())
        except Exception as e:
            logging.error(f"Failed to handle mouse press event: {e}")
            logging.exception(e)

    def mouseMoveEvent(self, event):
        try:
            if self.dragging:
                if self.activity_timer_callback is not None:
                    self.activity_timer_callback()
                dx, dy = (
                    event.pos().x() - self.drag_start[0],
                    event.pos().y() - self.drag_start[1],
                )
                self.maptile_surface.move(
                    self.maptile_surface.x() + dx, self.maptile_surface.y() + dy
                )
                self.drag_start = (event.pos().x(), event.pos().y())
        except Exception as e:
            logging.error(f"Failed to handle mouse move event: {e}")
            logging.exception(e)

    def mouseReleaseEvent(self, event):
        self.dragging = False

    def handle_response(self, reply):
        try:
            if str(reply.error()) != "NetworkError.NoError":
                logging.error(f"Failed to load radar data: {reply.error()}")
                return
            self.loading_check_timer.start(100)
            data = reply.readAll()
            data = json.loads(str(data, "utf-8"))
            self.timestamp_list = data["weather_radar_list"][-self.max_frames :]
            # Find the last timestamp that is less than the current time
            self.current_frame = len(self.timestamp_list) - 2 - 3
            # for i, timestamp in enumerate(self.timestamp_list.__reversed__()):
            #     if timestamp < time.time():
            #         self.current_frame = len(self.timestamp_list) - i - 2
            #         break
            # logging.info(f"Loaded {len(self.timestamp_list)} radar frames")
            for map_tile in self.map_tiles:
                map_tile.load_radar_overlays(self.timestamp_list.__reversed__())
            self.next_frame()
        except Exception as e:
            logging.error(f"Failed to load radar data: {e}")
            logging.exception(e)
        finally:
            reply.deleteLater()

    def next_frame(self):
        try:
            self.current_frame += 1
            self.current_frame %= len(self.timestamp_list)
            for map_tile in self.map_tiles:
                map_tile.set_radar_overlay(self.timestamp_list[self.current_frame])

            time_str = datetime.datetime.fromtimestamp(
                self.timestamp_list[self.current_frame]
            ).strftime("%Y-%m-%d %I:%M%p")
            self.timestamp_label.setText(
                f"{time_str} {str(self.current_frame + 1).zfill(2)}"
                f"/{len(self.timestamp_list)}"
            )

        except Exception as e:
            logging.error(f"Failed to load next frame: {e}")
            logging.exception(e)

    def load_radartiles(self):
        self.loading_label.setText("Acquiring Radar Frame List")
        self.loading_label.show()
        self.network_manager.get(
            QNetworkRequest(QUrl(f"{get_host()}/weather/available_radars"))
        )

    def load_maptiles(self):
        # All map tiles are 256x256 pixels in size and are stored in 'Assets/MapTiles/{x}-{y}.png'
        # The map is 4 tiles wide and 3 tiles tall (15-18, 22-24)
        center_tile_x, center_tile_y = 0, 0
        for y in range(self.min_y, self.max_y + 1):
            for x in range(self.min_x, self.max_x + 1):
                self.map_tiles.append(RadarTile(get_host(), self.maptile_surface, x, y))
        for i, map_tile in enumerate(self.map_tiles):
            map_tile.move((i % self.range_x) * 256, (i // self.range_x) * 256)
            if map_tile.tile_x == 16 and map_tile.tile_y == 22:
                center_tile_x, center_tile_y = map_tile.x(), map_tile.y()
            # Print where the tile was placed
            # logging.info(f"Placed tile {map_tile.tile_x}-{map_tile.tile_y} at {map_tile.x()},{map_tile.y()}")
        # Center the map tile surface so that tile 16-22 is in the center of the screen
        print(f"Center Tile: {center_tile_x}, {center_tile_y}")
        new_x, new_y = (
            -center_tile_x + round(self.width() / 2) - 50,
            -center_tile_y + round(self.height() / 2) - 128,
        )
        self.maptile_surface.move(new_x, new_y)

        self.load_radartiles()
