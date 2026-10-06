"""OpenCV USB camera lifecycle."""

import logging

import cv2

logger = logging.getLogger("VISION")


class Camera:
    def __init__(self, index: int, width: int, height: int):
        self.index = index
        self.width = width
        self.height = height
        self.capture = None

    def open(self) -> None:
        self.capture = cv2.VideoCapture(self.index)
        if not self.capture.isOpened():
            self.close()
            raise RuntimeError(f"Camera {self.index} unavailable; check AI_CAMERA_INDEX, "
                               "permissions and whether another app is using it")
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        logger.info("Camera opened index=%s resolution=%sx%s", self.index,
                    int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    def read(self):
        if self.capture is None:
            raise RuntimeError("Camera is not open")
        success, frame = self.capture.read()
        if not success or frame is None:
            raise RuntimeError("Camera frame unavailable; check the USB connection")
        return frame

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
            logger.info("Camera released")
