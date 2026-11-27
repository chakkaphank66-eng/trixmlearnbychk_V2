import os
import re
import time
import uuid
import shutil
import tempfile
from pathlib import Path

import cv2
import img2pdf
import numpy as np
import streamlit as st
import yt_dlp
from PIL import Image, ImageDraw
from skimage.metrics import structural_similarity as ssim

# -----------------------------------------------------------------------------
# ตั้งค่าหน้าเว็บ
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="YouTube to Study Sheet PDF",
    page_icon="📄",
    layout="wide",
)


# -----------------------------------------------------------------------------
# ฟังก์ชันช่วยเหลือ (จัดการไฟล์, เวลา, ภาพ รองรับพาธภาษาไทยบน Windows)
# -----------------------------------------------------------------------------
def get_safe_work_dir() -> Path:
    """สร้างโฟลเดอร์ชั่วคราวที่ปลอดภัยต่อพาธภาษาไทยบน Windows"""
    session_id = uuid.uuid4().hex[:10]
    temp_root = Path(tempfile.gettempdir())
    try:
        str(temp_root).encode("ascii")
        base_dir = temp_root / "yt2pdf_workspace" / session_id
    except UnicodeEncodeError:
        base_dir = Path.cwd() / "_yt2pdf_cache" / session_id
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def cleanup_dir(path_str: str | None) -> None:
    if path_str and os.path.exists(path_str):
        shutil.rmtree(path_str, ignore_errors=True)


def sanitize_filename(name: str, max_len: int = 80) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|\r\n]+', "_", name).strip()
    return (cleaned[:max_len].strip() or "study_sheet")


