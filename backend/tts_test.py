import asyncio
import io
import edge_tts
import av
import sounddevice as sd
import numpy as np

async def run_tts_test():
    """
    Standalone script to test Urdu TTS. 
    Enter text in Urdu, and hear it spoken back through your speakers.
    """
    print("\n" + "="*50)
    print("🔊  MOSAFIR.PK - URDU TTS TEST TOOL")
    print("="*50)
    print("Voice: ur-PK-UzmaNeural (Microsoft Edge)")
    print("-" * 50)
    
    voice = "ur-PK-UzmaNeural"
    
    while True:
        try:
            # Get Urdu text from user
            print("\n📝 Type Urdu text below (Example: السلام علیکم، آپ کیسے ہیں؟)")
            text = input("👉 : ").strip()
            
            if text.lower() in ['exit', 'quit', 'bye']:
                break
            
            if not text:
                continue
                
            print(f"⏳ Synthesizing...")
            
            # 1. Synthesize using edge-tts (Directly to memory)
            communicate = edge_tts.Communicate(text, voice)
            audio_bytes = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes.write(chunk["data"])
            
            audio_bytes.seek(0)
            
            # 2. Decode and Resample using PyAV (Same logic as Areeba)
            container = av.open(audio_bytes, format="mp3")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(
                format="s16",
                layout="mono",
                rate=24000,
            )
            
            print("📣 Playing audio...")
            all_samples = []
            for frame in container.decode(stream):
                resampled_frames = resampler.resample(frame)
                for resampled_frame in resampled_frames:
                    # Convert PyAV frame to Numpy array for sounddevice
                    all_samples.append(resampled_frame.to_ndarray())
            
            if all_samples:
                # Merge all chunks and play through default speakers
                full_audio = np.concatenate(all_samples, axis=1).reshape(-1)
                sd.play(full_audio, samplerate=24000)
                sd.wait() # Wait until finished
            
            container.close()
            print("✅ Finished playback.")

        except Exception as e:
            print(f"❌ Error during playback: {e}")
            if "KeyboardInterrupt" in str(e):
                break

if __name__ == "__main__":
    try:
        asyncio.run(run_tts_test())
    except KeyboardInterrupt:
        print("\n👋 Test stopped.")
