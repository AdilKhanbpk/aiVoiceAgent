import React, { useState, useEffect, useCallback } from 'react';
import { 
  LiveKitRoom, 
  useTracks, 
  useLocalParticipant,
  RoomAudioRenderer
} from '@livekit/components-react';
import { Track, RoomEvent } from 'livekit-client';
import { 
  Mic, 
  MicOff, 
  Phone, 
  PhoneOff, 
  Activity,
  User,
  ShieldCheck
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export default function App() {
  const [token, setToken] = useState(null);
  const [roomName, setRoomName] = useState('tech-support-call');
  const [isCalling, setIsCalling] = useState(false);

  const startCall = async () => {
    try {
      // Generate a unique room name for this specific call to avoid session conflicts
      const uniqueRoom = `mosafir-call-${Math.floor(Math.random() * 10000)}`;
      console.log(`[FRONTEND] Starting call in unique room: ${uniqueRoom}`);
      
      const resp = await fetch(`/get-token?room=${uniqueRoom}&identity=user-${Math.floor(Math.random() * 1000)}`);
      const data = await resp.json();
      
      setRoomName(uniqueRoom);
      setToken(data.token);
      setIsCalling(true);
    } catch (e) {
      console.error("Failed to fetch token", e);
    }
  };

  const endCall = useCallback(async () => {
    // Attempt to disconnect room if it exists (though LiveKitRoom unmounting handles most cases)
    setToken(null);
    setIsCalling(false);
  }, []);

  return (
    <div className="app-container">
      {!isCalling ? (
        <div className="status-header" style={{ marginTop: '100px' }}>
          <div className="status-badge">Ahmed is Online</div>
          <div className="agent-info">
            <h1 className="agent-name">Ahmed | Mosafir.pk</h1>
            <p className="agent-title">Friendly Travel Sales Assistant</p>
          </div>
          <div style={{ marginTop: '100px' }}>
             <button className="control-btn start-call" onClick={startCall}>
                <Phone fill="currentColor" />
             </button>
             <p style={{ marginTop: '15px', color: 'var(--text-muted)', textAlign:'center' }}>Connect</p>
          </div>
        </div>
      ) : (
        <LiveKitRoom
          serverUrl={import.meta.env.VITE_LIVEKIT_URL || "wss://livecallagent-vo2v1k51.livekit.cloud"}
          token={token}
          connect={true}
          audio={true}
          onDisconnected={endCall}
        >
          <VoiceInterface onDisconnect={endCall} />
          <RoomAudioRenderer />
        </LiveKitRoom>
      )}
    </div>
  );
}

function VoiceInterface({ onDisconnect }) {
  const { localParticipant, isMicrophoneEnabled } = useLocalParticipant();
  // We want to detect the agent's audio to animate the visualizer
  const tracks = useTracks([Track.Source.Microphone]);
  const agentTrack = tracks.find(t => t.participant.identity !== localParticipant?.identity);
  
  const [status, setStatus] = useState('Connected');

  // Add Frontend Logging for Speech Events
  useEffect(() => {
    if (!localParticipant?.room) return;

    const room = localParticipant.room;
    console.log("[FRONTEND] Room connection established:", room.name);

    const handleActiveSpeakers = (speakers) => {
      const isUserSpeaking = speakers.some(p => p.identity === localParticipant.identity);
      const isAgentSpeaking = speakers.some(p => p.identity !== localParticipant.identity);
      
      if (isUserSpeaking) console.log("[FRONTEND] User is speaking...");
      if (isAgentSpeaking) console.log("[FRONTEND] Ahmed (Agent) is speaking...");
    };

    const handleData = (payload, participant) => {
      const decoder = new TextDecoder();
      const strData = decoder.decode(payload);
      console.log(`[FRONTEND] Data received from ${participant?.identity || 'unknown'}:`, strData);
    };

    room.on(RoomEvent.ActiveSpeakersChanged, handleActiveSpeakers);
    room.on(RoomEvent.DataReceived, handleData);

    return () => {
      room.off(RoomEvent.ActiveSpeakersChanged, handleActiveSpeakers);
      room.off(RoomEvent.DataReceived, handleData);
    };
  }, [localParticipant]);

  // Simple animation for bars
  const bars = Array.from({ length: 15 });

  return (
    <>
      <div className="status-header">
        <div className="status-badge pulse">{status}</div>
        <div className="agent-info">
          <h1 className="agent-name">Ahmed | Mosafir.pk</h1>
          <p className="agent-title">Urdu & English Voice Channel</p>
        </div>
      </div>

      <div className="visualizer-container">
        <div className="waveform">
          {bars.map((_, i) => (
            <motion.div
              key={i}
              className="bar"
              animate={{
                height: [20, Math.random() * 80 + 20, 20]
              }}
              transition={{
                duration: 0.5,
                repeat: Infinity,
                delay: i * 0.05
              }}
            />
          ))}
        </div>
      </div>

      <div className="controls">
        <button 
          className="control-btn"
          onClick={() => localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled)}
        >
          {isMicrophoneEnabled ? <Mic /> : <MicOff color="#ef4444" />}
        </button>

        <button className="control-btn end-call" onClick={onDisconnect}>
          <PhoneOff fill="currentColor" />
        </button>
      </div>
    </>
  );
}
