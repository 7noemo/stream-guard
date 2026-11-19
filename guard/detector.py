"""检测后端：可插拔的画面风险评分器，输出 0.0~1.0 的风险分。

性能约定：
- 所有后端接收的图都应当已被采集层缩小（默认 <= 640x360），避免全尺寸数组进模型。
- 检测帧之间可用 FrameSkipDetector 做"画面没变就复用上次分数"，省掉模型推理。
"""
from __future__ import annotations

import logging
from typing import Protocol

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

# 检测用的统一小尺寸：足够判断风险，计算量只有 640x360 的 1/9（相对 1080p）
DETECT_SIZE = (256, 144)


class Detector(Protocol):
    def predict(self, image: Image.Image) -> float: ...

    def close(self) -> None: ...


class _BaseDetector:
    def close(self) -> None:
        pass


class MockDetector(_BaseDetector):
    """测试用：按配置循环返回分数，便于验证状态机与遮挡开关。"""

    def __init__(self, scores: list[float]):
        self.scores = scores or [0.05]
        self.i = 0

    def predict(self, image: Image.Image) -> float:
        value = float(self.scores[self.i % len(self.scores)])
        self.i += 1
        return value


class HeuristicDetector(_BaseDetector):
    """纯数值的肤色比例启发式，无需模型。

    在 DETECT_SIZE 小图上用 uint8 计算，单帧开销可忽略。
    注意：对游戏画面误报率很高，仅用于演示流程或兜底。
    """

    def __init__(self, alert_ratio: float = 0.30):
        self.alert_ratio = alert_ratio

    def predict(self, image: Image.Image) -> float:
        small = image.resize(DETECT_SIZE, Image.BILINEAR)
        arr = np.asarray(small, dtype=np.uint8)
        # uint8 运算：用 int16 中间量避免溢出，比 float32 省一半内存
        r = arr[..., 0].astype(np.int16)
        g = arr[..., 1].astype(np.int16)
        b = arr[..., 2].astype(np.int16)
        y = (77 * r + 150 * g + 29 * b) >> 8
        cr = ((128 * r - 107 * g - 21 * b) >> 8) + 128
        cb = ((-43 * r - 85 * g + 128 * b) >> 8) + 128
        mask = (cr > 133) & (cr < 180) & (cb > 77) & (cb < 127) & (y > 40)

        h, w = mask.shape
        mask[: int(h * 0.12), :] = False
        mask[int(h * 0.88) :, :] = False
        mask[:, : int(w * 0.10)] = False
        mask[:, int(w * 0.90) :] = False

        return min(1.0, float(mask.mean()) / self.alert_ratio)


class OpenNSFW2Detector(_BaseDetector):
    """本地 NSFW 分类模型，对写实内容较准，对卡通/3D 游戏画面误报偏高。

    限制 TF 只申请必要显存、限制线程，避免抢占游戏 GPU/CPU。
    """

    def __init__(self, threads: int = 2):
        import os

        # 必须在 import tensorflow 之前设置，抑制日志与线程膨胀
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        os.environ.setdefault("TF_NUM_INTEROP_THREADS", "1")
        os.environ.setdefault("TF_NUM_INTRAOP_THREADS", str(threads))
        import opennsfw2

        try:
            import tensorflow as tf

            for gpu in tf.config.list_physical_devices("GPU"):
                try:
                    tf.config.experimental.set_memory_growth(gpu, True)
                except Exception:
                    pass
            try:
                tf.config.threading.set_intra_op_parallelism_threads(threads)
                tf.config.threading.set_inter_op_parallelism_threads(1)
            except Exception:
                pass
        except Exception as exc:
            log.debug("TF 线程/显存设置跳过: %s", exc)

        self._predict = opennsfw2.predict_image
        self._predict(np.zeros((224, 224, 3), dtype=np.uint8))  # 预热

    def predict(self, image: Image.Image) -> float:
        small = image.resize((224, 224), Image.BILINEAR)
        return float(self._predict(np.asarray(small)))


class CLIPDetector(_BaseDetector):
    """CLIP 零样本分类，可用自定义提示词适配游戏画面。需 torch + transformers。"""

    def __init__(self, model_name: str = "openai/clip-vit-base-patch32",
                 labels: list[str] | None = None, threads: int = 2):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.torch = torch
        try:
            torch.set_num_threads(max(1, threads))
            torch.set_num_interop_threads(1)
        except Exception:
            pass
        self.model = CLIPModel.from_pretrained(model_name)
        self.model.eval()
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.labels = labels or [
            "a sexually explicit or nude scene",
            "a normal video game scene with fully clothed characters",
        ]

    def predict(self, image: Image.Image) -> float:
        # CLIP 输入 224x224，先缩小减少 processor 的预处理开销
        small = image.resize((224, 224), Image.BILINEAR)
        inputs = self.processor(
            text=self.labels, images=small, return_tensors="pt", padding=True
        )
        with self.torch.inference_mode():
            logits = self.model(**inputs).logits_per_image
            probs = logits.softmax(dim=-1)[0]
        return float(probs[0])

    def close(self) -> None:
        try:
            del self.model
            import gc

            gc.collect()
        except Exception:
            pass


class FrameSkipDetector:
    """包装任意检测器：画面几乎没变时复用上次分数，跳过昂贵的模型推理。

    用 32x18 灰度缩略图做差异判断，开销可忽略。连续跳过有上限，
    避免长期静止时状态机完全停滞（真实内容变化时一定会触发重算）。
    """

    def __init__(self, detector: Detector, threshold: float = 3.0,
                 max_skip: int = 12, cooldown_frames: int = 2):
        self.detector = detector
        self.threshold = float(threshold)   # 缩略图平均像素差阈值
        self.max_skip = int(max_skip)
        self.cooldown_frames = int(cooldown_frames)
        self._prev: np.ndarray | None = None
        self._last_score = 0.0
        self._skipped = 0
        self._since_real = 0

    def _thumb(self, image: Image.Image) -> np.ndarray:
        return np.asarray(image.convert("L").resize((32, 18), Image.BILINEAR), dtype=np.int16)

    def predict(self, image: Image.Image) -> float:
        thumb = self._thumb(image)
        self._since_real += 1
        if self._prev is not None and self._skipped < self.max_skip:
            diff = float(np.abs(thumb - self._prev).mean())
            if diff <= self.threshold and self._since_real <= self.max_skip:
                self._skipped += 1
                return self._last_score
        self._prev = thumb
        self._last_score = self.detector.predict(image)
        self._skipped = 0
        self._since_real = 0
        return self._last_score

    def close(self) -> None:
        self.detector.close()

    @property
    def skipped_frames(self) -> int:
        return self._skipped


def build_detector(cfg: dict) -> Detector:
    backend = cfg["backend"]
    threads = int(cfg.get("threads", 2))
    detector: Detector
    if backend == "mock":
        detector = MockDetector(cfg.get("mock_scores", [0.05]))
    elif backend == "heuristic":
        detector = HeuristicDetector()
    elif backend == "opennsfw2":
        detector = OpenNSFW2Detector(threads=threads)
    elif backend == "clip":
        detector = CLIPDetector(labels=cfg.get("clip_labels"), threads=threads)
    else:
        raise ValueError(f"未知检测后端: {backend}")

    # 启发式本身开销极低，无需跳过；模型后端才包装
    if cfg.get("frame_skip", True) and backend in ("opennsfw2", "clip"):
        detector = FrameSkipDetector(
            detector,
            threshold=float(cfg.get("frame_skip_threshold", 3.0)),
            max_skip=int(cfg.get("frame_skip_max", 12)),
        )
    return detector
