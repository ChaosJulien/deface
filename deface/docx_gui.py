"""PySide6 桌面 GUI:导入 docx → 提取图片 → 人工筛选每张人脸 + 单图参数 → 导出新 docx。"""
from __future__ import annotations

import io
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import cv2
import imageio.v2 as iio
import numpy as np
from PIL import Image as PilImage
from PySide6 import QtCore, QtGui, QtWidgets

from deface.deface import draw_det, scale_bb
from deface.docx_io import DocxImage, extract_images, write_docx


REPLACE_MODES = ["blur", "solid", "mosaic", "none"]
DEFAULT_THRESHOLD = 0.5
DEFAULT_MASK_SCALE = 1.3
DEFAULT_MOSAIC_SIZE = 20
MAX_FACES_PER_IMAGE = 100
DETECT_MAX_SIDE = 1280  # 大图缩到长边 1280 再检测,加速 + 避免边界
YUNET_MODEL = "face_detection_yunet_2023mar.onnx"


# ---------- 数据模型 ----------


@dataclass
class FaceBox:
    x1: int
    y1: int
    x2: int
    y2: int
    score: float
    keep: bool = False
    manual: bool = False   # 用户手动加的框


@dataclass
class ImageParams:
    replacewith: str = "blur"
    mask_scale: float = DEFAULT_MASK_SCALE
    mosaic_size: int = DEFAULT_MOSAIC_SIZE
    threshold: float = DEFAULT_THRESHOLD


@dataclass
class ImageState:
    arcname: str
    data: bytes
    suffix: str
    frame: Optional[np.ndarray] = None  # 解码后的 RGB
    faces: List[FaceBox] = field(default_factory=list)
    params: ImageParams = field(default_factory=ImageParams)
    detected: bool = False
    error: Optional[str] = None


# ---------- 检测 worker(单独 QThread,串行调 CenterFace,避免 ONNX 线程不安全)----------


class DetectorWorker(QtCore.QObject):
    detected = QtCore.Signal(int, list)        # (state_index, [FaceBox])
    failed = QtCore.Signal(int, str)           # (state_index, error)
    finished_batch = QtCore.Signal()           # 批量检测全部完成
    progress = QtCore.Signal(int, int)         # (done, total)

    def __init__(self) -> None:
        super().__init__()
        self._cf = None

    @QtCore.Slot()
    def ensure_loaded(self) -> None:
        if self._cf is None:
            model_path = str(Path(__file__).with_name(YUNET_MODEL))
            self._cf = cv2.FaceDetectorYN.create(
                model=model_path,
                config="",
                input_size=(320, 320),     # 占位,后面 setInputSize 覆盖
                score_threshold=0.5,
                nms_threshold=0.3,
                top_k=5000,
            )

    @QtCore.Slot(int, "QVariant", float)
    def detect_one(self, idx: int, frame_array, threshold: float) -> None:
        try:
            self.ensure_loaded()
            faces = self._run(frame_array, threshold)
            self.detected.emit(idx, faces)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(idx, f"{exc}\n{traceback.format_exc()}")

    @QtCore.Slot(list, float)
    def detect_batch(self, jobs, threshold: float) -> None:
        """jobs: list of (idx, frame_array)。串行检测,每完成一张发信号。"""
        try:
            self.ensure_loaded()
            total = len(jobs)
            thread = QtCore.QThread.currentThread()
            for done, (idx, frame) in enumerate(jobs, 1):
                if thread is not None and thread.isInterruptionRequested():
                    return
                try:
                    faces = self._run(frame, threshold)
                    self.detected.emit(idx, faces)
                except Exception as exc:  # noqa: BLE001
                    self.failed.emit(idx, str(exc))
                self.progress.emit(done, total)
        finally:
            self.finished_batch.emit()

    def _run(self, frame: np.ndarray, threshold: float) -> List[FaceBox]:
        h, w = frame.shape[:2]
        # imageio 出来是 RGB / RGBA / 灰度,YuNet 要 BGR
        if frame.ndim == 2:
            bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        else:
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # 大图缩到长边 DETECT_MAX_SIDE,加速并稳定
        scale = 1.0
        if max(h, w) > DETECT_MAX_SIDE:
            scale = DETECT_MAX_SIDE / max(h, w)
            new_w, new_h = int(round(w * scale)), int(round(h * scale))
            det_img = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            det_img = bgr

        dh, dw = det_img.shape[:2]
        self._cf.setScoreThreshold(float(threshold))
        self._cf.setInputSize((dw, dh))
        ret = self._cf.detect(det_img)
        # OpenCV 不同版本 detect 返回 (status, faces) 或仅 faces
        faces = ret[1] if isinstance(ret, tuple) else ret

        out: List[FaceBox] = []
        if faces is None:
            return out
        inv = 1.0 / scale if scale != 1.0 else 1.0
        for row in faces:
            x, y, fw, fh = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            score = float(row[14])
            x1, y1, x2, y2 = x * inv, y * inv, (x + fw) * inv, (y + fh) * inv
            if not all(np.isfinite([x1, y1, x2, y2])):
                continue
            bw, bh = x2 - x1, y2 - y1
            if bw <= 0 or bh <= 0 or bw >= w * 0.95 or bh >= h * 0.95:
                continue
            out.append(FaceBox(
                x1=max(0, int(x1)), y1=max(0, int(y1)),
                x2=min(w, int(x2)), y2=min(h, int(y2)),
                score=score,
            ))
        if len(out) > MAX_FACES_PER_IMAGE:
            out.sort(key=lambda f: f.score, reverse=True)
            out = out[:MAX_FACES_PER_IMAGE]
        return out


