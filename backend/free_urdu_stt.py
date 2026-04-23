import sounddevice as sd
import numpy as np
import speech_recognition as sr
import scipy.io.wavfile as wav
import io
import queue
import threading
import sys
import time

# Configuration
FS = 16000  
CHUNK_DURATION = 0.5  
SILENCE_THRESHOLD = 0.005  
SILENCE_DURATION = 4.0  # Increased patience to 1.5s
MAX_PHRASE_DURATION = 15.0 # Max 15s per sentence to prevent infinite buffers

# Synchronized queue for audio blocks
audio_queue = queue.Queue()
recognizer = sr.Recognizer()

def audio_callback(indata, frames, time, status):
    if status:
        print(f"⚠️ {status}", file=sys.stderr)
    audio_queue.put(indata.copy())

def transcription_worker():
    print("🟢 BACKGROUND WORKER: Started.")
    
    phrase_buffer = []
    last_speech_time = time.time()
    is_speaking = False

    while True:
        try:
            data = audio_queue.get(timeout=0.1)
            phrase_buffer.append(data)
            
            # Volume detection
            rms = np.sqrt(np.mean(data**2))
            
            if rms > SILENCE_THRESHOLD:
                if not is_speaking:
                    # print("\n🎤 Listening", end="", flush=True)
                    is_speaking = True
                else:
                    print(".", end="", flush=True) # visual heartbeat
                last_speech_time = time.time()
            
            # Logic to send:
            # 1. We were speaking and now it's been silent for 1.5s
            # 2. OR the sentence is getting too long (15s)
            curr_time = time.time()
            if is_speaking:
                if (curr_time - last_speech_time > SILENCE_DURATION) or (len(phrase_buffer) * CHUNK_DURATION > MAX_PHRASE_DURATION):
                    # print(" 🔍 Transcribing...", end="\r", flush=True)
                    
                    audio_data = np.concatenate(phrase_buffer)
                    phrase_buffer = [] # Clear buffer for next phrase
                    is_speaking = False

                    # Process in background
                    threading.Thread(target=send_to_api, args=(audio_data,)).start()

        except queue.Empty:
            continue

def send_to_api(audio_np):
    try:
        byte_io = io.BytesIO()
        wav.write(byte_io, FS, (audio_np * 32767).astype(np.int16))
        byte_io.seek(0)

        with sr.AudioFile(byte_io) as source:
            # Adjust for ambient noise automatically
            audio = recognizer.record(source)
        
        text = recognizer.recognize_google(audio, language='ur-PK')
        if text:
            # Clear line and print result
            sys.stdout.write("\033[K") 
            print(f"\r📝 {text}")
            
    except sr.UnknownValueError:
        sys.stdout.write("\033[K") 
        # print("\r🔇 (No words recognized)")
    except Exception as e:
        pass

def main():
    print("\n" + "="*50)
    print("🎙️  ULTRA-FAST FREE URDU STT (Threaded Mode)")
    print("="*50)
    print("✅ MIC ACTIVE: Recording non-stop.")
    print("👉 Speak naturally. Wait for the '...' to stop before result.")
    print("👉 Press Ctrl+C to quit.")
    print("-" * 50)

    worker_thread = threading.Thread(target=transcription_worker, daemon=True)
    worker_thread.start()

    try:
        with sd.InputStream(samplerate=FS, channels=1, callback=audio_callback):
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopped. Khuda Hafiz!")
    except Exception as e:
        print(f"\n❌ FATAL: {e}")

if __name__ == "__main__":
    main()
