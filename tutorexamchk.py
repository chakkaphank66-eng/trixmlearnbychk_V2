import streamlit as st
import fitz  # PyMuPDF
from PIL import Image
import io
import os
import re
import gc
import json
import time
import math
import shutil
import pickle
import tempfile
import html as html_lib
import requests
import markdown

try:
    from google import genai
    from google.genai import types
    HAS_GOOGLE_GENAI = True
except ImportError:
    HAS_GOOGLE_GENAI = False

try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDGS = True
    except ImportError:
        HAS_DDGS = False

# ==============================================================================
# 1. PAGE CONFIG & SESSION STATE INITIALIZATION
# ==============================================================================
st.set_page_config(
    page_title="MedRecall A4 Exam Tutor",
    page_icon="🩺",
    layout="wide"
)

WORKSPACE_META_FILE = "autosave_recall_tutor_meta.pkl"
WORKSPACE_PDF_FILE = "autosave_recall_tutor_source.pdf"

KEYS_TO_INIT = {
    "user_api_key": "",
    "available_models": [],
    "extract_model": "gemini-2.5-flash",
    "solve_model": "gemini-2.5-flash",
    "exhausted_models": {},
    "estimated_tokens_used": 0,

    # Source PDF
    "pdf_bytes": None,
    "pdf_name": "",
    "selected_pages": [],
    "customizer_page": 0,
    "expander_open": False,
    "show_reset_confirm": False,

    # Phase 1: Extracted Questions (1 Question = 1 A4 Page)
    "extracted_pages_done": [],
    "extracted_questions": [],  # List[dict]

    # Phase 2: Solved & Tutored Data keyed by question uid
    "solved_data": {},  # Dict[str, dict]

    # Execution Controls
    "run_mode": "idle",  # idle | extract | solve
    "is_running": False,
    "stop_clicked": False,
    "current_q_idx": 0,

    # Settings
    "med_level": "นสพ. ปี 4 (NL1 / Ward)",
    "use_google_search": True,
    "fetch_web_images": True,
    "ai_verify_images": True,
    "max_images_per_q": 2,
    "max_output_tokens": 4500,
    "use_custom_prompt": False,
    "custom_solve_prompt": "",

    # Export
    "compiled_pdf_bytes": None,
    "compiled_pdf_size_mb": 0.0,
    "include_summary_sheet": True,
    "summary_sheet_md": "",
}

for k, v in KEYS_TO_INIT.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ==============================================================================
# 2. RESTRAINED EDITORIAL CLINICAL CSS (ไม่ใช้สีพร่ำเพรื่อ เน้นอ่านสบายตา)
# ==============================================================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');

    html, body, [class*="st-"] {
        font-family: 'Sarabun', sans-serif !important;
    }
    .stApp {
        background-color: #F4F6F8;
    }
    .app-title {
        font-size: 1.95rem;
        font-weight: 700;
        color: #1E3A5F;
        letter-spacing: -0.3px;
        margin-bottom: 0.2rem;
    }
    .app-subtitle {
        font-size: 0.95rem;
        color: #475569;
        margin-bottom: 1.1rem;
    }
    /* A4 Sheet Preview Card */
    .a4-sheet {
        background: #FFFFFF;
        border: 1px solid #CBD5E1;
        border-radius: 8px;
        padding: 24px 28px;
        box-shadow: 0 6px 20px rgba(15, 23, 42, 0.06);
        color: #1E293B;
        line-height: 1.62;
        font-size: 15.5px;
    }
    .a4-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #1E3A5F;
        padding-bottom: 8px;
        margin-bottom: 14px;
    }
    .a4-qbadge {
        background: #1E3A5F;
        color: #FFFFFF;
        padding: 3px 10px;
        border-radius: 4px;
        font-weight: 700;
        font-size: 0.9rem;
    }
    .a4-topic {
        font-weight: 700;
        color: #1E3A5F;
        font-size: 1.05rem;
        margin-left: 10px;
    }
    .a4-meta {
        font-size: 0.82rem;
        color: #64748B;
    }
    .badge-partial {
        background: #FEF2F2;
        color: #B91C1C;
        border: 1px solid #FECACA;
        padding: 2px 7px;
        border-radius: 4px;
        font-size: 0.78rem;
        font-weight: 600;
    }
    .badge-complete {
        background: #F1F5F9;
        color: #334155;
        border: 1px solid #CBD5E1;
        padding: 2px 7px;
        border-radius: 4px;
        font-size: 0.78rem;
        font-weight: 600;
    }
    .zone-stem {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-left: 4px solid #1E3A5F;
        border-radius: 4px;
        padding: 12px 14px;
        margin-bottom: 14px;
    }
    .zone-verdict {
        background: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-left: 4px solid #15803D;
        border-radius: 4px;
        padding: 10px 14px;
        margin-bottom: 10px;
    }
    .zone-section-title {
        font-weight: 700;
        color: #1E3A5F;
        font-size: 0.95rem;
        border-bottom: 1px solid #E2E8F0;
        padding-bottom: 3px;
        margin: 12px 0 7px 0;
        text-transform: uppercase;
        letter-spacing: 0.3px;
    }
    .zone-textbook {
        background: #FFFFFF;
        border: 1px solid #CBD5E1;
        border-radius: 5px;
        padding: 12px 15px;
        margin-top: 12px;
    }
    .zone-hy {
        background: #FEF2F2;
        border: 1px solid #FECACA;
        border-left: 4px solid #B91C1C;
        border-radius: 4px;
        padding: 9px 13px;
        margin-top: 12px;
        font-size: 0.94rem;
    }
    .kw-highlight {
        color: #B91C1C;
        font-weight: 700;
    }
    .ans-text {
        color: #15803D;
        font-weight: 700;
    }
    .senior-alert {
        background: #FFFFFF;
        border: 1px dashed #94A3B8;
        padding: 6px 10px;
        border-radius: 4px;
        margin-top: 8px;
        font-size: 0.88rem;
        color: #334155;
    }
    .ref-footer {
        margin-top: 10px;
        padding-top: 6px;
        border-top: 1px solid #E2E8F0;
        font-size: 0.78rem;
        color: #64748B;
    }
    .status-banner {
        background: #EFF6FF;
        border-left: 4px solid #1E3A5F;
        color: #1E3A5F;
        padding: 12px 16px;
        border-radius: 6px;
        margin-bottom: 12px;
        font-size: 0.95rem;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. WORKSPACE PERSISTENCE (AUTO-SAVE / RESUME)
# ==============================================================================
def save_workspace(save_pdf_binary=False):
    if save_pdf_binary and st.session_state.pdf_bytes:
        try:
            with open(WORKSPACE_PDF_FILE, "wb") as f_pdf:
                f_pdf.write(st.session_state.pdf_bytes)
        except Exception:
            pass

    payload = {
        "user_api_key": st.session_state.user_api_key,
        "pdf_name": st.session_state.pdf_name,
        "selected_pages": st.session_state.selected_pages,
        "extracted_pages_done": st.session_state.extracted_pages_done,
        "extracted_questions": st.session_state.extracted_questions,
        "solved_data": st.session_state.solved_data,
        "estimated_tokens_used": st.session_state.estimated_tokens_used,
        "med_level": st.session_state.med_level,
        "use_google_search": st.session_state.use_google_search,
        "fetch_web_images": st.session_state.fetch_web_images,
        "ai_verify_images": st.session_state.ai_verify_images,
        "max_images_per_q": st.session_state.max_images_per_q,
        "use_custom_prompt": st.session_state.use_custom_prompt,
        "custom_solve_prompt": st.session_state.custom_solve_prompt,
        "summary_sheet_md": st.session_state.summary_sheet_md,
    }
    try:
        with open(WORKSPACE_META_FILE, "wb") as f:
            pickle.dump(payload, f)
    except Exception:
        pass


def load_workspace():
    if os.path.exists(WORKSPACE_META_FILE) and os.path.exists(WORKSPACE_PDF_FILE):
        try:
            with open(WORKSPACE_PDF_FILE, "rb") as f_pdf:
                st.session_state.pdf_bytes = f_pdf.read()
            with open(WORKSPACE_META_FILE, "rb") as f:
                data = pickle.load(f)
                for k, v in data.items():
                    st.session_state[k] = v
            return True
        except Exception:
            return False
    return False


def clear_workspace():
    for path in [WORKSPACE_META_FILE, WORKSPACE_PDF_FILE]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


@st.cache_data(max_entries=30, show_spinner=False)
def render_pdf_page_png(pdf_bytes, page_idx, dpi=120):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc[page_idx].get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


# ==============================================================================
# 4. GEMINI CLIENT & ROBUST MODEL MANAGEMENT
# ==============================================================================
def get_genai_client():
    if not HAS_GOOGLE_GENAI or not st.session_state.user_api_key:
        return None
    return genai.Client(api_key=st.session_state.user_api_key)


def fetch_available_models(api_key):
    client = genai.Client(api_key=api_key)
    models = []
    for m in client.models.list():
        name = (getattr(m, "name", "") or "").replace("models/", "")
        actions = getattr(m, "supported_actions", None) or []
        if "gemini" in name.lower() and "embedding" not in name.lower() and "imagen" not in name.lower():
            if not actions or "generateContent" in actions:
                models.append(name)

    priority = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-2.0-flash",
    ]
    models = sorted(
        list(set(models)),
        key=lambda x: next((i for i, p in enumerate(priority) if p in x), 99)
    )
    return models or ["gemini-2.5-flash", "gemini-2.5-flash-lite"]


def get_next_available_model(preferred_model=None):
    now = time.time()
    st.session_state.exhausted_models = {
        k: v for k, v in st.session_state.exhausted_models.items() if v > now
    }
    if preferred_model and preferred_model not in st.session_state.exhausted_models:
        return preferred_model
    for m in st.session_state.available_models:
        if m not in st.session_state.exhausted_models:
            return m
    return preferred_model or "gemini-2.5-flash"


def extract_json_from_text(raw_text):
    """ดึง JSON ออกจากข้อความของ AI อย่างปลอดภัยแม้มี Markdown code fence ปะปน"""
    if not raw_text:
        return None
    cleaned = raw_text.strip()
    # 1. ลองหา ```json ... ```
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except Exception:
            pass
    # 2. ลอง parse ตรงๆ
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    # 3. หา { แรกถึง } สุดท้าย
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start:end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            # แก้ไข trailing comma หรือ newline ใน string เบื้องต้น
            candidate_fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                return json.loads(candidate_fixed)
            except Exception:
                pass
    return None


def extract_grounding_sources(response):
    sources = []
    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return sources
        gm = getattr(candidates[0], "grounding_metadata", None)
        if not gm:
            return sources
        chunks = getattr(gm, "grounding_chunks", None) or []
        seen = set()
        for ch in chunks:
            web = getattr(ch, "web", None)
            if web:
                title = (getattr(web, "title", "") or "").strip()
                uri = (getattr(web, "uri", "") or "").strip()
                label = title if title else uri
                if label and label not in seen:
                    seen.add(label)
                    sources.append(f"{title}" if title else uri)
    except Exception:
        pass
    return sources[:5]


# ==============================================================================
# 5. VERIFIED MEDICAL IMAGE ENGINE (ZERO BROKEN IMAGES!)
# ==============================================================================
HTTP_HEADERS = {
    "User-Agent": "MedRecallA4Tutor/1.0 (Educational Medical Study App; Python Requests)"
}