# ---------- 人脸框 graphics item ----------


class FaceRectItem(QtWidgets.QGraphicsRectItem):
    """每张脸一个 item;点击切 keep。颜色:绿=保留,红=打码。"""

    KEEP_PEN = QtGui.QPen(QtGui.QColor("#34d399"), 0)
    MASK_PEN = QtGui.QPen(QtGui.QColor("#fb7185"), 0)

    def __init__(self, rect: QtCore.QRectF, idx: int, on_toggle, on_delete):
        super().__init__(rect)
        self.idx = idx
        self.on_toggle = on_toggle
        self.on_delete = on_delete
        self.setAcceptHoverEvents(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.refresh(False)

    def refresh(self, keep: bool) -> None:
        pen = self.KEEP_PEN if keep else self.MASK_PEN
        pen = QtGui.QPen(pen)
        pen.setWidthF(0)
        pen.setCosmetic(True)
        pen.setWidth(3)
        self.setPen(pen)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.on_toggle(self.idx)
            event.accept()
            return
        if event.button() == QtCore.Qt.RightButton:
            self.on_delete(self.idx)
            event.accept()
            return
        super().mousePressEvent(event)


# ---------- 图片视图 ----------


class ImageView(QtWidgets.QGraphicsView):
    face_clicked = QtCore.Signal(int)              # 切 keep
    face_delete_requested = QtCore.Signal(int)     # 右键删框
    box_added = QtCore.Signal(QtCore.QRectF)       # 手动拖出新框

    def __init__(self) -> None:
        super().__init__()
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QtGui.QColor("#0d0f13"))
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self._pixmap_item: Optional[QtWidgets.QGraphicsPixmapItem] = None
        self._face_items: List[FaceRectItem] = []
        self._user_zoomed = False
        self._manual_mode = False
        self._draw_start: Optional[QtCore.QPointF] = None
        self._draw_temp: Optional[QtWidgets.QGraphicsRectItem] = None

    def set_image(self, frame: Optional[np.ndarray], faces: List[FaceBox]) -> None:
        self._scene.clear()
        self._face_items.clear()
        self._pixmap_item = None
        self._user_zoomed = False
        if frame is None:
            return
        h, w = frame.shape[:2]
        rgb = frame
        if rgb.ndim == 2:
            rgb = np.stack([rgb] * 3, axis=-1)
        if rgb.shape[2] == 4:
            rgb = rgb[:, :, :3]
        rgb = np.ascontiguousarray(rgb)
        qimg = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy()
        pixmap = QtGui.QPixmap.fromImage(qimg)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(0, 0, w, h)
        for i, face in enumerate(faces):
            self._add_face_item(i, face)
        self.fit()

    def _add_face_item(self, idx: int, face: FaceBox) -> None:
        rect = QtCore.QRectF(face.x1, face.y1, face.x2 - face.x1, face.y2 - face.y1)
        item = FaceRectItem(rect, idx, self._on_toggle, self._on_delete)
        item.refresh(face.keep)
        self._scene.addItem(item)
        self._face_items.append(item)

    def update_face_states(self, faces: List[FaceBox]) -> None:
        for item, face in zip(self._face_items, faces):
            item.refresh(face.keep)

    def fit(self) -> None:
        if self._pixmap_item is None:
            return
        self.fitInView(self._pixmap_item, QtCore.Qt.KeepAspectRatio)
        self._user_zoomed = False

    def set_manual_mode(self, on: bool) -> None:
        self._manual_mode = on
        if on:
            self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
            self.setCursor(QtCore.Qt.CrossCursor)
        else:
            self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
            self.unsetCursor()

    def _on_toggle(self, idx: int) -> None:
        self.face_clicked.emit(idx)

    def _on_delete(self, idx: int) -> None:
        self.face_delete_requested.emit(idx)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self._user_zoomed:
            self.fit()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if event.modifiers() & QtCore.Qt.ControlModifier or event.modifiers() & QtCore.Qt.MetaModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            self._user_zoomed = True
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, ev: QtGui.QMouseEvent) -> None:
        if self._manual_mode and ev.button() == QtCore.Qt.LeftButton and self._pixmap_item is not None:
            self._draw_start = self.mapToScene(ev.position().toPoint())
            pen = QtGui.QPen(QtGui.QColor("#fbbf24"))
            pen.setCosmetic(True); pen.setWidth(2); pen.setStyle(QtCore.Qt.DashLine)
            self._draw_temp = self._scene.addRect(QtCore.QRectF(self._draw_start, self._draw_start), pen)
            ev.accept(); return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QtGui.QMouseEvent) -> None:
        if self._manual_mode and self._draw_temp is not None and self._draw_start is not None:
            cur = self.mapToScene(ev.position().toPoint())
            self._draw_temp.setRect(QtCore.QRectF(self._draw_start, cur).normalized())
            ev.accept(); return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QtGui.QMouseEvent) -> None:
        if self._manual_mode and self._draw_temp is not None and self._draw_start is not None:
            rect = self._draw_temp.rect()
            self._scene.removeItem(self._draw_temp)
            self._draw_temp = None
            self._draw_start = None
            if rect.width() >= 5 and rect.height() >= 5 and self._pixmap_item is not None:
                rect = rect.intersected(self._pixmap_item.boundingRect())
                if rect.width() >= 5 and rect.height() >= 5:
                    self.box_added.emit(rect)
            ev.accept(); return
        super().mouseReleaseEvent(ev)


