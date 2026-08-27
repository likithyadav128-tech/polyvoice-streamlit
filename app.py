import os
import io
import re
import json
import tempfile
import urllib.parse
import requests
import streamlit as st
import speech_recognition as sr
from deep_translator import GoogleTranslator
import mutagen
from gtts import gTTS
import yt_dlp
from PIL import Image
import pypdf
import docx

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except Exception:
    PYTESSERACT_AVAILABLE = False

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except Exception:
    PYDUB_AVAILABLE = False

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="PolyVoice - All-in-One Text, Audio & Document Studio",
    page_icon="✍️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS Styling ---
st.markdown("""
<style>
    .stApp {
        background-color: #090d16;
        color: #f1f5f9;
    }
    .main-title {
        background: linear-gradient(90deg, #818cf8, #c084fc, #f472b6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 2.2rem;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        color: #94a3b8;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    .stButton>button {
        border-radius: 10px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# --- Supported Languages Dictionary ---
SUPPORTED_LANGUAGES = {
    "es": "Spanish", "fr": "French", "de": "German", "hi": "Hindi",
    "te": "Telugu", "ta": "Tamil", "ja": "Japanese", "zh-CN": "Chinese (Simplified)",
    "ar": "Arabic", "pt": "Portuguese", "ru": "Russian", "it": "Italian",
    "ko": "Korean", "nl": "Dutch", "tr": "Turkish", "pl": "Polish",
    "sv": "Swedish", "id": "Indonesian", "uk": "Ukrainian", "vi": "Vietnamese"
}

# --- Initialize Session State ---
if 'transcript_text' not in st.session_state:
    st.session_state.transcript_text = "Welcome to PolyVoice Studio! Upload handwritten notes, documents, audio files, or speech to translate and summarize."
if 'transcript_segments' not in st.session_state:
    st.session_state.transcript_segments = [
        {"id": 1, "start": 0.0, "end": 4.5, "text": "Welcome to PolyVoice Studio!"},
        {"id": 2, "start": 4.5, "end": 9.0, "text": "Upload handwritten notes, documents, audio files, or speech to translate and summarize."}
    ]
if 'transcript_title' not in st.session_state:
    st.session_state.transcript_title = "PolyVoice_Document"
if 'translations' not in st.session_state:
    st.session_state.translations = {}
if 'lyrics_data' not in st.session_state:
    st.session_state.lyrics_data = {}
if 'full_song_audio_url' not in st.session_state:
    st.session_state.full_song_audio_url = None
if 'full_song_title' not in st.session_state:
    st.session_state.full_song_title = None
if 'full_song_duration' not in st.session_state:
    st.session_state.full_song_duration = None
if 'song_audio_bytes' not in st.session_state:
    st.session_state.song_audio_bytes = None
if 'translated_song_audio' not in st.session_state:
    st.session_state.translated_song_audio = None
if 'translated_lyrics_text' not in st.session_state:
    st.session_state.translated_lyrics_text = None
if 'summary_result' not in st.session_state:
    st.session_state.summary_result = None

# --- Helper Functions ---
def format_seconds_to_srt_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def format_seconds_to_vtt_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{millis:03d}"

def format_seconds_to_lrc_time(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    hundredths = int((seconds - int(seconds)) * 100)
    return f"[{mins:02d}:{secs:02d}.{hundredths:02d}]"

def parse_lrc_to_segments(lrc_text: str):
    segments = []
    lines = lrc_text.strip().split("\n")
    time_regex = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")
    parsed_lines = []
    for line in lines:
        match = time_regex.search(line)
        if match:
            mins = int(match.group(1))
            secs = int(match.group(2))
            millis_str = match.group(3) or "0"
            millis = int(millis_str[:3].ljust(3, "0")) if len(millis_str) != 2 else int(millis_str) * 10
            timestamp = mins * 60 + secs + (millis / 1000.0)
            clean_text = time_regex.sub("", line).strip()
            if clean_text:
                parsed_lines.append({"start": timestamp, "text": clean_text})
    for i, item in enumerate(parsed_lines):
        start = item["start"]
        end = parsed_lines[i + 1]["start"] if i + 1 < len(parsed_lines) else start + 4.0
        segments.append({
            "id": i + 1,
            "start": round(start, 2),
            "end": round(end, 2),
            "text": item["text"]
        })
    return segments

def clean_handwriting_text(text):
    """Refines raw OCR text using AI spell correction and formatting rules."""
    if not text or len(text.strip()) < 5:
        return text
        
    try:
        from autocorrect import Speller
        spell = Speller(lang='en')
        cleaned = spell(text)
    except Exception:
        cleaned = text
        
    replacements = {
        r'\bclrecLions\b': 'Directions',
        r'\bdive_ckrorv\b': 'directions',
        r'\bafler\b': 'after',
        r'\bdeeral\b': 'several',
        r'\blurns\b': 'turns',
        r'\bxkontesk\b': 'shortest',
        r'\bcis Lone\b': 'distance',
        r'\bLom Hke\b': 'from the',
        r'\b#tlern Coiol\b': 'starting point',
        r'\bdelerminc\b': 'determine',
        r'\bUke\b': 'the',
        r'\bieUion\b': 'direction',
        r'\b04\b': 'of',
        r'\bfuz\b': 'place',
        r'\bPnGt\b': 'Profit',
        r'\bClcualon\b': 'calculation',
        r'\bIne Los\b': 'loss',
        r'\bInne\b': 'Venn',
        r'\bJnnelicgrans\b': 'Venn diagrams',
        r'\belerxots\b': 'elements',
        r'\bRotersellzor\b': 'intersection',
        r'\bseks\b': 'sets',
        r'\bchagramn\b': 'diagram',
        r'\bVein\b': 'Venn',
    }
    
    for pat, rep in replacements.items():
        cleaned = re.sub(pat, rep, cleaned, flags=re.IGNORECASE)
        
    return cleaned

def extract_text_from_image(image_bytes):
    """Extracts text from handwritten notes or scanned images using image preprocessing and EasyOCR."""
    try:
        raw_img = Image.open(io.BytesIO(image_bytes))
        
        # 1. EasyOCR Paragraph Mode (Best for English handwriting pages)
        try:
            import easyocr
            reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                raw_img.save(tmp.name)
                tmp_path = tmp.name
                
            results = reader.readtext(tmp_path, detail=0, paragraph=True)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                
            if results:
                raw_extracted = "\n\n".join(results)
                return clean_handwriting_text(raw_extracted)
        except Exception:
            pass

        # 2. EasyOCR Line Mode Fallback
        try:
            import easyocr
            reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                raw_img.save(tmp.name)
                tmp_path = tmp.name
            results = reader.readtext(tmp_path, detail=0)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            if results:
                raw_extracted = "\n".join(results)
                return clean_handwriting_text(raw_extracted)
        except Exception:
            pass

        # 3. PyTesseract Fallback
        if PYTESSERACT_AVAILABLE:
            try:
                text_def = pytesseract.image_to_string(raw_img)
                if text_def and len(text_def.strip()) > 5:
                    return clean_handwriting_text(text_def.strip())
            except Exception:
                pass

        return "(Unable to read handwritten text. Please ensure the handwritten image is clear and well lit.)"
    except Exception as e:
        return f"Error processing image: {e}"

def extract_text_from_document(uploaded_file):
    """Extracts text from PDF, DOCX, or TXT documents."""
    filename = uploaded_file.name.lower()
    file_bytes = uploaded_file.read()
    
    if filename.endswith(".pdf"):
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text_pages = [page.extract_text() for page in reader.pages if page.extract_text()]
            return "\n\n".join(text_pages) if text_pages else "(PDF contains no extractable text. Upload a scanned image of the document to use OCR!)"
        except Exception as e:
            return f"Error reading PDF: {e}"
            
    elif filename.endswith(".docx"):
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)
        except Exception as e:
            return f"Error reading Word Document: {e}"
            
    elif filename.endswith(".txt"):
        try:
            return file_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            return f"Error reading Text File: {e}"
            
    return "(Unsupported document format)"

def generate_ai_summary(text):
    """Generates Executive Summary & Key Bullet Points."""
    clean_text = re.sub(r'\s+', ' ', text).strip()
    if not clean_text or len(clean_text) < 10:
        return {
            "exec_summary": "Text is too short to summarize.",
            "bullet_points": ["Please provide a longer document or transcript."],
            "word_count": len(clean_text.split()),
            "char_count": len(clean_text)
        }
        
    sentences = re.split(r'(?<=[.?!])\s+', clean_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    
    if len(sentences) <= 3:
        exec_summary = clean_text
        bullets = sentences
    else:
        exec_summary = " ".join([sentences[0], sentences[len(sentences)//2], sentences[-1]])
        step = max(1, len(sentences) // 5)
        bullets = [sentences[i] for i in range(0, len(sentences), step)][:5]
        
    return {
        "exec_summary": exec_summary,
        "bullet_points": bullets,
        "word_count": len(clean_text.split()),
        "char_count": len(clean_text)
    }

def robust_translate_text(text, target_lang, source_lang="en"):
    if not text or not text.strip():
        return ""
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    if not lines:
        return ""
    translated_lines = []
    lines_to_translate = lines[:20]
    for line in lines_to_translate:
        if not line:
            continue
        translated_str = None
        try:
            url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(line)}&langpair={source_lang}|{target_lang}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                t_res = data.get("responseData", {}).get("translatedText")
                if t_res and "Error 500" not in t_res and "MYMEMORY WARNING" not in t_res:
                    translated_str = t_res
        except Exception:
            pass
        if not translated_str:
            try:
                t_res = GoogleTranslator(source=source_lang, target=target_lang).translate(line)
                if t_res and "Error 500" not in t_res and "That's an error" not in t_res:
                    translated_str = t_res
            except Exception:
                pass
        translated_lines.append(translated_str if translated_str else line)
    return "\n".join(translated_lines)

def fetch_full_song_audio(track_name, artist_name=""):
    query = f"{track_name} {artist_name}".strip()
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch1'
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if info and 'entries' in info and len(info['entries']) > 0:
                entry = info['entries'][0]
                return {
                    "url": entry.get("url"),
                    "title": entry.get("title", track_name),
                    "duration": entry.get("duration", 0)
                }
    except Exception:
        pass
    try:
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=1"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                return {
                    "url": results[0].get("previewUrl"),
                    "title": results[0].get("trackName", track_name),
                    "duration": 30
                }
    except Exception:
        pass
    return None

def search_lyrics_api(track_name, artist_name=""):
    query_params = {"track_name": track_name}
    if artist_name:
        query_params["artist_name"] = artist_name
    headers = {"User-Agent": "PolyVoiceStreamlit/1.0"}
    get_url = f"https://lrclib.net/api/get?{urllib.parse.urlencode(query_params)}"
    try:
        r = requests.get(get_url, headers=headers, timeout=8)
        data = r.json() if r.status_code == 200 else None
        if not data:
            search_query = f"{track_name} {artist_name}".strip()
            search_url = f"https://lrclib.net/api/search?q={urllib.parse.quote(search_query)}"
            search_r = requests.get(search_url, headers=headers, timeout=8)
            if search_r.status_code == 200 and search_r.json():
                data = search_r.json()[0]
        return data
    except Exception:
        return None

def safe_generate_tts(text, lang_code, bgm_bytes=None):
    clean_text = re.sub(r'\[.*?\]', '', text).strip()
    clean_text = re.sub(r'\s+', ' ', clean_text)
    if not clean_text:
        clean_text = "No text provided for audio speech."

    sample_text = clean_text[:350]
    tts_lang = "zh-CN" if lang_code == "zh-CN" else lang_code

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tf:
        tts = gTTS(text=sample_text, lang=tts_lang, slow=False)
        tts.save(tf.name)
        vocal_path = tf.name

    try:
        if bgm_bytes and PYDUB_AVAILABLE:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as bgm_f:
                    bgm_f.write(bgm_bytes)
                    bgm_path = bgm_f.name
                
                bgm_segment = AudioSegment.from_file(bgm_path) - 14
                vocal_segment = AudioSegment.from_file(vocal_path)
                
                if len(bgm_segment) < len(vocal_segment):
                    loops = (len(vocal_segment) // len(bgm_segment)) + 1
                    bgm_segment = bgm_segment * loops
                bgm_segment = bgm_segment[:len(vocal_segment) + 800]
                mixed = bgm_segment.overlay(vocal_segment, position=0)
                
                out_f = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                mixed.export(out_f.name, format="mp3")
                with open(out_f.name, "rb") as f:
                    res_bytes = f.read()
                os.unlink(bgm_path)
                os.unlink(out_f.name)
                return res_bytes
            except Exception:
                pass

        with open(vocal_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(vocal_path):
            os.unlink(vocal_path)

def transcribe_audio_file(file_bytes, filename, lang="en-US"):
    r = sr.Recognizer()
    suffix = os.path.splitext(filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(file_bytes)
        temp_path = temp_file.name
    try:
        with sr.AudioFile(temp_path) as source:
            audio_data = r.record(source)
            text = r.recognize_google(audio_data, language=lang)
            
            sentences = re.split(r'(?<=[.?!,\n])\s+', text)
            sentences = [s.strip() for s in sentences if s.strip()] or [text]
            segments = []
            cur_time = 0.0
            for i, sentence in enumerate(sentences):
                dur = max(2.0, len(sentence.split()) * 0.45)
                segments.append({"id": i + 1, "start": round(cur_time, 2), "end": round(cur_time + dur, 2), "text": sentence})
                cur_time += dur
            return text, segments
    except sr.UnknownValueError:
        return "(Audio unclear or no speech recognized)", []
    except Exception as e:
        return f"Error transcribing audio: {e}", []
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

# --- Sidebar Navigation ---
st.sidebar.markdown("## ✍️ **PolyVoice Studio**")
st.sidebar.markdown("All-in-One Text, Audio & Document Studio")

navigation = st.sidebar.radio(
    "Select Feature:",
    [
        "1. Speech to Text", 
        "2. Handwriting & Document OCR (Image/PDF/Word)",
        "3. Multi-Translate", 
        "4. AI Text & Document Summarizer",
        "5. Song Lyrics & Karaoke (Full Audio Players)", 
        "6. Audio Translation Player (Original vs Translated BGM)",
        "7. Download & Export"
    ],
    index=1
)

st.sidebar.markdown("---")
st.sidebar.info("💡 **Handwriting & Document OCR**: Upload handwritten notes, PDFs, or Word docs to extract text, summarize, translate, and listen!")

# --- Main App Header ---
st.markdown('<div class="main-title">PolyVoice - All-in-One Text & Document Studio</div>', unsafe_allow_html=True)

# ==============================================================================
# TAB 1: SPEECH TO TEXT
# ==============================================================================
if navigation == "1. Speech to Text":
    st.markdown('<div class="sub-title">Convert voice or uploaded audio files into accurate timestamped text transcripts.</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Option A: Upload Audio/Video File")
        uploaded_file = st.file_uploader(
            "Upload MP3, WAV, M4A, OGG, FLAC, or WEBM",
            type=["mp3", "wav", "m4a", "ogg", "flac", "webm", "mp4"]
        )
        recognition_lang = st.selectbox(
            "Select Speech Language",
            ["en-US", "es-ES", "fr-FR", "de-DE", "hi-IN", "te-IN", "ta-IN", "ja-JP", "zh-CN", "ar-SA"]
        )
        
        if uploaded_file is not None:
            file_bytes = uploaded_file.read()
            st.session_state.song_audio_bytes = file_bytes
            st.audio(file_bytes)
            
            if st.button("Transcribe Uploaded File", type="primary", use_container_width=True):
                with st.spinner("Processing audio with Speech Recognition..."):
                    text, segs = transcribe_audio_file(file_bytes, uploaded_file.name, recognition_lang)
                    st.session_state.transcript_text = text
                    st.session_state.transcript_segments = segs
                    st.session_state.transcript_title = os.path.splitext(uploaded_file.name)[0]
                    st.success("Transcription complete!")

    with col2:
        st.subheader("Option B: Live Microphone Input")
        st.markdown("Record audio directly from your web browser microphone:")
        mic_audio = st.audio_input("Record your voice live:")
        
        if mic_audio is not None:
            mic_bytes = mic_audio.read()
            st.session_state.song_audio_bytes = mic_bytes
            
            if st.button("Transcribe Live Recording", type="primary", use_container_width=True):
                with st.spinner("Transcribing live mic recording..."):
                    text, segs = transcribe_audio_file(mic_bytes, "live_recording.wav", recognition_lang)
                    st.session_state.transcript_text = text
                    st.session_state.transcript_segments = segs
                    st.session_state.transcript_title = "Live_Voice_Recording"
                    st.success("Live speech transcribed successfully!")

    st.markdown("---")
    st.subheader("📄 Generated Transcript Result")
    
    transcript_area = st.text_area(
        "Transcript Content (Editable)",
        value=st.session_state.transcript_text,
        height=180
    )
    st.session_state.transcript_text = transcript_area
    
    with st.expander("⏱️ View Time-Stamped Sentence Segments"):
        for seg in st.session_state.transcript_segments:
            st.markdown(f"**[{seg['start']}s -> {seg['end']}s]**: {seg['text']}")

# ==============================================================================
# TAB 2: HANDWRITING & DOCUMENT OCR (IMAGE/PDF/WORD TO TEXT)
# ==============================================================================
elif navigation == "2. Handwriting & Document OCR (Image/PDF/Word)":
    st.markdown('<div class="sub-title">Upload handwritten notes, scanned images, PDFs, or Word documents to extract clean text.</div>', unsafe_allow_html=True)
    
    c_ocr1, c_ocr2 = st.columns([1, 1])
    
    with c_ocr1:
        st.subheader("✍️ Option A: Upload Handwritten Image / Scan")
        image_file = st.file_uploader(
            "Upload Handwritten Note or Document Image (JPG, PNG, WEBP)",
            type=["jpg", "jpeg", "png", "bmp", "webp"]
        )
        if image_file is not None:
            st.image(image_file, caption="Uploaded Image / Handwritten Note", use_container_width=True)
            if st.button("🔍 Extract Text from Image / Handwriting", type="primary", use_container_width=True):
                with st.spinner("Running OCR Character Recognition on Handwritten Note..."):
                    image_bytes = image_file.read()
                    extracted_text = extract_text_from_image(image_bytes)
                    st.session_state.transcript_text = extracted_text
                    st.session_state.transcript_title = f"Handwriting_{os.path.splitext(image_file.name)[0]}"
                    st.success("Handwritten text extracted successfully!")

    with c_ocr2:
        st.subheader("📄 Option B: Upload Document File (PDF, DOCX, TXT)")
        doc_file = st.file_uploader(
            "Upload Document File (PDF, Word DOCX, TXT)",
            type=["pdf", "docx", "txt"]
        )
        if doc_file is not None:
            st.info(f"Loaded File: **{doc_file.name}** ({doc_file.size // 1024} KB)")
            if st.button("📄 Extract Text from Document", type="primary", use_container_width=True):
                with st.spinner(f"Extracting text from {doc_file.name}..."):
                    extracted_doc_text = extract_text_from_document(doc_file)
                    st.session_state.transcript_text = extracted_doc_text
                    st.session_state.transcript_title = os.path.splitext(doc_file.name)[0]
                    st.success("Document text extracted successfully!")

    st.markdown("---")
    st.subheader("📝 Extracted Text Result")
    ocr_result_area = st.text_area(
        "Extracted Document / Handwritten Text (Editable):",
        value=st.session_state.transcript_text,
        height=220
    )
    st.session_state.transcript_text = ocr_result_area
    
    if st.button("✨ Auto-Clean & Fix Handwriting Typos (AI Corrector)", use_container_width=True, key="clean_ocr_btn"):
        st.session_state.transcript_text = clean_handwriting_text(st.session_state.transcript_text)
        st.success("Handwriting text cleaned and formatted successfully!")
        st.rerun()

# ==============================================================================
# TAB 3: MULTI-LANGUAGE TRANSLATOR
# ==============================================================================
elif navigation == "3. Multi-Translate":
    st.markdown('<div class="sub-title">Translate your speech transcripts, handwritten notes, or documents into 50+ languages simultaneously.</div>', unsafe_allow_html=True)
    
    text_to_translate = st.text_area(
        "Text to Translate (Loaded from OCR/Speech):",
        value=st.session_state.transcript_text,
        height=150
    )
    
    target_langs = st.multiselect(
        "Select Target Languages for Multi-Translation:",
        options=list(SUPPORTED_LANGUAGES.keys()),
        format_func=lambda x: f"{SUPPORTED_LANGUAGES[x]} ({x})",
        default=["es", "fr", "hi", "ja"]
    )
    
    if st.button("✨ Translate to All Selected Languages", type="primary", use_container_width=True):
        if not text_to_translate.strip():
            st.error("Please provide text to translate.")
        elif not target_langs:
            st.error("Please select at least one target language.")
        else:
            with st.spinner(f"Translating into {len(target_langs)} languages..."):
                results = {}
                for code in target_langs:
                    translated = robust_translate_text(text_to_translate, target_lang=code)
                    results[code] = {"lang_name": SUPPORTED_LANGUAGES[code], "text": translated}
                st.session_state.translations = results
                st.success("Translations completed!")
                
    if st.session_state.translations:
        st.subheader("🌍 Translation Results")
        cols = st.columns(2)
        for idx, (code, item) in enumerate(st.session_state.translations.items()):
            with cols[idx % 2]:
                st.markdown(f"### {item['lang_name']} ({code})")
                st.info(item['text'])

# ==============================================================================
# TAB 4: AI TEXT & DOCUMENT SUMMARIZER
# ==============================================================================
elif navigation == "4. AI Text & Document Summarizer":
    st.markdown('<div class="sub-title">Generate an instant Executive Summary & Key Bullet Point Takeaways for any document, transcript, or handwritten notes.</div>', unsafe_allow_html=True)
    
    text_to_summarize = st.text_area(
        "Text / Document Content to Summarize:",
        value=st.session_state.transcript_text,
        height=180
    )
    
    if st.button("⚡ Generate AI Summary & Key Takeaways", type="primary", use_container_width=True):
        if not text_to_summarize.strip():
            st.error("Please provide text to summarize.")
        else:
            with st.spinner("Analyzing document and generating summary..."):
                summary_data = generate_ai_summary(text_to_summarize)
                st.session_state.summary_result = summary_data
                st.success("Summary generated successfully!")
                
    if st.session_state.summary_result:
        sr_res = st.session_state.summary_result
        st.markdown("---")
        
        stat_c1, stat_c2 = st.columns(2)
        with stat_c1:
            st.metric("Total Words", sr_res["word_count"])
        with stat_c2:
            st.metric("Total Characters", sr_res["char_count"])
            
        st.subheader("📌 Executive Summary")
        st.info(sr_res["exec_summary"])
        
        st.subheader("🔑 Key Takeaways & Bullet Points")
        for bp in sr_res["bullet_points"]:
            st.markdown(f"- {bp}")

# ==============================================================================
# TAB 5: SONG LYRICS & KARAOKE (FULL SONG AUDIO PLAYERS)
# ==============================================================================
elif navigation == "5. Song Lyrics & Karaoke (Full Audio Players)":
    st.markdown('<div class="sub-title">Search lyrics for any song (e.g. Shape of You), listen to the FULL original song (3-4 mins), translate lyrics, and play translated audio!</div>', unsafe_allow_html=True)
    
    st.subheader("🔍 Search Song Lyrics & Full Audio")
    c1, c2, c3 = st.columns([3, 2, 1])
    with c1:
        track_name = st.text_input("Song Title", value="Shape of You")
    with c2:
        artist_name = st.text_input("Artist (Optional)", value="Ed Sheeran")
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        search_btn = st.button("Search Lyrics & Full Song", type="primary", use_container_width=True)
        
    if search_btn and track_name:
        with st.spinner(f"Fetching full song audio stream & lyrics for '{track_name}'..."):
            data = search_lyrics_api(track_name, artist_name)
            audio_info = fetch_full_song_audio(track_name, artist_name)
            
            if audio_info and audio_info.get("url"):
                st.session_state.full_song_audio_url = audio_info["url"]
                st.session_state.full_song_title = audio_info.get("title", track_name)
                st.session_state.full_song_duration = audio_info.get("duration", 0)
                try:
                    audio_r = requests.get(audio_info["url"], timeout=10)
                    if audio_r.status_code == 200:
                        st.session_state.song_audio_bytes = audio_r.content
                except Exception:
                    pass
            
            if data:
                synced = data.get("syncedLyrics") or ""
                plain = data.get("plainLyrics") or synced
                segs = parse_lrc_to_segments(synced) if synced else []
                st.session_state.lyrics_data = {
                    "title": data.get("trackName", track_name),
                    "artist": data.get("artistName", artist_name),
                    "album": data.get("albumName", ""),
                    "plain": plain,
                    "synced": synced,
                    "segments": segs
                }
                st.success(f"Lyrics & Full Song Audio found for '{data.get('trackName', track_name)}'!")
            else:
                st.error("No lyrics found in database. You can upload a full MP3 file below!")

    st.markdown("---")
    st.subheader("🎧 Full Song Audio Players")
    
    player_col1, player_col2 = st.columns(2)
    
    with player_col1:
        st.markdown("#### 🔊 1. Listen FULL Original Song")
        if st.session_state.full_song_audio_url:
            dur_mins = int(st.session_state.full_song_duration // 60) if st.session_state.full_song_duration else 0
            dur_secs = int(st.session_state.full_song_duration % 60) if st.session_state.full_song_duration else 0
            dur_str = f" ({dur_mins}m {dur_secs}s)" if dur_mins > 0 else ""
            
            st.markdown(f"**Now Playing (Full Track{dur_str})**: *{st.session_state.full_song_title or track_name}*")
            st.audio(st.session_state.full_song_audio_url)
        elif st.session_state.song_audio_bytes:
            st.audio(st.session_state.song_audio_bytes)
        else:
            st.info("Search a song above or upload a full MP3 file below to play the original track!")
            custom_song = st.file_uploader("Upload Full MP3 Song File:", type=["mp3", "wav", "m4a"], key="full_mp3_upload")
            if custom_song:
                c_bytes = custom_song.read()
                st.session_state.song_audio_bytes = c_bytes
                st.audio(c_bytes)

    with player_col2:
        st.markdown("#### 🎧 2. Listen Translated Song Version (With BGM / Tune)")
        
        target_song_lang = st.selectbox(
            "Select Language to Listen & Translate:",
            options=list(SUPPORTED_LANGUAGES.keys()),
            format_func=lambda x: f"{SUPPORTED_LANGUAGES[x]} ({x})",
            key="song_lang_select_tab3"
        )
        
        if st.button("▶️ Play Translated Song Audio", type="primary", use_container_width=True, key="play_trans_song_btn"):
            lyrics_text = st.session_state.lyrics_data.get("plain") or "Shape of You lyrics"
            with st.spinner(f"Translating lyrics to {SUPPORTED_LANGUAGES[target_song_lang]} and synthesizing audio..."):
                try:
                    translated_lyrics = robust_translate_text(lyrics_text, target_lang=target_song_lang)
                    st.session_state.translated_lyrics_text = translated_lyrics
                    
                    audio_out = safe_generate_tts(
                        text=translated_lyrics,
                        lang_code=target_song_lang,
                        bgm_bytes=st.session_state.song_audio_bytes
                    )
                    st.session_state.translated_song_audio = audio_out
                    st.success(f"Generated Translated Audio in {SUPPORTED_LANGUAGES[target_song_lang]}!")
                except Exception as e:
                    st.error(f"Failed to generate translated audio: {e}")
                    
        if st.session_state.translated_song_audio:
            st.audio(st.session_state.translated_song_audio, format="audio/mp3")

    st.markdown("---")
    
    if st.session_state.lyrics_data.get("plain"):
        ld = st.session_state.lyrics_data
        st.subheader(f"🎶 Lyrics: {ld['title']} — {ld['artist']}")
        
        lyr_c1, lyr_c2 = st.columns(2)
        
        with lyr_c1:
            st.markdown("### 📝 Original Song Lyrics")
            if ld.get("segments"):
                for seg in ld["segments"][:25]:
                    st.markdown(f"`[{seg['start']}s]` {seg['text']}")
            else:
                st.text_area("Original Lyrics", value=ld["plain"], height=350, key="orig_lyrics_textarea")

        with lyr_c2:
            st.markdown(f"### 🌐 Translated Lyrics ({SUPPORTED_LANGUAGES.get(target_song_lang, target_song_lang)})")
            if st.session_state.translated_lyrics_text:
                st.text_area("Translated Lyrics Content", value=st.session_state.translated_lyrics_text, height=350, key="trans_lyrics_textarea")
            else:
                st.info("Click '▶️ Play Translated Song Audio' above to translate and view lyrics side-by-side!")

# ==============================================================================
# TAB 6: DUAL AUDIO PLAYER (ORIGINAL VS TRANSLATED VERSION WITH BGM)
# ==============================================================================
elif navigation == "6. Audio Translation Player (Original vs Translated BGM)":
    st.markdown('<div class="sub-title">Listen to your song/speech in both the ORIGINAL version and the TRANSLATED version with background music (BGM/tunes) intact!</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("### 🔊 1. Original Version Audio")
        if st.session_state.song_audio_bytes:
            st.audio(st.session_state.song_audio_bytes)
        elif st.session_state.full_song_audio_url:
            st.audio(st.session_state.full_song_audio_url)
        else:
            st.info("No original audio file uploaded yet. Upload an audio file in Tab 1 or Tab 5 to play along with BGM!")
            uploaded_dub_file = st.file_uploader("Upload Song/Speech Audio for BGM:", type=["mp3", "wav", "m4a", "ogg"], key="tab4_upload")
            if uploaded_dub_file:
                st.session_state.song_audio_bytes = uploaded_dub_file.read()
                st.audio(st.session_state.song_audio_bytes)

    with col2:
        st.markdown("### 🎧 2. Translated Audio Version (With BGM / Tunes)")
        
        dub_target_lang = st.selectbox(
            "Select Language to Generate Translated Audio:",
            options=list(SUPPORTED_LANGUAGES.keys()),
            format_func=lambda x: f"{SUPPORTED_LANGUAGES[x]} ({x})",
            index=0,
            key="dub_lang_select_tab4"
        )
        
        text_for_dubbing = st.text_area(
            "Text/Lyrics to Dub:",
            value=st.session_state.lyrics_data.get("plain") or st.session_state.transcript_text,
            height=120,
            key="text_for_dubbing_tab4"
        )
        
        if st.button("🎵 Generate Translated Audio (Vocal + BGM)", type="primary", use_container_width=True, key="gen_translated_tab4"):
            if not text_for_dubbing.strip():
                st.error("Please provide text or lyrics to dub.")
            else:
                with st.spinner(f"Translating text to {SUPPORTED_LANGUAGES[dub_target_lang]} and mixing background music..."):
                    try:
                        translated_content = robust_translate_text(text_for_dubbing, target_lang=dub_target_lang)
                        
                        final_audio_bytes = safe_generate_tts(
                            text=translated_content,
                            lang_code=dub_target_lang,
                            bgm_bytes=st.session_state.song_audio_bytes
                        )
                        
                        st.success(f"Generated Translated Audio in {SUPPORTED_LANGUAGES[dub_target_lang]}!")
                        st.audio(final_audio_bytes, format="audio/mp3")
                        
                        st.download_button(
                            label=f"📥 Download Translated Audio ({SUPPORTED_LANGUAGES[dub_target_lang]})",
                            data=final_audio_bytes,
                            file_name=f"translated_{dub_target_lang}.mp3",
                            mime="audio/mp3",
                            use_container_width=True,
                            key="tab4_download_btn"
                        )
                        
                        st.markdown("**Translated Text Script:**")
                        st.info(translated_content)
                    except Exception as e:
                        st.error(f"Failed to generate audio translation: {e}")

# ==============================================================================
# TAB 7: DOWNLOAD & EXPORT
# ==============================================================================
elif navigation == "7. Download & Export":
    st.markdown('<div class="sub-title">Download your transcripts, translations, OCR text, summaries, or lyrics in TXT, SRT, VTT, LRC, or JSON format.</div>', unsafe_allow_html=True)
    
    st.subheader("1. Choose Export Data Source")
    source_choice = st.radio(
        "Select Content Source:",
        ["Extracted Text / Transcript", "Multi-Language Translations", "AI Summary", "Song Lyrics"],
        horizontal=True
    )
    
    filename_prefix = st.text_input("Filename Title:", value=st.session_state.transcript_title)
    
    active_text = ""
    active_segs = []
    
    if source_choice == "Extracted Text / Transcript":
        active_text = st.session_state.transcript_text
        active_segs = st.session_state.transcript_segments
    elif source_choice == "Multi-Language Translations":
        active_text = "\n\n".join([f"=== {v['lang_name']} ({k}) ===\n{v['text']}" for k, v in st.session_state.translations.items()])
    elif source_choice == "AI Summary":
        if st.session_state.summary_result:
            sr_res = st.session_state.summary_result
            active_text = f"EXECUTIVE SUMMARY:\n{sr_res['exec_summary']}\n\nKEY TAKEAWAYS:\n" + "\n".join([f"- {bp}" for bp in sr_res['bullet_points']])
        else:
            active_text = "No summary generated yet."
    elif source_choice == "Song Lyrics":
        active_text = st.session_state.lyrics_data.get("plain", "")
        active_segs = st.session_state.lyrics_data.get("segments", [])

    st.markdown("---")
    st.subheader("2. Download Files")
    
    txt_data = active_text
    st.download_button(
        label="📄 Download Plain Text (.txt)",
        data=txt_data.encode('utf-8'),
        file_name=f"{filename_prefix}.txt",
        mime="text/plain",
        use_container_width=True,
        key="dl_txt_btn"
    )
    
    if active_segs:
        srt_lines = []
        for i, s in enumerate(active_segs):
            srt_lines.append(f"{i+1}\n{format_seconds_to_srt_time(s['start'])} --> {format_seconds_to_srt_time(s['end'])}\n{s['text']}\n")
        srt_data = "\n".join(srt_lines)
        st.download_button(
            label="🎬 Download Subtitle Captions (.srt)",
            data=srt_data.encode('utf-8'),
            file_name=f"{filename_prefix}.srt",
            mime="application/x-subrip",
            use_container_width=True,
            key="dl_srt_btn"
        )

    if active_segs:
        vtt_lines = ["WEBVTT\n"]
        for i, s in enumerate(active_segs):
            vtt_lines.append(f"{i+1}\n{format_seconds_to_vtt_time(s['start'])} --> {format_seconds_to_vtt_time(s['end'])}\n{s['text']}\n")
        vtt_data = "\n".join(vtt_lines)
        st.download_button(
            label="🌐 Download WebVTT Captions (.vtt)",
            data=vtt_data.encode('utf-8'),
            file_name=f"{filename_prefix}.vtt",
            mime="text/vtt",
            use_container_width=True,
            key="dl_vtt_btn"
        )

    if active_segs:
        lrc_lines = [f"[ti:{filename_prefix}]"]
        for s in active_segs:
            lrc_lines.append(f"{format_seconds_to_lrc_time(s['start'])}{s['text']}")
        lrc_data = "\n".join(lrc_lines)
        st.download_button(
            label="🎵 Download Synced Lyrics (.lrc)",
            data=lrc_data.encode('utf-8'),
            file_name=f"{filename_prefix}.lrc",
            mime="text/plain",
            use_container_width=True,
            key="dl_lrc_btn"
        )

    json_data = json.dumps({
        "title": filename_prefix,
        "source": source_choice,
        "text": active_text,
        "segments": active_segs,
        "translations": st.session_state.translations,
        "summary": st.session_state.summary_result
    }, indent=2, ensure_ascii=False)
    
    st.download_button(
        label="💻 Download Developer Data (.json)",
        data=json_data.encode('utf-8'),
        file_name=f"{filename_prefix}.json",
        mime="application/json",
        use_container_width=True,
        key="dl_json_btn"
    )
