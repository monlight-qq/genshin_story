"""可标定的白色 UI 边缘检测与剧情结束状态机，不依赖第三方库。"""

from dataclasses import dataclass
import json

PATCH_SIZE = 25


def channels(pixels, index):
    return pixels[index * 4:index * 4 + 3]  # Windows BGRA；不使用 alpha


def brightness(pixels, index):
    b, g, r = channels(pixels, index)
    return (r * 77 + g * 150 + b * 29) / 256


@dataclass
class Marker:
    width: int
    height: int
    x: int
    y: int
    edges: list
    neutral: bool = True

    @classmethod
    def calibrate(cls, width, height, x, y, pixels, neutral=True):
        if len(pixels) != PATCH_SIZE * PATCH_SIZE * 4:
            raise ValueError("截图数据不完整。")
        edges = []
        for row in range(1, PATCH_SIZE - 1):
            for col in range(1, PATCH_SIZE - 1):
                index = row * PATCH_SIZE + col
                rgb = channels(pixels, index)
                if ((neutral and (min(rgb) < 170 or max(rgb) - min(rgb) > 55))
                        or (not neutral and brightness(pixels, index) < 120)):
                    continue
                neighbors = (index - 1, index + 1, index - PATCH_SIZE, index + PATCH_SIZE)
                neighbor = min(neighbors, key=lambda j: brightness(pixels, j))
                if brightness(pixels, index) - brightness(pixels, neighbor) >= 45:
                    edges.append([index, neighbor])
        if len(edges) < 12:
            raise ValueError("未找到足够的图标边缘。请选固定 UI 图标，避开纯色、变化文字和动画。")
        return cls(width, height, x, y, edges, neutral)

    def score(self, pixels):
        if len(pixels) != PATCH_SIZE * PATCH_SIZE * 4:
            raise ValueError("截图数据不完整。")
        matches = 0
        for index, neighbor in self.edges:
            rgb = channels(pixels, index)
            eligible = min(rgb) >= 150 and max(rgb) - min(rgb) <= 80 if self.neutral else brightness(pixels, index) >= 100
            if (eligible
                    and brightness(pixels, index) - brightness(pixels, neighbor) >= 22):
                matches += 1
        return matches / len(self.edges)

    def prepare_region(self, pixels, width, height):
        if width < PATCH_SIZE or height < PATCH_SIZE or len(pixels) != width * height * 4:
            raise ValueError("搜索区域尺寸或像素数据无效。")
        gray, eligible = [], []
        for offset in range(0, len(pixels), 4):
            b, g, r = pixels[offset:offset + 3]
            luminance = (r * 77 + g * 150 + b * 29) / 256
            gray.append(luminance)
            eligible.append(min(b, g, r) >= 150 and max(b, g, r) - min(b, g, r) <= 80
                            if self.neutral else luminance >= 100)
        offsets = [(i // PATCH_SIZE * width + i % PATCH_SIZE,
                    j // PATCH_SIZE * width + j % PATCH_SIZE) for i, j in self.edges]
        return gray, eligible, offsets

    def scan(self, pixels, width, height, threshold, limit=6):
        """在小区域寻找同一图标的多个位置，去重后按从上到下排列。"""
        gray, eligible, offsets = self.prepare_region(pixels, width, height)
        allowed = int(len(offsets) * (1 - threshold) + 1e-9)
        hits = []
        for y in range(height - PATCH_SIZE + 1):
            for x in range(width - PATCH_SIZE + 1):
                base, misses = y * width + x, 0
                for i, j in offsets:
                    if not eligible[base + i] or gray[base + i] - gray[base + j] < 22:
                        misses += 1
                        if misses > allowed:
                            break
                else:
                    hits.append((x, y, 1 - misses / len(offsets)))
        selected = []
        for hit in sorted(hits, key=lambda h: (-h[2], h[1], h[0])):
            if all(abs(hit[0] - other[0]) >= PATCH_SIZE or abs(hit[1] - other[1]) >= PATCH_SIZE
                   for other in selected):
                selected.append(hit)
                if len(selected) >= limit:
                    break
        return sorted(selected, key=lambda h: (h[1], h[0]))

    def best_score(self, pixels, width, height):
        """固定 UI 标记的小范围位移容错。"""
        gray, eligible, offsets = self.prepare_region(pixels, width, height)
        best = 0.0
        for y in range(height - PATCH_SIZE + 1):
            for x in range(width - PATCH_SIZE + 1):
                base = y * width + x
                score = sum(eligible[base + i] and gray[base + i] - gray[base + j] >= 22
                            for i, j in offsets) / len(offsets)
                best = max(best, score)
        return best

    def as_dict(self):
        return {name: getattr(self, name) for name in ("width", "height", "x", "y", "edges", "neutral")}

    @classmethod
    def from_dict(cls, value):
        marker = cls(**value)
        if type(marker.neutral) is not bool:
            raise ValueError("图标类型无效。")
        for name in ("width", "height", "x", "y"):
            if type(getattr(marker, name)) is not int:
                raise ValueError("标定坐标无效。")
        if not (marker.width >= PATCH_SIZE and marker.height >= PATCH_SIZE
                and 0 <= marker.x <= marker.width - PATCH_SIZE
                and 0 <= marker.y <= marker.height - PATCH_SIZE):
            raise ValueError("标定区域无效。")
        if not isinstance(marker.edges, list) or not 12 <= len(marker.edges) <= PATCH_SIZE ** 2:
            raise ValueError("标定边缘无效。")
        for pair in marker.edges:
            if (not isinstance(pair, list) or len(pair) != 2
                    or any(type(i) is not int or not 0 <= i < PATCH_SIZE ** 2 for i in pair)
                    or abs(pair[0] - pair[1]) not in (1, PATCH_SIZE)):
                raise ValueError("标定边缘无效。")
        return marker


def load_markers(path):
    if not path.exists():
        return None, None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("不支持的标定文件。")
    return tuple(Marker.from_dict(data[name]) if data.get(name) is not None else None
                 for name in ("dialogue", "gameplay"))


def save_markers(path, dialogue, gameplay):
    data = {"version": 1, "dialogue": dialogue.as_dict() if dialogue else None,
            "gameplay": gameplay.as_dict() if gameplay else None}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


@dataclass
class FixedPoint:
    width: int
    height: int
    x: int
    y: int

    def as_dict(self):
        return {name: getattr(self, name) for name in ("width", "height", "x", "y")}

    @classmethod
    def from_dict(cls, value):
        point = cls(**value)
        if (any(type(getattr(point, name)) is not int for name in ("width", "height", "x", "y"))
                or point.width <= 0 or point.height <= 0
                or not 0 <= point.x < point.width or not 0 <= point.y < point.height):
            raise ValueError("固定选项坐标无效。")
        return point


def load_option(path):
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") not in (1, 2):
        raise ValueError("不支持的选项标定文件。")
    if data.get("version") == 2:
        if data.get("kind") == "fixed":
            return FixedPoint.from_dict(data["point"])
        if data.get("kind") != "detect":
            raise ValueError("选项标定类型无效。")
    return Marker.from_dict(data["marker"])


def save_option(path, marker):
    temporary = path.with_suffix(".tmp")
    if isinstance(marker, FixedPoint):
        data = {"version": 2, "kind": "fixed", "point": marker.as_dict()}
    else:
        data = {"version": 2, "kind": "detect", "marker": marker.as_dict()}
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


def load_close_markers(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("markers"), list) or len(data["markers"]) > 8):
        raise ValueError("关闭按钮标定文件无效。")
    return [Marker.from_dict(value) for value in data["markers"]]


def save_close_marker(path, markers, candidate):
    # 同一位置重复标定时替换；可记录最多八种不同位置/样式。
    updated = [item for item in markers if not (
        (item.width, item.height) == (candidate.width, candidate.height)
        and abs(item.x - candidate.x) < PATCH_SIZE and abs(item.y - candidate.y) < PATCH_SIZE)]
    updated = (updated + [candidate])[-8:]
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"version": 1, "markers": [item.as_dict() for item in updated]}), encoding="utf-8")
    temporary.replace(path)
    return updated


