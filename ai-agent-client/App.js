import React, { useState, useRef, useEffect } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  FlatList,
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  StatusBar,
  Image,
  Alert,
  Animated,
  Modal,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { Audio } from 'expo-av';

// =============================================================================
// BACKEND CONFIGURATION
// =============================================================================
// 1. Android Emulator: Uses 'http://10.0.2.2:5000/api/agent' (host loopback alias)
// 2. iOS Simulator: Uses 'http://localhost:5000/api/agent'
// 3. Physical Device (Expo Go): Replace with your PC's local LAN IP:
//    e.g., 'http://192.168.1.105:5000/api/agent'
// =============================================================================
const BACKEND_URL = Platform.select({
  android: 'http://10.0.2.2:5000/api/agent',
  ios: 'http://localhost:5000/api/agent',
  default: 'http://localhost:5000/api/agent',
});

// Identifier sent to Flask backend to resolve user profile in SQLite
const USER_ID = 'mobile_user_01';

export default function App() {
  // ---------------------------------------------------------------------------
  // State Management
  // ---------------------------------------------------------------------------
  const [messages, setMessages] = useState([
    {
      id: 'welcome_1',
      role: 'assistant',
      text: 'Hello! I am Muse, your executive personal AI assistant. Type a message, attach an image (+), or tap Live Voice (📞) to start a real-time hands-free voice conversation. How can I assist you today?',
      imageUri: null,
      timestamp: formatTime(new Date()),
      isError: false,
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [selectedImage, setSelectedImage] = useState(null); // { uri, base64 }
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null); // Captured from backend for multi-turn context

  // Standard Voice recording state (Chat Input Bar)
  const [recording, setRecording] = useState(null);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const recordingTimerRef = useRef(null);

  // Web Speech Synthesis (TTS) State
  const [playingMessageId, setPlayingMessageId] = useState(null);

  // ---------------------------------------------------------------------------
  // Live Voice Conversation Mode (Gemini Live Style) State
  // ---------------------------------------------------------------------------
  const [isLiveVoiceOpen, setIsLiveVoiceOpen] = useState(false);
  const [liveVoiceStatus, setLiveVoiceStatus] = useState('idle'); // 'idle' | 'recording' | 'thinking' | 'speaking'
  const [liveTranscript, setLiveTranscript] = useState('');
  const [liveAgentText, setLiveAgentText] = useState('');
  const [liveVoiceDuration, setLiveVoiceDuration] = useState(0);
  const [hasSpokenVoice, setHasSpokenVoice] = useState(false);

  const liveRecordingRef = useRef(null);
  const liveTimerRef = useRef(null);
  const liveSoundRef = useRef(null);
  const isLiveVoiceOpenRef = useRef(false);
  const liveVoiceStatusRef = useRef('idle');
  const isSendingLiveVoiceRef = useRef(false);

  // VAD (Voice Activity Detection & Silence Auto-Stop) Refs
  const vadStreamRef = useRef(null);
  const vadAudioCtxRef = useRef(null);
  const vadIntervalRef = useRef(null);
  const vadHasSpokenRef = useRef(false);
  const vadLastSoundTimeRef = useRef(0);
  const vadSpeechCounterRef = useRef(0);

  // Synchronize state values into refs to prevent stale closure issues in async callbacks
  useEffect(() => {
    liveVoiceStatusRef.current = liveVoiceStatus;
  }, [liveVoiceStatus]);

  useEffect(() => {
    isLiveVoiceOpenRef.current = isLiveVoiceOpen;
  }, [isLiveVoiceOpen]);

  // Concentric Halo Animations for Live Voice Mode
  const orbScaleAnim = useRef(new Animated.Value(1)).current;
  const orbRingAnim = useRef(new Animated.Value(1)).current;
  const orbOpacityAnim = useRef(new Animated.Value(0.7)).current;

  // Animations for In-Bar Voice Recording State
  const pulseAnim = useRef(new Animated.Value(1)).current;
  const waveAnim1 = useRef(new Animated.Value(0.4)).current;
  const waveAnim2 = useRef(new Animated.Value(0.8)).current;
  const waveAnim3 = useRef(new Animated.Value(0.5)).current;
  const waveAnim4 = useRef(new Animated.Value(0.9)).current;

  const flatListRef = useRef(null);

  // Auto-scroll to latest message on state changes
  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading, selectedImage, isRecording]);

  // Helper to safely stop and release Web Audio VAD resources
  const stopVad = () => {
    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current);
      vadIntervalRef.current = null;
    }
    if (vadStreamRef.current) {
      try {
        vadStreamRef.current.getTracks().forEach((track) => track.stop());
      } catch (e) {}
      vadStreamRef.current = null;
    }
    if (vadAudioCtxRef.current) {
      try {
        vadAudioCtxRef.current.close().catch(() => {});
      } catch (e) {}
      vadAudioCtxRef.current = null;
    }
    vadHasSpokenRef.current = false;
    vadSpeechCounterRef.current = 0;
    setHasSpokenVoice(false);
  };

  // Cleanup audio recording, VAD & speech synthesis on component unmount
  useEffect(() => {
    return () => {
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      if (liveTimerRef.current) clearInterval(liveTimerRef.current);
      stopVad();
      if (recording) recording.stopAndUnloadAsync().catch(() => {});
      if (liveRecordingRef.current) liveRecordingRef.current.stopAndUnloadAsync().catch(() => {});
      if (liveSoundRef.current) liveSoundRef.current.unloadAsync().catch(() => {});
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
    };
  }, [recording]);

  // Pre-load and cache browser speech synthesis voices (fixes empty getVoices() on initial load in Chromium/Safari)
  useEffect(() => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      const handleVoicesChanged = () => {
        if (window.speechSynthesis) {
          window.speechSynthesis.getVoices();
        }
      };
      if (window.speechSynthesis.onvoiceschanged !== undefined) {
        window.speechSynthesis.onvoiceschanged = handleVoicesChanged;
      }
      window.speechSynthesis.getVoices();
      return () => {
        if (window.speechSynthesis && window.speechSynthesis.onvoiceschanged === handleVoicesChanged) {
          window.speechSynthesis.onvoiceschanged = null;
        }
      };
    }
  }, []);


  // Audio wave and recording indicator animation loop for Input Bar
  useEffect(() => {
    if (isRecording) {
      const pulseLoop = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {
            toValue: 0.3,
            duration: 600,
            useNativeDriver: false,
          }),
          Animated.timing(pulseAnim, {
            toValue: 1,
            duration: 600,
            useNativeDriver: false,
          }),
        ])
      );

      const createWaveLoop = (anim, minVal, maxVal, dur) =>
        Animated.loop(
          Animated.sequence([
            Animated.timing(anim, {
              toValue: maxVal,
              duration: dur,
              useNativeDriver: false,
            }),
            Animated.timing(anim, {
              toValue: minVal,
              duration: dur,
              useNativeDriver: false,
            }),
          ])
        );

      const waveLoop1 = createWaveLoop(waveAnim1, 0.3, 1.0, 420);
      const waveLoop2 = createWaveLoop(waveAnim2, 0.2, 0.9, 360);
      const waveLoop3 = createWaveLoop(waveAnim3, 0.4, 1.1, 480);
      const waveLoop4 = createWaveLoop(waveAnim4, 0.2, 0.8, 320);

      pulseLoop.start();
      waveLoop1.start();
      waveLoop2.start();
      waveLoop3.start();
      waveLoop4.start();

      return () => {
        pulseLoop.stop();
        waveLoop1.stop();
        waveLoop2.stop();
        waveLoop3.stop();
        waveLoop4.stop();
      };
    } else {
      pulseAnim.setValue(1);
      waveAnim1.setValue(0.4);
      waveAnim2.setValue(0.8);
      waveAnim3.setValue(0.5);
      waveAnim4.setValue(0.9);
    }
  }, [isRecording]);

  // Breathing halo animation loop for Live Voice Orb
  useEffect(() => {
    if (isLiveVoiceOpen) {
      const breathing = Animated.loop(
        Animated.sequence([
          Animated.parallel([
            Animated.timing(orbScaleAnim, {
              toValue: 1.12,
              duration: 900,
              useNativeDriver: false,
            }),
            Animated.timing(orbRingAnim, {
              toValue: 1.45,
              duration: 900,
              useNativeDriver: false,
            }),
            Animated.timing(orbOpacityAnim, {
              toValue: 0.2,
              duration: 900,
              useNativeDriver: false,
            }),
          ]),
          Animated.parallel([
            Animated.timing(orbScaleAnim, {
              toValue: 1.0,
              duration: 900,
              useNativeDriver: false,
            }),
            Animated.timing(orbRingAnim, {
              toValue: 1.0,
              duration: 900,
              useNativeDriver: false,
            }),
            Animated.timing(orbOpacityAnim, {
              toValue: 0.7,
              duration: 900,
              useNativeDriver: false,
            }),
          ]),
        ])
      );
      breathing.start();
      return () => breathing.stop();
    } else {
      orbScaleAnim.setValue(1);
      orbRingAnim.setValue(1);
      orbOpacityAnim.setValue(0.7);
    }
  }, [isLiveVoiceOpen, liveVoiceStatus]);

  const scrollToBottom = () => {
    flatListRef.current?.scrollToEnd({ animated: true });
  };

  function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
  }

  // Clean markdown symbols for natural speech synthesis
  const stripMarkdownForSpeech = (text) => {
    if (!text) return '';
    return text
      .replace(/```[\s\S]*?```/g, 'Code snippet omitted.')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/https?:\/\/\S+/g, '')
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/__([^_]+)__/g, '$1')
      .replace(/_([^_]+)_/g, '$1')
      .replace(/^[•\-\*]\s+/gm, '')
      .replace(/^\d+\.\s+/gm, '')
      .replace(/\s+/g, ' ')
      .trim();
  };

  // ---------------------------------------------------------------------------
  // Dynamic Female Voice Selector for Professional Executive Tone
  // ---------------------------------------------------------------------------
  const getProfessionalFemaleVoice = () => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null;

    const voices = window.speechSynthesis.getVoices();
    if (!voices || voices.length === 0) return null;

    // Curated high-fidelity female voice keywords across Windows, macOS/iOS, Chrome & Edge:
    // - Windows/Edge: 'zira', 'jenny', 'aria', 'ava'
    // - macOS/iOS/Safari: 'samantha', 'victoria', 'karen', 'moira', 'tessa'
    // - Chrome/Android: 'google us english', 'google uk english female'
    // - Generic keywords: 'female', 'woman'
    const femaleVoiceKeywords = [
      'jenny',
      'aria',
      'zira',
      'samantha',
      'victoria',
      'karen',
      'google us english',
      'google uk english female',
      'ava',
      'female',
      'woman',
    ];

    // 1. First priority: English female voice matching preferred keywords
    const preferredEnglishFemale = voices.find((v) => {
      const nameLower = v.name.toLowerCase();
      const isEnglish = !v.lang || v.lang.toLowerCase().startsWith('en');
      return isEnglish && femaleVoiceKeywords.some((keyword) => nameLower.includes(keyword));
    });

    if (preferredEnglishFemale) return preferredEnglishFemale;

    // 2. Second priority: Any voice explicitly containing female keywords
    const anyFemaleVoice = voices.find((v) => {
      const nameLower = v.name.toLowerCase();
      return femaleVoiceKeywords.some((keyword) => nameLower.includes(keyword));
    });

    if (anyFemaleVoice) return anyFemaleVoice;

    // 3. Third priority: Natural or high-quality English voice
    const naturalEnglishVoice = voices.find((v) => {
      const lang = v.lang ? v.lang.toLowerCase() : '';
      return lang.startsWith('en') && (v.name.toLowerCase().includes('natural') || v.default);
    });

    if (naturalEnglishVoice) return naturalEnglishVoice;

    // 4. Graceful fallback: Default voice or first available voice
    return voices.find((v) => v.default) || voices[0] || null;
  };

  /**
   * Speaks the specified text with an articulate, professional female voice
   * applying optimized speech rate and pitch tuning.
   */
  const speakText = (text, options = {}) => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null;
    window.speechSynthesis.cancel(); // Stop any ongoing speech

    const clean = stripMarkdownForSpeech(text);
    if (!clean) return null;

    const utterance = new window.SpeechSynthesisUtterance(clean);
    const femaleVoice = getProfessionalFemaleVoice();

    if (femaleVoice) {
      utterance.voice = femaleVoice;
    }

    // Speech Rate & Pitch Tuning for articulate, executive tone
    utterance.rate = options.rate !== undefined ? options.rate : 1.0;
    utterance.pitch = options.pitch !== undefined ? options.pitch : 1.1;

    if (options.onStart) utterance.onstart = options.onStart;
    if (options.onEnd) utterance.onend = options.onEnd;
    if (options.onError) utterance.onerror = options.onError;

    window.speechSynthesis.speak(utterance);
    return utterance;
  };

  // Helper: Convert File URI to Base64 Data URL
  const convertUriToBase64 = async (uri) => {
    if (!uri) return null;
    if (uri.startsWith('data:')) return uri;

    try {
      const response = await fetch(uri);
      const blob = await response.blob();
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    } catch (err) {
      console.warn('Failed to convert URI to Base64:', err);
      return null;
    }
  };

  // ---------------------------------------------------------------------------
  // Image Selection Handler (expo-image-picker triggered by + button)
  // ---------------------------------------------------------------------------
  const handlePickImage = async () => {
    if (isLoading || isRecording || isLiveVoiceOpen) return;

    try {
      if (Platform.OS !== 'web') {
        const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (status !== 'granted') {
          Alert.alert(
            'Permission Required',
            'Please grant photo library access to upload and analyze images.'
          );
          return;
        }
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        quality: 0.7,
        base64: true,
      });

      if (!result.canceled && result.assets && result.assets.length > 0) {
        const asset = result.assets[0];
        let base64Url = null;

        if (asset.base64) {
          const mimeType = asset.mimeType || 'image/jpeg';
          base64Url = asset.base64.startsWith('data:')
            ? asset.base64
            : `data:${mimeType};base64,${asset.base64}`;
        } else {
          base64Url = await convertUriToBase64(asset.uri);
        }

        setSelectedImage({
          uri: asset.uri,
          base64: base64Url,
        });
      }
    } catch (err) {
      console.error('Image selection error:', err);
      Alert.alert('Error', 'Unable to select image. Please try again.');
    }
  };

  const handleRemoveImage = () => {
    setSelectedImage(null);
  };

  // ---------------------------------------------------------------------------
  // Standard Voice Recording Handlers (Chat Bar)
  // ---------------------------------------------------------------------------
  const startRecording = async () => {
    if (isLoading || isRecording || isLiveVoiceOpen) return;

    try {
      const permission = await Audio.requestPermissionsAsync();
      if (permission.status !== 'granted') {
        Alert.alert(
          'Microphone Permission Required',
          'Please allow microphone access to record voice messages.'
        );
        return;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording: newRecording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );

      setRecording(newRecording);
      setIsRecording(true);
      setRecordingDuration(0);

      recordingTimerRef.current = setInterval(() => {
        setRecordingDuration((prev) => prev + 1);
      }, 1000);

    } catch (err) {
      console.error('Failed to start voice recording:', err);
      Alert.alert('Recording Error', 'Could not access the microphone.');
      setIsRecording(false);
    }
  };

  const stopAndSendRecording = async () => {
    if (!recording || !isRecording) return;

    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }

    const currentDuration = recordingDuration;
    setIsRecording(false);
    setIsLoading(true);

    try {
      await recording.stopAndUnloadAsync();
      const audioUri = recording.getURI();
      setRecording(null);

      if (!audioUri) {
        throw new Error('No audio file was generated.');
      }

      const tempUserMsgId = `voice_user_${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: tempUserMsgId,
          role: 'user',
          text: `🎙️ Voice Note (${formatDuration(currentDuration)}) — Transcribing...`,
          imageUri: null,
          timestamp: formatTime(new Date()),
          isError: false,
        },
      ]);

      const formData = new FormData();
      formData.append('user_id', USER_ID);
      if (sessionId) {
        formData.append('session_id', sessionId);
      }

      if (Platform.OS === 'web') {
        const audioBlob = await fetch(audioUri).then((r) => r.blob());
        formData.append('audio', audioBlob, 'recording.webm');
      } else {
        formData.append('audio', {
          uri: audioUri,
          type: 'audio/m4a',
          name: 'recording.m4a',
        });
      }

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 45000);

      const response = await fetch(BACKEND_URL, {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      const json = await response.json();

      if (!response.ok || json.status === 'error') {
        const errorMsg = json.error?.message || `Server returned error status: ${response.status}`;
        throw new Error(errorMsg);
      }

      if (json.data?.session_id) {
        setSessionId(json.data.session_id);
      }

      const transcription = json.data?.transcription || json.data?.user_message || 'Voice Message';

      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === tempUserMsgId
            ? { ...msg, text: `🎙️ "${transcription}"` }
            : msg
        )
      );

      setMessages((prev) => [
        ...prev,
        {
          id: `agent_${Date.now()}`,
          role: 'assistant',
          text: json.data?.agent_response || 'No response content returned.',
          imageUri: null,
          timestamp: formatTime(new Date()),
          isError: false,
        },
      ]);

    } catch (err) {
      console.error('Audio processing error:', err);
      setMessages((prev) => [
        ...prev,
        {
          id: `error_${Date.now()}`,
          role: 'assistant',
          text: `⚠️ Voice Error: ${err.message || 'Failed to transcribe voice note.'}`,
          imageUri: null,
          timestamp: formatTime(new Date()),
          isError: true,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const cancelRecording = async () => {
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
    setIsRecording(false);
    setRecordingDuration(0);
    if (recording) {
      try {
        await recording.stopAndUnloadAsync();
      } catch (e) {}
      setRecording(null);
    }
  };

  const handleToggleRecording = () => {
    if (isRecording) {
      stopAndSendRecording();
    } else {
      startRecording();
    }
  };

  // ---------------------------------------------------------------------------
  // Web Speech Synthesis (TTS) Voice Playback Handler (Speaker 🔊 Button)
  // ---------------------------------------------------------------------------
  const handlePlayMessageAudio = (message) => {
    if (!message || !message.text) return;

    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      Alert.alert(
        'Speech Synthesis Unavailable',
        'Your current browser or device platform does not support native speech synthesis.'
      );
      return;
    }

    if (playingMessageId === message.id) {
      window.speechSynthesis.cancel();
      setPlayingMessageId(null);
      return;
    }

    window.speechSynthesis.cancel();
    setPlayingMessageId(null);

    speakText(message.text, {
      rate: 1.0,
      pitch: 1.1,
      onStart: () => {
        setPlayingMessageId(message.id);
      },
      onEnd: () => {
        setPlayingMessageId(null);
      },
      onError: (e) => {
        if (e.error !== 'canceled' && e.error !== 'interrupted') {
          console.warn('SpeechSynthesis error:', e);
        }
        setPlayingMessageId(null);
      },
    });
    setPlayingMessageId(message.id);
  };

  // ---------------------------------------------------------------------------
  // Live Voice Mode Handlers (Continuous Speech-to-Speech with Auto-Stop VAD)
  // ---------------------------------------------------------------------------
  const handleOpenLiveVoice = () => {
    // Stop any ongoing in-bar actions or speech
    cancelRecording();
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    setPlayingMessageId(null);

    setIsLiveVoiceOpen(true);
    isLiveVoiceOpenRef.current = true;
    setLiveVoiceStatus('recording');
    setLiveTranscript('');
    setLiveAgentText('Listening for your voice... Speak anytime.');

    // Auto-start recording & VAD when opening live voice mode
    setTimeout(() => {
      if (isLiveVoiceOpenRef.current) {
        startLiveVoiceRecording();
      }
    }, 350);
  };

  const handleCloseLiveVoice = async () => {
    isLiveVoiceOpenRef.current = false;
    stopVad();

    if (liveTimerRef.current) {
      clearInterval(liveTimerRef.current);
      liveTimerRef.current = null;
    }
    if (liveRecordingRef.current) {
      try {
        await liveRecordingRef.current.stopAndUnloadAsync();
      } catch (e) {}
      liveRecordingRef.current = null;
    }
    if (liveSoundRef.current) {
      try {
        await liveSoundRef.current.stopAsync();
        await liveSoundRef.current.unloadAsync();
      } catch (e) {}
      liveSoundRef.current = null;
    }
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    isSendingLiveVoiceRef.current = false;
    setIsLiveVoiceOpen(false);
    setLiveVoiceStatus('idle');
    setLiveVoiceDuration(0);
    setHasSpokenVoice(false);
  };

  const startLiveVoiceRecording = async () => {
    if (isSendingLiveVoiceRef.current) return;
    if (!isLiveVoiceOpenRef.current) return;

    // Stop any active audio/speech and clean previous VAD
    interruptLiveVoice();
    stopVad();

    try {
      const permission = await Audio.requestPermissionsAsync();
      if (permission.status !== 'granted') {
        Alert.alert('Microphone Access Required', 'Please enable microphone access for voice chat.');
        setLiveVoiceStatus('idle');
        return;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording: newRecording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );

      liveRecordingRef.current = newRecording;
      isSendingLiveVoiceRef.current = false;
      setLiveVoiceStatus('recording');
      setLiveVoiceDuration(0);
      setHasSpokenVoice(false);
      vadHasSpokenRef.current = false;
      vadSpeechCounterRef.current = 0;
      vadLastSoundTimeRef.current = Date.now();

      // Live duration timer
      if (liveTimerRef.current) clearInterval(liveTimerRef.current);
      liveTimerRef.current = setInterval(() => {
        setLiveVoiceDuration((prev) => {
          // Safety cutoff: if user spoke and recording reaches 25s, auto-send
          if (prev >= 25 && vadHasSpokenRef.current) {
            stopAndSendLiveVoice();
          }
          return prev + 1;
        });
      }, 1000);

      // Web Audio API VAD (Voice Activity Detection) on Expo Web
      if (Platform.OS === 'web' && typeof window !== 'undefined') {
        try {
          const AudioContextClass = window.AudioContext || window.webkitAudioContext;
          if (AudioContextClass && navigator.mediaDevices?.getUserMedia) {
            const audioCtx = new AudioContextClass();
            vadAudioCtxRef.current = audioCtx;

            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            vadStreamRef.current = stream;

            const source = audioCtx.createMediaStreamSource(stream);
            const analyser = audioCtx.createAnalyser();
            analyser.fftSize = 256;
            analyser.smoothingTimeConstant = 0.2;
            source.connect(analyser);

            const bufferLength = analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);

            const SILENCE_TIMEOUT_MS = 2200; // 2.2 seconds of silence after speech triggers auto-stop
            const SPEECH_VOLUME_THRESHOLD = 14; // Speech energy threshold

            vadIntervalRef.current = setInterval(() => {
              if (liveVoiceStatusRef.current !== 'recording' || isSendingLiveVoiceRef.current) {
                return;
              }

              analyser.getByteFrequencyData(dataArray);
              let sum = 0;
              for (let i = 0; i < bufferLength; i++) {
                sum += dataArray[i];
              }
              const avgVolume = sum / bufferLength;

              if (avgVolume > SPEECH_VOLUME_THRESHOLD) {
                vadSpeechCounterRef.current += 1;
                // If sustained sound detected for ~200ms, mark that user has spoken
                if (vadSpeechCounterRef.current >= 2) {
                  vadHasSpokenRef.current = true;
                  setHasSpokenVoice(true);
                }
                vadLastSoundTimeRef.current = Date.now();
              } else {
                vadSpeechCounterRef.current = 0;
                // Once speech was registered, detect 2.2s of continuous silence
                if (vadHasSpokenRef.current) {
                  const silenceElapsed = Date.now() - vadLastSoundTimeRef.current;
                  if (silenceElapsed >= SILENCE_TIMEOUT_MS) {
                    stopAndSendLiveVoice();
                  }
                }
              }
            }, 100);
          }
        } catch (vadErr) {
          console.warn('Web Audio VAD setup note:', vadErr);
        }
      }

      // Native Mobile metering fallback
      if (Platform.OS !== 'web' && newRecording) {
        newRecording.setOnRecordingStatusUpdate((status) => {
          if (!status.isRecording || isSendingLiveVoiceRef.current) return;
          if (status.metering !== undefined) {
            if (status.metering > -42) {
              vadHasSpokenRef.current = true;
              setHasSpokenVoice(true);
              vadLastSoundTimeRef.current = Date.now();
            } else if (vadHasSpokenRef.current) {
              if (Date.now() - vadLastSoundTimeRef.current >= 2200) {
                stopAndSendLiveVoice();
              }
            }
          }
        });
      }

    } catch (err) {
      console.error('Failed to start live recording:', err);
      Alert.alert('Recording Error', 'Could not access the microphone.');
      setLiveVoiceStatus('idle');
      stopVad();
    }
  };

  const stopAndSendLiveVoice = async () => {
    if (isSendingLiveVoiceRef.current || !liveRecordingRef.current) return;
    if (liveVoiceStatusRef.current !== 'recording') return;

    isSendingLiveVoiceRef.current = true;

    if (liveTimerRef.current) {
      clearInterval(liveTimerRef.current);
      liveTimerRef.current = null;
    }

    // Stop VAD monitoring
    stopVad();

    // Show live state: "Processing your voice..."
    setLiveVoiceStatus('thinking');

    const rec = liveRecordingRef.current;
    liveRecordingRef.current = null;

    try {
      await rec.stopAndUnloadAsync();
      const audioUri = rec.getURI();

      if (!audioUri) {
        throw new Error('No audio captured.');
      }

      const formData = new FormData();
      formData.append('user_id', USER_ID);
      formData.append('return_audio', 'true');
      if (sessionId) {
        formData.append('session_id', sessionId);
      }

      if (Platform.OS === 'web') {
        const audioBlob = await fetch(audioUri).then((r) => r.blob());
        if (!audioBlob || audioBlob.size < 200) {
          // Silent or empty recording captured, safely resume listening
          isSendingLiveVoiceRef.current = false;
          setLiveVoiceStatus('recording');
          startLiveVoiceRecording();
          return;
        }
        formData.append('audio', audioBlob, 'recording.webm');
      } else {
        formData.append('audio', {
          uri: audioUri,
          type: 'audio/m4a',
          name: 'recording.m4a',
        });
      }

      const voiceChatUrl = BACKEND_URL.replace('/agent', '/voice-chat');

      // Enforce a 25-second safety timeout so requests never hang indefinitely
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 25000);

      let response;
      try {
        response = await fetch(voiceChatUrl, {
          method: 'POST',
          body: formData,
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timeoutId);
      }

      const json = await response.json();
      if (!response.ok || json.status === 'error') {
        throw new Error(json.error?.message || `Voice server error (${response.status})`);
      }

      // If user closed the modal while waiting for response, discard playback
      if (!isLiveVoiceOpenRef.current) {
        return;
      }

      if (json.data?.session_id) {
        setSessionId(json.data.session_id);
      }

      const userTranscript = json.data?.transcription || 'Voice message';
      const agentReply = json.data?.agent_response || 'No response returned.';
      const responseAudioUrl = json.data?.response_audio_url;

      setLiveTranscript(userTranscript);
      setLiveAgentText(agentReply);

      // Persist to main conversation history
      setMessages((prev) => [
        ...prev,
        {
          id: `live_user_${Date.now()}`,
          role: 'user',
          text: `🎙️ "${userTranscript}"`,
          imageUri: null,
          timestamp: formatTime(new Date()),
          isError: false,
        },
        {
          id: `live_agent_${Date.now()}`,
          role: 'assistant',
          text: agentReply,
          imageUri: null,
          timestamp: formatTime(new Date()),
          isError: false,
        },
      ]);

      // Show live state: "Muse is speaking..."
      setLiveVoiceStatus('speaking');

      if (responseAudioUrl) {
        try {
          const serverOrigin = BACKEND_URL.replace('/api/agent', '');
          const fullAudioUrl = `${serverOrigin}${responseAudioUrl}`;

          await Audio.setAudioModeAsync({
            allowsRecordingIOS: false,
            playsInSilentModeIOS: true,
            shouldDuckAndroid: true,
          });

          const { sound } = await Audio.Sound.createAsync(
            { uri: fullAudioUrl },
            { shouldPlay: true }
          );

          liveSoundRef.current = sound;
          sound.setOnPlaybackStatusUpdate((status) => {
            if (status.didJustFinish) {
              sound.unloadAsync().catch(() => {});
              liveSoundRef.current = null;
              // Continuous loop: automatically listen again when Muse finishes speaking
              if (isLiveVoiceOpenRef.current) {
                setTimeout(() => {
                  if (isLiveVoiceOpenRef.current) {
                    startLiveVoiceRecording();
                  }
                }, 300);
              } else {
                setLiveVoiceStatus('idle');
              }
            }
          });
        } catch (audioErr) {
          console.warn('Audio.Sound playback failed, attempting speech synthesis fallback:', audioErr);
          playSpeechSynthesisFallback(agentReply);
        }
      } else {
        playSpeechSynthesisFallback(agentReply);
      }

    } catch (err) {
      console.error('Live voice processing error:', err);
      // Immediately reset thinking status to avoid freezing UI
      setLiveVoiceStatus('idle');
      const errorMsg = err.name === 'AbortError'
        ? 'Voice request timed out. Tap orb or speak again.'
        : (err.message || 'Could not process audio.');
      setLiveAgentText(errorMsg);

      if (isLiveVoiceOpenRef.current) {
        // Automatically recover and listen again after 1.5s
        setTimeout(() => {
          if (isLiveVoiceOpenRef.current) {
            startLiveVoiceRecording();
          }
        }, 1500);
      }
    } finally {
      isSendingLiveVoiceRef.current = false;
    }
  };

  const playSpeechSynthesisFallback = (text) => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      speakText(text, {
        rate: 1.0,
        pitch: 1.1,
        onEnd: () => {
          // Continuous loop: automatically listen again after speech ends
          if (isLiveVoiceOpenRef.current) {
            setTimeout(() => {
              if (isLiveVoiceOpenRef.current) {
                startLiveVoiceRecording();
              }
            }, 300);
          } else {
            setLiveVoiceStatus('idle');
          }
        },
        onError: (e) => {
          if (isLiveVoiceOpenRef.current && e.error !== 'canceled') {
            setTimeout(() => {
              if (isLiveVoiceOpenRef.current) {
                startLiveVoiceRecording();
              }
            }, 300);
          } else {
            setLiveVoiceStatus('idle');
          }
        },
      });
    } else {
      if (isLiveVoiceOpenRef.current) {
        startLiveVoiceRecording();
      } else {
        setLiveVoiceStatus('idle');
      }
    }
  };

  const interruptLiveVoice = () => {
    if (liveSoundRef.current) {
      liveSoundRef.current.stopAsync().catch(() => {});
      liveSoundRef.current.unloadAsync().catch(() => {});
      liveSoundRef.current = null;
    }
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    setLiveVoiceStatus('idle');
  };

  const interruptAndListen = () => {
    interruptLiveVoice();
    setTimeout(() => {
      if (isLiveVoiceOpenRef.current) {
        startLiveVoiceRecording();
      }
    }, 250);
  };

  const handleOrbPress = () => {
    if (liveVoiceStatus === 'speaking') {
      interruptAndListen();
    } else if (liveVoiceStatus === 'thinking') {
      // Tap while thinking unlocks and restarts listening immediately
      isSendingLiveVoiceRef.current = false;
      setLiveVoiceStatus('idle');
      startLiveVoiceRecording();
    } else if (liveVoiceStatus === 'recording') {
      stopAndSendLiveVoice();
    } else if (liveVoiceStatus === 'idle') {
      startLiveVoiceRecording();
    }
  };

  // ---------------------------------------------------------------------------
  // Reset Conversation
  // ---------------------------------------------------------------------------
  const handleResetSession = () => {
    setSessionId(null);
    setSelectedImage(null);
    cancelRecording();
    interruptLiveVoice();
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    setPlayingMessageId(null);
    setMessages([
      {
        id: `reset_${Date.now()}`,
        role: 'assistant',
        text: 'Conversation reset. Starting a fresh session!',
        imageUri: null,
        timestamp: formatTime(new Date()),
        isError: false,
      },
    ]);
  };

  // ---------------------------------------------------------------------------
  // API Send Handler (Multimodal Text + Image)
  // ---------------------------------------------------------------------------
  const handleSendMessage = async () => {
    const trimmedMessage = inputText.trim();
    const hasImage = selectedImage !== null;

    if ((!trimmedMessage && !hasImage) || isLoading || isRecording) return;

    const activeImage = selectedImage;
    const finalUserText = trimmedMessage || (hasImage ? 'Please analyze this attached image.' : '');

    const userMsgId = `user_${Date.now()}`;
    const userMessage = {
      id: userMsgId,
      role: 'user',
      text: finalUserText,
      imageUri: activeImage ? activeImage.uri : null,
      timestamp: formatTime(new Date()),
      isError: false,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputText('');
    setSelectedImage(null);
    setIsLoading(true);

    const payload = {
      user_id: USER_ID,
      message: finalUserText,
      ...(sessionId ? { session_id: sessionId } : {}),
      ...(activeImage?.base64 ? { image_base64: activeImage.base64 } : {}),
    };

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 35000);

    try {
      const response = await fetch(BACKEND_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      const json = await response.json();

      if (!response.ok || json.status === 'error') {
        const errorMsg =
          json.error?.message ||
          `Server returned error status: ${response.status}`;
        throw new Error(errorMsg);
      }

      if (json.data?.session_id) {
        setSessionId(json.data.session_id);
      }

      const agentMessage = {
        id: `agent_${Date.now()}`,
        role: 'assistant',
        text: json.data?.agent_response || 'No response content returned.',
        imageUri: null,
        timestamp: formatTime(new Date()),
        isError: false,
      };

      setMessages((prev) => [...prev, agentMessage]);
    } catch (error) {
      clearTimeout(timeoutId);

      let displayedError = 'An unexpected connection error occurred.';
      if (error.name === 'AbortError') {
        displayedError = 'Request timed out waiting for AI response. Please try again.';
      } else if (error.message && error.message.includes('Network request failed')) {
        displayedError = `Cannot reach backend at ${BACKEND_URL}. Ensure Flask server is running and accessible on this network.`;
      } else {
        displayedError = error.message;
      }

      setMessages((prev) => [
        ...prev,
        {
          id: `error_${Date.now()}`,
          role: 'assistant',
          text: `⚠️ Error: ${displayedError}`,
          imageUri: null,
          timestamp: formatTime(new Date()),
          isError: true,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (Platform.OS === 'web') {
      if (e.nativeEvent.key === 'Enter' && !e.nativeEvent.shiftKey) {
        e.preventDefault();
        handleSendMessage();
      }
    }
  };

  const handleSubmitEditing = () => {
    if (Platform.OS !== 'web') {
      handleSendMessage();
    }
  };

  const canSend = (inputText.trim().length > 0 || selectedImage !== null) && !isLoading && !isRecording;

  // ---------------------------------------------------------------------------
  // Message Item Renderer (ChatGPT / Claude Professional Aesthetics)
  // ---------------------------------------------------------------------------
  const renderMessageItem = ({ item }) => {
    const isUser = item.role === 'user';

    return (
      <View
        style={[
          styles.messageRow,
          isUser ? styles.messageRowUser : styles.messageRowAgent,
        ]}
      >
        <View style={styles.bubbleContainer}>
          <Text style={[styles.roleLabel, isUser ? styles.roleLabelUser : styles.roleLabelAgent]}>
            {isUser ? 'You' : '🤖 Muse Agent'}
          </Text>

          <View
            style={[
              styles.bubble,
              isUser
                ? styles.userBubble
                : item.isError
                  ? styles.errorBubble
                  : styles.agentBubble,
            ]}
          >
            {item.imageUri && (
              <View style={styles.bubbleImageWrapper}>
                <Image
                  source={{ uri: item.imageUri }}
                  style={styles.bubbleImage}
                  resizeMode="cover"
                />
              </View>
            )}

            <Text
              style={[
                styles.messageText,
                item.isError && styles.errorText,
              ]}
              selectable
            >
              {item.text}
            </Text>

            {/* Turn Timestamp & Agent Speaker Playback Button */}
            {isUser ? (
              <Text style={[styles.timestampText, styles.timestampTextUser]}>
                {item.timestamp}
              </Text>
            ) : (
              <View style={styles.bubbleFooter}>
                <Text style={styles.timestampText}>{item.timestamp}</Text>
                {!item.isError && (
                  <TouchableOpacity
                    style={[
                      styles.speakerButton,
                      playingMessageId === item.id && styles.speakerButtonPlaying,
                    ]}
                    onPress={() => handlePlayMessageAudio(item)}
                    activeOpacity={0.7}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    accessibilityLabel={playingMessageId === item.id ? "Stop voice audio" : "Play response audio"}
                  >
                    <Text style={styles.speakerIcon}>
                      {playingMessageId === item.id ? '⏹️' : '🔊'}
                    </Text>
                    <Text
                      style={[
                        styles.speakerText,
                        playingMessageId === item.id && styles.speakerTextPlaying,
                      ]}
                    >
                      {playingMessageId === item.id ? 'Speaking...' : 'Listen'}
                    </Text>
                  </TouchableOpacity>
                )}
              </View>
            )}
          </View>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar barStyle="light-content" backgroundColor="#0F172A" />

      {/* Modern Header Bar */}
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Text style={styles.headerTitle}>✨ Muse Personal AI</Text>
          <View style={styles.statusBadge}>
            <View style={styles.statusDot} />
            <Text style={styles.statusText}>
              {sessionId ? 'Active Context' : 'Online • Vision & Voice'}
            </Text>
          </View>
        </View>
        <View style={styles.headerRight}>
          {/* Live Voice Mode Launch Button (Gemini Live Style) */}
          <TouchableOpacity
            onPress={handleOpenLiveVoice}
            style={styles.liveVoiceButton}
            activeOpacity={0.8}
            accessibilityLabel="Open Live Voice Conversation"
          >
            <View style={styles.liveVoiceButtonDot} />
            <Text style={styles.liveVoiceButtonText}>Live Voice 📞</Text>
          </TouchableOpacity>

          <TouchableOpacity
            onPress={handleResetSession}
            style={styles.resetButton}
            activeOpacity={0.7}
          >
            <Text style={styles.resetButtonText}>+ New</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Main Conversation Stream */}
      <KeyboardAvoidingView
        style={styles.keyboardContainer}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 10 : 0}
      >
        <FlatList
          ref={flatListRef}
          data={messages}
          keyExtractor={(item) => item.id}
          renderItem={renderMessageItem}
          contentContainerStyle={styles.messageList}
          onContentSizeChange={scrollToBottom}
          onLayout={scrollToBottom}
        />

        {/* Thinking / Agent Processing Indicator */}
        {isLoading && (
          <View style={styles.thinkingContainer}>
            <ActivityIndicator size="small" color="#38BDF8" />
            <Text style={styles.thinkingText}>
              {selectedImage
                ? 'Inspecting image & reasoning...'
                : 'Muse is thinking & transcribing...'}
            </Text>
          </View>
        )}

        {/* Sleek Image Attachment Preview Card */}
        {selectedImage && (
          <View style={styles.previewCard}>
            <View style={styles.previewLeft}>
              <Image source={{ uri: selectedImage.uri }} style={styles.previewThumbnail} />
              <View style={styles.previewMeta}>
                <Text style={styles.previewTitle}>Attached Image</Text>
                <Text style={styles.previewSubtitle}>Ready for Vision Perception</Text>
              </View>
            </View>
            <TouchableOpacity
              style={styles.removeImageButton}
              onPress={handleRemoveImage}
              activeOpacity={0.7}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              accessibilityLabel="Remove image"
            >
              <Text style={styles.removeImageText}>✕</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Modern AI Assistant Capsule Input Bar (ChatGPT / Gemini Style) */}
        <View style={styles.inputOuterContainer}>
          <View style={[styles.inputInnerContainer, isRecording && styles.inputInnerContainerRecording]}>
            {isRecording ? (
              /* Sleek In-Bar Voice Recording State (Gemini / ChatGPT Style) */
              <View style={styles.recordingInBarContainer}>
                <View style={styles.recordingInBarLeft}>
                  <Animated.View
                    style={[
                      styles.recordingPulsingDot,
                      { opacity: pulseAnim },
                    ]}
                  />
                  <Text style={styles.recordingInBarTimer}>
                    {formatDuration(recordingDuration)}
                  </Text>

                  <View style={styles.audioWaveContainer}>
                    <Animated.View style={[styles.audioWaveBar, { transform: [{ scaleY: waveAnim1 }] }]} />
                    <Animated.View style={[styles.audioWaveBar, { transform: [{ scaleY: waveAnim2 }] }]} />
                    <Animated.View style={[styles.audioWaveBar, { transform: [{ scaleY: waveAnim3 }] }]} />
                    <Animated.View style={[styles.audioWaveBar, { transform: [{ scaleY: waveAnim4 }] }]} />
                  </View>

                  <Text style={styles.recordingListeningText}>Listening...</Text>
                </View>

                <View style={styles.recordingInBarActions}>
                  <TouchableOpacity
                    style={styles.recordingCancelButton}
                    onPress={cancelRecording}
                    activeOpacity={0.7}
                    accessibilityLabel="Cancel Recording"
                  >
                    <Text style={styles.recordingCancelIcon}>✕</Text>
                  </TouchableOpacity>

                  <TouchableOpacity
                    style={styles.recordingSendButton}
                    onPress={stopAndSendRecording}
                    activeOpacity={0.8}
                    accessibilityLabel="Finish and Send Voice Recording"
                  >
                    <Text style={styles.recordingSendIcon}>✓</Text>
                  </TouchableOpacity>
                </View>
              </View>
            ) : (
              /* Regular Text Input & Attachment Bar */
              <>
                <TouchableOpacity
                  style={styles.plusButton}
                  onPress={handlePickImage}
                  disabled={isLoading}
                  activeOpacity={0.7}
                  accessibilityLabel="Attach Image from Gallery"
                >
                  <Text style={styles.plusButtonIcon}>+</Text>
                </TouchableOpacity>

                <TextInput
                  style={styles.textInput}
                  placeholder={
                    selectedImage
                      ? 'Ask about this image...'
                      : 'Message Muse...'
                  }
                  placeholderTextColor="#64748B"
                  value={inputText}
                  onChangeText={setInputText}
                  onKeyPress={handleKeyPress}
                  onSubmitEditing={handleSubmitEditing}
                  multiline={true}
                  blurOnSubmit={false}
                  returnKeyType="send"
                  maxLength={3000}
                  editable={!isLoading}
                />

                <View style={styles.rightActionsContainer}>
                  {(!inputText.trim() || selectedImage) && (
                    <TouchableOpacity
                      style={styles.micButton}
                      onPress={handleToggleRecording}
                      disabled={isLoading}
                      activeOpacity={0.7}
                      accessibilityLabel="Record Voice Message"
                    >
                      <Text style={styles.micButtonIcon}>🎙️</Text>
                    </TouchableOpacity>
                  )}

                  {canSend && (
                    <TouchableOpacity
                      style={styles.sendButton}
                      onPress={handleSendMessage}
                      activeOpacity={0.8}
                      accessibilityLabel="Send message"
                    >
                      <Text style={styles.sendButtonArrow}>↑</Text>
                    </TouchableOpacity>
                  )}
                </View>
              </>
            )}
          </View>
        </View>
      </KeyboardAvoidingView>

      {/* =========================================================================
          Live Voice Conversation Mode (Gemini Live / ChatGPT Voice Mode Overlay)
         ========================================================================= */}
      <Modal
        visible={isLiveVoiceOpen}
        animationType="slide"
        transparent={false}
        onRequestClose={handleCloseLiveVoice}
      >
        <SafeAreaView style={styles.liveVoiceSafeArea}>
          <StatusBar barStyle="light-content" backgroundColor="#090D16" />

          {/* Top Bar */}
          <View style={styles.liveVoiceHeader}>
            <View style={styles.liveVoiceHeaderTitleRow}>
              <View style={styles.liveVoiceHeaderPulseDot} />
              <Text style={styles.liveVoiceHeaderTitle}>Muse Live Conversation</Text>
            </View>
            <TouchableOpacity
              style={styles.liveVoiceCloseButton}
              onPress={handleCloseLiveVoice}
              activeOpacity={0.7}
              accessibilityLabel="Exit Voice Mode"
            >
              <Text style={styles.liveVoiceCloseIcon}>✕</Text>
            </TouchableOpacity>
          </View>

          {/* Center Stage: Glowing Concentric Halo / Orb */}
          <View style={styles.liveVoiceCenterStage}>
            <TouchableOpacity
              activeOpacity={0.85}
              onPress={handleOrbPress}
              accessibilityLabel="Voice Mode Orb"
            >
              <View style={styles.orbWrapper}>
                {/* Outer Ring Animation */}
                <Animated.View
                  style={[
                    styles.orbHaloRing,
                    styles[`orbHaloRing_${liveVoiceStatus}`] || styles.orbHaloRing_idle,
                    {
                      transform: [{ scale: orbRingAnim }],
                      opacity: orbOpacityAnim,
                    },
                  ]}
                />

                {/* Core Orb */}
                <Animated.View
                  style={[
                    styles.orbCore,
                    styles[`orbCore_${liveVoiceStatus}`] || styles.orbCore_idle,
                    {
                      transform: [{ scale: orbScaleAnim }],
                    },
                  ]}
                >
                  <Text style={styles.orbIcon}>
                    {liveVoiceStatus === 'recording'
                      ? (hasSpokenVoice ? '🎙️' : '🎧')
                      : liveVoiceStatus === 'thinking'
                        ? '✨'
                        : liveVoiceStatus === 'speaking'
                          ? '🔊'
                          : '💬'}
                  </Text>
                </Animated.View>
              </View>
            </TouchableOpacity>

            {/* Dynamic Status Pill */}
            <View style={styles.liveVoiceStatusPill}>
              <View
                style={[
                  styles.liveStatusDot,
                  liveVoiceStatus === 'recording'
                    ? styles.liveStatusDot_recording
                    : liveVoiceStatus === 'thinking'
                      ? styles.liveStatusDot_thinking
                      : liveVoiceStatus === 'speaking'
                        ? styles.liveStatusDot_speaking
                        : styles.liveStatusDot_idle,
                ]}
              />
              <Text style={styles.liveVoiceStatusPillText}>
                {liveVoiceStatus === 'recording'
                  ? hasSpokenVoice
                    ? `Listening (${formatDuration(liveVoiceDuration)})...`
                    : 'Listening...'
                  : liveVoiceStatus === 'thinking'
                    ? 'Processing your voice...'
                    : liveVoiceStatus === 'speaking'
                      ? 'Muse is speaking...'
                      : 'Ready to listen'}
              </Text>
            </View>

            {/* Real-Time Live Transcript & Subtitle Card */}
            <View style={styles.liveTranscriptCard}>
              <Text style={styles.liveTranscriptCardLabel}>
                {liveVoiceStatus === 'recording'
                  ? 'Your Voice'
                  : liveVoiceStatus === 'thinking'
                    ? 'Processing'
                    : liveVoiceStatus === 'speaking'
                      ? 'Muse Response'
                      : 'Conversation'}
              </Text>
              <Text style={styles.liveTranscriptCardText} numberOfLines={4}>
                {liveVoiceStatus === 'speaking'
                  ? liveAgentText || 'Listening to your response...'
                  : liveVoiceStatus === 'thinking'
                    ? 'Converting your speech and formulating reply...'
                    : liveVoiceStatus === 'recording'
                      ? (hasSpokenVoice
                          ? 'Speech detected • Pausing will auto-send...'
                          : 'Speak naturally • Silence automatically sends')
                      : (liveAgentText || 'Tap the orb or start speaking.')}
              </Text>
            </View>
          </View>

          {/* Bottom Live Controls - Clean Hands-Free Interface (No Manual Finish & Send) */}
          <View style={styles.liveVoiceControls}>
            {liveVoiceStatus === 'speaking' ? (
              <TouchableOpacity
                style={[styles.liveMainActionButton, styles.liveActionInterrupt]}
                onPress={interruptAndListen}
                activeOpacity={0.8}
                accessibilityLabel="Interrupt Muse"
              >
                <Text style={styles.liveMainActionIcon}>⏹️</Text>
                <Text style={styles.liveMainActionLabel}>Interrupt & Speak</Text>
              </TouchableOpacity>
            ) : liveVoiceStatus === 'thinking' ? (
              <View style={[styles.liveHandsfreeNotice, styles.liveHandsfreeNoticeThinking]}>
                <ActivityIndicator size="small" color="#818CF8" style={{ marginRight: 8 }} />
                <Text style={styles.liveHandsfreeNoticeText}>Processing your voice...</Text>
              </View>
            ) : liveVoiceStatus === 'recording' ? (
              <View style={styles.liveHandsfreeNotice}>
                <View style={[styles.liveListeningPulseDot, hasSpokenVoice && styles.liveListeningPulseDotActive]} />
                <Text style={styles.liveHandsfreeNoticeText}>
                  {hasSpokenVoice
                    ? 'Listening... Auto-sends when you pause'
                    : 'Hands-Free Active • Auto-sends on pause'}
                </Text>
              </View>
            ) : (
              <TouchableOpacity
                style={[styles.liveMainActionButton, styles.liveActionSpeak]}
                onPress={startLiveVoiceRecording}
                activeOpacity={0.8}
                accessibilityLabel="Resume Live Voice"
              >
                <Text style={styles.liveMainActionIcon}>🎙️</Text>
                <Text style={styles.liveMainActionLabel}>Start Speaking</Text>
              </TouchableOpacity>
            )}

            <TouchableOpacity
              style={styles.liveEndCallButton}
              onPress={handleCloseLiveVoice}
              activeOpacity={0.7}
              accessibilityLabel="End Live Call"
            >
              <Text style={styles.liveEndCallText}>📞 End Call</Text>
            </TouchableOpacity>
          </View>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

// =============================================================================
// Professional Dark Theme Stylesheet (Inspired by ChatGPT & Gemini)
// =============================================================================
const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#0F172A',
  },
  keyboardContainer: {
    flex: 1,
  },

  // ---------------------------------------------------------------------------
  // Header
  // ---------------------------------------------------------------------------
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
    backgroundColor: '#0F172A',
  },
  headerLeft: {
    flexDirection: 'column',
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: '#F8FAFC',
    letterSpacing: -0.3,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 3,
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: '#10B981',
    marginRight: 6,
  },
  statusText: {
    fontSize: 11,
    color: '#94A3B8',
    fontWeight: '500',
  },
  liveVoiceButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    paddingHorizontal: 11,
    paddingVertical: 6,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: '#38BDF8',
    marginRight: 8,
  },
  liveVoiceButtonDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: '#38BDF8',
    marginRight: 6,
  },
  liveVoiceButtonText: {
    color: '#38BDF8',
    fontSize: 12,
    fontWeight: '700',
  },
  resetButton: {
    backgroundColor: '#1E293B',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: '#334155',
  },
  resetButtonText: {
    color: '#E2E8F0',
    fontSize: 12,
    fontWeight: '600',
  },

  // ---------------------------------------------------------------------------
  // Message Stream & Bubbles
  // ---------------------------------------------------------------------------
  messageList: {
    paddingHorizontal: 16,
    paddingVertical: 18,
  },
  messageRow: {
    flexDirection: 'row',
    marginBottom: 16,
  },
  messageRowUser: {
    justifyContent: 'flex-end',
  },
  messageRowAgent: {
    justifyContent: 'flex-start',
  },
  bubbleContainer: {
    maxWidth: '85%',
  },
  roleLabel: {
    fontSize: 11,
    fontWeight: '600',
    marginBottom: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  roleLabelUser: {
    color: '#60A5FA',
    alignSelf: 'flex-end',
  },
  roleLabelAgent: {
    color: '#94A3B8',
    alignSelf: 'flex-start',
  },
  bubble: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 18,
  },
  userBubble: {
    backgroundColor: '#2563EB',
    borderBottomRightRadius: 4,
    shadowColor: '#2563EB',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 3,
  },
  agentBubble: {
    backgroundColor: '#1E293B',
    borderBottomLeftRadius: 4,
    borderWidth: 1,
    borderColor: '#334155',
  },
  errorBubble: {
    backgroundColor: 'rgba(239, 68, 68, 0.12)',
    borderWidth: 1,
    borderColor: '#EF4444',
    borderBottomLeftRadius: 4,
  },
  bubbleImageWrapper: {
    borderRadius: 12,
    overflow: 'hidden',
    marginBottom: 10,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.15)',
  },
  bubbleImage: {
    width: 240,
    height: 170,
    backgroundColor: '#0F172A',
  },
  messageText: {
    fontSize: 15,
    lineHeight: 23,
    color: '#F8FAFC',
  },
  errorText: {
    color: '#FCA5A5',
  },
  timestampText: {
    fontSize: 10,
    color: '#64748B',
    marginTop: 6,
    alignSelf: 'flex-start',
  },
  timestampTextUser: {
    color: 'rgba(255, 255, 255, 0.65)',
    alignSelf: 'flex-end',
  },
  bubbleFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 8,
    paddingTop: 4,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255, 255, 255, 0.06)',
  },
  speakerButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#334155',
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#475569',
  },
  speakerButtonPlaying: {
    backgroundColor: 'rgba(56, 189, 248, 0.18)',
    borderColor: '#38BDF8',
  },
  speakerIcon: {
    fontSize: 11,
    marginRight: 4,
  },
  speakerText: {
    fontSize: 11,
    color: '#E2E8F0',
    fontWeight: '600',
  },
  speakerTextPlaying: {
    color: '#38BDF8',
  },

  // ---------------------------------------------------------------------------
  // Thinking Indicator
  // ---------------------------------------------------------------------------
  thinkingContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 22,
    paddingVertical: 10,
  },
  thinkingText: {
    fontSize: 13,
    color: '#38BDF8',
    marginLeft: 10,
    fontStyle: 'italic',
  },

  // ---------------------------------------------------------------------------
  // Image Attachment Preview Card
  // ---------------------------------------------------------------------------
  previewCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginHorizontal: 16,
    marginBottom: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: '#1E293B',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#334155',
  },
  previewLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  previewThumbnail: {
    width: 44,
    height: 44,
    borderRadius: 8,
    backgroundColor: '#0F172A',
    borderWidth: 1,
    borderColor: '#475569',
  },
  previewMeta: {
    marginLeft: 12,
    flex: 1,
  },
  previewTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#F8FAFC',
  },
  previewSubtitle: {
    fontSize: 11,
    color: '#38BDF8',
    marginTop: 2,
  },
  removeImageButton: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    borderWidth: 1,
    borderColor: '#EF4444',
    justifyContent: 'center',
    alignItems: 'center',
  },
  removeImageText: {
    color: '#EF4444',
    fontSize: 13,
    fontWeight: '700',
  },

  // ---------------------------------------------------------------------------
  // Modern AI Chat Input Bar (Gemini / ChatGPT Capsule Style)
  // ---------------------------------------------------------------------------
  inputOuterContainer: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: '#0F172A',
    borderTopWidth: 1,
    borderTopColor: '#1E293B',
  },
  inputInnerContainer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: '#1E293B',
    borderRadius: 26,
    borderWidth: 1,
    borderColor: '#334155',
    paddingHorizontal: 6,
    paddingVertical: 6,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 3,
    minHeight: 48,
  },
  inputInnerContainerRecording: {
    borderColor: '#EF4444',
    paddingVertical: 7,
    paddingHorizontal: 12,
  },

  // ---------------------------------------------------------------------------
  // Sleek In-Bar Voice Recording State (Gemini / ChatGPT Style)
  // ---------------------------------------------------------------------------
  recordingInBarContainer: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 36,
  },
  recordingInBarLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  recordingPulsingDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#EF4444',
    marginRight: 8,
  },
  recordingInBarTimer: {
    color: '#F8FAFC',
    fontSize: 14,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
    marginRight: 10,
  },
  audioWaveContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 18,
    marginRight: 8,
  },
  audioWaveBar: {
    width: 3,
    height: 16,
    borderRadius: 2,
    backgroundColor: '#38BDF8',
    marginHorizontal: 1.5,
  },
  recordingListeningText: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '500',
    fontStyle: 'italic',
  },
  recordingInBarActions: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  recordingCancelButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#334155',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  recordingCancelIcon: {
    color: '#94A3B8',
    fontSize: 14,
    fontWeight: '700',
  },
  recordingSendButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: '#2563EB',
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#2563EB',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.4,
    shadowRadius: 3,
    elevation: 3,
  },
  recordingSendIcon: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '800',
  },

  // ---------------------------------------------------------------------------
  // Standard Text Input Bar Controls
  // ---------------------------------------------------------------------------
  plusButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: '#334155',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 2,
    marginLeft: 3,
    marginRight: 4,
  },
  plusButtonIcon: {
    color: '#F1F5F9',
    fontSize: 22,
    fontWeight: '400',
    lineHeight: 24,
    textAlign: 'center',
  },
  textInput: {
    flex: 1,
    minHeight: 38,
    maxHeight: 120,
    paddingHorizontal: 10,
    paddingTop: 8,
    paddingBottom: 8,
    fontSize: 15,
    color: '#F8FAFC',
    lineHeight: 20,
  },
  rightActionsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 2,
    marginRight: 3,
  },
  micButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: 'transparent',
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: 2,
  },
  micButtonIcon: {
    fontSize: 18,
  },
  sendButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: '#2563EB',
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: 6,
    shadowColor: '#2563EB',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.4,
    shadowRadius: 3,
    elevation: 3,
  },
  sendButtonArrow: {
    color: '#FFFFFF',
    fontSize: 17,
    fontWeight: '700',
  },

  // ===========================================================================
  // Live Voice Mode Styles (Gemini Live / ChatGPT Voice Mode Overlay)
  // ===========================================================================
  liveVoiceSafeArea: {
    flex: 1,
    backgroundColor: '#090D16',
  },
  liveVoiceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 22,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
  },
  liveVoiceHeaderTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  liveVoiceHeaderPulseDot: {
    width: 9,
    height: 9,
    borderRadius: 5,
    backgroundColor: '#10B981',
    marginRight: 8,
  },
  liveVoiceHeaderTitle: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: -0.3,
  },
  liveVoiceCloseButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#334155',
    justifyContent: 'center',
    alignItems: 'center',
  },
  liveVoiceCloseIcon: {
    color: '#94A3B8',
    fontSize: 14,
    fontWeight: '700',
  },
  liveVoiceCenterStage: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 24,
  },
  orbWrapper: {
    width: 180,
    height: 180,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 28,
  },
  orbHaloRing: {
    position: 'absolute',
    width: 170,
    height: 170,
    borderRadius: 85,
    borderWidth: 2,
  },
  orbHaloRing_idle: {
    borderColor: '#38BDF8',
  },
  orbHaloRing_recording: {
    borderColor: '#EF4444',
  },
  orbHaloRing_thinking: {
    borderColor: '#818CF8',
  },
  orbHaloRing_speaking: {
    borderColor: '#10B981',
  },
  orbCore: {
    width: 120,
    height: 120,
    borderRadius: 60,
    justifyContent: 'center',
    alignItems: 'center',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.6,
    shadowRadius: 20,
    elevation: 8,
  },
  orbCore_idle: {
    backgroundColor: '#1E293B',
    shadowColor: '#38BDF8',
    borderWidth: 2,
    borderColor: '#38BDF8',
  },
  orbCore_recording: {
    backgroundColor: '#7F1D1D',
    shadowColor: '#EF4444',
    borderWidth: 2,
    borderColor: '#EF4444',
  },
  orbCore_thinking: {
    backgroundColor: '#3730A3',
    shadowColor: '#818CF8',
    borderWidth: 2,
    borderColor: '#818CF8',
  },
  orbCore_speaking: {
    backgroundColor: '#064E3B',
    shadowColor: '#10B981',
    borderWidth: 2,
    borderColor: '#10B981',
  },
  orbIcon: {
    fontSize: 42,
  },
  liveVoiceStatusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#334155',
    marginBottom: 20,
  },
  liveStatusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  liveStatusDot_recording: {
    backgroundColor: '#EF4444',
  },
  liveStatusDot_thinking: {
    backgroundColor: '#818CF8',
  },
  liveStatusDot_speaking: {
    backgroundColor: '#10B981',
  },
  liveStatusDot_idle: {
    backgroundColor: '#94A3B8',
  },
  liveVoiceStatusPillText: {
    color: '#F8FAFC',
    fontSize: 14,
    fontWeight: '600',
  },
  liveHandsfreeNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1E293B',
    paddingHorizontal: 18,
    paddingVertical: 12,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: '#334155',
    marginBottom: 16,
  },
  liveHandsfreeNoticeThinking: {
    borderColor: '#818CF8',
  },
  liveListeningPulseDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#64748B',
    marginRight: 8,
  },
  liveListeningPulseDotActive: {
    backgroundColor: '#EF4444',
  },
  liveHandsfreeNoticeText: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '500',
  },
  liveTranscriptCard: {
    width: '100%',
    maxWidth: 420,
    backgroundColor: '#1E293B',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#334155',
    padding: 16,
    minHeight: 90,
  },
  liveTranscriptCardLabel: {
    color: '#94A3B8',
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 6,
  },
  liveTranscriptCardText: {
    color: '#F8FAFC',
    fontSize: 14,
    lineHeight: 20,
  },
  liveVoiceControls: {
    paddingHorizontal: 24,
    paddingBottom: 30,
    alignItems: 'center',
  },
  liveMainActionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 28,
    paddingVertical: 14,
    borderRadius: 30,
    marginBottom: 16,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 6,
    elevation: 4,
  },
  liveActionSpeak: {
    backgroundColor: '#2563EB',
    shadowColor: '#2563EB',
  },
  liveActionStop: {
    backgroundColor: '#EF4444',
    shadowColor: '#EF4444',
  },
  liveActionThinking: {
    backgroundColor: '#475569',
    shadowColor: '#475569',
  },
  liveActionInterrupt: {
    backgroundColor: '#D97706',
    shadowColor: '#D97706',
  },
  liveMainActionIcon: {
    fontSize: 18,
    marginRight: 8,
  },
  liveMainActionLabel: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '700',
  },
  liveEndCallButton: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 20,
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    borderWidth: 1,
    borderColor: '#EF4444',
  },
  liveEndCallText: {
    color: '#EF4444',
    fontSize: 13,
    fontWeight: '700',
  },
});