def download_and_verify_image(url, source_label="", caption_th=""):
    """
    ดาวน์โหลดรูปจริงและตรวจสอบไบนารีด้วย PIL:
    - ต้อง HTTP 200 และเปิดภาพได้จริง (ไม่เสีย / ไม่ใช่ HTML error page)
    - ขนาดต้องชัดเจน (กว้าง >= 220px, สูง >= 150px, สัดส่วนไม่เพี้ยน)
    - แปลงเป็น RGB JPEG พื้นขาวเพื่อฝังใน PDF โดยไม่เกิดพื้นดำ
    """
    if not url or not url.startswith("http"):
        return None
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=8, stream=True)
        if resp.status_code != 200:
            return None
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "html" in ctype or "svg" in ctype or "xml" in ctype:
            return None

        raw_bytes = resp.content
        if len(raw_bytes) < 4000 or len(raw_bytes) > 12_000_000:
            return None

        # Verify integrity
        with Image.open(io.BytesIO(raw_bytes)) as img_check:
            img_check.verify()

        with Image.open(io.BytesIO(raw_bytes)) as img:
            w, h = img.size
            if w < 220 or h < 150:
                return None
            aspect = w / float(h)
            if aspect < 0.38 or aspect > 2.9:
                return None

            # Flatten transparency onto crisp white background
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                converted = img.convert("RGBA")
                bg.paste(converted, mask=converted.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")

            # Resize neatly to save RAM & PDF size while staying sharp
            max_side = 900
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

            out_buf = io.BytesIO()
            img.save(out_buf, format="JPEG", quality=84, optimize=True)
            clean_bytes = out_buf.getvalue()
            final_w, final_h = img.size

        return {
            "bytes": clean_bytes,
            "width": final_w,
            "height": final_h,
            "url": url,
            "source": source_label,
            "caption": caption_th,
        }
    except Exception:
        return None


def search_wikimedia_commons(query, limit=5):
    """ค้นหาภาพจาก Wikimedia Commons (เด่นด้าน Anatomy, Diagram, Surgical, Lesion) แปลง SVG เป็น PNG 800px อัตโนมัติ"""
    results = []
    try:
        params = {
            "action": "query",
            "generator": "search",
            "gsrnamespace": 6,
            "gsrsearch": query,
            "gsrlimit": limit,
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            "iiurlwidth": 800,
            "format": "json",
        }
        r = requests.get("https://commons.wikimedia.org/w/api.php", params=params, headers=HTTP_HEADERS, timeout=8)
        if r.status_code != 200:
            return results
        pages = r.json().get("query", {}).get("pages", {})
        bad_words = ["icon", "logo", "flag", "map", "seal", "signature", "pdf", "djvu", "coat_of_arms"]
        for _, pinfo in pages.items():
            title = (pinfo.get("title") or "").lower()
            if any(bw in title for bw in bad_words):
                continue
            ii = (pinfo.get("imageinfo") or [{}])[0]
            mime = (ii.get("mime") or "").lower()
            if "pdf" in mime or "tiff" in mime or "video" in mime or "audio" in mime:
                continue
            # thumburl แปลง SVG diagram เป็น PNG 800px ให้พร้อมใช้งานทันที!
            img_url = ii.get("thumburl") or ii.get("url")
            if img_url:
                results.append({"url": img_url, "source": "Wikimedia Commons", "title": pinfo.get("title", "")})
    except Exception:
        pass
    return results


def search_nih_openi(query, limit=5):
    """ค้นหาภาพการแพทย์จากฐานข้อมูล NIH Open-i (PubMed Central — เด่นด้าน X-ray, CT, US, Pathology, Lesion, Surgery)"""
    results = []
    try:
        params = {
            "m": 1,
            "n": limit,
            "query": query,
        }
        r = requests.get("https://openi.nlm.nih.gov/api/search", params=params, headers=HTTP_HEADERS, timeout=8)
        if r.status_code != 200:
            return results
        items = r.json().get("list", [])
        for it in items:
            rel_url = it.get("imgLarge") or it.get("imgThumbLarge")
            if rel_url:
                full_url = f"https://openi.nlm.nih.gov{rel_url}" if rel_url.startswith("/") else rel_url
                results.append({
                    "url": full_url,
                    "source": "NIH Open-i (PubMed Central)",
                    "title": it.get("title", ""),
                })
    except Exception:
        pass
    return results


def search_ddg_medical_images(query, limit=5):
    """Fallback เสริมด้วย DuckDuckGo Image Search (ถ้าติดตั้ง ddgs / duckduckgo_search)"""
    results = []
    if not HAS_DDGS:
        return results
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.images(f"{query} medical", max_results=limit))
            for h in hits:
                u = h.get("image")
                if u:
                    results.append({"url": u, "source": "Medical Web", "title": h.get("title", "")})
    except Exception:
        pass
    return results


def ai_check_image_relevance(client, img_bytes, topic, caption_th):
    """ให้ Gemini Flash-Lite ตรวจภาพจริงก่อนแปะลงชีท เพื่อป้องกันภาพไม่ตรงปกหรือภาพแตก"""
    try:
        pil_img = Image.open(io.BytesIO(img_bytes))
        check_model = get_next_available_model("gemini-2.5-flash-lite")
        prompt = (
            f"คุณคือบรรณาธิการตำราแพทย์ ตรวจภาพนี้ว่าเกี่ยวข้องและช่วยสอนเรื่อง '{topic}' "
            f"(คำอธิบายที่ต้องการ: '{caption_th}') ได้จริงหรือไม่\n"
            f"ปฏิเสธทันที (ตอบ NO) หากเป็นภาพโลโก้ ภาพไม่ชัด ข้อความล้วนไม่มีรูปประกอบ หรือไม่เกี่ยวข้องกับเรื่องนี้\n"
            f"ตอบคำเดียวเท่านั้น: YES หรือ NO"
        )
        resp = client.models.generate_content(
            model=check_model,
            contents=[prompt, pil_img],
            config=types.GenerateContentConfig(max_output_tokens=10, temperature=0.0),
        )
        ans = (resp.text or "").strip().upper()
        return "YES" in ans
    except Exception:
        # ถ้าตรวจสอบไม่ได้เนื่องจากโควต้า ให้ผ่านได้เพราะตรวจไบนารีภาพแล้ว
        return True


def fetch_verified_medical_images(image_requests, topic, max_images=2, client=None, use_ai_verify=True):
    """
    ดึงภาพจากฐานข้อมูลการแพทย์ที่เชื่อถือได้ + ตรวจไฟล์ภาพไม่เสีย 100%
    หากหาภาพที่ดีไม่ได้ จะคืนค่า [] เพื่อให้หน้า A4 ขยายข้อความเต็มพื้นที่โดยไม่มีภาพเสีย
    """
    verified = []
    seen_urls = set()

    for req in (image_requests or []):
        if len(verified) >= max_images:
            break
        query = (req.get("query") or "").strip()
        caption_th = (req.get("caption_th") or "").strip()
        img_type = (req.get("type") or "anatomy").lower()
        if not query:
            continue

        # จัดลำดับแหล่งข้อมูลให้เหมาะกับประเภทภาพ
        candidates = []
        if img_type in ("imaging", "radiology", "lesion", "pathology", "procedure", "surgery"):
            candidates.extend(search_nih_openi(query, limit=4))
            candidates.extend(search_wikimedia_commons(query, limit=4))
        else:
            candidates.extend(search_wikimedia_commons(query, limit=5))
            candidates.extend(search_nih_openi(query, limit=3))

        if len(candidates) < 2:
            candidates.extend(search_ddg_medical_images(query, limit=4))

        for cand in candidates:
            url = cand.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            img_obj = download_and_verify_image(
                url=url,
                source_label=cand.get("source", "Medical Atlas"),
                caption_th=caption_th or query,
            )
            if not img_obj:
                continue

            if use_ai_verify and client is not None:
                if not ai_check_image_relevance(client, img_obj["bytes"], topic, caption_th):
                    continue

            verified.append(img_obj)
            break  # ได้ภาพที่ดีที่สุด 1 ภาพสำหรับ request นี้แล้ว

    return verified


# ==============================================================================
# 6. PHASE 1 & PHASE 2 AI ENGINES
# ==============================================================================
def extract_questions_from_page(client, model_name, pdf_bytes, page_idx):
    """
    Phase 1: แกะข้อสอบทุกข้อใน 1 หน้า PDF ออกมาเป็นรายการแยกทีละข้อ (1 ข้อ = 1 หน้า A4)
    รองรับทั้งข้อสอบสมบูรณ์และโพยความจำรุ่นพี่ที่ไม่สมบูรณ์
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_idx]
        raw_text = page.get_text("text").strip()
        pix = page.get_pixmap(dpi=135)
        pil_img = Image.open(io.BytesIO(pix.tobytes("png")))
    finally:
        doc.close()

    prompt = f"""คุณคือผู้เชี่ยวชาญในการแกะโพยข้อสอบแพทย์จากไฟล์ PDF (ทั้งข้อสอบฉบับสมบูรณ์และโพยที่รุ่นพี่จำออกมาแบบไม่ครบ)
หน้าที่ของคุณ: อ่านภาพหน้า PDF หน้าที่ {page_idx + 1} (ร่วมกับข้อความที่ดึงได้ด้านล่าง) แล้วแยกข้อสอบออกมา **ทีละข้ออย่างครบถ้วน ห้ามข้ามแม้แต่ข้อเดียว**

ข้อความเบื้องต้นจากหน้านี้ (อาจขาดหายถ้าเป็นไฟล์สแกน ให้ยึดภาพเป็นหลัก):
{raw_text[:4500]}

ให้ตอบเป็น JSON ที่ถูกต้องตามโครงสร้างนี้เท่านั้น:
{{
  "questions": [
    {{
      "q_label": "เลขข้อตามต้นฉบับ เช่น ข้อ 1 หรือ 14 (ถ้าไม่มีเลขให้รันลำดับ)",
      "completeness": "complete" หรือ "partial_recall",
      "raw_stem": "ข้อความโจทย์ทั้งหมดของข้อนี้ (คงคำศัพท์และตัวเลข Lab ตามต้นฉบับ)",
      "choices": ["A. ...", "B. ..."],
      "senior_note": "เฉลยหรือหมายเหตุที่รุ่นพี่จดไว้ในโพย (ถ้าไม่มีใส่ค่าว่าง)",
      "has_pdf_figure": true หรือ false
    }}
  ]
}}

หมายเหตุ:
- ถ้าหน้านั้นเป็นหน้าปก สารบัญ หรือไม่มีข้อสอบ ให้ส่ง {{"questions": []}}
- หากข้อสอบเป็นโพยความจำที่รุ่นพี่เขียนสั้นๆ ไม่มีช้อยส์ ให้ใส่ "completeness": "partial_recall" และ "choices": []
- ห้ามรวมหลายข้อเป็นข้อเดียวกัน ต้องแยก 1 ข้อต่อ 1 object เสมอ"""

    resp = client.models.generate_content(
        model=model_name,
        contents=[prompt, pil_img],
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=6000,
            response_mime_type="application/json",
        ),
    )
    txt = resp.text or ""
    st.session_state.estimated_tokens_used += len(txt) + 600
    parsed = extract_json_from_text(txt)
    if not parsed or "questions" not in parsed:
        return []
    return parsed.get("questions", [])


DEFAULT_SOLVE_PROMPT_TEMPLATE = """คุณคืออาจารย์แพทย์และติวเตอร์ชั้นนำ กำลังทำชีทเฉลยข้อสอบ+ติวเนื้อหาแบบกระชับ 1 ข้อต่อ 1 หน้า A4 สำหรับ {med_level}

