import sys
import os
import json
import queue
import sounddevice as sd
from vosk import Model, KaldiRecognizer
from indic_transliteration import sanscript

# --- Configuration ---
MODEL_LANG = "hi"
SAMPLE_RATE = 16000

# Audio queue to pass data from callback to main loop
audio_queue = queue.Queue()

def to_urdu(text):
    """Converts Devanagari to Urdu and REVERSES it for correct terminal display."""
    if not text:
        return ""
    trans = sanscript.transliterate(text, sanscript.DEVANAGARI, 'urdu')
    # Reverse characters to fix Right-to-Left display in standard terminals
    return trans[::-1]

def audio_callback(indata, frames, time, status):
    """This callback is called for every block of audio from the mic."""
    if status:
        print(f"⚠️ Mic status: {status}", file=sys.stderr)
    audio_queue.put(bytes(indata))

def run_vosk_stt_test():
    print("\n" + "="*50)
    print("🎙️  VOSK REAL-TIME URDU STT (Local & Free)")
    print("="*50)
    
    # 1. Load/Download Model
    print(f"🔄 Initializing Fast Engine...")
    try:
        model = Model(lang=MODEL_LANG)
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    print("✅ Ready! Results will show in URDU script.")
    print("🟢 LISTENING! (Speak now)")
    print("   -> Press Ctrl+C to stop.")
    print("-" * 50)

    # 2. Start Audio Stream
    try:
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=8000, dtype='int16',
                               channels=1, callback=audio_callback):
            
            while True:
                data = audio_queue.get()
                
                # Check for results
                if recognizer.AcceptWaveform(data):
                    # Final result (full sentence)
                    result_json = json.loads(recognizer.Result())
                    final_text = result_json.get("text", "")
                    if final_text:
                        urdu_final = to_urdu(final_text)
                        print(f"\n✅ HEARD: {urdu_final}")
                else:
                    # Partial result (words as you speak)
                    partial_json = json.loads(recognizer.PartialResult())
                    partial_text = partial_json.get("partial", "")
                    if partial_text:
                        urdu_partial = to_urdu(partial_text)
                        # Print partial without newline to show live progress
                        sys.stdout.write(f"\r🎤 Listening: {urdu_partial}")
                        sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n\n🛑 Test stopped by user. Khuda Hafiz!")
    except Exception as e:
        print(f"\n❌ Streaming Error: {e}")

if __name__ == "__main__":
    run_vosk_stt_test()