# ---------- 单图参数面板 ----------


class ParamsPanel(QtWidgets.QWidget):
    params_changed = QtCore.Signal()           # 任意参数变,但 threshold 单独走
    threshold_changed = QtCore.Signal(float)   # 防抖后的最终值
    keep_all_clicked = QtCore.Signal()
    mask_all_clicked = QtCore.Signal()
    redetect_clicked = QtCore.Signal()
    manual_toggled = QtCore.Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        form = QtWidgets.QFormLayout(self)

        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(REPLACE_MODES)
        form.addRow("打码方式", self.mode)

        self.mask_scale = QtWidgets.QDoubleSpinBox()
        self.mask_scale.setRange(1.0, 2.0)
        self.mask_scale.setSingleStep(0.05)
        self.mask_scale.setDecimals(2)
        self.mask_scale.setValue(DEFAULT_MASK_SCALE)
        form.addRow("遮罩外扩", self.mask_scale)

        self.mosaic_size = QtWidgets.QSpinBox()
        self.mosaic_size.setRange(4, 200)
        self.mosaic_size.setValue(DEFAULT_MOSAIC_SIZE)
        form.addRow("马赛克尺寸", self.mosaic_size)

        self.threshold = QtWidgets.QDoubleSpinBox()
        self.threshold.setRange(0.01, 1.0)
        self.threshold.setSingleStep(0.01)
        self.threshold.setDecimals(2)
        self.threshold.setValue(DEFAULT_THRESHOLD)
        form.addRow("检测阈值", self.threshold)

        self.manual_btn = QtWidgets.QPushButton("✏️ 手动加框(漏检补充)")
        self.manual_btn.setCheckable(True)
        form.addRow(self.manual_btn)

        btns = QtWidgets.QHBoxLayout()
        keep_all = QtWidgets.QPushButton("全保留")
        mask_all = QtWidgets.QPushButton("全打码")
        redetect = QtWidgets.QPushButton("重新检测")
        btns.addWidget(keep_all)
        btns.addWidget(mask_all)
        btns.addWidget(redetect)
        form.addRow(btns)

        tip = QtWidgets.QLabel(
            "<b>操作:</b><br>"
            "• 红框 = 会被打码<br>"
            "• 绿框 = 保留(不打码)<br>"
            "• 左键点框 切换红/绿<br>"
            "• 右键点框 = 删除<br>"
            "• 按上下方向键切换图片"
        )
        tip.setWordWrap(True); tip.setStyleSheet("color:#888; padding:8px;")
        form.addRow(tip)

        self._threshold_timer = QtCore.QTimer(self)
        self._threshold_timer.setSingleShot(True)
        self._threshold_timer.setInterval(350)
        self._threshold_timer.timeout.connect(
            lambda: self.threshold_changed.emit(self.threshold.value())
        )

        self.mode.currentIndexChanged.connect(lambda _: self.params_changed.emit())
        self.mask_scale.valueChanged.connect(lambda _: self.params_changed.emit())
        self.mosaic_size.valueChanged.connect(lambda _: self.params_changed.emit())
        self.threshold.valueChanged.connect(lambda _: self._threshold_timer.start())

        keep_all.clicked.connect(self.keep_all_clicked)
        mask_all.clicked.connect(self.mask_all_clicked)
        redetect.clicked.connect(self.redetect_clicked)
        self.manual_btn.toggled.connect(self.manual_toggled)

    def load_params(self, p: ImageParams) -> None:
        # blockSignals 防回调风暴
        for w in (self.mode, self.mask_scale, self.mosaic_size, self.threshold):
            w.blockSignals(True)
        self.mode.setCurrentText(p.replacewith)
        self.mask_scale.setValue(p.mask_scale)
        self.mosaic_size.setValue(p.mosaic_size)
        self.threshold.setValue(p.threshold)
        for w in (self.mode, self.mask_scale, self.mosaic_size, self.threshold):
            w.blockSignals(False)

    def write_to(self, p: ImageParams) -> None:
        p.replacewith = self.mode.currentText()
        p.mask_scale = float(self.mask_scale.value())
        p.mosaic_size = int(self.mosaic_size.value())
        p.threshold = float(self.threshold.value())