ข้อมูลข้อสอบ (จากโพยหน้า {source_page}):
- สถานะโจทย์: {completeness}
- โจทย์ต้นฉบับ: {raw_stem}
- ตัวเลือก (ถ้ามี): {choices_text}
- โน้ต/เฉลยจากรุ่นพี่ในโพย (ถ้ามี): {senior_note}

**ภารกิจสำคัญ (ต้องแม่นยำ อัปเดตตามแนวทางเวชปฏิบัติล่าสุด เช่น ACC/AHA, ESC, CHEST, NCCN, IDSA, UpToDate, Thai CPG):**
1. **ตรวจสอบและเติมเต็มโจทย์ (กรณีโพยไม่สมบูรณ์):** หากโจทย์จำมาไม่ครบ ให้ระบุสั้นๆ ว่าโจทย์น่าจะสื่อถึงสถานการณ์คลินิกใด และหากรุ่นพี่เขียนเฉลยไว้ ให้ **ตรวจสอบว่าเฉลยรุ่นพี่ถูกต้องหรือผิด/ล้าสมัยแล้ว**
2. **เฉลยแบบเข้าใจถึงแก่น:** เน้น **ตัวหนาที่คำสำคัญ (Keywords)** และทุกการอธิบายต้องให้เหตุผลด้วยคำว่า **'...เพราะ...'** เชื่อมโยงด้วยลูกศร `คำใบ้ ➡️ กลไก ➡️ คำตอบ`
3. **ผ่าตัดช้อยส์ทุกข้อ (Why Right & Why Wrong):**
   - บอกว่าข้อที่ถูกคือข้อไหนและทำไมถึงถูก
   - บอกว่าช้อยส์หลอกแต่ละข้อผิดเพราะอะไร **และถ้าจะตอบช้อยส์นั้น โจทย์ต้องเปลี่ยนคำใบ้เป็นอะไร**
   - (หากโพยไม่มีช้อยส์ ให้สร้าง 3-4 **ตัวหลอก/DDx ที่ออกสอบคู่กันบ่อย** แทน เพื่อให้ผู้อ่านได้ฝึกแยกโรค)
4. **ติวเนื้อหาเรื่องนั้นเหมือนเปิดตำราบทนั้นแบบกระชับ (Mini-Textbook Chapter):** เช่น ถ้าโจทย์ถามเรื่อง DVT ให้ติวครบทั้ง Pathophysiology/Risk, Clinical/Scoring, Diagnosis Algorithm (Initial ➡️ Gold Standard), และ Management/Complications แบบกระชับ ตรงประเด็น อ่านจบในหน้าเดียว
5. **เสนอคำค้นหาภาพการแพทย์ภาษาอังกฤษ (1-2 ภาพ):** เลือกภาพที่ช่วยให้เห็นภาพจริง (Anatomy / Imaging X-ray-CT-US / รอยโรค / หัตถการ Operation) โดยระบุ `query` ภาษาอังกฤษสั้นๆ ชัดๆ (2-5 คำ) ที่ค้นเจอง่ายใน Wikimedia Commons หรือ PubMed Open-i พร้อมคำอธิบายภาพภาษาไทยว่าให้มองจุดไหน

