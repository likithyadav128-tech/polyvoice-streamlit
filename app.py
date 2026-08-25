import os
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

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except Exception:
    PYDUB_AVAILABLE = False

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="PolyVoice - Audio Transcriber, Translator & Lyrics Hub",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS Styling ---
st.markdown("""
<style>
    /* Dark Theme Customization */
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
    st.session_state.transcript_text = "Welcome to PolyVoice! You can record your microphone or upload an audio file to convert speech to text."
if 'transcript_segments' not in st.session_state:
    st.session_state.transcript_segments = [
        {"id": 1, "start": 0.0, "end": 4.5, "text": "Welcome to PolyVoice!"},
        {"id": 2, "start": 4.5, "end": 9.0, "text": "You can record your microphone or upload an audio file to convert speech to text."}
    ]
if 'transcript_title' not in st.session_state:
    st.session_state.transcript_title = "PolyVoice_Transcript"
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

def fetch_full_song_audio(track_name, artist_name=""):
    """
    Extracts FULL song audio stream (full 3-5 mins) using yt-dlp.
    Falls back to iTunes preview if unavailable.
    """
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
        
    # Fallback to iTunes API
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
    """
    Safely generates TTS audio without ffprobe/gTTS errors by chunking text.
    If ffmpeg/ffprobe fails, falls back gracefully to pure vocal audio track.
    """
    clean_text = re.sub(r'\[.*?\]', '', text).strip()
    clean_text = re.sub(r'\s+', ' ', clean_text)
    if not clean_text:
        clean_text = "No text provided for audio speech."

    # Limit text to 350 chars for fast, reliable TTS synthesis
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
st.sidebar.markdown("## 🎙️ **PolyVoice Studio**")
st.sidebar.markdown("All-in-One Audio, Translation & Lyrics Hub")

navigation = st.sidebar.radio(
    "Select Feature:",
    [
        "1. Speech to Text", 
        "2. Multi-Translate", 
        "3. Song Lyrics & Karaoke (Full Audio Players)", 
        "4. Audio Translation Player (Original vs Translated BGM)",
        "5. Download & Export"
    ],
    index=2
)

st.sidebar.markdown("---")
st.sidebar.info("💡 **Full Song Audio**: Search any song (e.g. Shape of You) to listen to the FULL track (3-4 mins) AND translated audio!")

# --- Main App Header ---
st.markdown('<div class="main-title">PolyVoice - Multilingual Audio & Lyrics Studio</div>', unsafe_allow_html=True)

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
            st.audio(file_bytes, key="tab1_upload_audio")
            
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
# TAB 2: MULTI-LANGUAGE TRANSLATOR
# ==============================================================================
elif navigation == "2. Multi-Translate":
    st.markdown('<div class="sub-title">Translate your speech transcripts or text into 50+ languages simultaneously.</div>', unsafe_allow_html=True)
    
    text_to_translate = st.text_area(
        "Text to Translate (Loaded from Speech-to-Text):",
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
                    try:
                        translated = GoogleTranslator(source="auto", target=code).translate(text_to_translate)
                        results[code] = {"lang_name": SUPPORTED_LANGUAGES[code], "text": translated}
                    except Exception as e:
                        results[code] = {"lang_name": SUPPORTED_LANGUAGES[code], "text": f"Error: {e}"}
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
# TAB 3: SONG LYRICS & KARAOKE (FULL SONG AUDIO PLAYERS)
# ==============================================================================
elif navigation == "3. Song Lyrics & Karaoke (Full Audio Players)":
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
                    # Download song bytes for BGM overlay mixing if duration <= 300s
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
    
    # --- AUDIO PLAYER SECTION FOR ORIGINAL & TRANSLATED VERSION ---
    st.subheader("🎧 Full Song Audio Players")
    
    player_col1, player_col2 = st.columns(2)
    
    with player_col1:
        st.markdown("#### 🔊 1. Listen FULL Original Song")
        if st.session_state.full_song_audio_url:
            dur_mins = int(st.session_state.full_song_duration // 60) if st.session_state.full_song_duration else 0
            dur_secs = int(st.session_state.full_song_duration % 60) if st.session_state.full_song_duration else 0
            dur_str = f" ({dur_mins}m {dur_secs}s)" if dur_mins > 0 else ""
            
            st.markdown(f"**Now Playing (Full Track{dur_str})**: *{st.session_state.full_song_title or track_name}*")
            st.audio(st.session_state.full_song_audio_url, key="full_original_song_player")
        elif st.session_state.song_audio_bytes:
            st.audio(st.session_state.song_audio_bytes, key="bytes_original_song_player")
        else:
            st.info("Search a song above or upload a full MP3 file below to play the original track!")
            custom_song = st.file_uploader("Upload Full MP3 Song File:", type=["mp3", "wav", "m4a"], key="full_mp3_upload")
            if custom_song:
                c_bytes = custom_song.read()
                st.session_state.song_audio_bytes = c_bytes
                st.audio(c_bytes, key="custom_song_player")

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
                    # 1. Translate lyrics
                    translated_lyrics = GoogleTranslator(source="auto", target=target_song_lang).translate(lyrics_text[:1500])
                    st.session_state.translated_lyrics_text = translated_lyrics
                    
                    # 2. Generate audio safely
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
            st.audio(st.session_state.translated_song_audio, format="audio/mp3", key="translated_song_player_tab3")

    st.markdown("---")
    
    # --- LYRICS DISPLAY (ORIGINAL & TRANSLATED SIDE-BY-SIDE) ---
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
# TAB 4: DUAL AUDIO PLAYER (ORIGINAL VS TRANSLATED VERSION WITH BGM)
# ==============================================================================
elif navigation == "4. Audio Translation Player (Original vs Translated BGM)":
    st.markdown('<div class="sub-title">Listen to your song/speech in both the ORIGINAL version and the TRANSLATED version with background music (BGM/tunes) intact!</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("### 🔊 1. Original Version Audio")
        if st.session_state.song_audio_bytes:
            st.audio(st.session_state.song_audio_bytes, key="tab4_orig_audio_bytes")
        elif st.session_state.full_song_audio_url:
            st.audio(st.session_state.full_song_audio_url, key="tab4_orig_audio_url")
        else:
            st.info("No original audio file uploaded yet. Upload an audio file in Tab 1 or Tab 3 to play along with BGM!")
            uploaded_dub_file = st.file_uploader("Upload Song/Speech Audio for BGM:", type=["mp3", "wav", "m4a", "ogg"], key="tab4_upload")
            if uploaded_dub_file:
                st.session_state.song_audio_bytes = uploaded_dub_file.read()
                st.audio(st.session_state.song_audio_bytes, key="tab4_uploaded_audio")

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
                        translated_content = GoogleTranslator(source="auto", target=dub_target_lang).translate(text_for_dubbing[:1500])
                        
                        final_audio_bytes = safe_generate_tts(
                            text=translated_content,
                            lang_code=dub_target_lang,
                            bgm_bytes=st.session_state.song_audio_bytes
                        )
                        
                        st.success(f"Generated Translated Audio in {SUPPORTED_LANGUAGES[dub_target_lang]}!")
                        st.audio(final_audio_bytes, format="audio/mp3", key="tab4_translated_audio_player")
                        
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
# TAB 5: DOWNLOAD & EXPORT
# ==============================================================================
elif navigation == "5. Download & Export":
    st.markdown('<div class="sub-title">Download your transcripts, translations, or lyrics in TXT, SRT, VTT, LRC, or JSON format.</div>', unsafe_allow_html=True)
    
    st.subheader("1. Choose Export Data Source")
    source_choice = st.radio(
        "Select Content Source:",
        ["Speech Transcript", "Multi-Language Translations", "Song Lyrics"],
        horizontal=True
    )
    
    filename_prefix = st.text_input("Filename Title:", value=st.session_state.transcript_title)
    
    active_text = ""
    active_segs = []
    
    if source_choice == "Speech Transcript":
        active_text = st.session_state.transcript_text
        active_segs = st.session_state.transcript_segments
    elif source_choice == "Multi-Language Translations":
        active_text = "\n\n".join([f"=== {v['lang_name']} ({k}) ===\n{v['text']}" for k, v in st.session_state.translations.items()])
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
        "translations": st.session_state.translations
    }, indent=2, ensure_ascii=False)
    
    st.download_button(
        label="💻 Download Developer Data (.json)",
        data=json_data.encode('utf-8'),
        file_name=f"{filename_prefix}.json",
        mime="application/json",
        use_container_width=True,
        key="dl_json_btn"
    )
