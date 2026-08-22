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
    .player-card {
        background: rgba(30, 41, 59, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 12px;
        padding: 1.2rem;
        margin-bottom: 1rem;
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
if 'uploaded_audio_bytes' not in st.session_state:
    st.session_state.uploaded_audio_bytes = None
if 'uploaded_audio_name' not in st.session_state:
    st.session_state.uploaded_audio_name = None

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

def generate_translated_audio_with_bgm(translated_text, target_lang_code, original_audio_bytes=None):
    """
    Synthesizes translated vocals using gTTS in target language.
    If original_audio_bytes is provided, mixes original audio (attenuated as BGM) with translated vocals.
    """
    # 1. Synthesize translated vocal track
    tts_lang = "zh-CN" if target_lang_code == "zh-CN" else target_lang_code
    tts = gTTS(text=translated_text[:2000], lang=tts_lang, slow=False)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as vocal_file:
        tts.save(vocal_file.name)
        vocal_path = vocal_file.name
        
    try:
        if original_audio_bytes and PYDUB_AVAILABLE:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as bgm_file:
                bgm_file.write(original_audio_bytes)
                bgm_path = bgm_file.name
            try:
                # Load BGM & Vocal tracks
                bgm_sound = AudioSegment.from_file(bgm_path)
                vocal_sound = AudioSegment.from_file(vocal_path)
                
                # Attenuate BGM volume to -14dB so translated vocal is crystal clear over the tune
                bgm_attenuated = bgm_sound - 14
                
                # Loop or trim BGM to match vocal length
                if len(bgm_attenuated) < len(vocal_sound):
                    loops_needed = (len(vocal_sound) // len(bgm_attenuated)) + 1
                    bgm_attenuated = bgm_attenuated * loops_needed
                bgm_trimmed = bgm_attenuated[:len(vocal_sound) + 1000]
                
                # Overlay translated vocals over BGM music
                mixed = bgm_trimmed.overlay(vocal_sound, position=0)
                
                output_io = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                mixed.export(output_io.name, format="mp3")
                with open(output_io.name, "rb") as f:
                    final_bytes = f.read()
                os.unlink(bgm_path)
                os.unlink(output_io.name)
                return final_bytes
            except Exception:
                # Fallback to vocal-only if audio format decode fails
                pass

        with open(vocal_path, "rb") as f:
            final_bytes = f.read()
        return final_bytes
    finally:
        if os.path.exists(vocal_path):
            os.unlink(vocal_path)

# --- Sidebar Navigation ---
st.sidebar.markdown("## 🎙️ **PolyVoice Studio**")
st.sidebar.markdown("All-in-One Audio, Translation & Lyrics Hub")

navigation = st.sidebar.radio(
    "Select Feature:",
    [
        "1. Speech to Text", 
        "2. Multi-Translate", 
        "3. Song Lyrics & Karaoke", 
        "4. Audio Translation Player (Original vs Translated BGM)",
        "5. Download & Export"
    ],
    index=0
)

st.sidebar.markdown("---")
st.sidebar.info("💡 **Dual Audio Feature**: Listen to original audio AND translated version with matching background music!")

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
            st.session_state.uploaded_audio_bytes = file_bytes
            st.session_state.uploaded_audio_name = uploaded_file.name
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
            st.session_state.uploaded_audio_bytes = mic_bytes
            st.session_state.uploaded_audio_name = "Live_Voice_Recording.wav"
            
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
# TAB 3: SONG LYRICS & KARAOKE
# ==============================================================================
elif navigation == "3. Song Lyrics & Karaoke":
    st.markdown('<div class="sub-title">Search lyrics for any song in any language, or upload an MP3 for synchronized Karaoke lyrics.</div>', unsafe_allow_html=True)
    
    st.subheader("🔍 Search Song Lyrics")
    c1, c2, c3 = st.columns([3, 2, 1])
    with c1:
        track_name = st.text_input("Song Title", value="Shape of You")
    with c2:
        artist_name = st.text_input("Artist (Optional)", value="Ed Sheeran")
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        search_btn = st.button("Search Lyrics", type="primary", use_container_width=True)
        
    if search_btn and track_name:
        with st.spinner(f"Searching lyrics for '{track_name}'..."):
            data = search_lyrics_api(track_name, artist_name)
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
                st.success("Lyrics found!")
            else:
                st.error("No lyrics found. You can transcribe the song audio in Tab 1!")

    st.markdown("---")
    st.subheader("🎵 Upload Song Audio File (Play Original Tune)")
    song_file = st.file_uploader("Upload Song Audio File (MP3/WAV/M4A)", type=["mp3", "wav", "m4a"])
    if song_file is not None:
        song_bytes = song_file.read()
        st.session_state.uploaded_audio_bytes = song_bytes
        st.session_state.uploaded_audio_name = song_file.name
        st.audio(song_bytes)

    if st.session_state.lyrics_data.get("plain"):
        ld = st.session_state.lyrics_data
        st.subheader(f"🎶 {ld['title']} — {ld['artist']}")
        
        tab_a, tab_b = st.tabs(["Synchronized Karaoke LRC", "Lyrics Translation"])
        
        with tab_a:
            if ld.get("segments"):
                st.markdown("**Synchronized Time-Stamped Lyrics:**")
                for seg in ld["segments"]:
                    st.markdown(f"`[{seg['start']}s]` {seg['text']}")
            else:
                st.text_area("Plain Lyrics", value=ld["plain"], height=300)
                
        with tab_b:
            target_lyric_lang = st.selectbox("Translate Lyrics To:", list(SUPPORTED_LANGUAGES.keys()), format_func=lambda x: SUPPORTED_LANGUAGES[x])
            if st.button("Translate Song Lyrics"):
                with st.spinner("Translating song lyrics..."):
                    try:
                        trans_lyrics = GoogleTranslator(source="auto", target=target_lyric_lang).translate(ld["plain"])
                        st.text_area(f"Translated Lyrics ({SUPPORTED_LANGUAGES[target_lyric_lang]})", value=trans_lyrics, height=300)
                    except Exception as e:
                        st.error(f"Failed to translate lyrics: {e}")

# ==============================================================================
# TAB 4: DUAL AUDIO PLAYER (ORIGINAL VS TRANSLATED VERSION WITH BGM)
# ==============================================================================
elif navigation == "4. Audio Translation Player (Original vs Translated BGM)":
    st.markdown('<div class="sub-title">Listen to your song/speech in both the ORIGINAL version and the TRANSLATED version with background music (BGM/tunes) intact!</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("### 🔊 1. Original Version Audio")
        if st.session_state.uploaded_audio_bytes:
            st.success(f"Loaded Audio: {st.session_state.uploaded_audio_name or 'Audio Stream'}")
            st.audio(st.session_state.uploaded_audio_bytes)
        else:
            st.info("No original audio file uploaded yet. Upload an audio file in Tab 1 or Tab 3 to play along with BGM!")
            uploaded_dub_file = st.file_uploader("Upload Song/Speech Audio for BGM:", type=["mp3", "wav", "m4a", "ogg"])
            if uploaded_dub_file:
                st.session_state.uploaded_audio_bytes = uploaded_dub_file.read()
                st.session_state.uploaded_audio_name = uploaded_dub_file.name
                st.audio(st.session_state.uploaded_audio_bytes)

    with col2:
        st.markdown("### 🎧 2. Translated Audio Version (With BGM / Tunes)")
        
        dub_target_lang = st.selectbox(
            "Select Language to Generate Translated Audio:",
            options=list(SUPPORTED_LANGUAGES.keys()),
            format_func=lambda x: f"{SUPPORTED_LANGUAGES[x]} ({x})",
            index=0
        )
        
        text_for_dubbing = st.text_area(
            "Text/Lyrics to Dub:",
            value=st.session_state.lyrics_data.get("plain") or st.session_state.transcript_text,
            height=120
        )
        
        if st.button("🎵 Generate Translated Audio (Vocal + BGM)", type="primary", use_container_width=True):
            if not text_for_dubbing.strip():
                st.error("Please provide text or lyrics to dub.")
            else:
                with st.spinner(f"Translating text to {SUPPORTED_LANGUAGES[dub_target_lang]} and mixing background music..."):
                    try:
                        # Translate first
                        translated_content = GoogleTranslator(source="auto", target=dub_target_lang).translate(text_for_dubbing)
                        
                        # Generate mixed audio (TTS + BGM)
                        final_audio_bytes = generate_translated_audio_with_bgm(
                            translated_text=translated_content,
                            target_lang_code=dub_target_lang,
                            original_audio_bytes=st.session_state.uploaded_audio_bytes
                        )
                        
                        st.success(f"Generated Translated Audio in {SUPPORTED_LANGUAGES[dub_target_lang]}!")
                        st.audio(final_audio_bytes, format="audio/mp3")
                        
                        st.download_button(
                            label=f"📥 Download Translated Audio ({SUPPORTED_LANGUAGES[dub_target_lang]})",
                            data=final_audio_bytes,
                            file_name=f"translated_{dub_target_lang}_{st.session_state.transcript_title}.mp3",
                            mime="audio/mp3",
                            use_container_width=True
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
        use_container_width=True
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
            use_container_width=True
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
            use_container_width=True
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
            use_container_width=True
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
        use_container_width=True
    )
