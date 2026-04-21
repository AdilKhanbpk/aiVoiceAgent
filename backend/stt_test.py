import asyncio
import aiohttp
import sys
import sounddevice as sd
from livekit import rtc
from livekit.plugins.deepgram import STT

# Using your existing API Key from agent.py
DEEPGRAM_API_KEY = "151b44d0af7076214f9d8b2800284ad552ec8a9e"

async def run_livekit_stt_test():
    """
    Standalone script using the LiveKit-Deepgram plugin to test your mic.
    This exactly mimics how your main voice agent hears you.
    """
    print("\n" + "="*50)
    print("🎙️  MOSAFIR.PK - LIVEKIT STT TEST TOOL")
    print("="*50)
    
    try:
        # Create a manual HTTP session for standalone usage
        async with aiohttp.ClientSession() as http_session:
            # Initialize the LiveKit Deepgram Plugin
            stt_client = STT(
                api_key=DEEPGRAM_API_KEY,
                http_session=http_session,
                model="nova-3",
                language="ur",
            )

            # Create a transcription stream
            stt_stream = stt_client.stream()

            async def display_results():
                """Task to print results as they come back from Deepgram."""
                async for result in stt_stream:
                    if result.alternatives:
                        text = result.alternatives[0].text
                        if text:
                            print(f"✅ HEARD: {text}")

            # Start the background task to listen for results
            asyncio.create_task(display_results())

            print("🚀 Initializing LiveKit-Deepgram Pipeline...")
            print("🟢 LISTENING! (Speak now, Urdu supported)")
            print("   -> Press Ctrl+C to stop.")
            print("-" * 50)

            # Microphone streaming callback
            def mic_callback(indata, frames, time, status):
                if status:
                    print(f"⚠️ Mic Warning: {status}")
                
                audio_frame = rtc.AudioFrame(
                    data=bytes(indata),
                    sample_rate=16000,
                    num_channels=1,
                    samples_per_channel=frames
                )
                stt_stream.push_frame(audio_frame)

            # Start recording from default microphone
            with sd.RawInputStream(samplerate=16000, channels=1, dtype='int16', callback=mic_callback):
                while True:
                    await asyncio.sleep(0.5)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
    finally:
        print("\n🛑 Test completed.")

if __name__ == "__main__":
    try:
        asyncio.run(run_livekit_stt_test())
    except KeyboardInterrupt:
        print("\n👋 Test stopped by user.")
