import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
from PIL import Image
import io
import re

# --- 1. ตั้งค่าเริ่มต้น Session State ---
st.set_page_config(page_title="Textbook Smart Reader 📚", layout="wide")

keys_to_init = {
    'pdf_bytes': None,
    'pdf_name': "",
    'processed_data': {},  # เก็บข้อมูลรายหน้า: ai_text, raw_text, extracted_images
    'page_idx': 0,
    'user_api_key': "",
    'active_model': "gemini-3.1-flash-lite" # ค่าเริ่มต้นโมเดลที่อ่านภาพเก่งและเร็ว
}

for k, v in keys_to_init.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --- 2. Custom CSS (เน้นสำหรับอ่านตัวหนังสือเยอะๆ) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
    html, body, [class*="st-"] { font-family: 'Sarabun', sans-serif !important; }
    
    .stApp { background-color: #F8FAFC; }
    
    /* กล่องสำหรับอ่านเนื้อหาที่จัดเรียงใหม่ */
    .reading-box { 
        background: #FFFFFF; border-radius: 12px; padding: 30px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        border-top: 5px solid #3B82F6;
        font-size: 17px; line-height: 1.8; color: #1E293B;
    }
    
    .reading-box b, .reading-box strong { color: #0F172A; font-weight: 700; background: #FEF9C3; padding: 0 4px; border-radius: 4px; }
    
    .reading-box table { width: 100%; border-collapse: collapse; margin: 20px 0; border-radius: 8px; overflow: hidden; }
    .reading-box th { background-color: #F1F5F9; padding: 12px; border-bottom: 2px solid #CBD5E1; color: #334155; text-align: left; }
    .reading-box td { border: 1px solid #E2E8F0; padding: 12px; }
    
    .reading-box ul { padding-left: 20px; }
    .reading-box li { margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# --- 3. ฟังก์ชันสกัดรูปภาพย่อยจากหน้า PDF (Image Extraction) ---
def extract_images_from_page(doc, page_num):
    page = doc[page_num]
    image_list = page.get_images(full=True)
    extracted_images = []
    
    for img_index, img in enumerate(image_list):
        xref = img[0]
        try:
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            
            # กรองรูปเล็กๆ (เช่น โลโก้จุด, เส้น, mask) ทิ้งไป
            im = Image.open(io.BytesIO(image_bytes))
            if im.width >= 150 and im.height >= 150: 
                extracted_images.append(image_bytes)
        except:
            pass
            
    return extracted_images

# --- 4. Sidebar: การตั้งค่า AI ---
with st.sidebar:
    st.markdown("## ⚙️ ตั้งค่าระบบอ่านอัจฉริยะ")
    api_key = st.text_input("🔑 ใส่ Gemini API Key:", type="password", value=st.session_state.user_api_key)
    if api_key != st.session_state.user_api_key:
        st.session_state.user_api_key = api_key
        st.rerun()
        
    if api_key:
        genai.configure(api_key=api_key)
        
    st.info("💡 **ทริค:** แอปนี้จะไม่อ่านล่วงหน้าทั้งหมด แต่จะประมวลผล 'เฉพาะหน้าที่คุณเปิดอ่าน' เพื่อความรวดเร็วและประหยัดโควต้า Token")
    
    st.markdown("### 🛠️ Prompt วิศวกรข้อมูล")
    system_prompt = st.text_area("Prompt จัดโครงสร้าง (แก้ไขได้):", height=350, value="""คุณคือผู้เชี่ยวชาญการจัดโครงสร้างข้อมูลการแพทย์ (Medical Information Architect)
หน้าที่ของคุณ: เปลี่ยนข้อความและเนื้อหาจากหน้าที่แนบมานี้ ให้อยู่ในรูปแบบที่อ่านง่ายที่สุด โดย **ห้ามตัดเนื้อหาสาระสำคัญทิ้งเด็ดขาด** และ **ต้องเรียงลำดับเนื้อหาตามต้นฉบับเดิมเป๊ะๆ**

กฎการจัดโครงสร้าง (Restructuring Rules):
1. ย่อหน้าไหนยาวเกินไป ให้แตกเป็น Bullet points หรือตาราง (Markdown Table) ให้สวยงามทันที
2. เน้นตัวหนา (**Keyword**) ที่คำสำคัญ อาการ ยา หรือเกณฑ์วินิจฉัย เพื่อช่วยให้กวาดสายตา (Skim) ได้ไว
3. หากในเอกสารมีตาราง ให้จำลองตารางนั้นออกมาเป็น Markdown ให้เหมือนต้นฉบับที่สุด
4. จุดไหนที่มีการอธิบายกลไก (Pathophysiology) หรือเหตุผลการรักษา ให้เชื่อมประโยคด้วยคำว่า '...เพราะ...' เสมอ 
5. รูปภาพประกอบ: หากมีรูปภาพหรือกราฟแทรกอยู่ในเอกสาร ให้พิมพ์คำว่า [IMAGE_PLACEHOLDER] ไว้ในตำแหน่งนั้นๆ เพื่อให้ระบบดึงรูปเดิมมาแทรกให้
6. ข้อมูลปริมาณ ตัวเลข ขนาดยา ต้องตรงตามต้นฉบับ 100% ห้ามย่อทิ้ง""")

# --- 5. Main UI: จัดการไฟล์ ---
st.title("📚 Textbook Smart Reader: ทุบกำแพงตัวหนังสือ")

if not st.session_state.pdf_bytes:
    st.markdown("อัปโหลดเอกสาร Textbook หรือ Paper (PDF) ที่ตัวหนังสือแน่นๆ ระบบจะจัดหน้าใหม่ให้อ่านง่ายขึ้น")
    uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์ PDF", type="pdf")
    if uploaded_file:
        st.session_state.pdf_bytes = uploaded_file.getvalue()
        st.session_state.pdf_name = uploaded_file.name
        st.rerun()
else:
    doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    
    st.caption(f"📄 กำลังอ่านไฟล์: **{st.session_state.pdf_name}** ({total_pages} หน้า)")
    
    # --- ระบบนำทาง Navigation ---
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.button("⬅️ หน้าก่อนหน้า", use_container_width=True) and st.session_state.page_idx > 0:
            st.session_state.page_idx -= 1
            st.rerun()
    with c2:
        new_page = st.slider("ไปที่หน้า:", 1, total_pages, st.session_state.page_idx + 1, label_visibility="collapsed")
        if new_page - 1 != st.session_state.page_idx:
            st.session_state.page_idx = new_page - 1
            st.rerun()
    with c3:
        if st.button("หน้าถัดไป ➡️", use_container_width=True) and st.session_state.page_idx < total_pages - 1:
            st.session_state.page_idx += 1
            st.rerun()

    st.write("---")
    
    curr = st.session_state.page_idx
    page_obj = doc[curr]
    
    # แบ่งหน้าจอ: ซ้าย (ต้นฉบับ) | ขวา (AI จัดเรียงใหม่)
    col_left, col_right = st.columns([1, 1.3])
    
    with col_left:
        st.markdown(f"### 📖 หน้า {curr+1} (ต้นฉบับ)")
        img_page = Image.open(io.BytesIO(page_obj.get_pixmap(dpi=100).tobytes("png")))
        st.image(img_page, use_container_width=True)

    with col_right:
        st.markdown(f"### ✨ เนื้อหาที่จัดโครงสร้างใหม่")
        
        # ถ้ายังไม่ได้ประมวลผลหน้านี้
        if curr not in st.session_state.processed_data:
            st.info("หน้านี้ยังไม่ได้จัดโครงสร้าง กดปุ่มด้านล่างเพื่อเริ่มอ่าน")
            if st.button("🤖 จัดโครงสร้างหน้านี้ (Restructure)", type="primary", use_container_width=True):
                if not st.session_state.user_api_key:
                    st.error("กรุณาใส่ API Key ที่เมนูด้านซ้ายก่อนครับ")
                else:
                    with st.spinner("กำลังอ่านและรื้อโครงสร้างเนื้อหา... (รอสักครู่)"):
                        # 1. ดึง Text ดิบ (กันข้อมูลตกหล่น)
                        raw_text = page_obj.get_text()
                        
                        # 2. ดึงรูปภาพย่อยออกมาเก็บไว้
                        extracted_imgs = extract_images_from_page(doc, curr)
                        
                        # 3. เตรียมส่งให้ Gemini (ภาพหน้ากระดาษ + Text ดิบ + Prompt)
                        model = genai.GenerativeModel(st.session_state.active_model)
                        safety = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE }
                        config = GenerationConfig(max_output_tokens=6000)
                        
                        prompt = system_prompt + f"\n\n--- ข้อมูล Text ดิบกันพลาด ---\n{raw_text}"
                        
                        try:
                            # โยนให้ Gemini อ่านทั้งหน้ากระดาษและข้อความดิบ
                            resp = model.generate_content([prompt, img_page], safety_settings=safety, generation_config=config)
                            
                            st.session_state.processed_data[curr] = {
                                "ai_text": resp.text,
                                "raw_text": raw_text,
                                "images": extracted_imgs
                            }
                            st.rerun()
                        except Exception as e:
                            st.error(f"เกิดข้อผิดพลาด: {e}")
        
        # ถ้าประมวลผลแล้ว
        else:
            data = st.session_state.processed_data[curr]
            ai_content = data["ai_text"]
            ext_images = data["images"]
            
            # --- ระบบแทรกรูปภาพ (Placeholder Replacement) ---
            st.markdown("<div class='reading-box'>", unsafe_allow_html=True)
            
            # แยกข้อความด้วย [IMAGE_PLACEHOLDER]
            parts = ai_content.split("[IMAGE_PLACEHOLDER]")
            
            for i, text_part in enumerate(parts):
                # แสดงข้อความ (Markdown)
                st.markdown(text_part, unsafe_allow_html=True)
                
                # ถ้ายังมีคั่น Placeholder อยู่ และเรามีไฟล์รูปเพียงพอ ให้โชว์รูป
                if i < len(parts) - 1:
                    if i < len(ext_images):
                        st.markdown("<br>", unsafe_allow_html=True) # เว้นบรรทัดก่อนวางรูป
                        st.image(ext_images[i], use_container_width=True, caption="รูปภาพจากต้นฉบับ")
                        st.markdown("<br>", unsafe_allow_html=True)
                    else:
                        st.info("🖼️ *มีรูปในต้นฉบับ แต่ระบบสกัดไฟล์รูปดิบออกมาไม่ได้ (สามารถดูเทียบจากหน้าต่างซ้ายมือได้ครับ)*")
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # เผื่อมีรูปเหลือที่ AI ไม่ได้วาง Placeholder ไว้
            remaining_images = ext_images[len(parts)-1:]
            if remaining_images:
                with st.expander("🖼️ รูปภาพประกอบเพิ่มเติมในหน้านี้"):
                    for r_img in remaining_images:
                        st.image(r_img, use_container_width=True)

            st.write("")
            with st.expander("🔍 ดูข้อความ Text ดิบ (สกัดจาก PDF)"):
                st.text(data["raw_text"])
                
            if st.button("🔄 สร้างโครงสร้างใหม่ (Regenerate)"):
                del st.session_state.processed_data[curr]
                st.rerun()
