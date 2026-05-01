<p align="right"><a href="README.md">English</a> · <b>中文</b></p>

# deface · Office / ODF 文档人脸打码 GUI

> 本仓库 fork 自 [ORB-HD/deface](https://github.com/ORB-HD/deface)。原版是面向视频 / 图片的命令行工具。**这个 fork 在原版基础上加了一个面向 Office 和 OpenDocument 文档的 PySide6 桌面 GUI** —— Word / PowerPoint / Excel / LibreOffice 都吃。打开 `.docx` / `.pptx` / `.xlsx` / `.odt` / `.odp` / `.ods`,逐张人工审核每张图的人脸,导出匿名化后的副本,**不破坏原文档**。原版 deface 的视频/图片 CLI 仍然可用,见下文 [上游 CLI](#-上游-cli)。

原图 | 打码后 (`deface examples/city.jpg`)
:--:|:--:
![](examples/city.jpg) | ![](examples/city_anonymized.jpg)

## ✨ 主要功能

- **支持 Office / ODF 文档** — `.docx` `.docm` `.dotx` / `.pptx` `.pptm` `.potx` / `.xlsx` `.xlsm` `.xltx` / `.odt` `.odp` `.ods`。从对应 zip 前缀(`word/media/`、`ppt/media/`、`xl/media/`、`Pictures/`,加 `*/embeddings/`)抽出全部嵌入图片。
- **YuNet 检测人脸**,走 OpenCV `cv2.FaceDetectorYN` —— 静图上比原版 CenterFace 准,大图也不会爆显存。
- **逐张人工审核**:
  - 🔴 红框 = 会被高斯模糊
  - 🟢 绿框 = 保留(误判时点掉它)
  - 左键点框切换、右键删框
  - **手动加框**:漏检的脸自己拖矩形补,生成 `manual=True` 的红框,重新检测时**不会被覆盖**
- **阈值滑块** 350 ms 防抖,自动对当前图重检测,旧的红/绿状态用 IoU 自动复用
- **`Up/Down`(或 `J/K`)切换图片**,无论焦点在哪都生效
- **导出** 写新文件:
  - 只重编码改过的图;`document.xml` / 关系 / 样式 / 幻灯片 / 表格按字节透传,Word / PowerPoint / Excel / LibreOffice 100% 能正常打开
  - 导出后缀自动跟源文件一致
- **解码用 PIL `convert("RGB")`** —— CMYK / RGBA / 调色板 PNG 不会再反色
- **编码按扩展名强制 mode** —— `.jpg/.bmp/.gif` 强制 RGB(去 alpha)、`.png/.tif/.webp` 透传 alpha,JPEG 不会再因 alpha 崩

## 🚀 安装

需要 **Python 3.10+**(在 3.14 上测过)。建议先建 venv:

```bash
git clone https://github.com/ChaosJulien/deface.git
cd deface
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e .
pip install PySide6 onnxruntime imageio Pillow
```

YuNet 模型 (`face_detection_yunet_2023mar.onnx`,228 KB) 已随仓库一起提交,无需额外下载。

## 🖱 使用 GUI

```bash
python -m deface.docx_gui
```

操作流程:

1. 工具栏 **「打开文档」** → 选 `.docx` / `.pptx` / `.xlsx` / `.odt` / `.odp` / `.ods` 等
2. 后台并行检测所有图片,左侧列表显示进度 `打码 N / 总数`
3. 在中央画布上审核每一张:
   - **左键** 框 = 切换 红 / 绿(打码 / 保留)
   - **右键** 框 = 删除(无论是误判还是手动加的)
   - **Cmd+滚轮 / Ctrl+滚轮** = 缩放;不缩放时鼠标可拖动平移
4. 漏检的脸 → 右侧 **「✏️ 手动加框」**,鼠标拖矩形,松手生成红框(`manual=True`)
5. 误判太多 / 漏检太多 → 调右侧 **检测阈值**(0.3 ~ 0.7),350 ms 防抖后自动对当前图重检测
6. 工具栏 **「导出文档」** → 默认存成 `<原文件名>_anonymized.<原后缀>`

### ⌨️ 快捷键

| 键 | 作用 |
|---|---|
| `↑` / `K` | 上一张图 |
| `↓` / `J` | 下一张图 |
| `Cmd / Ctrl + 滚轮` | 缩放当前图 |
| 鼠标左键拖 | 平移图(非手动模式)|

### ⚙️ 参数说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| 打码方式 | `blur` | 高斯模糊;另可选 `solid`(实心黑)、`mosaic`(马赛克)、`none`(只画框,不打码) |
| 遮罩外扩 | `1.30` | 外扩 30% 把头发/下巴吃进去,防止边缘漏 |
| 马赛克尺寸 | `20` | 仅 mosaic 模式生效 |
| 检测阈值 | `0.50` | YuNet score 阈值,越高越严(漏检多但误判少)|

### 🛡 设计上保证不破坏原文件

- 原文件永远不动,导出是新文件
- 没勾打码、没检出脸、所有框都是绿框的图片 → **原图字节透传**(`zin.read → zout.writestr`),不会被重新编码导致质量下降
- 检测时大图缩到长边 1280 加速,但**打码画在原图全分辨率上**,导出图清晰度 = 原图清晰度

## 🔬 工作原理

1. **解析 OOXML / ODF**(zip):`word/media`、`ppt/media`、`xl/media`、`*/embeddings`、`Pictures/` 下的 `.png/.jpg/.jpeg/.bmp/.gif/.tif/.webp` 全部抽出
2. **解码归一**:PIL `Image.open + convert("RGB")` 把 CMYK / RGBA / 调色板 / 灰度统一成 3 通道 RGB,杜绝反色
3. **检测**:YuNet (`cv2.FaceDetectorYN`) 在 BGR 上跑,大图先 `cv2.resize` 到长边 1280,框结果 ×inv 放回原坐标
4. **打码**:沿用原版 `draw_det` 函数(椭圆遮罩 + 高斯/马赛克/实心)
5. **回写**:`zipfile` 重打包,只对改过的图片走 `zout.writestr`,其余条目按 `ZipInfo` 字节级透传

## 🖥 上游 CLI

原版 `deface` 仍然可用,适合视频或一堆散图的批量处理:

```bash
# 视频
deface myvideo.mp4

# 图片(支持通配符)
deface 'photos/*.jpg'

# 调阈值 + 改打码方式
deface input.mp4 --thresh 0.5 --replacewith mosaic --mosaicsize 30
```

完整选项详见原仓库 README:[ORB-HD/deface](https://github.com/ORB-HD/deface#cli-usage-and-options-summary)。

## 🙏 致谢

- 上游项目:[ORB-HD/deface](https://github.com/ORB-HD/deface) (MIT)
- CenterFace 模型(原版 CLI 用):[Star-Clouds/centerface](https://github.com/Star-Clouds/centerface) (MIT)
- YuNet 模型(本 GUI 用):[opencv/opencv_zoo · face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (MIT)
- 训练数据集:[WIDER FACE](http://shuoyang1213.me/WIDERFACE/)
- 示例图片:[Pexels](https://www.pexels.com/de-de/foto/stadt-kreuzung-strasse-menschen-109919/) (Pexels license)

## 📄 License

MIT —— 沿用上游 [LICENSE](LICENSE)。