def parse_time_to_sec(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        return max(0.0, nums[0])
    if len(nums) == 2:
        return max(0.0, nums[0] * 60 + nums[1])
    if len(nums) == 3:
        return max(0.0, nums[0] * 3600 + nums[1] * 60 + nums[2])
    return None


def format_sec(sec: float) -> str:
    sec_int = max(0, int(sec))
    h = sec_int // 3600
    m = (sec_int % 3600) // 60
    s = sec_int % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def save_bgr_image(path: Path, bgr: np.ndarray, quality: int = 95) -> None:
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if ok:
        path.write_bytes(buf.tobytes())


def load_bgr_image(path: Path) -> np.ndarray | None:
    if not path.exists():
        return None
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


# -----------------------------------------------------------------------------
# ขั้นที่ 1: ดาวน์โหลดเฉพาะไฟล์ภาพความละเอียดสูงด้วย yt-dlp
# -----------------------------------------------------------------------------
def download_youtube_video(
    url: str,
    work_dir: Path,
    max_height: int,
    progress_bar,
    status_box,
) -> tuple[Path, str, float]:
    last_update = [0.0]

    def progress_hook(d: dict) -> None:
        now = time.time()
        if d.get("status") == "downloading":
            if now - last_update[0] < 0.3:
                return
            last_update[0] = now
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            speed = d.get("speed") or 0
            speed_mb = speed / (1024 * 1024)
            if total > 0:
                ratio = min(1.0, downloaded / total)
                progress_bar.progress(ratio)
                status_box.info(
                    f"กำลังดาวน์โหลดวิดีโอ... {ratio * 100:.1f}% "
                    f"({downloaded / 1e6:.1f} / {total / 1e6:.1f} MB | {speed_mb:.1f} MB/s)"
                )
            else:
                status_box.info(
                    f"กำลังดาวน์โหลดวิดีโอ... {downloaded / 1e6:.1f} MB ({speed_mb:.1f} MB/s)"
                )
        elif d.get("status") == "finished":
            progress_bar.progress(1.0)
            status_box.info("ดาวน์โหลดเสร็จสิ้น กำลังเตรียมสแกนหน้าจอ...")

    # เลือก H.264 (avc1) ก่อนเพื่อให้ OpenCV ข้ามเฟรมได้เร็วและเสถียรที่สุด
    fmt = (
        f"bestvideo[height<={max_height}][vcodec^=avc1]/"
        f"bestvideo[height<={max_height}][ext=mp4]/"
        f"bestvideo[height<={max_height}]/"
        f"best[height<={max_height}][ext=mp4]/"
        f"best[height<={max_height}]/best"
    )

    ydl_opts = {
        "format": fmt,
        "outtmpl": str(work_dir / "source_video.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "progress_hooks": [progress_hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title") or "YouTube_Lecture"
        duration = float(info.get("duration") or 0.0)

    candidates = [
        p for p in work_dir.glob("source_video.*")
        if p.suffix not in {".part", ".ytdl"}
    ]
    if not candidates:
        raise FileNotFoundError("ไม่พบไฟล์วิดีโอหลังจากดาวน์โหลด กรุณาตรวจสอบลิงก์อีกครั้ง")

    return candidates[0], title, duration


# -----------------------------------------------------------------------------
# ขั้นที่ 2: สแกนข้ามเฟรมและคัดแยกหน้าจอที่ไม่ซ้ำ (รองรับคลิปยาว)
# -----------------------------------------------------------------------------
def to_small_gray(bgr: np.ndarray) -> np.ndarray:
    resized = cv2.resize(bgr, (320, 180), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (5, 5), 0)


def is_blank_screen(gray: np.ndarray) -> bool:
    return float(np.std(gray)) < 8.0


def sharpness_score(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def save_extracted_item(
    frames_dir: Path,
    thumbs_dir: Path,
    idx: int,
    bgr: np.ndarray,
    sec: float,
) -> dict:
    item_id = f"f_{idx:04d}"
    full_path = frames_dir / f"{item_id}.jpg"
    thumb_path = thumbs_dir / f"{item_id}.jpg"

    save_bgr_image(full_path, bgr, quality=95)

    h, w = bgr.shape[:2]
    thumb_w = 480
    thumb_h = max(1, int(h * (thumb_w / w)))
    thumb = cv2.resize(bgr, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
    save_bgr_image(thumb_path, thumb, quality=80)

    return {
        "id": item_id,
        "full_path": str(full_path),
        "thumb_path": str(thumb_path),
        "time_sec": sec,
        "time_str": format_sec(sec),
    }


def extract_unique_frames(
    video_path: Path,
    work_dir: Path,
    fallback_duration: float,
    interval_sec: float,
    similarity_threshold: float,
    capture_mode: str,
    start_sec: float | None,
    end_sec: float | None,
    max_frames: int,
    progress_bar,
    status_box,
) -> tuple[list[dict], bool]:
    frames_dir = work_dir / "frames"
    thumbs_dir = work_dir / "thumbs"
    frames_dir.mkdir(exist_ok=True)
    thumbs_dir.mkdir(exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError("ไม่สามารถเปิดไฟล์วิดีโอเพื่อสแกนได้")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = (total_frames / fps) if (total_frames > 0 and fps > 0) else fallback_duration
    if duration <= 0:
        cap.release()
        raise RuntimeError("ไม่สามารถอ่านความยาวของวิดีโอได้")

    scan_start = max(0.0, start_sec if start_sec is not None else 0.0)
    scan_end = min(duration, end_sec if end_sec is not None else duration)
    if scan_end <= scan_start:
        scan_end = duration

    total_span = max(1.0, scan_end - scan_start)
    dedup_threshold = min(0.96, similarity_threshold + 0.03)

    items: list[dict] = []
    reached_limit = False

    last_saved_small: np.ndarray | None = None
    candidate_bgr: np.ndarray | None = None
    candidate_small: np.ndarray | None = None
    candidate_time: float = 0.0
    candidate_sharp: float = 0.0
    scene_anchor_small: np.ndarray | None = None

    t = scan_start
    fail_streak = 0
    last_ui_update = 0.0

    try:
        while t <= scan_end:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ret, frame = cap.read()
            if not ret or frame is None:
                fail_streak += 1
                if fail_streak >= 5:
                    break
                t += interval_sec
                continue
            fail_streak = 0

            small_gray = to_small_gray(frame)
            if not is_blank_screen(small_gray):
                sharp = sharpness_score(small_gray)

                if capture_mode == "smart":
                    # โหมดเขียนสด / iPad / สไลด์มีอนิเมชัน: เก็บเฟรมสุดท้ายที่สมบูรณ์ก่อนเปลี่ยนหน้า
                    if candidate_bgr is None:
                        candidate_bgr = frame.copy()
                        candidate_small = small_gray
                        candidate_time = t
                        candidate_sharp = sharp
                        scene_anchor_small = small_gray
                    else:
                        step_sim = float(ssim(candidate_small, small_gray, data_range=255))
                        drift_sim = float(ssim(scene_anchor_small, small_gray, data_range=255))

                        if step_sim < similarity_threshold:
                            # เกิดการเปลี่ยนหน้าชัดเจน -> บันทึกเฟรมที่เขียนเสร็จแล้วก่อนหน้า
                            should_save = (
                                last_saved_small is None
                                or float(ssim(last_saved_small, candidate_small, data_range=255)) < dedup_threshold
                            )
                            if should_save:
                                items.append(
                                    save_extracted_item(frames_dir, thumbs_dir, len(items) + 1, candidate_bgr, candidate_time)
                                )
                                last_saved_small = candidate_small

                            # เริ่มหน้าใหม่
                            candidate_bgr = frame.copy()
                            candidate_small = small_gray
                            candidate_time = t
                            candidate_sharp = sharp
                            scene_anchor_small = small_gray

                        elif drift_sim < max(0.50, similarity_threshold - 0.12) and step_sim >= 0.94:
                            # กรณีเลื่อนหน้าจอลงทีละนิด (เช่น GoodNotes) จนเนื้อหาเปลี่ยนไปมากแล้วหยุดนิ่ง
                            should_save = (
                                last_saved_small is None
                                or float(ssim(last_saved_small, candidate_small, data_range=255)) < dedup_threshold
                            )
                            if should_save:
                                items.append(
                                    save_extracted_item(frames_dir, thumbs_dir, len(items) + 1, candidate_bgr, candidate_time)
                                )
                                last_saved_small = candidate_small
                            scene_anchor_small = small_gray
                            candidate_bgr = frame.copy()
                            candidate_small = small_gray
                            candidate_time = t
                            candidate_sharp = sharp
                        else:
                            # ยังอยู่หน้าเดิม -> อัปเดตเป็นเฟรมล่าสุดที่คมชัดเพื่อเก็บข้อความที่เขียนเพิ่ม
                            if sharp >= candidate_sharp * 0.80:
                                candidate_bgr = frame.copy()
                                candidate_small = small_gray
                                candidate_time = t
                                candidate_sharp = sharp
                else:
                    # โหมดสไลด์เปลี่ยนหน้าชัดเจน
                    if last_saved_small is None:
                        items.append(
                            save_extracted_item(frames_dir, thumbs_dir, len(items) + 1, frame, t)
                        )
                        last_saved_small = small_gray
                    else:
                        sim = float(ssim(last_saved_small, small_gray, data_range=255))
                        if sim < similarity_threshold:
                            items.append(
                                save_extracted_item(frames_dir, thumbs_dir, len(items) + 1, frame, t)
                            )
                            last_saved_small = small_gray

            if len(items) >= max_frames:
                reached_limit = True
                break

            now = time.time()
            if now - last_ui_update >= 0.25:
                last_ui_update = now
                ratio = min(1.0, (t - scan_start) / total_span)
                progress_bar.progress(ratio)
                status_box.info(
                    f"กำลังสแกนคลิป {format_sec(t)} / {format_sec(scan_end)} | แคปได้แล้ว {len(items)} หน้า"
                )

            t += interval_sec

        # บันทึกหน้าสุดท้ายของโหมดเขียนสด
        if capture_mode == "smart" and candidate_bgr is not None and not reached_limit:
            should_save = (
                last_saved_small is None
                or float(ssim(last_saved_small, candidate_small, data_range=255)) < dedup_threshold
            )
            if should_save:
                items.append(
                    save_extracted_item(frames_dir, thumbs_dir, len(items) + 1, candidate_bgr, candidate_time)
                )

    finally:
        cap.release()

    progress_bar.progress(1.0)
    return items, reached_limit


# -----------------------------------------------------------------------------
# ขั้นที่ 3: ปรับภาพคมชัดและโหมดพื้นดำเป็นพื้นขาว (รักษาสีปากกาไฮไลต์)
# -----------------------------------------------------------------------------
def enhance_bgr_image(
    bgr: np.ndarray,
    invert_mode: str,
    auto_contrast: bool,
    sharpen: bool,
) -> np.ndarray:
    img = bgr.copy()

    # 1. โหมดกลับพื้นหลังดำเป็นขาวด้วย LAB L-Channel (สีปากกาแดง/ฟ้า/เขียวไม่เพี้ยน)
    do_invert = False
    if invert_mode == "always":
        do_invert = True
    elif invert_mode == "auto":
        gray_mean = float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean())
        do_invert = gray_mean < 110.0

    if do_invert:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        l_ch = cv2.bitwise_not(l_ch)
        img = cv2.cvtColor(cv2.merge([l_ch, a_ch, b_ch]), cv2.COLOR_LAB2BGR)

    # 2. เพิ่มความต่างสี (CLAHE) ให้ลายมือและตัวหนังสือเด้งชัดขึ้น
    if auto_contrast:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
        l_ch = clahe.apply(l_ch)
        img = cv2.cvtColor(cv2.merge([l_ch, a_ch, b_ch]), cv2.COLOR_LAB2BGR)

    # 3. เพิ่มความคมตัวอักษรด้วย Unsharp Mask
    if sharpen:
        blurred = cv2.GaussianBlur(img, (0, 0), 1.4)
        img = cv2.addWeighted(img, 1.5, blurred, -0.5, 0)

    return img


def draw_timestamp_badge(bgr: np.ndarray, time_str: str) -> np.ndarray:
    out = bgr.copy()
    h, w = out.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.55, w / 1920.0 * 0.8)
    thickness = max(1, int(scale * 2))
    (tw, th), baseline = cv2.getTextSize(time_str, font, scale, thickness)

    pad_x, pad_y = 12, 8
    x2 = w - 16
    y2 = h - 16
    x1 = max(0, x2 - tw - pad_x * 2)
    y1 = max(0, y2 - th - pad_y * 2)

    overlay = out.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.65, out, 0.35, 0, out)
    cv2.putText(
        out,
        time_str,
        (x1 + pad_x, y2 - pad_y),
        font,
        scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )
    return out


# -----------------------------------------------------------------------------
# ขั้นที่ 4: จัดหน้าและส่งออกเป็น PDF (ประหยัด RAM ทีละหน้า)
# -----------------------------------------------------------------------------
def paste_fit_pil(canvas: Image.Image, img: Image.Image, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    box_w = x2 - x1
    box_h = y2 - y1
    ratio = min(box_w / img.width, box_h / img.height)
    new_w = max(1, int(img.width * ratio))
    new_h = max(1, int(img.height * ratio))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    px = x1 + (box_w - new_w) // 2
    py = y1 + (box_h - new_h) // 2
    canvas.paste(resized, (px, py))


def build_pdf(
    selected_items: list[dict],
    work_dir: Path,
    layout_mode: str,
    invert_mode: str,
    auto_contrast: bool,
    sharpen: bool,
    add_timestamp: bool,
    progress_bar,
) -> bytes:
    pdf_pages_dir = work_dir / "pdf_pages"
    if pdf_pages_dir.exists():
        shutil.rmtree(pdf_pages_dir, ignore_errors=True)
    pdf_pages_dir.mkdir(exist_ok=True)

    page_paths: list[str] = []
    total = len(selected_items)

    def get_processed_pil(item: dict) -> Image.Image:
        bgr = load_bgr_image(Path(item["full_path"]))
        if bgr is None:
            raise RuntimeError(f"ไม่พบไฟล์ภาพ {item['id']}")
        bgr = enhance_bgr_image(bgr, invert_mode, auto_contrast, sharpen)
        if add_timestamp:
            bgr = draw_timestamp_badge(bgr, item["time_str"])
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    if layout_mode == "full":
        # เต็มหน้าพอดีภาพ เหมาะอ่านบน iPad/แท็บเล็ต
        for i, item in enumerate(selected_items):
            pil_img = get_processed_pil(item)
            out_path = pdf_pages_dir / f"page_{i:04d}.jpg"
            pil_img.save(out_path, "JPEG", quality=92, optimize=True)
            page_paths.append(str(out_path))
            progress_bar.progress((i + 1) / total)

    elif layout_mode == "a4_landscape_1":
        # A4 แนวนอน 200 DPI (2339 x 1654)
        W, H, M = 2339, 1654, 70
        for i, item in enumerate(selected_items):
            pil_img = get_processed_pil(item)
            canvas = Image.new("RGB", (W, H), (255, 255, 255))
            paste_fit_pil(canvas, pil_img, (M, M, W - M, H - M))
            out_path = pdf_pages_dir / f"page_{i:04d}.jpg"
            canvas.save(out_path, "JPEG", quality=92, optimize=True)
            page_paths.append(str(out_path))
            progress_bar.progress((i + 1) / total)

    elif layout_mode == "a4_portrait_2":
        # A4 แนวตั้ง 200 DPI (1654 x 2339) 2 สไลด์ต่อหน้า
        W, H, M, GAP = 1654, 2339, 75, 60
        half_h = (H - 2 * M - GAP) // 2
        boxes = [
            (M, M, W - M, M + half_h),
            (M, M + half_h + GAP, W - M, H - M),
        ]
        page_idx = 0
        for i in range(0, total, 2):
            canvas = Image.new("RGB", (W, H), (255, 255, 255))
            for slot in range(2):
                if i + slot < total:
                    pil_img = get_processed_pil(selected_items[i + slot])
                    paste_fit_pil(canvas, pil_img, boxes[slot])
                    progress_bar.progress(min(1.0, (i + slot + 1) / total))
            out_path = pdf_pages_dir / f"page_{page_idx:04d}.jpg"
            canvas.save(out_path, "JPEG", quality=92, optimize=True)
            page_paths.append(str(out_path))
            page_idx += 1

    elif layout_mode == "a4_portrait_notes":
        # A4 แนวตั้ง (1 สไลด์ด้านบน + เส้นบรรทัดจดโน้ตด้านล่าง)
        W, H, M = 1654, 2339, 80
        slide_bottom = int(H * 0.48)
        for i, item in enumerate(selected_items):
            pil_img = get_processed_pil(item)
            canvas = Image.new("RGB", (W, H), (255, 255, 255))
            paste_fit_pil(canvas, pil_img, (M, M, W - M, slide_bottom))

            draw = ImageDraw.Draw(canvas)
            y = slide_bottom + 75
            while y < H - M:
                draw.line([(M, y), (W - M, y)], fill=(215, 215, 215), width=2)
                y += 72

            out_path = pdf_pages_dir / f"page_{i:04d}.jpg"
            canvas.save(out_path, "JPEG", quality=92, optimize=True)
            page_paths.append(str(out_path))
            progress_bar.progress((i + 1) / total)

    pdf_bytes = img2pdf.convert(page_paths)
    shutil.rmtree(pdf_pages_dir, ignore_errors=True)
    return pdf_bytes


# -----------------------------------------------------------------------------
# ส่วนติดต่อผู้ใช้ (Streamlit UI)
# -----------------------------------------------------------------------------
if "work_dir" not in st.session_state:
    st.session_state.work_dir = None
if "items" not in st.session_state:
    st.session_state.items = []
if "video_title" not in st.session_state:
    st.session_state.video_title = ""
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None

st.title("📄 YouTube to Study Sheet PDF")
st.caption("วางลิงก์คลิปติว YouTube ดึงหน้าสไลด์/กระดานคมชัด คัดรูปที่ไม่ต้องการออก แล้วส่งออกเป็นไฟล์ PDF ฟรี 100%")

# --- แถบตั้งค่าด้านข้าง ---
with st.sidebar:
    st.header("⚙️ ตั้งค่าการดึงภาพ")

    max_height = st.selectbox(
        "ความละเอียดวิดีโอสูงสุด",
        options=[1080, 720],
        index=0,
        help="1080p ให้ภาพตัวหนังสือคมชัดที่สุด หากเน็ตช้าหรือคลิปยาวมากปรับเป็น 720p ได้",
    )

    capture_mode_label = st.radio(
        "รูปแบบคลิปติว",
        options=[
            "เขียนสด / iPad / สไลด์มีอนิเมชัน (แนะนำ)",
            "สไลด์เปลี่ยนหน้าชัดเจน",
        ],
        index=0,
        help="โหมดแนะนำจะรอเก็บเฟรมที่เขียนเสร็จก่อนเปลี่ยนหน้า เพื่อไม่ให้ได้รูปตอนเพิ่งเขียนครึ่งหน้า",
    )
    capture_mode = "smart" if "แนะนำ" in capture_mode_label else "slide"

    interval_sec = st.slider(
        "ระยะห่างการสแกน (วินาที)",
        min_value=1.0,
        max_value=10.0,
        value=3.0,
        step=0.5,
        help="คลิปยาว 2-3 ชม. แนะนำ 3-5 วินาที จะสแกนจบไวมาก",
    )

    similarity_threshold = st.slider(
        "ความไวในการจับเปลี่ยนหน้า",
        min_value=0.70,
        max_value=0.96,
        value=0.88,
        step=0.01,
        help="ค่ายิ่งสูง ยิ่งจับความเปลี่ยนแปลงเล็กๆ ได้ไว (ถ้าได้รูปซ้ำเยอะให้ลดค่านี้ลง)",
    )

    max_frames = st.number_input(
        "จำนวนหน้าสูงสุดที่อนุญาต (กันไฟล์ล้น)",
        min_value=20,
        max_value=600,
        value=250,
        step=10,
    )

    st.divider()
    st.subheader("⏱️ กำหนดช่วงเวลา (ไม่บังคับ)")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        start_time_str = st.text_input("เริ่ม (เช่น 05:00)", value="")
    with col_t2:
        end_time_str = st.text_input("จบ (เช่น 01:30:00)", value="")

    st.divider()
    if st.button("🗑️ ล้างข้อมูลทั้งหมด / เริ่มใหม่", use_container_width=True):
        cleanup_dir(st.session_state.work_dir)
        st.session_state.work_dir = None
        st.session_state.items = []
        st.session_state.video_title = ""
        st.session_state.pdf_bytes = None
        for k in list(st.session_state.keys()):
            if k.startswith("sel_"):
                del st.session_state[k]
        st.rerun()

# --- ช่องใส่ลิงก์ YouTube ---
url_col, btn_col = st.columns([4, 1], vertical_alignment="bottom")
with url_col:
    yt_url = st.text_input(
        "วางลิงก์ YouTube ที่นี่",
        placeholder="https://www.youtube.com/watch?v=...",
    )
with btn_col:
    start_btn = st.button("🚀 เริ่มดึงสไลด์", type="primary", use_container_width=True)

if start_btn:
    if not yt_url.strip():
        st.warning("กรุณาวางลิงก์ YouTube ก่อนครับ")
    else:
        # ล้างงานเก่าก่อนเริ่มงานใหม่
        cleanup_dir(st.session_state.work_dir)
        for k in list(st.session_state.keys()):
            if k.startswith("sel_"):
                del st.session_state[k]
        st.session_state.items = []
        st.session_state.pdf_bytes = None

        work_dir = get_safe_work_dir()
        st.session_state.work_dir = str(work_dir)

        progress_bar = st.progress(0.0)
        status_box = st.empty()
        video_path: Path | None = None

        try:
            start_s = parse_time_to_sec(start_time_str)
            end_s = parse_time_to_sec(end_time_str)

            video_path, title, duration = download_youtube_video(
                yt_url.strip(), work_dir, max_height, progress_bar, status_box
            )

            progress_bar.progress(0.0)
            items, reached_limit = extract_unique_frames(
                video_path=video_path,
                work_dir=work_dir,
                fallback_duration=duration,
                interval_sec=interval_sec,
                similarity_threshold=similarity_threshold,
                capture_mode=capture_mode,
                start_sec=start_s,
                end_sec=end_s,
                max_frames=int(max_frames),
                progress_bar=progress_bar,
                status_box=status_box,
            )

            # ลบไฟล์วิดีโอทันทีหลังสแกนเสร็จเพื่อประหยัดพื้นที่ดิสก์
            if video_path and video_path.exists():
                video_path.unlink(missing_ok=True)

            st.session_state.video_title = title
            st.session_state.items = items
            for item in items:
                st.session_state[f"sel_{item['id']}"] = True

            status_box.success(f"สแกนเสร็จสมบูรณ์! ดึงภาพได้ทั้งหมด {len(items)} หน้าจากคลิป: {title}")
            if reached_limit:
                st.warning(
                    f"หยุดสแกนอัตโนมัติเนื่องจากครบเพดาน {max_frames} หน้า "
                    "(หากได้ภาพซ้ำเยอะ ให้ลดค่า 'ความไวในการจับเปลี่ยนหน้า' แล้วลองใหม่)"
                )

        except yt_dlp.utils.DownloadError as e:
            cleanup_dir(str(work_dir))
            st.session_state.work_dir = None
            status_box.error(
                "ดาวน์โหลดวิดีโอไม่สำเร็จ (อาจเป็นคลิปส่วนตัว/ติดจำกัดอายุ หรือต้องอัปเดต yt-dlp ด้วยคำสั่ง pip install -U yt-dlp)"
            )
            st.exception(e)
        except Exception as e:
            if video_path and video_path.exists():
                video_path.unlink(missing_ok=True)
            status_box.error(f"เกิดข้อผิดพลาด: {e}")


# -----------------------------------------------------------------------------
# ส่วนคัดกรองภาพ ปรับแต่ง และสร้างไฟล์ PDF
# -----------------------------------------------------------------------------
if st.session_state.items:
    items = st.session_state.items
    selected_items = [it for it in items if st.session_state.get(f"sel_{it['id']}", True)]

    st.divider()
    st.subheader(f"🖼️ คัดเลือกหน้าเอกสาร ({len(selected_items)} / {len(items)} หน้าที่เลือก)")

    # ปุ่มเลือกทั้งหมด / ยกเลิกทั้งหมด
    ctrl1, ctrl2, ctrl3 = st.columns([1, 1, 3])
    with ctrl1:
        if st.button("✅ เลือกทั้งหมด", use_container_width=True):
            for it in items:
                st.session_state[f"sel_{it['id']}"] = True
            st.session_state.pdf_bytes = None
            st.rerun()
    with ctrl2:
        if st.button("⬜ ยกเลิกทั้งหมด", use_container_width=True):
            for it in items:
                st.session_state[f"sel_{it['id']}"] = False
            st.session_state.pdf_bytes = None
            st.rerun()

    # ระบบแบ่งหน้า (Pagination) เพื่อให้เบราว์เซอร์ลื่นแม้คลิปยาวมีเป็นร้อยหน้า
    per_page = 24
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    with ctrl3:
        if total_pages > 1:
            current_page = st.number_input(
                f"หน้าที่แสดง (ทั้งหมด {total_pages} หน้า)",
                min_value=1,
                max_value=total_pages,
                value=1,
                step=1,
            )
        else:
            current_page = 1

    start_idx = (current_page - 1) * per_page
    page_items = items[start_idx : start_idx + per_page]

    # แสดงตารางภาพ 4 คอลัมน์
    cols = st.columns(4)
    for idx, item in enumerate(page_items):
        with cols[idx % 4]:
            st.image(item["thumb_path"], use_container_width=True)
            chk_key = f"sel_{item['id']}"
            if chk_key not in st.session_state:
                st.session_state[chk_key] = True
            st.checkbox(
                f"หน้า {start_idx + idx + 1} ({item['time_str']})",
                key=chk_key,
            )

    # --- ตั้งค่าปรับแต่งภาพและส่งออก PDF ---
    st.divider()
    st.subheader("📑 ตั้งค่าความคมชัดและจัดหน้า PDF")

    opt1, opt2 = st.columns(2)
    with opt1:
        layout_label = st.selectbox(
            "รูปแบบหน้ากระดาษ PDF",
            options=[
                "เต็มหน้าพอดีภาพ (เหมาะอ่านบน iPad/จอ)",
                "A4 แนวนอน (1 สไลด์/หน้า)",
                "A4 แนวตั้ง (2 สไลด์/หน้า พร้อมปริ้นท์)",
                "A4 แนวตั้ง (1 สไลด์ + เส้นจดโน้ตด้านล่าง)",
            ],
            index=0,
        )
        layout_map = {
            "เต็มหน้าพอดีภาพ (เหมาะอ่านบน iPad/จอ)": "full",
            "A4 แนวนอน (1 สไลด์/หน้า)": "a4_landscape_1",
            "A4 แนวตั้ง (2 สไลด์/หน้า พร้อมปริ้นท์)": "a4_portrait_2",
            "A4 แนวตั้ง (1 สไลด์ + เส้นจดโน้ตด้านล่าง)": "a4_portrait_notes",
        }
        layout_mode = layout_map[layout_label]

        invert_label = st.selectbox(
            "โหมดสไลด์พื้นดำ / กระดานดำ (ประหยัดหมึก)",
            options=[
                "ไม่สลับสี (ใช้สีต้นฉบับ)",
                "สลับอัตโนมัติเฉพาะหน้าพื้นดำเป็นพื้นขาว",
                "สลับเป็นพื้นขาวทุกหน้า",
            ],
            index=0,
        )
        invert_map = {
            "ไม่สลับสี (ใช้สีต้นฉบับ)": "none",
            "สลับอัตโนมัติเฉพาะหน้าพื้นดำเป็นพื้นขาว": "auto",
            "สลับเป็นพื้นขาวทุกหน้า": "always",
        }
        invert_mode = invert_map[invert_label]

    with opt2:
        auto_contrast = st.checkbox("ปรับ Contrast ให้ตัวหนังสือชัดขึ้น (CLAHE)", value=True)
        sharpen = st.checkbox("เร่งความคมขอบตัวอักษร (Unsharp Mask)", value=True)
        add_timestamp = st.checkbox("แปะเวลาคลิป (Timestamp) มุมขวาล่างทุกหน้า", value=True)

    # ดูตัวอย่างภาพหลังปรับแต่งก่อนสั่งรวมไฟล์
    if selected_items:
        with st.expander("🔍 ดูตัวอย่างภาพก่อน–หลังปรับความคมชัด (หน้าแรกที่เลือก)", expanded=False):
            sample_item = selected_items[0]
            raw_bgr = load_bgr_image(Path(sample_item["full_path"]))
            if raw_bgr is not None:
                enh_bgr = enhance_bgr_image(raw_bgr, invert_mode, auto_contrast, sharpen)
                if add_timestamp:
                    enh_bgr = draw_timestamp_badge(enh_bgr, sample_item["time_str"])
                p1, p2 = st.columns(2)
                with p1:
                    st.caption("ต้นฉบับจากคลิป")
                    st.image(cv2.cvtColor(raw_bgr, cv2.COLOR_BGR2RGB), use_container_width=True)
                with p2:
                    st.caption("หลังปรับแต่ง (ที่จะลง PDF)")
                    st.image(cv2.cvtColor(enh_bgr, cv2.COLOR_BGR2RGB), use_container_width=True)

    # ปุ่มสร้าง PDF
    if st.button(
        f"⚡ สร้างไฟล์ PDF ({len(selected_items)} หน้า)",
        type="primary",
        use_container_width=True,
        disabled=(len(selected_items) == 0),
    ):
        pdf_prog = st.progress(0.0)
        with st.spinner("กำลังปรับความคมชัดและจัดหน้า PDF..."):
            pdf_bytes = build_pdf(
                selected_items=selected_items,
                work_dir=Path(st.session_state.work_dir),
                layout_mode=layout_mode,
                invert_mode=invert_mode,
                auto_contrast=auto_contrast,
                sharpen=sharpen,
                add_timestamp=add_timestamp,
                progress_bar=pdf_prog,
            )
            st.session_state.pdf_bytes = pdf_bytes
        st.success("สร้างไฟล์ PDF เรียบร้อยแล้ว!")

    if st.session_state.pdf_bytes:
        safe_name = sanitize_filename(st.session_state.video_title) + ".pdf"
        st.download_button(
            label=f"⬇️ ดาวน์โหลดไฟล์ {safe_name}",
            data=st.session_state.pdf_bytes,
            file_name=safe_name,
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )
