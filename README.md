<p align="right"><b>English</b> · <a href="README_zh.md">中文</a></p>

# deface · Office / ODF document face-anonymizer GUI

> Fork of [ORB-HD/deface](https://github.com/ORB-HD/deface). Upstream is a CLI for video / image anonymization. **This fork adds a PySide6 desktop GUI focused on Office and OpenDocument files** — Word / PowerPoint / Excel / LibreOffice. Open a `.docx` / `.pptx` / `.xlsx` / `.odt` / `.odp` / `.ods`, review every detected face one by one, export an anonymized copy without breaking the document. The original `deface` CLI for videos and images is still available — see [Upstream CLI](#-upstream-cli).

Original | After (`deface examples/city.jpg`)
:--:|:--:
![](examples/city.jpg) | ![](examples/city_anonymized.jpg)

## ✨ Features

- **Open Office / ODF documents** — `.docx` `.docm` `.dotx` / `.pptx` `.pptm` `.potx` / `.xlsx` `.xlsm` `.xltx` / `.odt` `.odp` `.ods`. Embedded images extracted from the right zip prefix (`word/media/`, `ppt/media/`, `xl/media/`, `Pictures/`, plus `*/embeddings/`).
- **YuNet face detection** via OpenCV's `cv2.FaceDetectorYN` — more accurate than upstream's CenterFace on still images, and won't OOM on huge inputs.
- **Five replace modes**: `blur` · `frosted` (blur + light fog, more obviously "covered") · `solid` (black) · `mosaic` · `none` (boxes only).
- **Mask shape / feather / opacity** — pick `ellipse` or `rect`, soften edges with a Gaussian feather radius, dial overall mask strength down to let the original peek through.
- **Keyword OCR redaction** — paste keywords (one per line), the GUI scans every image and adds boxes around matching text so you can mask it just like a face. Backends: macOS Vision (`ocrmac`, native, no extra binary) and **cross-platform Tesseract** (chi_sim + eng bundled in the Windows release).
- **Per-image manual review:**
  - 🔴 red box = will be masked · 🟢 green = kept · 🟡/🔵 = OCR text matches (mask / keep)
  - left-click toggles, right-click deletes
  - **Manual box drawing** for missed faces — drag a rectangle, generates a red `manual=True` box that survives re-detection.
- **Threshold slider** with 350 ms debounce. Current image is re-detected automatically; old red/green flags are reused via IoU when boxes overlap.
- **`Up/Down` or `J/K` navigation** between images, focus-independent.
- **Export** writes a new file with a non-blocking progress dialog (no more "not responding"):
  - Only modified images are re-encoded — everything else (`document.xml`, relationships, styles, slides, sheets) is byte-passthrough, so the result opens cleanly in Word / PowerPoint / Excel / LibreOffice.
  - Output extension matches input automatically.
- **Transparent PNG safe** — alpha channel is preserved on load and re-attached on encode, so PNGs with transparency no longer export with a black background.
- **Per-extension encoding** — `.jpg/.bmp/.gif` forced to RGB (drop alpha), `.png/.tif/.webp` keep alpha. JPEG no longer crashes on alpha-bearing inputs.

## 📥 Windows one-click bundle

Don't want to install Python? Grab a self-contained bundle from CI:

1. Open the [`build-windows-gui` workflow](https://github.com/ChaosJulien/deface/actions/workflows/build-windows-gui.yml) and click the latest successful run.
2. Scroll to **Artifacts** → download `deface_gui-windows-x64`.
3. Unzip → double-click `deface_gui.exe`. Bundled with Qt, onnxruntime (CPU), and Tesseract + `chi_sim`/`eng` data — the target machine needs nothing pre-installed.

> Downloading from Actions requires being signed in to GitHub. Tagged Releases will be added later for anonymous downloads.

## 🚀 Install (from source)

Requires **Python 3.10+** (tested on 3.14). Use a venv:

```bash
git clone https://github.com/ChaosJulien/deface.git
cd deface
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e .
pip install PySide6 onnxruntime imageio Pillow pytesseract
# macOS only, for Apple Vision OCR (faster + zero deps): pip install ocrmac
```

The YuNet model (`face_detection_yunet_2023mar.onnx`, 228 KB) is committed to this repo — no extra download needed.

For the OCR keyword feature: macOS uses `ocrmac` (Apple Vision, install separately). Linux / Windows source installs need Tesseract installed system-wide (`brew install tesseract` / `apt install tesseract-ocr` / [UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki)). The Windows bundle above already ships with Tesseract.

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
| Replace mode | `blur` | `blur` · `frosted` (blur + light fog) · `solid` (black box) · `mosaic` · `none` (boxes only) |
| Shape | `ellipse` | Mask shape. `rect` for hard rectangles |
| Mask scale | `1.30` | Expand mask by 30% to cover hair / chin |
| Feather | `0` | Gaussian feather radius (px). `0` = hard edge |
| Opacity | `100` | Mask strength (%). `<100` lets the original image bleed through |
| Mosaic size | `20` | Only when mode = mosaic |
| Detection threshold | `0.50` | YuNet score; higher = stricter (more misses, fewer false positives) |

### 🛡 Non-destructive guarantees

- The source file is never touched — export goes to a new file.
- Images with no red boxes (no detection, or all flipped to green) → **byte-level passthrough** (`zin.read → zout.writestr`), no quality loss from re-encoding.
- Detection downscales large images to long-edge 1280 for speed, but **anonymization is drawn on the full-resolution original**, so exported image quality matches the source.

## 🔬 How it works

1. **Parse OOXML / ODF** (zip): pull all `.png/.jpg/.jpeg/.bmp/.gif/.tif/.webp` from `word/media`, `ppt/media`, `xl/media`, `*/embeddings`, `Pictures/`.
2. **Decode**: PIL `Image.open` → 3-channel RGB for detection. RGBA / `LA` / palette-with-transparency: alpha is split off and stored separately so it can be re-attached on encode (transparent PNGs no longer flatten to a black background).
3. **Detect**: YuNet (`cv2.FaceDetectorYN`) on BGR. Large images are `cv2.resize`'d to long edge 1280; results are scaled back to original coordinates.
4. **OCR (optional)**: keyword scan via `ocrmac` (macOS) or `pytesseract` (cross-platform). Word-level boxes are aggregated by line, then matched both space-joined and concatenated for CJK + Latin coverage.
5. **Anonymize**: ellipse / rectangle mask with optional Gaussian feather + per-image opacity, blended into the original ROI. Modes: blur, frosted (blur + fog), mosaic, solid.
6. **Repack**: a background `QThread` runs masking + encoding + zip rewrite while a progress dialog updates. Modified images go through `zout.writestr`; every other entry is byte-pass-through via `ZipInfo`.

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
