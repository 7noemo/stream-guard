"""检测后端：可插拔的画面风险评分器，输出 0.0~1.0 的风险分。"""
from __future__ import annotations

import logging
from typing import Protocol

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)


class Detector(Protocol):
    def predict(self, image: Image.Image) -> float: ...


class MockDetector:
    """测试用：按配置循环返回分数，便于验证状态机与遮挡开关。"""

    def __init__(self, scores: list[float]):
        self.scores = scores or [0.05]
        self.i = 0

    def predict(self, image: Image.Image) -> float:
        value = float(self.scores[self.i % len(self.scores)])
        self.i += 1
        return value


class HeuristicDetector:
    """纯数值的肤色比例启发式，无需模型。

    注意：对游戏画面误报率很高，仅用于演示流程或兜底，不建议正式直播使用。
    """

    def __init__(self, alert_ratio: float = 0.30):
        self.alert_ratio = alert_ratio

    def predict(self, image: Image.Image) -> float:
        arr = np.asarray(image.convert("RGB").resize((256, 144)), dtype=np.float32)
        r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        y = 0.299 * r + 0.587 * g + 0.114 * b
        cr = 0.500 * r - 0.4187 * g - 0.0813 * b + 128
        cb = -0.1687 * r - 0.3313 * g + 0.500 * b + 128
        mask = (cr > 133) & (cr < 180) & (cb > 77) & (cb < 127) & (y > 40)

        h, w = mask.shape
        mask[: int(h * 0.12), :] = False
        mask[int(h * 0.88) :, :] = False
        mask[:, : int(w * 0.10)] = False
        mask[:, int(w * 0.90) :] = False

        return min(1.0, float(mask.mean()) / self.alert_ratio)


class OpenNSFW2Detector:
    """本地 NSFW 分类模型，对写实内容较准，对卡通/3D 游戏画面误报偏高。"""

    def __init__(self):
        import opennsfw2

        self._predict = opennsfw2.predict_image
        self._predict(np.zeros((224, 224, 3), dtype=np.uint8))  # 预热

    def predict(self, image: Image.Image) -> float:
        return float(self._predict(np.asarray(image.convert("RGB"))))


class CLIPDetector:
    """CLIP 零样本分类，可用自定义提示词适配游戏画面。需 torch + transformers。"""

    def __init__(
        self,
        model_name: str = "openai/clip-vit-base-patch32",
        labels: list[str] | None = None,
    ):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.torch = torch
        self.model = CLIPModel.from_pretrained(model_name)
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.labels = labels or [
            "a sexually explicit or nude scene",
            "a normal video game scene with fully clothed characters",
        ]

    def predict(self, image: Image.Image) -> float:
        inputs = self.processor(
            text=self.labels, images=image, return_tensors="pt", padding=True
        )
        with self.torch.no_grad():
            logits = self.model(**inputs).logits_per_image
            probs = logits.softmax(dim=-1)[0]
        return float(probs[0])


def build_detector(cfg: dict) -> Detector:
    backend = cfg["backend"]
    if backend == "mock":
        return MockDetector(cfg.get("mock_scores", [0.05]))
    if backend == "heuristic":
        return HeuristicDetector()
    if backend == "opennsfw2":
        return OpenNSFW2Detector()
    if backend == "clip":
        return CLIPDetector(labels=cfg.get("clip_labels"))
    raise ValueError(f"未知检测后端: {backend}")
