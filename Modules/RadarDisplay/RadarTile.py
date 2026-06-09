import queue
import random
import time
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, QByteArray
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt6.QtWidgets import QLabel

from loguru import logger as logging

from Utils.UtilMethods import get_host


class RadarTile(QLabel):
    MAX_PARSE_TIME = (
        0.01  # Maximum time to spend parsing responses in milliseconds per parse event
    )

    def __init__(self, host, parent=None, x=0, y=0):
        super().__init__(parent)
        self.parent = parent
        self.host = host
        self.setFixedSize(256, 256)
        self.tile_x = x
        self.tile_y = y
        self.screen_x = 0
        self.screen_y = 0

        #   Previous method of getting the saved tile

        # self.setPixmap(
        #     QPixmap(f"Assets/MapTiles/{self.tile_x}-{self.tile_y}.png").scaled(
        #         self.width(),
        #         self.height(),
        #         Qt.AspectRatioMode.KeepAspectRatio,
        #         Qt.TransformationMode.SmoothTransformation,
        #     )
        # )

        self.tile_manager = QNetworkAccessManager()
        self.tile_manager.finished.connect(self.handle_tile_response)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        tile_dir = os.path.join(script_dir, ".cachedtiles")
        file_path = Path(os.path.join(tile_dir, f"6-{self.tile_x}-{self.tile_y}"))

        if os.path.isfile(file_path):
            with open(file_path, "rb") as file:
                data = file.read()
                image = QImage.fromData(QByteArray(data))
                self.setPixmap(QPixmap.fromImage(image))
        else:
            self.request_new_tile(self.tile_x, self.tile_y)

        self.timestamps = []

        self.radar_images = []
        self.displayed_radar_image = 0
        self.setStyleSheet("background-color: white;")
        self.radar_overlay = QLabel(self)
        self.radar_overlay.setFixedSize(256, 256)
        self.radar_overlay.setStyleSheet("background-color: transparent;")
        self.radar_overlay.raise_()

        self.network_manager = QNetworkAccessManager()
        self.network_manager.finished.connect(self.handle_response)

        self.response_queue = queue.Queue()
        self.parse_timer = QTimer(self)
        self.parse_timer.timeout.connect(self.parse_responses)
        self.parse_timer.start(100 + int(random.random() * 50))

        self.total_frames = 0
        self.outstanding_requests = 0
        self.outstanding_parses = 0
        self.loading = False

        self.visibility_timer = QTimer(self)
        self.visibility_timer.timeout.connect(self.start_loading)

    def position(self, x, y):
        self.screen_x = x
        self.screen_y = y

    def load_radar_overlays(self, timestamps):
        self.timestamps = timestamps
        self.start_loading()
        self.visibility_timer.start(100 + int(random.random() * 50))

    def start_loading(self):
        # self.debug_title.setText(f"{self.tile_x}-{self.tile_y} [{self.on_screen()}]")
        # return
        if not self.on_screen():
            return
        self.loading = True
        self.visibility_timer.stop()
        # logging.info(f"{self.tile_x}-{self.tile_y} is on screen")
        for timestamp in self.timestamps:
            self.outstanding_requests += 1
            self.total_frames += 1
            self.network_manager.get(
                QNetworkRequest(
                    QUrl(
                        f"{get_host()}/weather/radar/{timestamp}/{self.tile_x}/{self.tile_y}/4"
                    )
                )
            )

    def set_radar_overlay(self, timestamp):
        self.displayed_radar_image = timestamp
        for radar_image in self.radar_images:
            if radar_image["timestamp"] == timestamp:
                self.radar_overlay.setPixmap(QPixmap.fromImage(radar_image["image"]))
                return
        self.radar_overlay.setPixmap(QPixmap())

    def handle_response(self, reply):
        # Defer the parsing of the response to a background loop that only runs once every 100ms to prevent
        # holding up the refresh of the main UI
        try:
            timestamp = int(
                reply.url().toString().split("/")[-4]
            )  # Extract the timestamp from the URL
            self.outstanding_requests -= 1
            if str(reply.error()) != "NetworkError.NoError":
                logging.error(
                    f"Failed to load map tile {self.tile_x}-{self.tile_y}@{timestamp}: {reply.error()}"
                )
                return
            self.response_queue.put(reply)
        except Exception as e:
            logging.error(f"Failed to handle radar response: {e}")
            logging.exception(e)
            reply.deleteLater()

    def parse_responses(self):
        parse_start = time.time()
        # starting_size = len(self.radar_images)
        while (
            not self.response_queue.empty()
            and time.time() - parse_start < self.MAX_PARSE_TIME
        ):
            reply = self.response_queue.get()
            timestamp = int(
                reply.url().toString().split("/")[-4]
            )  # Extract the timestamp from the URL
            try:
                data = reply.readAll()
                image = QImage.fromData(data)
                # Resize the image to 256x256 pixels
                image = image.scaled(
                    self.width(),
                    self.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.radar_images.append({"timestamp": timestamp, "image": image})
                if timestamp == self.displayed_radar_image:
                    self.radar_overlay.setPixmap(QPixmap.fromImage(image))
            except Exception as e:
                logging.error(
                    f"Failed to load map tile {self.tile_x}-{self.tile_y}@{timestamp}: {e}"
                )
                logging.exception(e)
            finally:
                reply.deleteLater()  # Clean up the reply object
        # print(f"Parsed {len(self.radar_images) - starting_size} images in {time.time() - parse_start:.2f}s")
        if (
            self.outstanding_requests == 0
            and self.response_queue.empty()
            and self.loading
        ):
            # logging.info(f"Finished parsing {len(self.radar_images)} images for {self.tile_x}-{self.tile_y}")
            self.parse_timer.stop()

    def change_size(self, factor):
        self.setFixedSize(round(self.width() * factor), round(self.height() * factor))
        self.radar_overlay.setFixedSize(
            round(self.radar_overlay.width() * factor),
            round(self.radar_overlay.height() * factor),
        )
        # Resize the map tile image to match the new size
        self.setPixmap(
            QPixmap(f"Assets/MapTiles/{self.tile_x}-{self.tile_y}.png").scaled(
                self.width(),
                self.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.radar_images.clear()

    def on_screen(self):
        # Check if the tile is visible on the main window (not just the parent widget)
        # Get the parent surfaces X and Y coordinates
        parent_x = self.parent.x()
        parent_y = self.parent.y()
        # Offset the parent's coordinates by the tile's coordinates
        parent_x += self.x()
        parent_y += self.y()
        # If the value is negative, the tile is off the left or top of the screen
        if parent_x < -256 or parent_y < -256:
            return False
        # If the value is greater than the parent's parent's width or height, the tile is off the right or bottom
        if (
            parent_x > self.parent.parent().width()
            or parent_y > self.parent.parent().height()
        ):
            return False
        return True

    def request_new_tile(self, x, y):
        url = f"https://tile.openstreetmap.org/6/{x}/{y}.png"

        request = QNetworkRequest(QUrl(url))
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "application/x-www-form-urlencoded",
        )
        request.setRawHeader(b"User-Agent", b"RoomInterfactMk2/0.0")

        self.tile_manager.get(request)

    def handle_tile_response(self, reply):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:

                print("Error")
                print(reply.errorString())
                return
            data = reply.readAll()

            original_query = reply.request().url().toString()
            zoom = int(original_query.split("/")[3])
            x = int(original_query.split("/")[4])
            y = int(original_query.split("/")[5][:-4])

            script_dir = os.path.dirname(os.path.abspath(__file__))
            tile_dir = os.path.join(script_dir, ".cachedtiles")
            file_path = Path(os.path.join(tile_dir, f"{zoom}-{x}-{y}"))

            if not os.path.exists(tile_dir):
                os.makedirs(tile_dir)

            with open(file_path, "wb") as file:
                file.write(data.data())

            image = QImage.fromData(data)
            self.setPixmap(QPixmap.fromImage(image))
        except Exception as e:
            print("Response handling error:", e)
        finally:
            reply.deleteLater()
