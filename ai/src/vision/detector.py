"""YOLO nano inference restricted to the person class, on CPU."""

import logging
import time
from dataclasses import dataclass

import cv2
from ultralytics import YOLO

logger = logging.getLogger("VISION")


@dataclass(frozen=True)
class PersonDetection:
    confidence: float
    boxes: tuple

    @property
    def person_detected(self) -> bool:
        return bool(self.boxes)


class PersonDetector:
    def __init__(self, model: str, confidence: float, inference_size: int):
        self.threshold = confidence
        self.inference_size = inference_size
        self._inference_seconds = 0.0
        self._inference_count = 0
        try:
            self.model = YOLO(model)
        except Exception as exc:
            raise RuntimeError(f"Cannot load YOLO model {model!r}; use a local .pt file "
                               "or allow the first download with Internet access") from exc
        self.person_class = next((index for index, name in self.model.names.items()
                                  if name == "person"), None)
        if self.person_class is None:
            raise ValueError("YOLO model must contain a class named 'person'")
        logger.info("YOLO model loaded: %s (CPU, imgsz=%s)", model, inference_size)

    def detect(self, frame) -> PersonDetection:
        started = time.perf_counter()
        result = self.model.predict(source=frame, device="cpu",
                                    classes=[self.person_class], conf=self.threshold,
                                    imgsz=self.inference_size, verbose=False)[0]
        self._inference_seconds += time.perf_counter() - started
        self._inference_count += 1
        if self._inference_count % 30 == 0:
            mean = self._inference_seconds / self._inference_count
            logger.debug("YOLO mean inference=%.1f ms (%s frames, inference throughput=%.1f/s)",
                         mean * 1000, self._inference_count, 1 / mean if mean else 0)
        boxes = []
        if result.boxes is not None:
            for coordinates, score in zip(result.boxes.xyxy.cpu().tolist(),
                                          result.boxes.conf.cpu().tolist()):
                boxes.append((*coordinates, float(score)))
        return PersonDetection(max((box[4] for box in boxes), default=0.0), tuple(boxes))

    @staticmethod
    def annotate(frame, detection: PersonDetection):
        annotated = frame.copy()
        for x1, y1, x2, y2, confidence in detection.boxes:
            cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
            cv2.putText(annotated, f"PERSON {confidence:.2f}",
                        (int(x1), max(20, int(y1) - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (0, 255, 0), 2)
        return annotated
