import os
import io
import logging
import aiohttp
import asyncio
import static_ffmpeg
import av
import edge_tts
from livekit import agents, rtc
from livekit.agents import AgentSession, Agent, JobContext, cli, tts, tokenize
from livekit.plugins import openai, deepgram, silero

# ─────────────────────────────────────────────────────────────
# CUSTOM FREE URDU TTS (Microsoft Edge)
# ─────────────────────────────────────────────────────────────
class EdgeTTS(tts.TTS):
    def __init__(self, voice: str = "ur-PK-UzmaNeural"):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
            sample_rate=24000,
            num_channels=1,
        )
        self._voice = voice

    def synthesize(self, text: str, *, conn_options: tts.APIConnectOptions) -> tts.SynthesizeStream:
        # Final safety log: This will show the vLLM's answer even if synthesis fails
        logger.info(f"🧠 [VLLM ANSWER]: \"{text}\"")
        return EdgeSynthesizeStream(self, text, self._voice, conn_options)

class EdgeSynthesizeStream(tts.SynthesizeStream):
    def __init__(self, tts_instance: tts.TTS, text: str, voice: str, conn_options: tts.APIConnectOptions):
        super().__init__(tts=tts_instance, conn_options=conn_options)
        self._text = text
        self._voice = voice

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        try:
            communicate = edge_tts.Communicate(self._text, self._voice)
            audio_data = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.write(chunk["data"])
            
            audio_data.seek(0)
            
            # Initialize the emitter (Required by LiveKit 1.5+)
            output_emitter.initialize(
                request_id="ahmed-call",
                sample_rate=24000,
                num_channels=1,
                mime_type="audio/pcm",
            )
            
            # Decode MP3 to PCM using PyAV
            container = av.open(audio_data, format="mp3")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(
                format="s16",
                layout="mono",
                rate=24000,
            )
            
            for frame in container.decode(stream):
                resampled_frames = resampler.resample(frame)
                for resampled_frame in resampled_frames:
                    # Push raw bytes (modern LiveKit AudioEmitter expects bytes)
                    output_emitter.push(resampled_frame.to_ndarray().tobytes())
            
            container.close()
            output_emitter.flush()
        except Exception as e:
            logging.error(f"❌ [EdgeTTS] Error during synthesis: {e}")

# Initialize FFmpeg paths for Windows
static_ffmpeg.add_paths()

# Configure Logging to be extremely detailed
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mosafir-agent")
logger.setLevel(logging.DEBUG) # Set to DEBUG for maximum output

# ─────────────────────────────────────────────────────────────
# SALESMAN SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────
SALESMAN_PROMPT = """
NAME & ROLE: You are "Areeba", a professional and elite Senior Travel Consultant at Mosafir.pk.
TARGET: Selling premium Pakistan travel packages.

STRICT OPERATING RULES:
1. LANGUAGE: Speak EXCLUSIVELY in Urdu script (اردو). If the user speaks in Roman Urdu (like 'kese ho ap'), you MUST still respond in proper Urdu script. Use English only for brand names (Mosafir.pk) or technical terms (Booking, Ticket).
2. CONCISENESS: Responses MUST be between 20-40 words. Voice conversations must be snappy.
3. TONE: High-end hospitality. Use "Aap" and "Sahib/Sahiba". Be warm but business-focused.

CONVERSATION LOGIC:
- PHASE 1 (Discovery): If you don't know the destination or duration, you MUST ask: "Aap kahan jana chahte hain aur kitne dinon ke liye?"
- PHASE 2 (Handling Confusion): If the user's input is unclear or noisy, say: "Maazrat chahti hoon, main aap ki baat samajh nahi saki. Kya aap baraye meherbani doobara bata sakte hain?"
- PHASE 3 (The Pitch): Once you have the destination/days, provide a dummy "Mosafir Exclusive" package. 
  Example: "Behtareen! Hunza ke 5 dinon ke liye hamare paas 'Luxury North' package hai jis mein hotel aur travel shamil hai."

CURRENT GOAL: Get the user's destination and duration, then offer a dummy travel deal.
"""

