<p align="right"><b>English</b> · <a href="README_zh.md">中文</a></p>

# deface · Office / ODF document face-anonymizer GUI

> Fork of [ORB-HD/deface](https://github.com/ORB-HD/deface). Upstream is a CLI for video / image anonymization. **This fork adds a PySide6 desktop GUI focused on Office and OpenDocument files** — Word / PowerPoint / Excel / LibreOffice. Open a `.docx` / `.pptx` / `.xlsx` / `.odt` / `.odp` / `.ods`, review every detected face one by one, export an anonymized copy without breaking the document. The original `deface` CLI for videos and images is still available — see [Upstream CLI](#-upstream-cli).

Original | After (`deface examples/city.jpg`)
:--:|:--:
![](examples/city.jpg) | ![](examples/city_anonymized.jpg)

## ✨ Features

- **Open Office / ODF documents** — `.docx` `.docm` `.dotx` / `.pptx` `.pptm` `.potx` / `.xlsx` `.xlsm` `.xltx` / `.odt` `.odp` `.ods`. Embedded images extracted from the right zip prefix (`word/media/`, `ppt/media/`, `xl/media/`, `Pictures/`, plus `*/embeddings/`).
- **YuNet face detection** via OpenCV's `cv2.FaceDetectorYN` — more accurate than upstream's CenterFace on still images, and won't OOM on huge inputs.
- **Per-image manual review:**
  - 🔴 red box = will be blurred
  - 🟢 green box = kept (flip misdetections with a click)
  - left-click toggles, right-click deletes
  - **Manual box drawing** for missed faces — drag a rectangle, generates a red `manual=True` box that survives re-detection.
- **Threshold slider** with 350 ms debounce. Current image is re-detected automatically; old red/green flags are reused via IoU when boxes overlap.
- **`Up/Down` or `J/K` navigation** between images, focus-independent.
- **Export** writes a new file:
  - Only modified images are re-encoded — everything else (`document.xml`, relationships, styles, slides, sheets) is byte-passthrough, so the result opens cleanly in Word / PowerPoint / Excel / LibreOffice.
  - Output extension matches input automatically.
- **PIL `convert("RGB")`** decoding — CMYK / RGBA / palette PNGs no longer come back inverted.
- **Per-extension encoding** — `.jpg/.bmp/.gif` forced to RGB (drop alpha), `.png/.tif/.webp` keep alpha. JPEG no longer crashes on alpha-bearing inputs.

## 🚀 Install

Requires **Python 3.10+** (tested on 3.14). Use a venv:

```bash
git clone https://github.com/ChaosJulien/deface.git
cd deface
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e .
pip install PySide6 onnxruntime imageio Pillow
```

The YuNet model (`face_detection_yunet_2023mar.onnx`, 228 KB) is committed to this repo — no extra download needed.

## 🖱 Using the GUI

```bash
python -m deface.docx_gui
```

Workflow:

1. Toolbar **"Open document"** → pick a `.docx` / `.pptx` / `.xlsx` / `.odt` / `.odp` / `.ods` etc.
2. All images are detected in parallel in the background. Left panel shows progress as `blurred N / total`.
3. Review each image on the central canvas:
   - **Left-click** a box → toggle red ↔ green
   - **Right-click** a box → delete
   - **Cmd/Ctrl + scroll** → zoom; drag the image to pan when not in manual mode
4. For missed faces → right panel **"✏️ Manual box"**, drag a rectangle, releases as a red `manual=True` box. Manual boxes are not overwritten on re-detection.
5. Too many false positives / negatives → adjust **threshold** (0.3 ~ 0.7) on the right; the current image is re-detected after 350 ms debounce.
6. Toolbar **"Export document"** → defaults to `<filename>_anonymized.<same-ext>`.

### ⌨️ Shortcuts

| Key | Action |
|---|---|
| `↑` / `K` | Previous image |
| `↓` / `J` | Next image |
| `Cmd/Ctrl + scroll` | Zoom |
| Mouse drag (non-manual) | Pan |

### ⚙️ Parameters

| Param | Default | Meaning |
|---|---|---|
| Replace mode | `blur` | Gaussian blur. Also: `solid` (black box), `mosaic`, `none` (boxes only) |
| Mask scale | `1.30` | Expand mask by 30% to cover hair / chin |
| Mosaic size | `20` | Only when mode = mosaic |
| Detection threshold | `0.50` | YuNet score; higher = stricter (more misses, fewer false positives) |

### 🛡 Non-destructive guarantees

- The source file is never touched — export goes to a new file.
- Images with no red boxes (no detection, or all flipped to green) → **byte-level passthrough** (`zin.read → zout.writestr`), no quality loss from re-encoding.
- Detection downscales large images to long-edge 1280 for speed, but **anonymization is drawn on the full-resolution original**, so exported image quality matches the source.

## 🔬 How it works

1. **Parse OOXML / ODF** (zip): pull all `.png/.jpg/.jpeg/.bmp/.gif/.tif/.webp` from `word/media`, `ppt/media`, `xl/media`, `*/embeddings`, `Pictures/`.
2. **Decode**: PIL `Image.open + convert("RGB")` normalizes CMYK / RGBA / palette / grayscale into 3-channel RGB to avoid color inversion.
3. **Detect**: YuNet (`cv2.FaceDetectorYN`) on BGR. Large images are `cv2.resize`'d to long edge 1280; results are scaled back to original coordinates.
4. **Anonymize**: reuses upstream's `draw_det` (ellipse mask + Gaussian / mosaic / solid).
5. **Repack**: `zipfile` rewrites the container, modified images go through `zout.writestr`, every other entry is byte-pass-through via `ZipInfo`.

## 🖥 Upstream CLI

The original `deface` CLI is still available for videos and batch image processing:

```bash
# video
deface myvideo.mp4

# images (glob supported)
deface 'photos/*.jpg'

# threshold + mode
deface input.mp4 --thresh 0.5 --replacewith mosaic --mosaicsize 30
```

Full options: see [ORB-HD/deface](https://github.com/ORB-HD/deface#cli-usage-and-options-summary).

## 🙏 Credits

- Upstream project: [ORB-HD/deface](https://github.com/ORB-HD/deface) (MIT)
- CenterFace model (upstream CLI): [Star-Clouds/centerface](https://github.com/Star-Clouds/centerface) (MIT)
- YuNet model (this GUI): [opencv/opencv_zoo · face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (MIT)
- Training data: [WIDER FACE](http://shuoyang1213.me/WIDERFACE/)
- Example photo: [Pexels](https://www.pexels.com/de-de/foto/stadt-kreuzung-strasse-menschen-109919/) (Pexels license)

## 📄 License

MIT — same as upstream [LICENSE](LICENSE).