class CloseGuard:
    """要求关闭按钮稳定出现，限制重试，并避免短暂闪烁导致重复点击。"""
    def __init__(self, cooldown=1.5):
        self.cooldown = cooldown
        self.target = None
        self.since = None
        self.next_click = 0.0
        self.attempts = 0
        self.misses = 0

    def update(self, now, target):
        if target is None:
            self.misses += 1
            self.since = None
            if self.misses >= 2:
                self.target = None
                self.attempts = 0
            return False
        same = (self.target is not None and target[:3] == self.target[:3]
                and abs(target[3] - self.target[3]) <= 12 and abs(target[4] - self.target[4]) <= 12)
        if not same:
            self.attempts = 0
            self.since = now
        elif self.since is None:
            self.since = now
        self.target, self.misses = target, 0
        if now - self.since < 0.12 or now < self.next_click:
            return False
        if self.attempts >= 3:
            raise RuntimeError("同一 × 按钮点击三次后仍存在，已暂停。请检查按钮是否能关闭或重新用 F3 标定。")
        self.attempts += 1
        self.next_click = now + self.cooldown
        return True


class StoryGuard:
    def __init__(self, end_delay, mode="dialogue"):
        self.end_delay = end_delay
        self.missing_since = None
        self.ended = False
        if mode not in ("dialogue", "gameplay"):
            raise ValueError("不支持的结束检测模式。")
        self.mode = mode

    def update(self, now, dialogue_visible, gameplay_visible=False):
        if self.ended or gameplay_visible:
            self.ended = True
            return "ended"
        if self.mode == "gameplay":
            return "active"  # 只用探索 UI 判断结束，不因对白/选项 UI 切换而中断。
        if dialogue_visible:
            self.missing_since = None
            return "active"
        if self.missing_since is None:
            self.missing_since = now
        if now - self.missing_since >= self.end_delay:
            self.ended = True
            return "ended"
        return "hold"  # 进入宽限期时立即禁用输入，而非等倒计时结束。