# Hardcoded Credentials as requested for debugging
LIVEKIT_URL = "wss://livecallagent-vo2v1k51.livekit.cloud"
DEEPGRAM_API_KEY = "151b44d0af7076214f9d8b2800284ad552ec8a9e"
VLLM_URL = "https://unworn-numeric-move.ngrok-free.dev/v1"
VLLM_MODEL = "meta-llama/Llama-3.2-1B-Instruct"

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 [JOB START] Registered for room: {ctx.room.name}")
    session = None
    
    try:
        await ctx.connect()
        logger.info(f"✅ [CONNECTED] Agent joined room: {ctx.room.name}")

        # 0. Check LLM Connectivity
        logger.info(f"🔍 [BACKEND] [vLLM] Checking connection to: {VLLM_URL}/models")
        try:
            async with aiohttp.ClientSession() as session_test:
                async with session_test.get(VLLM_URL + "/models", timeout=2) as resp:
                    logger.info(f"✅ [BACKEND] [vLLM] Connection verified (Status {resp.status})")
        except Exception:
            logger.warning(f"⚠️ [BACKEND] [vLLM] OFFLINE. Ahmed cannot think without Colab/ngrok running.")

        # 1. Setup Brain (vLLM)
        logger.debug(f"🧠 [LLM CONFIG] Using vLLM at {VLLM_URL} with model {VLLM_MODEL}")
        vllm_llm = openai.LLM(
            base_url=VLLM_URL,
            api_key="not-needed",
            model=VLLM_MODEL,
        )

        # 2. Setup Voice Pipeline
        session = AgentSession(
            vad=silero.VAD.load(),
            stt=deepgram.STT(
                api_key=DEEPGRAM_API_KEY,
                model="nova-3",
                language="ur",
            ),
            llm=vllm_llm,
            tts=tts.StreamAdapter(
                tts=EdgeTTS(voice="ur-PK-UzmaNeural"), # Free Microsoft Urdu Voice
                sentence_tokenizer=tokenize.basic.SentenceTokenizer(),
            ),
        )

        # 3. Add Event Handlers for Tracing
        @session.on("user_started_speaking")
        def _user_started():
            logger.info("🎤 [USER] started speaking...")

        @session.on("user_stopped_speaking")
        def _user_stopped():
            logger.info("silence [USER] stopped speaking.")

        @session.on("user_speech_committed")
        def _user_speech(msg: agents.voice.SpeechData):
            logger.info(f"🎤 [Deepgram Transcript]: \"{msg.text}\"")
            # Direct console output for maximum visibility
            print(f"\n💬 YOU SAID: {msg.text}\n")
            
            # Async task to send data to the specified URL
            async def send_to_url(text):
                url = "https://livecallagent-vo2v1k51.livekit.cloud/settings/regions"
                logger.info(f"📤 [BACKEND] Attempting to send transcript to: {url}")
                try:
                    async with aiohttp.ClientSession() as session_http:
                        # We use a GET request here as the target is likely a dashboard page
                        async with session_http.get(url, params={"transcript": text}) as resp:
                            logger.info(f"✅ [BACKEND] Network Request Result: Status {resp.status}")
                except Exception as e:
                    logger.error(f"❌ [BACKEND] Network Request Failed: {e}")

            # Schedule the async task without blocking the agent's response
            asyncio.create_task(send_to_url(msg.text))

        @session.on("agent_started_speaking")
        def _agent_started():
            logger.info("🗣️ [AGENT] Areeba is speaking...")

        @session.on("agent_speech_committed")
        def _agent_speech(msg: agents.voice.SpeechData):
            logger.info(f"🤖 [BACKEND] [Areeba's Response]: \"{msg.text}\"")

        @session.on("agent_stopped_speaking")
        def _agent_stopped():
            logger.info("✅ [AGENT] Areeba finished speaking.")

        @session.on("state_changed")
        def _state_changed(state: agents.voice.AgentState):
            logger.debug(f"🔄 [STATE] Agent is now: {state}")

        # Start the agent personality
        my_agent = Agent(instructions=SALESMAN_PROMPT)
        
        logger.info("🤖 [SESSION] Starting Areeba's personality...")
        await session.start(room=ctx.room, agent=my_agent)

        # Initial Greeting
        logger.info("👋 [GREETING] Triggering initial Urdu welcome...")
        await session.generate_reply(
            instructions="Greet the customer warmly in Urdu as Areeba from Mosafir.pk. Ask where they want to go in Pakistan. Keep it short (max 50 words)."
        )

        # 4. Instant Shutdown Trigger
        should_exit = asyncio.Event()

        @ctx.room.on("participant_disconnected")
        def _on_participant_disconnected(participant: rtc.RemoteParticipant):
            # If no more human participants are left, shut down immediately
            human_count = len([p for p in ctx.room.remote_participants.values()])
            logger.info(f"👤 [ROOM] Participant left. Humans remaining: {human_count}")
            if human_count == 0:
                logger.info("👋 [ROOM] Last human left. Triggering instant shutdown...")
                asyncio.create_task(ctx.shutdown())

        # Register a shutdown callback to exit the loop
        async def _on_shutdown():
            logger.info("🛑 [JOB] Shutdown signal received.")
            should_exit.set()
        
        ctx.add_shutdown_callback(_on_shutdown)

        # Monitor for room disconnection or job shutdown
        while not should_exit.is_set() and ctx.room.connection_state != rtc.ConnectionState.CONN_DISCONNECTED:
            await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"⚠️ [FATAL ERROR] {e}")
    finally:
        logger.info(f"🛑 [CLEANUP] Areeba is leaving room: {ctx.room.name}")
        if session:
            await session.aclose()
        await ctx.room.disconnect()
        logger.info("✨ [CLEANUP] Resources released successfully.")

if __name__ == "__main__":
    cli.run_app(agents.WorkerOptions(
        entrypoint_fnc=entrypoint,
        ws_url=LIVEKIT_URL,
        api_key="APIB2vg7QvPMNUA",
        api_secret="avWelhyxeUhbBHWYePf44XcV5uwejXBm6CNG06kNKj4B",
    ))