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
from livekit.plugins import openai, deepgram, silero, groq
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CUSTOM FREE URDU TTS (Microsoft Edge)
# ─────────────────────────────────────────────────────────────
class EdgeTTS(tts.TTS):
    def __init__(self, voice: str = "hi-IN-SwaraNeural"):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
            sample_rate=24000,
            num_channels=1,
        )
        self._voice = voice

    def synthesize(self, text: str, *, conn_options: tts.APIConnectOptions) -> tts.SynthesizeStream:
        # Final safety log: This shows exactly what the TTS engine receives
        logger.info(f"🧠 [LLM -> TTS]: \"{text}\"")
        return EdgeSynthesizeStream(self, text, self._voice, conn_options)

class EdgeSynthesizeStream(tts.SynthesizeStream):
    def __init__(self, tts_instance: tts.TTS, text: str, voice: str, conn_options: tts.APIConnectOptions):
        super().__init__(tts=tts_instance, conn_options=conn_options)
        self._text = text
        self._voice = voice

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        try:
            communicate = edge_tts.Communicate(self._text, self._voice, rate="+20%")
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
NAME & ROLE: You are "Areeba", a friendly and professional Senior Travel Consultant at Mosafir.pk.
TARGET: Selling premium Pakistan travel packages.

STRICT FOCUS:
- STYLE: Use simple Hindi (conversational style).
- VOCABULARY: Use common Hindi words. Avoid difficult or formal Urdu/Sanskrit words.
- SCRIPT: Every single response MUST be in Hindi script (Devanagari/हिंदी). 
- PRONUNCIATION: Write in a way that sounds natural for the "Swara" voice you are using.

STRICT OPERATING RULES:
1. LANGUAGE: Speak EXCLUSIVELY in Hindi script (हिंदी).
2. CONCISENESS: Responses MUST be between 10-25 words.
3. TONE: Warm and helpful hospitality. Use "Aap" and "Ji".

CONVERSATION LOGIC:
- PHASE 1 (Greeting): Always start with: "नमस्ते, मुसाफिर की ओर से अरीबा बात कर रही हूँ। बताइए, मैं आपकी क्या मदद कर सकती हूँ?"
- PHASE 2 (No English Letters): NEVER use English letters for Hindi words.
- PHASE 3 (Travel Focus): Assist with tours and bookings after the greeting.
"""

# Hardcoded Credentials as requested for debugging
# Credentials from environment
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://livecallagent-vo2v1k51.livekit.cloud")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 [JOB START] Registered for room: {ctx.room.name}")
    session = None
    
    try:
        await ctx.connect()
        logger.info(f"✅ [CONNECTED] Agent joined room: {ctx.room.name}")

        # 1. Setup Brain (Groq)
        logger.debug(f"🧠 [LLM CONFIG] Using Groq with model {GROQ_MODEL}")
        llm = groq.LLM(
            model=GROQ_MODEL,
            temperature=0.7,
        )

        # 2. Setup Voice Pipeline
        session = AgentSession(
            vad=silero.VAD.load(),
            stt=deepgram.STT(
                api_key=DEEPGRAM_API_KEY,
                model="nova-3",
                language="hi",
            ),
            llm=llm,
            tts=tts.StreamAdapter(
                tts=EdgeTTS(voice="hi-IN-SwaraNeural"), # Swara Hindi Voice (as requested)
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
            # The exact text handed off from STT to LLM
            print(f"\nUser input query : {msg.text}\n")
            logger.info(f"🎤 [DEEPGRAM -> GROQ]: \"{msg.text}\"")
            
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
            # The final answer committed to speech
            logger.info(f"🤖 [BACKEND] [Areeba's Response]: \"{msg.text}\"")
            print(f"🤖 Areeba: {msg.text}")

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
            instructions='Start the conversation by saying exactly: "नमस्ते, मुसाफिर की ओर से अरीबा बात कर रही हूँ। बताइए, मैं आपकी क्या मदद कर सकती हूँ?"'
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