**ตอบกลับเป็น JSON ภายใน ```json ... ``` ตามโครงสร้างนี้เท่านั้น (ห้ามเขียนข้อความนอก JSON):**
```json
{
  "topic": "ชื่อโรค/หัวข้อหลัก (ภาษาอังกฤษ + ไทยสั้นๆ เช่น Deep Vein Thrombosis (DVT))",
  "specialty": "แผนก/ระบบ เช่น Medicine / Vascular หรือ Surgery",
  "reconstructed_note": "หมายเหตุกรณีโจทย์ไม่สมบูรณ์ (ถ้าสมบูรณ์แล้วให้ใส่ค่าว่าง)",
  "stem_highlighted": "โจทย์ต้นฉบับที่เน้น **ตัวหนา** ตรงคำใบ้สำคัญ (Buzzwords)",
  "correct_answer": "ระบุคำตอบที่ถูกต้องชัดเจน 1 บรรทัด",
  "senior_check": "ตรวจเฉลยรุ่นพี่ (เช่น 'ตรงกับเฉลยรุ่นพี่' หรือ '⚠️ แก้ไขจากโพยรุ่นพี่: ... เพราะ ...' ถ้าไม่มีโน้ตรุ่นพี่ใส่ค่าว่าง)",
  "why_correct": "อธิบายเหตุผลที่ตอบข้อนี้แบบกระชับ ใช้ลูกศรและคำว่า **เพราะ...**",
  "choice_dissection": [
    {
      "label": "ชื่อช้อยส์ หรือ DDx คู่แข่ง",
      "status": "wrong",
      "reason": "ผิดเพราะ... | จะตอบข้อนี้เมื่อโจทย์ให้คำใบ้ว่า..."
    }
  ],
  "textbook_review": {
    "pathophysiology": "กลไกเกิดโรคและปัจจัยเสี่ยงสำคัญ (กระชับ เน้น **ตัวหนา** และ **เพราะ...**)",
    "clinical_clues": "อาการเด่น ตรวจร่างกาย และ Scoring สำคัญ พร้อมจุดหลอกที่ต้องระวัง",
    "diagnosis": "ลำดับการส่งตรวจ: Initial Test ➡️ Confirm / Gold Standard (พร้อมเหตุผล)",
    "management": "การรักษา First-line, ข้อห้าม/ผลข้างเคียงสำคัญ และภาวะแทรกซ้อนหลัก"
  },
  "high_yield": [
    "กฎเหล็กทำข้อสอบข้อที่ 1 (สั้นคม อ่าน 3 วิจำได้)",
    "กฎเหล็กทำข้อสอบข้อที่ 2 (จุดตัดแยกโรคหรือ Pitfall ห้ามพลาด)"
  ],
  "image_requests": [
    {
      "query": "English medical search query 2-5 words",
      "caption_th": "คำอธิบายสั้นๆ ว่าภาพนี้แสดงอะไรและให้สังเกตตรงไหน",
      "type": "anatomy | imaging | lesion | procedure"
    }
  ],
  "guideline_ref": "ชื่อแนวทางเวชปฏิบัติหรือตำราอ้างอิงสั้นๆ เช่น CHEST 2021 / ESC / UpToDate"
}
```"""


def solve_single_question(client, model_name, q_item, use_search=True):
    """Phase 2: เฉลยข้อสอบ + ค้นหาข้อมูลล่าสุดด้วย Google Search Grounding + ติวเนื้อหาแบบ Mini-Textbook"""
    choices_list = q_item.get("choices") or []
    choices_text = "\n".join(choices_list) if choices_list else "(ไม่มีตัวเลือกในโพย — เป็นโพยความจำรุ่นพี่)"

    tmpl = st.session_state.custom_solve_prompt if (
        st.session_state.use_custom_prompt and st.session_state.custom_solve_prompt.strip()
    ) else DEFAULT_SOLVE_PROMPT_TEMPLATE

    prompt = (
        tmpl
        .replace("{med_level}", str(st.session_state.med_level))
        .replace("{source_page}", str(q_item.get("source_page", 0) + 1))
        .replace("{completeness}", "สมบูรณ์" if q_item.get("completeness") == "complete" else "โพยความจำไม่สมบูรณ์ (Partial Recall)")
        .replace("{raw_stem}", str(q_item.get("raw_stem", "")))
        .replace("{choices_text}", str(choices_text))
        .replace("{senior_note}", str(q_item.get("senior_note") or "(ไม่มี)"))
    )

    tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
    grounding_sources = []

    try:
        cfg = types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=st.session_state.max_output_tokens,
            tools=tools,
        )
        resp = client.models.generate_content(model=model_name, contents=prompt, config=cfg)
        grounding_sources = extract_grounding_sources(resp)
    except Exception as e:
        # Fallback กรณีโมเดลที่เลือกไม่รองรับ Google Search tool -> ลองรันแบบปิด tool
        if use_search and ("tool" in str(e).lower() or "search" in str(e).lower() or "400" in str(e)):
            cfg_no_tool = types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=st.session_state.max_output_tokens,
            )
            resp = client.models.generate_content(model=model_name, contents=prompt, config=cfg_no_tool)
        else:
            raise e

    raw_text = (resp.text or "").strip()
    st.session_state.estimated_tokens_used += len(raw_text) + 900

    parsed = extract_json_from_text(raw_text)
    if not parsed:
        # Safe fallback หาก JSON แตก
        parsed = {
            "topic": f"ข้อสอบข้อที่ {q_item.get('q_num', '')}",
            "specialty": "Clinical Medicine",
            "reconstructed_note": "",
            "stem_highlighted": q_item.get("raw_stem", ""),
            "correct_answer": "โปรดตรวจสอบคำอธิบายด้านล่าง",
            "senior_check": "",
            "why_correct": raw_text,
            "choice_dissection": [],
            "textbook_review": {
                "pathophysiology": "",
                "clinical_clues": "",
                "diagnosis": "",
                "management": "",
            },
            "high_yield": [],
            "image_requests": [],
            "guideline_ref": "",
        }

    # รวมแหล่งอ้างอิงจาก Google Search Grounding
    refs = []
    if parsed.get("guideline_ref"):
        refs.append(parsed["guideline_ref"])
    for src in grounding_sources:
        if src not in refs:
            refs.append(src)
    parsed["references"] = refs[:4]
    parsed["images"] = []

    # ดึงและตรวจสอบภาพทางการแพทย์จริงจากเน็ต
    if st.session_state.fetch_web_images and parsed.get("image_requests"):
        imgs = fetch_verified_medical_images(
            image_requests=parsed.get("image_requests"),
            topic=parsed.get("topic", ""),
            max_images=st.session_state.max_images_per_q,
            client=client if st.session_state.ai_verify_images else None,
            use_ai_verify=st.session_state.ai_verify_images,
        )
        parsed["images"] = imgs

    return parsed


# ==============================================================================
# 7. TEXT FORMATTING & A4 EDITORIAL HTML RENDERER (WEB + PDF)
# ==============================================================================
def md_inline_to_html(text, highlight_bold=True):
    """แปลง **คำสำคัญ** และ Markdown inline เป็น HTML สะอาดตา (เน้นสีเฉพาะจุดสำคัญ)"""
    if not text:
        return ""
    safe = html_lib.escape(str(text))
    if highlight_bold:
        safe = re.sub(r"\*\*(.+?)\*\*", r"<strong class='kw'>\1</strong>", safe)
    else:
        safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"\*(.+?)\*", r"<em>\1</em>", safe)
    safe = safe.replace("\n", "<br>")
    return safe


def render_web_a4_card(q_item, solved):
    """แสดงหน้าพรีวิว 1 ข้อ = 1 หน้า A4 บน Streamlit"""
    q_num = q_item.get("q_num", 1)
    src_p = q_item.get("source_page", 0) + 1
    completeness = q_item.get("completeness", "complete")
    badge_html = (
        "<span class='badge-partial'>Partial Recall (โพยไม่สมบูรณ์)</span>"
        if completeness != "complete"
        else "<span class='badge-complete'>Complete Question</span>"
    )

    topic = html_lib.escape(solved.get("topic", ""))
    specialty = html_lib.escape(solved.get("specialty", ""))
    recon = solved.get("reconstructed_note", "").strip()
    stem_html = md_inline_to_html(solved.get("stem_highlighted") or q_item.get("raw_stem", ""), highlight_bold=True)

    choices_html = ""
    if q_item.get("choices"):
        ch_items = "".join(f"<div style='margin-left:8px;'>{md_inline_to_html(c, False)}</div>" for c in q_item["choices"])
        choices_html = f"<div style='margin-top:6px; font-size:0.94rem;'>{ch_items}</div>"

    recon_html = f"<div style='font-size:0.86rem; color:#B91C1C; margin-top:6px;'><b>หมายเหตุโจทย์:</b> {md_inline_to_html(recon, False)}</div>" if recon else ""
    senior_html = f"<div class='senior-alert'><b>ตรวจโพยรุ่นพี่:</b> {md_inline_to_html(solved.get('senior_check', ''), True)}</div>" if solved.get("senior_check") else ""

    # Header + Zone 1 (Stem)
    st.markdown(f"""
    <div class='a4-sheet'>
        <div class='a4-header'>
            <div>
                <span class='a4-qbadge'>Q{q_num:02d}</span>
                <span class='a4-topic'>{topic}</span>
            </div>
            <div class='a4-meta'>{specialty} &nbsp;|&nbsp; หน้าต้นฉบับ {src_p} &nbsp;{badge_html}</div>
        </div>
        <div class='zone-stem'>
            <div>{stem_html}</div>
            {choices_html}
            {recon_html}
            {senior_html}
        </div>
    """, unsafe_allow_html=True)

    # Zone 2: Split Verdict/Choices + Visual Reference Images
    images = solved.get("images") or []
    if images:
        col_left, col_right = st.columns([1.45, 1.0])
    else:
        col_left = st.container()
        col_right = None

    with col_left:
        ans_html = md_inline_to_html(solved.get("correct_answer", ""), highlight_bold=False)
        why_html = md_inline_to_html(solved.get("why_correct", ""), highlight_bold=True)
        st.markdown(f"""
        <div class='zone-verdict'>
            <div class='ans-text'>✅ คำตอบ: {ans_html}</div>
            <div style='margin-top:4px; font-size:0.95rem;'>{why_html}</div>
        </div>
        """, unsafe_allow_html=True)

        dissection = solved.get("choice_dissection") or []
        if dissection:
            rows_html = ""
            for d in dissection:
                lbl = html_lib.escape(str(d.get("label", "")))
                rsn = md_inline_to_html(d.get("reason", ""), highlight_bold=True)
                rows_html += f"<div style='margin-bottom:5px; font-size:0.93rem;'><span style='color:#B91C1C; font-weight:700;'>✗ {lbl}:</span> {rsn}</div>"
            st.markdown(f"""
            <div class='zone-section-title'>ผ่าตัดช้อยส์หลอก & จุดแยกโรค (Why Wrong / DDx)</div>
            <div>{rows_html}</div>
            """, unsafe_allow_html=True)

    if col_right is not None:
        with col_right:
            st.markdown("<div class='zone-section-title' style='margin-top:0;'>ภาพประกอบความเข้าใจ (Verified Visuals)</div>", unsafe_allow_html=True)
            for idx_im, im in enumerate(images):
                st.image(im["bytes"], use_container_width=True)
                st.caption(f"ภาพที่ {idx_im + 1}: {im.get('caption', '')} ({im.get('source', '')})")

    # Zone 3: Mini-Textbook Chapter Review
    tb = solved.get("textbook_review") or {}
    tb_sections = [
        ("1. Pathophysiology & Risk", tb.get("pathophysiology", "")),
        ("2. Clinical Clues & Scoring", tb.get("clinical_clues", "")),
        ("3. Diagnostic Algorithm", tb.get("diagnosis", "")),
        ("4. Management & Complications", tb.get("management", "")),
    ]
    tb_grid = ""
    for title_s, body_s in tb_sections:
        if body_s and str(body_s).strip():
            tb_grid += f"""
            <div style='margin-bottom:8px;'>
                <div style='font-weight:700; color:#1E3A5F; font-size:0.92rem;'>{title_s}</div>
                <div style='font-size:0.93rem; color:#1E293B;'>{md_inline_to_html(body_s, True)}</div>
            </div>
            """

    hy_list = solved.get("high_yield") or []
    hy_html = ""
    if hy_list:
        hy_items = "".join(f"<li style='margin-bottom:2px;'>{md_inline_to_html(h, True)}</li>" for h in hy_list)
        hy_html = f"""
        <div class='zone-hy'>
            <b style='color:#B91C1C;'>KEY TAKE-HOME (กฎเหล็กจำเข้าห้องสอบ):</b>
            <ul style='margin:4px 0 0 0; padding-left:18px;'>{hy_items}</ul>
        </div>
        """

    refs = solved.get("references") or []
    ref_html = f"<div class='ref-footer'><b>อ้างอิง / แหล่งข้อมูลตรวจสอบ:</b> {' • '.join(html_lib.escape(r) for r in refs)}</div>" if refs else ""

    st.markdown(f"""
        <div class='zone-textbook'>
            <div class='zone-section-title' style='margin-top:0;'>Mini-Textbook Review: {topic}</div>
            {tb_grid}
        </div>
        {hy_html}
        {ref_html}
    </div>
    """, unsafe_allow_html=True)


# ==============================================================================
# 8. A4 PDF COMPILER WITH REAL AUTO-FIT (NO CUT-OFF TEXT, ZERO BROKEN IMAGES)
# ==============================================================================
def prepare_thai_fonts(tmp_dir):
    """ค้นหาฟอนต์ภาษาไทยในโฟลเดอร์แอปหรือ Windows Fonts เพื่อคัดลอกเข้า Archive ของ PyMuPDF"""
    candidates_reg = [
        "THSarabunNew.ttf",
        "Sarabun-Regular.ttf",
        r"C:\Windows\Fonts\THSarabunNew.ttf",
        r"C:\Windows\Fonts\LeelawUI.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\cordia.ttf",
        "/usr/share/fonts/truetype/tlwg/Garuda.ttf",
    ]
    candidates_bold = [
        "THSarabunNew Bold.ttf",
        "Sarabun-Bold.ttf",
        r"C:\Windows\Fonts\THSarabunNew Bold.ttf",
        r"C:\Windows\Fonts\LeelaUIb.ttf",
        r"C:\Windows\Fonts\tahomabd.ttf",
        r"C:\Windows\Fonts\cordiab.ttf",
        "/usr/share/fonts/truetype/tlwg/Garuda-Bold.ttf",
    ]

    reg_path = next((p for p in candidates_reg if os.path.exists(p)), None)
    bold_path = next((p for p in candidates_bold if os.path.exists(p)), None)

    has_font = False
    font_css = ""
    if reg_path:
        shutil.copyfile(reg_path, os.path.join(tmp_dir, "thai_reg.ttf"))
        font_css += "@font-face { font-family: 'ThaiFont'; src: url('thai_reg.ttf'); font-weight: normal; }\n"
        has_font = True
    if bold_path:
        shutil.copyfile(bold_path, os.path.join(tmp_dir, "thai_bold.ttf"))
        font_css += "@font-face { font-family: 'ThaiFont'; src: url('thai_bold.ttf'); font-weight: bold; }\n"
    elif reg_path:
        font_css += "@font-face { font-family: 'ThaiFont'; src: url('thai_reg.ttf'); font-weight: bold; }\n"

    font_family = "'ThaiFont', sans-serif" if has_font else "sans-serif"
    return font_css, font_family


def build_a4_page_html(q_item, solved, img_filenames, font_css, font_family, base_font_px=12.0, img_max_h=120):
    """สร้างโครงสร้าง HTML แบบ 4 โซนลงกระดาษ A4 แนวตั้ง (595x842 pt) อย่างสมดุล"""
    q_num = q_item.get("q_num", 1)
    src_p = q_item.get("source_page", 0) + 1
    completeness = "Partial Recall" if q_item.get("completeness") != "complete" else "Complete"
    topic = html_lib.escape(solved.get("topic", f"Question {q_num}"))
    specialty = html_lib.escape(solved.get("specialty", ""))

    stem_html = md_inline_to_html(solved.get("stem_highlighted") or q_item.get("raw_stem", ""), True)
    choices = q_item.get("choices") or []
    choices_html = ""
    if choices:
        # วางช้อยส์แบบกระชับ 2 คอลัมน์ถ้าช้อยส์สั้น เพื่อประหยัดพื้นที่กระดาษ A4
        all_short = all(len(str(c)) < 48 for c in choices)
        if all_short and len(choices) >= 4:
            rows = []
            for idx in range(0, len(choices), 2):
                c1 = md_inline_to_html(choices[idx], False)
                c2 = md_inline_to_html(choices[idx + 1], False) if idx + 1 < len(choices) else ""
                rows.append(f"<tr><td style='width:50%; padding:1px 6px 1px 0; border:none;'>{c1}</td><td style='width:50%; padding:1px 0; border:none;'>{c2}</td></tr>")
            choices_html = f"<table style='width:100%; border:none; margin-top:3px;'>{''.join(rows)}</table>"
        else:
            choices_html = "<div style='margin-top:3px;'>" + "".join(f"<div>{md_inline_to_html(c, False)}</div>" for c in choices) + "</div>"

    recon_html = f"<div class='note-line'><b>หมายเหตุโพย:</b> {md_inline_to_html(solved.get('reconstructed_note', ''), False)}</div>" if solved.get("reconstructed_note") else ""
    senior_html = f"<div class='note-line'><b>ตรวจเฉลยรุ่นพี่:</b> {md_inline_to_html(solved.get('senior_check', ''), True)}</div>" if solved.get("senior_check") else ""

    # Zone 2: Answer + Choice Dissection (Left) | Images (Right, auto-collapse if none)
    ans_html = md_inline_to_html(solved.get("correct_answer", ""), False)
    why_html = md_inline_to_html(solved.get("why_correct", ""), True)

    dissect_html = ""
    for d in (solved.get("choice_dissection") or []):
        lbl = html_lib.escape(str(d.get("label", "")))
        rsn = md_inline_to_html(d.get("reason", ""), True)
        dissect_html += f"<div class='dissect-item'><span class='wrong-tag'>✗ {lbl}:</span> {rsn}</div>"

    left_col_html = f"""
        <div class='verdict-box'>
            <div class='ans-title'>✓ คำตอบ: {ans_html}</div>
            <div>{why_html}</div>
        </div>
        {f"<div class='sec-head'>ผ่าตัดช้อยส์หลอก &amp; จุดแยกโรค</div>{dissect_html}" if dissect_html else ""}
    """

    if img_filenames:
        img_blocks = []
        per_img_h = img_max_h if len(img_filenames) == 1 else int(img_max_h * 0.78)
        for fname, cap, src_lbl in img_filenames:
            cap_safe = html_lib.escape(cap[:130])
            src_safe = html_lib.escape(src_lbl)
            img_blocks.append(f"""
            <div class='img-card'>
                <img src='{fname}' style='max-width:100%; max-height:{per_img_h}px; display:block; margin:0 auto;' />
                <div class='img-cap'>{cap_safe} <span style='color:#64748B;'>({src_safe})</span></div>
            </div>
            """)
        zone2_html = f"""
        <table class='split-table'>
            <tr>
                <td style='width:60%; vertical-align:top; padding-right:10px; border:none;'>{left_col_html}</td>
                <td style='width:40%; vertical-align:top; padding-left:6px; border-left:1px solid #E2E8F0; border-top:none; border-right:none; border-bottom:none;'>
                    <div class='sec-head' style='margin-top:0;'>ภาพประกอบ (Visual Reference)</div>
                    {''.join(img_blocks)}
                </td>
            </tr>
        </table>
        """
    else:
        zone2_html = f"<div style='margin-bottom:6px;'>{left_col_html}</div>"

    # Zone 3: Mini-Textbook 2x2 Compact Grid
    tb = solved.get("textbook_review") or {}
    p1 = md_inline_to_html(tb.get("pathophysiology", ""), True)
    p2 = md_inline_to_html(tb.get("clinical_clues", ""), True)
    p3 = md_inline_to_html(tb.get("diagnosis", ""), True)
    p4 = md_inline_to_html(tb.get("management", ""), True)

    zone3_html = f"""
    <div class='tb-box'>
        <div class='tb-banner'>MINI-TEXTBOOK REVIEW: {topic}</div>
        <table class='tb-grid'>
            <tr>
                <td class='tb-cell' style='width:50%;'>
                    <div class='tb-sub'>1. Pathophysiology &amp; Risk</div>
                    <div>{p1}</div>
                </td>
                <td class='tb-cell' style='width:50%;'>
                    <div class='tb-sub'>2. Clinical Clues &amp; Scoring</div>
                    <div>{p2}</div>
                </td>
            </tr>
            <tr>
                <td class='tb-cell' style='width:50%;'>
                    <div class='tb-sub'>3. Diagnostic Algorithm</div>
                    <div>{p3}</div>
                </td>
                <td class='tb-cell' style='width:50%;'>
                    <div class='tb-sub'>4. Management &amp; Complications</div>
                    <div>{p4}</div>
                </td>
            </tr>
        </table>
    </div>
    """

    # Zone 4: High-Yield Strip + Micro Reference
    hy_list = solved.get("high_yield") or []
    hy_html = ""
    if hy_list:
        hy_lines = "".join(f"<div>• {md_inline_to_html(h, True)}</div>" for h in hy_list)
        hy_html = f"""
        <div class='hy-box'>
            <span class='hy-title'>HIGH-YIELD TAKE-HOME:</span>
            {hy_lines}
        </div>
        """

    refs = solved.get("references") or []
    ref_line = f"<div class='ref-line'>Ref: {' | '.join(html_lib.escape(r) for r in refs[:3])}</div>" if refs else ""

    css = f"""
    {font_css}
    body {{
        font-family: {font_family};
        font-size: {base_font_px:.1f}px;
        line-height: 1.32;
        color: #1E293B;
        margin: 0;
        padding: 0;
    }}
    .kw {{ color: #B91C1C; font-weight: bold; }}
    .hdr-table {{ width: 100%; border-collapse: collapse; border-bottom: 1.8px solid #1E3A5F; margin-bottom: 6px; padding-bottom: 3px; }}
    .q-pill {{ background: #1E3A5F; color: #FFFFFF; font-weight: bold; padding: 1px 6px; font-size: 0.95em; }}
    .hdr-topic {{ color: #1E3A5F; font-weight: bold; font-size: 1.08em; }}
    .hdr-meta {{ color: #64748B; font-size: 0.82em; text-align: right; }}
    .stem-box {{ background: #F8FAFC; border: 0.8px solid #CBD5E1; border-left: 3.5px solid #1E3A5F; padding: 5px 8px; margin-bottom: 6px; }}
    .note-line {{ color: #475569; font-size: 0.9em; margin-top: 3px; border-top: 0.5px dashed #CBD5E1; padding-top: 2px; }}
    .split-table {{ width: 100%; border-collapse: collapse; margin-bottom: 6px; }}
    .verdict-box {{ background: #F0FDF4; border: 0.8px solid #BBF7D0; border-left: 3.5px solid #15803D; padding: 5px 8px; margin-bottom: 5px; }}
    .ans-title {{ color: #15803D; font-weight: bold; font-size: 1.04em; margin-bottom: 2px; }}
    .sec-head {{ color: #1E3A5F; font-weight: bold; font-size: 0.92em; border-bottom: 0.8px solid #CBD5E1; margin: 4px 0 3px 0; padding-bottom: 1px; }}
    .dissect-item {{ margin-bottom: 2.5px; }}
    .wrong-tag {{ color: #B91C1C; font-weight: bold; }}
    .img-card {{ border: 0.7px solid #CBD5E1; padding: 3px; margin-bottom: 5px; background: #FFFFFF; text-align: center; }}
    .img-cap {{ font-size: 0.82em; color: #334155; margin-top: 2px; text-align: left; line-height: 1.22; }}
    .tb-box {{ border: 0.9px solid #94A3B8; margin-top: 5px; }}
    .tb-banner {{ background: #1E3A5F; color: #FFFFFF; font-weight: bold; padding: 3px 7px; font-size: 0.92em; }}
    .tb-grid {{ width: 100%; border-collapse: collapse; }}
    .tb-cell {{ border: 0.6px solid #CBD5E1; padding: 4px 6px; vertical-align: top; }}
    .tb-sub {{ color: #1E3A5F; font-weight: bold; font-size: 0.92em; margin-bottom: 1.5px; }}
    .hy-box {{ background: #FEF2F2; border: 0.8px solid #FECACA; border-left: 3.5px solid #B91C1C; padding: 4px 8px; margin-top: 6px; }}
    .hy-title {{ color: #B91C1C; font-weight: bold; font-size: 0.92em; }}
    .ref-line {{ color: #64748B; font-size: 0.78em; margin-top: 4px; text-align: right; }}
    """

    return f"""<style>{css}</style><body>
        <table class='hdr-table'>
            <tr>
                <td style='border:none; padding:0 0 3px 0;'>
                    <span class='q-pill'>Q{q_num:02d}</span>&nbsp;
                    <span class='hdr-topic'>{topic}</span>
                </td>
                <td class='hdr-meta' style='border:none; padding:0 0 3px 0;'>
                    {specialty} | Source p.{src_p} | {completeness}
                </td>
            </tr>
        </table>
        <div class='stem-box'>
            <div>{stem_html}</div>
            {choices_html}
            {recon_html}
            {senior_html}
        </div>
        {zone2_html}
        {zone3_html}
        {hy_html}
        {ref_line}
    </body>"""


def compile_a4_exam_pdf(comp_level, include_summary_sheet=True, progress_cb=None):
    """ประกอบไฟล์ PDF ขนาด A4 แนวตั้ง (1 ข้อสอบ = 1 หน้า A4) พร้อม Auto-Fit ไม่ให้ข้อความล้น"""
    A4_W, A4_H = 595.0, 842.0
    CONTENT_RECT = fitz.Rect(24, 22, A4_W - 24, A4_H - 22)

    doc_out = fitz.open()
    tmp_dir = tempfile.mkdtemp(prefix="medrecall_a4_")

    try:
        font_css, font_family = prepare_thai_fonts(tmp_dir)
        questions = st.session_state.extracted_questions
        total_q = len(questions)

        for idx, q_item in enumerate(questions):
            if progress_cb:
                progress_cb(0.1 + 0.75 * ((idx + 1) / max(1, total_q)), f"กำลังจัดหน้า A4 ข้อที่ {idx + 1} / {total_q}...")

            uid = q_item["uid"]
            solved = st.session_state.solved_data.get(uid)
            if not solved:
                # ถ้าข้อนี้ยังไม่ได้เฉลย สร้างหน้าโครงโจทย์ไว้ก่อน
                solved = {
                    "topic": f"ข้อสอบข้อที่ {q_item.get('q_num', idx + 1)} (ยังไม่ได้ประมวลผล)",
                    "specialty": "-",
                    "stem_highlighted": q_item.get("raw_stem", ""),
                    "correct_answer": "ยังไม่ได้ให้ AI เฉลยข้อนี้",
                    "why_correct": "",
                    "choice_dissection": [],
                    "textbook_review": {},
                    "high_yield": [],
                    "images": [],
                    "references": [],
                }

            # บันทึกรูปภาพที่ตรวจสอบแล้วลง tmp_dir เพื่อให้ Archive โหลดได้ 100%
            img_filenames = []
            for j, im in enumerate(solved.get("images") or []):
                fname = f"q{idx}_im{j}.jpg"
                fpath = os.path.join(tmp_dir, fname)
                with open(fpath, "wb") as f_im:
                    f_im.write(im["bytes"])
                img_filenames.append((fname, im.get("caption", ""), im.get("source", "")))

            arch = fitz.Archive(tmp_dir)

            # Auto-Fit Search: ทดสอบฟอนต์จากใหญ่ไปเล็กเพื่อให้ใช้พื้นที่ A4 เต็มที่แต่ไม่ล้นหน้า
            chosen_html = None
            fit_trials = [
                (13.0, 145),
                (12.2, 135),
                (11.4, 125),
                (10.8, 112),
                (10.2, 100),
                (9.6, 92),
                (9.0, 85),
                (8.5, 78),
            ]
            for f_px, im_h in fit_trials:
                candidate_html = build_a4_page_html(
                    q_item, solved, img_filenames, font_css, font_family,
                    base_font_px=f_px, img_max_h=im_h
                )
                # ทดสอบบนหน้าจำลองว่าฟิตพอดีโดยไม่ต้องถูกบีบสเกลหรือไม่
                scratch = fitz.open()
                try:
                    sp = scratch.new_page(width=A4_W, height=A4_H)
                    spare_h, scale = sp.insert_htmlbox(CONTENT_RECT, candidate_html, archive=arch)
                    if spare_h >= 0 and scale >= 0.99:
                        chosen_html = candidate_html
                        break
                except Exception:
                    chosen_html = candidate_html
                    break
                finally:
                    scratch.close()

            if chosen_html is None:
                chosen_html = build_a4_page_html(
                    q_item, solved, img_filenames, font_css, font_family,
                    base_font_px=8.5, img_max_h=75
                )

            page = doc_out.new_page(width=A4_W, height=A4_H)
            page.insert_htmlbox(CONTENT_RECT, chosen_html, archive=arch)

        # แนบหน้าสรุปสารบัญ High-Yield ท้ายเล่ม (Quick Cram Index)
        if include_summary_sheet and st.session_state.solved_data:
            if progress_cb:
                progress_cb(0.88, "กำลังสร้างหน้าสารบัญ High-Yield ท้ายเล่ม...")
            rows = []
            for q_item in questions:
                s = st.session_state.solved_data.get(q_item["uid"])
                if not s:
                    continue
                q_n = q_item.get("q_num", "")
                top = html_lib.escape(s.get("topic", ""))
                ans = html_lib.escape(s.get("correct_answer", ""))
                hy1 = html_lib.escape((s.get("high_yield") or [""])[0])
                rows.append(f"<tr><td style='width:7%; text-align:center; font-weight:bold;'>Q{q_n:02d}</td><td style='width:24%; font-weight:bold; color:#1E3A5F;'>{top}</td><td style='width:24%; color:#15803D; font-weight:bold;'>{ans}</td><td style='width:45%;'>{hy1}</td></tr>")

            # แบ่งตารางทีละ 18 แถวต่อ 1 หน้า A4 เพื่อให้อ่านง่ายไม่เบียด
            chunk_size = 18
            arch = fitz.Archive(tmp_dir)
            for c_idx in range(0, len(rows), chunk_size):
                chunk_rows = "".join(rows[c_idx:c_idx + chunk_size])
                idx_page_num = (c_idx // chunk_size) + 1
                sum_html = f"""
                <style>
                    {font_css}
                    body {{ font-family: {font_family}; font-size: 10.5px; color: #1E293B; line-height: 1.3; margin: 0; }}
                    h2 {{ color: #1E3A5F; border-bottom: 2px solid #1E3A5F; margin: 0 0 8px 0; padding-bottom: 3px; font-size: 14px; }}
                    table {{ width: 100%; border-collapse: collapse; }}
                    th {{ background: #1E3A5F; color: #FFFFFF; padding: 4px 5px; text-align: left; border: 0.6px solid #1E3A5F; }}
                    td {{ border: 0.6px solid #CBD5E1; padding: 4px 5px; vertical-align: top; }}
                </style>
                <body>
                    <h2>QUICK EXAM INDEX &amp; HIGH-YIELD SUMMARY (หน้า {idx_page_num})</h2>
                    <table>
                        <tr><th>ข้อ</th><th>หัวข้อ / โรค</th><th>คำตอบฟันธง</th><th>กฎเหล็ก High-Yield</th></tr>
                        {chunk_rows}
                    </table>
                </body>
                """
                p_sum = doc_out.new_page(width=A4_W, height=A4_H)
                p_sum.insert_htmlbox(CONTENT_RECT, sum_html, archive=arch)

        if progress_cb:
            progress_cb(0.95, "กำลังบีบอัดไฟล์ PDF...")

        try:
            doc_out.subset_fonts()
        except Exception:
            pass

        if "1. บีบอัดขั้นสุด" in comp_level:
            try:
                doc_out.rewrite_images(dpi_threshold=140, dpi_target=100, quality=72)
            except Exception:
                pass
            out_bytes = doc_out.tobytes(garbage=4, deflate=True, clean=True)
        elif "2. บีบอัดสมดุล" in comp_level:
            try:
                doc_out.rewrite_images(dpi_threshold=180, dpi_target=135, quality=82)
            except Exception:
                pass
            out_bytes = doc_out.tobytes(garbage=4, deflate=True, clean=True)
        else:
            out_bytes = doc_out.tobytes(garbage=3, deflate=True)

        return out_bytes
    finally:
        doc_out.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        gc.collect()


# ==============================================================================
# 9. SIDEBAR: API KEY, MODELS & TUTOR SETTINGS
# ==============================================================================
with st.sidebar:
    st.markdown("<h2 style='color:#1E3A5F; margin-bottom:0.3rem;'>🩺 Recall Tutor Settings</h2>", unsafe_allow_html=True)
    if not HAS_GOOGLE_GENAI:
        st.error("ยังไม่ได้ติดตั้ง `google-genai` กรุณารัน:\n`pip install google-genai`")

    is_locked = st.session_state.is_running

    api_in = st.text_input(
        "🔑 Gemini API Key:",
        type="password",
        value=st.session_state.user_api_key,
        disabled=is_locked,
        help="กรอก Google AI Studio API Key ของคุณ (บันทึกอัตโนมัติในเครื่อง)"
    )
    if api_in != st.session_state.user_api_key:
        st.session_state.user_api_key = api_in.strip()
        st.session_state.available_models = []
        save_workspace()
        st.rerun()

    if st.session_state.user_api_key and HAS_GOOGLE_GENAI:
        try:
            if not st.session_state.available_models:
                st.session_state.available_models = fetch_available_models(st.session_state.user_api_key)

            models = st.session_state.available_models
            ext_idx = models.index(st.session_state.extract_model) if st.session_state.extract_model in models else 0
            slv_idx = models.index(st.session_state.solve_model) if st.session_state.solve_model in models else 0

            st.session_state.extract_model = st.selectbox(
                "AI Model สำหรับแกะโจทย์ (Phase 1):",
                models,
                index=ext_idx,
                disabled=is_locked,
            )
            st.session_state.solve_model = st.selectbox(
                "AI Model สำหรับเฉลย+ติว (Phase 2):",
                models,
                index=slv_idx,
                disabled=is_locked,
                help="แนะนำ gemini-2.5-flash หรือ gemini-2.5-pro เพื่อความแม่นยำและรองรับ Google Search Grounding"
            )
        except Exception as e:
            st.error(f"เชื่อมต่อ API ไม่สำเร็จ: {e}")

    st.markdown("### 💳 Token Usage")
    tok = st.session_state.estimated_tokens_used
    st.progress(min(tok / 1_000_000, 1.0))
    st.caption(f"ประมาณการที่ใช้ไป: **{tok:,} Tokens**")

    st.divider()
    levels = [
        "นสพ. ปี 4 (NL1 / Ward)",
        "นสพ. ปี 5 (Clinical)",
        "นสพ. ปี 6 (NL2 / Comprehensive)",
        "นสพ. พรีคลินิก (ปี 2-3)",
    ]
    st.session_state.med_level = st.selectbox(
        "ระดับชั้น / เป้าหมายการสอบ:",
        levels,
        index=levels.index(st.session_state.med_level) if st.session_state.med_level in levels else 0,
        disabled=is_locked,
    )

    st.markdown("### 🌐 ข้อมูลล่าสุด & ภาพประกอบ")
    st.session_state.use_google_search = st.checkbox(
        "เปิด Google Search Grounding (เช็ก Guideline ล่าสุด)",
        value=st.session_state.use_google_search,
        disabled=is_locked,
    )
    st.session_state.fetch_web_images = st.checkbox(
        "ค้นหาและแทรกรูปการแพทย์จากเน็ตอัตโนมัติ (ไม่เสีย 100%)",
        value=st.session_state.fetch_web_images,
        disabled=is_locked,
    )
    if st.session_state.fetch_web_images:
        st.session_state.max_images_per_q = st.slider(
            "จำนวนรูปสูงสุดต่อ 1 ข้อ (1 หน้า A4):",
            1, 2, st.session_state.max_images_per_q,
            disabled=is_locked,
        )
        st.session_state.ai_verify_images = st.checkbox(
            "ให้ AI ตรวจความตรงปกของภาพก่อนแปะ",
            value=st.session_state.ai_verify_images,
            disabled=is_locked,
            help="ช่วยตัดภาพที่ไม่เกี่ยวข้องออก หากหาภาพดีไม่ได้จะเว้นว่างและขยายข้อความแทน"
        )

    st.session_state.max_output_tokens = st.number_input(
        "Max Output Tokens ต่อข้อ:",
        min_value=1500, max_value=8192, value=st.session_state.max_output_tokens, step=500,
        disabled=is_locked,
    )

    with st.expander("🛠️ ปรับแต่ง Prompt เฉลยและติว (ขั้นสูง)"):
        st.session_state.use_custom_prompt = st.checkbox(
            "ใช้ Custom Prompt",
            value=st.session_state.use_custom_prompt,
            disabled=is_locked,
        )
        if st.session_state.use_custom_prompt:
            st.session_state.custom_solve_prompt = st.text_area(
                "แก้ไข Prompt (คงตัวแปร {...} ไว้):",
                value=st.session_state.custom_solve_prompt or DEFAULT_SOLVE_PROMPT_TEMPLATE,
                height=260,
                disabled=is_locked,
            )
            if st.button("💾 บันทึก Prompt", use_container_width=True):
                save_workspace()
                st.toast("บันทึก Prompt แล้ว")


# ==============================================================================
# 10. MAIN WORKSPACE: UPLOAD -> EXTRACT (1 Q = 1 A4) -> SOLVE -> READER -> EXPORT
# ==============================================================================
st.markdown("<div class='app-title'>🩺 MedRecall A4 Exam Tutor</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='app-subtitle'>แตกโพยข้อสอบรุ่นพี่ 1 ข้อต่อ 1 หน้า A4 • เฉลยพร้อมค้นข้อมูลล่าสุด • แทรกภาพการแพทย์จริงไม่เสีย • ติวเนื้อหาแบบ Mini-Textbook</div>",
    unsafe_allow_html=True,
)

# --- Step 1: Upload or Restore PDF ---
if not st.session_state.pdf_bytes:
    if os.path.exists(WORKSPACE_META_FILE) and os.path.exists(WORKSPACE_PDF_FILE):
        st.info("💾 พบงานเฉลยโพยข้อสอบที่ทำค้างไว้ในเครื่อง")
        if st.button("🔄 กู้คืนงานเดิม", type="primary"):
            if load_workspace():
                st.success("กู้คืนสำเร็จ!")
                time.sleep(0.4)
                st.rerun()
            else:
                st.error("ไม่สามารถโหลดไฟล์กู้คืนได้")

    uploaded = st.file_uploader("อัปโหลดไฟล์ PDF โพยข้อสอบ (รองรับทั้งไฟล์ข้อความและไฟล์สแกนที่มีหลายข้อใน 1 หน้า)", type="pdf")
    if uploaded:
        st.session_state.pdf_bytes = uploaded.getvalue()
        st.session_state.pdf_name = uploaded.name
        doc_tmp = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
        n_pages = len(doc_tmp)
        doc_tmp.close()
        st.session_state.selected_pages = list(range(n_pages))
        save_workspace(save_pdf_binary=True)
        st.rerun()
else:
    doc_meta = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc_meta)
    doc_meta.close()

    total_q = len(st.session_state.extracted_questions)
    solved_q = len(st.session_state.solved_data)

    c_top1, c_top2 = st.columns([3.5, 1])
    with c_top1:
        st.info(
            f"📄 ไฟล์โพย: **{st.session_state.pdf_name}** ({total_pages} หน้า)  |  "
            f"แยกข้อสอบได้: **{total_q} ข้อ (= {total_q} หน้า A4)**  |  "
            f"เฉลย+ติวเสร็จแล้ว: **{solved_q} / {total_q} ข้อ**"
        )
    with c_top2:
        if st.button("🗑️ เปลี่ยนไฟล์ / Reset", use_container_width=True, disabled=is_locked):
            st.session_state.show_reset_confirm = True

    if st.session_state.show_reset_confirm:
        st.warning("ยืนยันการล้างข้อมูลทั้งหมดและเริ่มไฟล์ใหม่?")
        cr1, cr2 = st.columns(2)
        if cr1.button("✅ ยืนยันล้างข้อมูล", type="primary"):
            clear_workspace()
            st.cache_data.clear()
            for k in list(KEYS_TO_INIT.keys()):
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()
        if cr2.button("❌ ยกเลิก"):
            st.session_state.show_reset_confirm = False
            st.rerun()

    # --- Step 1.5: Page Selector ---
    if not is_locked:
        with st.expander(f"⚙️ เลือกหน้า PDF ต้นฉบับที่ต้องการแตกข้อสอบ (เลือกไว้ {len(st.session_state.selected_pages)}/{total_pages} หน้า)", expanded=False):
            cp1, cp2, cp3, cp4 = st.columns([1, 1, 2, 1.2])
            if cp1.button("✅ เลือกทุกหน้า", use_container_width=True):
                st.session_state.selected_pages = list(range(total_pages))
                save_workspace()
                st.rerun()
            if cp2.button("❌ ล้างทั้งหมด", use_container_width=True):
                st.session_state.selected_pages = []
                save_workspace()
                st.rerun()
            with cp3:
                rng_txt = st.text_input("ช่วงหน้า เช่น 1-5, 8:", label_visibility="collapsed", placeholder="ระบุช่วงหน้า เช่น 1-5, 8")
            if cp4.button("🎯 ใช้ช่วงหน้า", use_container_width=True) and rng_txt:
                chosen = set()
                for part in rng_txt.split(","):
                    part = part.strip()
                    if "-" in part:
                        try:
                            a, b = map(int, part.split("-"))
                            chosen.update(range(max(0, a - 1), min(total_pages, b)))
                        except Exception:
                            pass
                    elif part.isdigit():
                        p_i = int(part) - 1
                        if 0 <= p_i < total_pages:
                            chosen.add(p_i)
                if chosen:
                    st.session_state.selected_pages = sorted(chosen)
                    save_workspace()
                    st.rerun()

    # --- Step 2: Action Controls (Phase 1 Extract vs Phase 2 Solve) ---
    status_box = st.empty()
    col_a1, col_a2, col_a3 = st.columns([1.3, 1.3, 1])

    pending_extract_pages = [p for p in st.session_state.selected_pages if p not in st.session_state.extracted_pages_done]
    pending_solve_qs = [q for q in st.session_state.extracted_questions if q["uid"] not in st.session_state.solved_data]

    if col_a1.button(
        f"✂️ ขั้นที่ 1: แตกข้อสอบจาก PDF ({len(pending_extract_pages)} หน้าที่เหลือ)",
        type="primary" if len(pending_extract_pages) > 0 else "secondary",
        disabled=is_locked or not st.session_state.user_api_key or len(pending_extract_pages) == 0,
        use_container_width=True,
    ):
        st.session_state.run_mode = "extract"
        st.session_state.is_running = True
        st.session_state.stop_clicked = False
        st.rerun()

    if col_a2.button(
        f"🧠 ขั้นที่ 2: เฉลย+ติว+หารูป ({len(pending_solve_qs)} ข้อที่เหลือ)",
        type="primary" if (len(pending_extract_pages) == 0 and len(pending_solve_qs) > 0) else "secondary",
        disabled=is_locked or not st.session_state.user_api_key or len(pending_solve_qs) == 0,
        use_container_width=True,
    ):
        st.session_state.run_mode = "solve"
        st.session_state.is_running = True
        st.session_state.stop_clicked = False
        st.rerun()

    if col_a3.button("🛑 หยุดชั่วคราว (Pause)", disabled=not is_locked, use_container_width=True):
        st.session_state.is_running = False
        st.session_state.stop_clicked = True
        st.session_state.run_mode = "idle"
        save_workspace()
        st.rerun()

    # --- Step 3: Manage Extracted Question Queue ---
    if total_q > 0 and not is_locked:
        with st.expander(f"📋 จัดการคิวข้อสอบที่แตกออกมา ({total_q} ข้อ = {total_q} หน้า A4) — แก้ไข/รวมข้อข้ามหน้า/ลบข้อขยะ", expanded=False):
            q_labels = [
                f"Q{q['q_num']:02d} (หน้า {q['source_page']+1}) {'✅' if q['uid'] in st.session_state.solved_data else '⏳'} — {q['raw_stem'][:65]}..."
                for q in st.session_state.extracted_questions
            ]
            sel_manage = st.selectbox("เลือกข้อที่ต้องการตรวจสอบ/แก้ไขโจทย์:", range(total_q), format_func=lambda i: q_labels[i])
            q_obj = st.session_state.extracted_questions[sel_manage]

            new_stem = st.text_area("ข้อความโจทย์:", value=q_obj.get("raw_stem", ""), height=100, key=f"m_stem_{q_obj['uid']}")
            new_choices_str = st.text_area(
                "ตัวเลือก (1 บรรทัดต่อ 1 ช้อยส์ ถ้าไม่มีเว้นว่าง):",
                value="\n".join(q_obj.get("choices") or []),
                height=90,
                key=f"m_ch_{q_obj['uid']}",
            )
            new_snote = st.text_input("โน้ต/เฉลยรุ่นพี่ในโพย:", value=q_obj.get("senior_note", ""), key=f"m_sn_{q_obj['uid']}")

            cm1, cm2, cm3 = st.columns(3)
            if cm1.button("💾 บันทึกการแก้โจทย์", use_container_width=True):
                q_obj["raw_stem"] = new_stem.strip()
                q_obj["choices"] = [ln.strip() for ln in new_choices_str.split("\n") if ln.strip()]
                q_obj["senior_note"] = new_snote.strip()
                save_workspace()
                st.toast("อัปเดตโจทย์แล้ว")
                st.rerun()
            if cm2.button("🔗 รวมกับข้อถัดไป (กรณีโจทย์ข้ามหน้า)", disabled=(sel_manage >= total_q - 1), use_container_width=True):
                nxt = st.session_state.extracted_questions[sel_manage + 1]
                q_obj["raw_stem"] = (q_obj["raw_stem"] + "\n" + nxt["raw_stem"]).strip()
                q_obj["choices"] = (q_obj.get("choices") or []) + (nxt.get("choices") or [])
                if nxt.get("senior_note"):
                    q_obj["senior_note"] = (q_obj.get("senior_note", "") + " " + nxt["senior_note"]).strip()
                st.session_state.solved_data.pop(nxt["uid"], None)
                st.session_state.extracted_questions.pop(sel_manage + 1)
                for idx_r, item_r in enumerate(st.session_state.extracted_questions, start=1):
                    item_r["q_num"] = idx_r
                save_workspace()
                st.rerun()
            if cm3.button("🗑️ ลบข้อนี้ออก", use_container_width=True):
                st.session_state.solved_data.pop(q_obj["uid"], None)
                st.session_state.extracted_questions.pop(sel_manage)
                for idx_r, item_r in enumerate(st.session_state.extracted_questions, start=1):
                    item_r["q_num"] = idx_r
                st.session_state.current_q_idx = min(st.session_state.current_q_idx, max(0, len(st.session_state.extracted_questions) - 1))
                save_workspace()
                st.rerun()

    # --- Step 4: Interactive A4 Reader, Image Manager & Editor ---
    if total_q > 0:
        st.divider()
        st.session_state.current_q_idx = min(st.session_state.current_q_idx, total_q - 1)
        curr_idx = st.session_state.current_q_idx
        curr_q = st.session_state.extracted_questions[curr_idx]
        curr_uid = curr_q["uid"]

        nav1, nav2, nav3 = st.columns([1, 3, 1])
        with nav1:
            if st.button("⬅️ ข้อก่อนหน้า", use_container_width=True, disabled=(curr_idx == 0)):
                st.session_state.current_q_idx -= 1
                st.rerun()
        with nav2:
            if total_q > 1:
                chosen_num = st.slider("เลือกข้อสอบ (1 ข้อ = 1 หน้า A4):", 1, total_q, curr_idx + 1, label_visibility="collapsed")
                if chosen_num - 1 != curr_idx:
                    st.session_state.current_q_idx = chosen_num - 1
                    st.rerun()
            else:
                st.markdown("<div style='text-align:center; font-weight:700; padding-top:6px;'>ข้อที่ 1 / 1</div>", unsafe_allow_html=True)
        with nav3:
            if st.button("ข้อถัดไป ➡️", use_container_width=True, disabled=(curr_idx >= total_q - 1)):
                st.session_state.current_q_idx += 1
                st.rerun()

        if curr_uid in st.session_state.solved_data:
            solved_obj = st.session_state.solved_data[curr_uid]
            render_web_a4_card(curr_q, solved_obj)

            # เครื่องมือเสริมประจำข้อ (ดูหน้า PDF เดิม / เปลี่ยนรูป / อัปโหลดรูปเอง / แก้ไขข้อความ / เฉลยข้อนี้ใหม่)
            tool_c1, tool_c2, tool_c3 = st.columns([1.2, 1.2, 1])
            with tool_c1:
                with st.expander("📄 ดูหน้า PDF โพยต้นฉบับ"):
                    src_img = render_pdf_page_png(st.session_state.pdf_bytes, curr_q["source_page"], dpi=115)
                    st.image(src_img, use_container_width=True, caption=f"โพยต้นฉบับ หน้า {curr_q['source_page'] + 1}")

            with tool_c2:
                with st.expander("🖼️ จัดการรูปภาพของข้อนี้ (ค้นใหม่ / อัปโหลด / ลบ)"):
                    cur_imgs = solved_obj.get("images") or []
                    for im_i, im_d in enumerate(cur_imgs):
                        st.caption(f"รูปที่ {im_i+1}: {im_d.get('caption', '')}")
                        if st.button(f"🗑️ ลบรูปที่ {im_i+1}", key=f"del_im_{curr_uid}_{im_i}"):
                            cur_imgs.pop(im_i)
                            solved_obj["images"] = cur_imgs
                            save_workspace()
                            st.rerun()

                    custom_q = st.text_input("ค้นหารูปใหม่ (ภาษาอังกฤษ เช่น DVT ultrasound anatomy):", key=f"img_q_{curr_uid}")
                    custom_cap = st.text_input("คำบรรยายภาพภาษาไทย:", key=f"img_cap_{curr_uid}")
                    if st.button("🔍 ค้นหาและเพิ่มรูปนี้", key=f"btn_img_{curr_uid}") and custom_q.strip():
                        with st.spinner("กำลังค้นหาและตรวจสอบไฟล์ภาพ..."):
                            found = fetch_verified_medical_images(
                                [{"query": custom_q.strip(), "caption_th": custom_cap.strip() or custom_q.strip(), "type": "anatomy"}],
                                topic=solved_obj.get("topic", ""),
                                max_images=1,
                                client=None,
                                use_ai_verify=False,
                            )
                            if found:
                                solved_obj.setdefault("images", []).extend(found)
                                save_workspace()
                                st.success("เพิ่มภาพสำเร็จ!")
                                st.rerun()
                            else:
                                st.warning("ไม่พบภาพที่ผ่านการตรวจสอบ ลองเปลี่ยนคำค้นภาษาอังกฤษสั้นๆ ครับ")

                    up_img = st.file_uploader("หรืออัปโหลดรูปภาพเอง (PNG/JPG):", type=["png", "jpg", "jpeg"], key=f"up_im_{curr_uid}")
                    if up_img is not None:
                        if st.button("➕ แนบภาพที่อัปโหลดลงหน้า A4 นี้", key=f"attach_up_{curr_uid}"):
                            with Image.open(up_img) as u_im:
                                u_im = u_im.convert("RGB")
                                u_im.thumbnail((900, 900), Image.Resampling.LANCZOS)
                                buf = io.BytesIO()
                                u_im.save(buf, format="JPEG", quality=85)
                                solved_obj.setdefault("images", []).append({
                                    "bytes": buf.getvalue(),
                                    "width": u_im.size[0],
                                    "height": u_im.size[1],
                                    "url": "local_upload",
                                    "source": "Uploaded",
                                    "caption": custom_cap.strip() or "ภาพประกอบเพิ่มเติม",
                                })
                                save_workspace()
                                st.rerun()

            with tool_c3:
                if st.button("🔄 ให้ AI เฉลยข้อนี้ใหม่", use_container_width=True, disabled=is_locked or not st.session_state.user_api_key):
                    with st.spinner("กำลังค้นข้อมูลล่าสุดและเรียบเรียงเฉลยใหม่..."):
                        client = get_genai_client()
                        m_use = get_next_available_model(st.session_state.solve_model)
                        st.session_state.solved_data[curr_uid] = solve_single_question(
                            client, m_use, curr_q, use_search=st.session_state.use_google_search
                        )
                        save_workspace()
                        st.rerun()

            with st.expander("✏️ แก้ไขข้อความเฉลย & เนื้อหาติวของข้อนี้"):
                ed_ans = st.text_input("คำตอบฟันธง:", value=solved_obj.get("correct_answer", ""), key=f"ed_ans_{curr_uid}")
                ed_why = st.text_area("เหตุผลที่ถูก:", value=solved_obj.get("why_correct", ""), height=90, key=f"ed_why_{curr_uid}")
                tb_e = solved_obj.get("textbook_review") or {}
                ec1, ec2 = st.columns(2)
                with ec1:
                    ed_p1 = st.text_area("1. Pathophysiology & Risk:", value=tb_e.get("pathophysiology", ""), height=100, key=f"ed_p1_{curr_uid}")
                    ed_p3 = st.text_area("3. Diagnostic Algorithm:", value=tb_e.get("diagnosis", ""), height=100, key=f"ed_p3_{curr_uid}")
                with ec2:
                    ed_p2 = st.text_area("2. Clinical Clues & Scoring:", value=tb_e.get("clinical_clues", ""), height=100, key=f"ed_p2_{curr_uid}")
                    ed_p4 = st.text_area("4. Management & Complications:", value=tb_e.get("management", ""), height=100, key=f"ed_p4_{curr_uid}")
                ed_hy = st.text_area("High-Yield (บรรทัดละ 1 ข้อ):", value="\n".join(solved_obj.get("high_yield") or []), height=75, key=f"ed_hy_{curr_uid}")

                if st.button("💾 บันทึกการแก้ไขข้อนี้", type="primary", key=f"save_ed_{curr_uid}"):
                    solved_obj["correct_answer"] = ed_ans
                    solved_obj["why_correct"] = ed_why
                    solved_obj["textbook_review"] = {
                        "pathophysiology": ed_p1,
                        "clinical_clues": ed_p2,
                        "diagnosis": ed_p3,
                        "management": ed_p4,
                    }
                    solved_obj["high_yield"] = [ln.strip() for ln in ed_hy.split("\n") if ln.strip()]
                    save_workspace()
                    st.toast("บันทึกการแก้ไขเรียบร้อย!")
                    st.rerun()
        else:
            st.markdown(f"""
            <div class='a4-sheet'>
                <div class='a4-header'>
                    <div><span class='a4-qbadge'>Q{curr_q['q_num']:02d}</span><span class='a4-topic'>รอประมวลผลเฉลยและติวเนื้อหา</span></div>
                    <div class='a4-meta'>หน้าต้นฉบับ {curr_q['source_page']+1}</div>
                </div>
                <div class='zone-stem'>{md_inline_to_html(curr_q.get('raw_stem', ''), False)}</div>
            </div>
            """, unsafe_allow_html=True)

    # --- Step 5: Export A4 PDF ---
    if solved_q > 0 and not is_locked:
        st.divider()
        st.subheader("📦 ส่งออกไฟล์ PDF ติวสอบขนาด A4 (1 ข้อสอบ = 1 หน้า A4)")

        ex_c1, ex_c2 = st.columns([1.5, 1])
        with ex_c1:
            comp_level = st.selectbox(
                "ระดับการบีบอัดไฟล์ PDF:",
                [
                    "1. บีบอัดขั้นสุด (ไฟล์เล็ก ประหยัดพื้นที่ iPad/GoodNotes)",
                    "2. บีบอัดสมดุล (คมชัดสูง ขนาดกำลังดี - แนะนำ)",
                    "3. บีบอัดน้อย (คุณภาพรูปภาพสูงสุด)",
                ],
                index=1,
            )
        with ex_c2:
            inc_idx = st.checkbox("แนบตารางสารบัญ High-Yield ท้ายเล่ม", value=True)

        if st.button("🖨️ สร้างไฟล์ PDF ติวสอบ A4 ฉบับสมบูรณ์", type="primary", use_container_width=True):
            prog = st.progress(0.05, text="กำลังเตรียมจัดหน้า A4...")
            pdf_out = compile_a4_exam_pdf(
                comp_level=comp_level,
                include_summary_sheet=inc_idx,
                progress_cb=lambda p, m: prog.progress(min(0.99, p), text=m),
            )
            st.session_state.compiled_pdf_bytes = pdf_out
            st.session_state.compiled_pdf_size_mb = len(pdf_out) / (1024 * 1024)
            prog.empty()

        if st.session_state.compiled_pdf_bytes:
            st.success(f"✅ สร้างไฟล์ PDF สำเร็จ! ({total_q} หน้าข้อสอบ A4 | ขนาด {st.session_state.compiled_pdf_size_mb:.2f} MB)")
            st.download_button(
                label=f"💾 ดาวน์โหลดชีทเฉลย+ติว A4 ({st.session_state.compiled_pdf_size_mb:.2f} MB)",
                data=st.session_state.compiled_pdf_bytes,
                file_name=f"A4_MedTutor_{st.session_state.pdf_name}",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )

    # ==========================================================================
    # 11. BACKGROUND EXECUTION LOOP (PHASE 1 EXTRACT & PHASE 2 SOLVE)
    # ==========================================================================
    if st.session_state.is_running and not st.session_state.stop_clicked:
        client = get_genai_client()
        if client is None:
            st.session_state.is_running = False
            st.error("กรุณากรอก Gemini API Key และติดตั้ง `google-genai` ก่อนเริ่มทำงาน")
            st.stop()

        # --- PHASE 1: EXTRACT QUESTIONS FROM PDF PAGES ---
        if st.session_state.run_mode == "extract":
            next_page = next((p for p in st.session_state.selected_pages if p not in st.session_state.extracted_pages_done), None)
            if next_page is None:
                st.session_state.is_running = False
                st.session_state.run_mode = "idle"
                save_workspace()
                status_box.markdown(
                    f"<div class='status-banner'><b>✅ แตกข้อสอบครบทุกหน้าแล้ว!</b> ได้ทั้งหมด <b>{len(st.session_state.extracted_questions)} ข้อ</b> พร้อมกดเริ่มขั้นที่ 2 (เฉลย+ติว+หารูป) ได้เลยครับ</div>",
                    unsafe_allow_html=True,
                )
            else:
                active_m = get_next_available_model(st.session_state.extract_model)
                status_box.markdown(
                    f"<div class='status-banner'><b>✂️ [ขั้นที่ 1/2] กำลังแกะข้อสอบจากหน้า PDF ที่ {next_page + 1} / {total_pages}</b> "
                    f"(สะสมแล้ว {len(st.session_state.extracted_questions)} ข้อ | โมเดล: <code>{active_m}</code>)</div>",
                    unsafe_allow_html=True,
                )
                try:
                    found_qs = extract_questions_from_page(client, active_m, st.session_state.pdf_bytes, next_page)
                    base_num = len(st.session_state.extracted_questions)
                    for offset, q_raw in enumerate(found_qs, start=1):
                        stem = (q_raw.get("raw_stem") or "").strip()
                        if not stem:
                            continue
                        new_num = base_num + offset
                        uid = f"q_{next_page}_{offset}_{int(time.time()*1000) % 100000}"
                        st.session_state.extracted_questions.append({
                            "uid": uid,
                            "q_num": new_num,
                            "source_page": next_page,
                            "completeness": q_raw.get("completeness", "complete"),
                            "raw_stem": stem,
                            "choices": q_raw.get("choices") or [],
                            "senior_note": (q_raw.get("senior_note") or "").strip(),
                            "has_pdf_figure": bool(q_raw.get("has_pdf_figure", False)),
                        })
                    # Re-number cleanly
                    for idx_r, item_r in enumerate(st.session_state.extracted_questions, start=1):
                        item_r["q_num"] = idx_r

                    st.session_state.extracted_pages_done.append(next_page)
                    save_workspace()
                    time.sleep(0.25)
                    st.rerun()
                except Exception as e:
                    err_s = str(e)
                    if "429" in err_s or "RESOURCE_EXHAUSTED" in err_s or "quota" in err_s.lower():
                        st.session_state.exhausted_models[active_m] = time.time() + 65
                        status_box.warning(f"⚠️ โมเดล {active_m} ติดโควต้า กำลังสลับโมเดลสำรอง...")
                        time.sleep(2.0)
                        st.rerun()
                    else:
                        st.session_state.is_running = False
                        st.session_state.run_mode = "idle"
                        st.error(f"เกิดข้อผิดพลาดขณะแกะหน้า {next_page + 1}: {err_s}")

        # --- PHASE 2: SOLVE + SEARCH + FETCH VERIFIED IMAGES + MINI-TEXTBOOK ---
        elif st.session_state.run_mode == "solve":
            next_q = next((q for q in st.session_state.extracted_questions if q["uid"] not in st.session_state.solved_data), None)
            if next_q is None:
                st.session_state.is_running = False
                st.session_state.run_mode = "idle"
                save_workspace()
                status_box.markdown(
                    "<div class='status-banner' style='border-left-color:#15803D; background:#F0FDF4; color:#15803D;'>"
                    "<b>✅ เฉลยและติวเนื้อหาครบทุกข้อแล้ว!</b> ตรวจสอบหน้าตัวอย่างหรือกดสร้างไฟล์ PDF A4 ด้านล่างได้เลยครับ</div>",
                    unsafe_allow_html=True,
                )
            else:
                active_m = get_next_available_model(st.session_state.solve_model)
                done_cnt = len(st.session_state.solved_data)
                status_box.markdown(
                    f"<div class='status-banner'><b>🧠 [ขั้นที่ 2/2] กำลังเฉลย + ค้นข้อมูลล่าสุด + หารูปประกอบ ข้อที่ {next_q['q_num']} / {total_q}</b> "
                    f"(เสร็จแล้ว {done_cnt}/{total_q} ข้อ | โมเดล: <code>{active_m}</code>)</div>",
                    unsafe_allow_html=True,
                )
                try:
                    solved_res = solve_single_question(
                        client=client,
                        model_name=active_m,
                        q_item=next_q,
                        use_search=st.session_state.use_google_search,
                    )
                    st.session_state.solved_data[next_q["uid"]] = solved_res
                    st.session_state.current_q_idx = next_q["q_num"] - 1
                    save_workspace()
                    time.sleep(0.35)
                    st.rerun()
                except Exception as e:
                    err_s = str(e)
                    if "429" in err_s or "RESOURCE_EXHAUSTED" in err_s or "quota" in err_s.lower():
                        st.session_state.exhausted_models[active_m] = time.time() + 65
                        status_box.warning(f"⚠️ โมเดล {active_m} ติดโควต้า กำลังสลับโมเดลสำรอง...")
                        time.sleep(2.5)
                        st.rerun()
                    else:
                        st.session_state.is_running = False
                        st.session_state.run_mode = "idle"
                        st.error(f"เกิดข้อผิดพลาดที่ข้อ {next_q['q_num']}: {err_s}")