# ---------- 主窗口 ----------


class MainWindow(QtWidgets.QMainWindow):
    request_detect_one = QtCore.Signal(int, "QVariant", float)
    request_detect_batch = QtCore.Signal(list, float)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("deface · docx 人脸打码工具")
        self.resize(1400, 860)

        self._states: List[ImageState] = []
        self._docx_path: Optional[Path] = None
        self._current: int = -1

        self._build_ui()
        self._build_worker()

    # --- UI 搭建 ---

    def _build_ui(self) -> None:
        self.image_list = QtWidgets.QListWidget()
        self.image_list.setMinimumWidth(240)
        self.image_list.currentRowChanged.connect(self._on_select_image)

        self.image_view = ImageView()
        self.image_view.face_clicked.connect(self._on_face_clicked)
        self.image_view.face_delete_requested.connect(self._on_face_deleted)
        self.image_view.box_added.connect(self._on_box_added)

        self.params = ParamsPanel()
        self.params.params_changed.connect(self._on_params_changed)
        self.params.threshold_changed.connect(self._on_threshold_changed)
        self.params.keep_all_clicked.connect(lambda: self._set_all_keep(True))
        self.params.mask_all_clicked.connect(lambda: self._set_all_keep(False))
        self.params.redetect_clicked.connect(self._redetect_current)
        self.params.manual_toggled.connect(self.image_view.set_manual_mode)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.addWidget(self.params)
        right_layout.addStretch(1)
        right.setMinimumWidth(280)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.image_list)
        splitter.addWidget(self.image_view)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([260, 880, 300])
        self.setCentralWidget(splitter)

        self._build_toolbar()
        self.status = self.statusBar()
        self.status.showMessage("就绪。点工具栏「打开 docx」开始")

        # 全局快捷键:Up/Down 切图,J/K 也兼容
        for keys, delta in (
            ((QtCore.Qt.Key_Up, QtCore.Qt.Key_K), -1),
            ((QtCore.Qt.Key_Down, QtCore.Qt.Key_J), 1),
        ):
            for key in keys:
                sc = QtGui.QShortcut(QtGui.QKeySequence(key), self)
                sc.setContext(QtCore.Qt.WindowShortcut)
                sc.activated.connect(lambda d=delta: self._step_image(d))

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("main")
        tb.setMovable(False)
        act_open = tb.addAction("打开 docx")
        act_export = tb.addAction("导出 docx")
        tb.addSeparator()
        act_fit = tb.addAction("适应窗口")
        act_open.triggered.connect(self._open_docx)
        act_export.triggered.connect(self._export_docx)
        act_fit.triggered.connect(self.image_view.fit)
        self._act_export = act_export
        act_export.setEnabled(False)

    def _build_worker(self) -> None:
        self._worker = DetectorWorker()
        self._thread = QtCore.QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.start()
        self._worker.detected.connect(self._on_detected)
        self._worker.failed.connect(self._on_detect_failed)
        self._worker.finished_batch.connect(self._on_batch_done)
        self._worker.progress.connect(self._on_progress)
        self.request_detect_one.connect(self._worker.detect_one)
        self.request_detect_batch.connect(self._worker.detect_batch)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        # 让 detect_batch 能尽快跳出循环
        self._thread.requestInterruption()
        self._thread.quit()
        # 给当前正跑的单张推理一点时间收尾
        if not self._thread.wait(5000):
            self._thread.terminate()
            self._thread.wait(1000)
        super().closeEvent(event)

    def _step_image(self, delta: int) -> None:
        n = self.image_list.count()
        if n == 0:
            return
        cur = max(0, self.image_list.currentRow())
        nxt = max(0, min(n - 1, cur + delta))
        if nxt != cur:
            self.image_list.setCurrentRow(nxt)

    # --- docx 打开 ---

    def _open_docx(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 Word 文档", "", "Word 文档 (*.docx)"
        )
        if not path:
            return
        try:
            images = extract_images(Path(path))
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "打开失败", str(exc))
            return
        if not images:
            QtWidgets.QMessageBox.information(self, "无图片", "这个 docx 里找不到图片。")
            return

        self._docx_path = Path(path)
        self._states = []
        self.image_list.clear()
        for img in images:
            st = ImageState(arcname=img.arcname, data=img.data, suffix=img.suffix)
            try:
                # 用 PIL 统一解到 3 通道 RGB:CMYK 不会反色、RGBA/P/L 也都正确转换
                im = PilImage.open(io.BytesIO(img.data))
                if im.mode != "RGB":
                    im = im.convert("RGB")
                st.frame = np.array(im, dtype=np.uint8)
            except Exception as exc:  # noqa: BLE001
                st.error = f"解码失败: {exc}"
            self._states.append(st)
            short = Path(img.arcname).name
            QtWidgets.QListWidgetItem(short, self.image_list)

        self.setWindowTitle(f"deface · {self._docx_path.name}")
        self._act_export.setEnabled(True)
        self.image_list.setCurrentRow(0)

        # 后台批量检测全部图片
        jobs = [(i, st.frame) for i, st in enumerate(self._states) if st.frame is not None]
        if jobs:
            self.status.showMessage(f"正在检测 0/{len(jobs)} ...")
            self.request_detect_batch.emit(jobs, DEFAULT_THRESHOLD)

    # --- 选图切换 ---

    def _on_select_image(self, row: int) -> None:
        self._current = row
        if row < 0 or row >= len(self._states):
            self.image_view.set_image(None, [])
            return
        st = self._states[row]
        self.params.load_params(st.params)
        self.image_view.set_image(st.frame, st.faces)
        self._refresh_list_label(row)

    def _refresh_list_label(self, row: int) -> None:
        st = self._states[row]
        item = self.image_list.item(row)
        if item is None:
            return
        name = Path(st.arcname).name
        if st.error:
            item.setText(f"{name}  ⚠ {st.error}")
        elif not st.detected:
            item.setText(f"{name}  ⏳")
        else:
            kept = sum(1 for f in st.faces if f.keep)
            item.setText(f"{name}  {kept}/{len(st.faces)} 保留")

    # --- 检测信号 ---

    @QtCore.Slot(int, list)
    def _on_detected(self, idx: int, faces: List[FaceBox]) -> None:
        if not (0 <= idx < len(self._states)):
            return
        st = self._states[idx]
        # 复用旧 keep(IoU 匹配)+ 保留所有手动加的框
        old_keeps = [f for f in st.faces if f.keep and not f.manual]
        manual = [f for f in st.faces if f.manual]
        for face in faces:
            face.keep = any(_iou(face, k) >= 0.35 for k in old_keeps)
        st.faces = faces + manual
        st.detected = True
        st.error = None
        self._refresh_list_label(idx)
        if idx == self._current:
            self.image_view.set_image(st.frame, st.faces)

    @QtCore.Slot(int, str)
    def _on_detect_failed(self, idx: int, msg: str) -> None:
        if 0 <= idx < len(self._states):
            self._states[idx].error = msg.split("\n", 1)[0]
            self._refresh_list_label(idx)

    @QtCore.Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self.status.showMessage(f"正在检测 {done}/{total} ...")

    @QtCore.Slot()
    def _on_batch_done(self) -> None:
        self.status.showMessage(f"全部检测完成({len(self._states)} 张)")

    # --- 人脸点击 ---

    @QtCore.Slot(int)
    def _on_face_clicked(self, idx: int) -> None:
        if not (0 <= self._current < len(self._states)):
            return
        st = self._states[self._current]
        if not (0 <= idx < len(st.faces)):
            return
        st.faces[idx].keep = not st.faces[idx].keep
        self.image_view.update_face_states(st.faces)
        self._refresh_list_label(self._current)

    @QtCore.Slot(int)
    def _on_face_deleted(self, idx: int) -> None:
        if not (0 <= self._current < len(self._states)):
            return
        st = self._states[self._current]
        if not (0 <= idx < len(st.faces)):
            return
        del st.faces[idx]
        # 索引会重排,重建整图
        self.image_view.set_image(st.frame, st.faces)
        self._refresh_list_label(self._current)

    @QtCore.Slot(QtCore.QRectF)
    def _on_box_added(self, rect: QtCore.QRectF) -> None:
        if not (0 <= self._current < len(self._states)):
            return
        st = self._states[self._current]
        st.faces.append(FaceBox(
            x1=int(rect.x()), y1=int(rect.y()),
            x2=int(rect.x() + rect.width()), y2=int(rect.y() + rect.height()),
            score=1.0, keep=False, manual=True,
        ))
        self.image_view.set_image(st.frame, st.faces)
        self._refresh_list_label(self._current)

    def _set_all_keep(self, keep: bool) -> None:
        if not (0 <= self._current < len(self._states)):
            return
        st = self._states[self._current]
        for f in st.faces:
            f.keep = keep
        self.image_view.update_face_states(st.faces)
        self._refresh_list_label(self._current)

    # --- 参数变化 ---

    def _on_params_changed(self) -> None:
        if not (0 <= self._current < len(self._states)):
            return
        self.params.write_to(self._states[self._current].params)

    def _on_threshold_changed(self, value: float) -> None:
        if not (0 <= self._current < len(self._states)):
            return
        st = self._states[self._current]
        st.params.threshold = value
        self._redetect_current()

    def _redetect_current(self) -> None:
        if not (0 <= self._current < len(self._states)):
            return
        st = self._states[self._current]
        if st.frame is None:
            return
        self.status.showMessage(f"重新检测 {Path(st.arcname).name} ...")
        self.request_detect_one.emit(self._current, st.frame, st.params.threshold)

    # --- 导出 ---

    def _export_docx(self) -> None:
        if self._docx_path is None or not self._states:
            return
        default_out = self._docx_path.with_name(self._docx_path.stem + "_anonymized.docx")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出新 docx", str(default_out), "Word 文档 (*.docx)"
        )
        if not path:
            return
        out_path = Path(path)
        try:
            replacements = self._build_replacements()
            write_docx(self._docx_path, out_path, replacements)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self, "导出失败",
                f"{exc}\n\n{traceback.format_exc()}",
            )
            return
        QtWidgets.QMessageBox.information(
            self, "完成",
            f"导出完成:\n{out_path}\n\n替换图片 {len(replacements)} 张。"
        )
        self.status.showMessage(f"导出到 {out_path}")

    def _build_replacements(self) -> dict[str, bytes]:
        """对每张有要打码的图,跑掉非 keep 的脸,编码回原格式。无脸或全 keep 的图跳过(原图保留)。"""
        replacements: dict[str, bytes] = {}
        for st in self._states:
            if st.frame is None or not st.faces:
                continue
            to_mask = [f for f in st.faces if not f.keep]
            if not to_mask:
                continue
            frame = st.frame.copy()
            self._apply_masking(frame, to_mask, st.params)
            replacements[st.arcname] = _encode_image(frame, st.suffix)
        return replacements

    @staticmethod
    def _apply_masking(frame: np.ndarray, faces: List[FaceBox], params: ImageParams) -> None:
        for i, face in enumerate(faces):
            x1, y1, x2, y2 = scale_bb(face.x1, face.y1, face.x2, face.y2, params.mask_scale)
            y1 = max(0, int(y1)); y2 = min(frame.shape[0], int(y2))
            x1 = max(0, int(x1)); x2 = min(frame.shape[1], int(x2))
            if x2 <= x1 or y2 <= y1:
                continue
            draw_det(
                frame, face.score, i, x1, y1, x2, y2,
                replacewith=params.replacewith,
                ellipse=True,
                draw_scores=False,
                mosaicsize=params.mosaic_size,
            )


# ---------- helpers ----------


def _iou(a: FaceBox, b: FaceBox) -> float:
    x1 = max(a.x1, b.x1); y1 = max(a.y1, b.y1)
    x2 = min(a.x2, b.x2); y2 = min(a.y2, b.y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    area_a = max(1, (a.x2 - a.x1) * (a.y2 - a.y1))
    area_b = max(1, (b.x2 - b.x1) * (b.y2 - b.y1))
    return inter / (area_a + area_b - inter)


_EXT_TO_PIL = {
    ".jpg": ("JPEG", "RGB"),
    ".jpeg": ("JPEG", "RGB"),
    ".png": ("PNG", None),       # PNG 保留 RGBA / RGB / L
    ".bmp": ("BMP", "RGB"),
    ".tif": ("TIFF", None),
    ".tiff": ("TIFF", None),
    ".webp": ("WEBP", None),
    ".gif": ("GIF", "RGB"),
}


def _encode_image(frame: np.ndarray, suffix: str) -> bytes:
    """把 numpy 数组编码为指定后缀的图片字节。

    JPEG 不支持 alpha,PIL 直接写 4 通道会炸。这里按 ext 强制转 mode:
    - JPEG/BMP/GIF 一律 RGB(去 alpha)
    - PNG/TIFF/WEBP 透传(支持 alpha)
    """
    suffix = suffix.lower()
    fmt, force_mode = _EXT_TO_PIL.get(suffix, ("PNG", None))

    arr = frame
    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)
    # 单通道灰度 → 给个 mode 给 PIL
    if arr.ndim == 2:
        im = PilImage.fromarray(arr, mode="L")
    elif arr.shape[2] == 4:
        im = PilImage.fromarray(arr, mode="RGBA")
    elif arr.shape[2] == 3:
        im = PilImage.fromarray(arr, mode="RGB")
    else:
        im = PilImage.fromarray(arr[:, :, :3], mode="RGB")

    if force_mode is not None and im.mode != force_mode:
        im = im.convert(force_mode)

    buf = io.BytesIO()
    save_kwargs = {}
    if fmt == "JPEG":
        save_kwargs["quality"] = 92
        save_kwargs["subsampling"] = 0
    im.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
