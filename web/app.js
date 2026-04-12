// ============================================
// Real-Time Indian Language Translation
// Sonix STT → Llama Translation → ElevenLabs TTS
// ============================================

const API_BASE = 'http://localhost:5000';
const ASR_API = 'http://localhost:5002';
const TRANSLATION_API = 'http://localhost:5003';
const TTS_API = 'http://localhost:5005';

// 6 Target Indian Languages
const TARGET_LANGUAGES = {
    'ta': { name: 'Tamil', nativeName: 'தமிழ்', flag: '🇮🇳' },
    'en': { name: 'English', nativeName: 'English', flag: '🇮🇳' },
    'te': { name: 'Telugu', nativeName: 'తెలుగు', flag: '🇮🇳' },
    'ml': { name: 'Malayalam', nativeName: 'മലയാളം', flag: '🇮🇳' },
    'kn': { name: 'Kannada', nativeName: 'ಕನ್ನಡ', flag: '🇮🇳' },
    'hi': { name: 'Hindi', nativeName: 'हिंदी', flag: '🇮🇳' }
};

// State
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let currentTranscription = '';
let translationInProgress = false;
let audioStreams = {};
let currentStreamId = null;

// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener('DOMContentLoaded', async () => {
    console.log('🚀 Real-time Language Translation System initialized');
    
    // Create language cards
    initializeLanguageGrid();
    
    // Request microphone access
    await requestMicrophoneAccess();
    
    // Check services
    await checkServiceStatus();
    
    // Setup periodic status checks
    setInterval(checkServiceStatus, 30000);
});

function initializeLanguageGrid() {
    const grid = document.getElementById('languageGrid');
    
    for (const [code, lang] of Object.entries(TARGET_LANGUAGES)) {
        const card = document.createElement('div');
        card.className = 'language-card';
        card.id = `lang-${code}`;
        card.innerHTML = `
            <div class="language-header">
                <div class="language-name">${lang.flag} ${lang.name}</div>
                <div class="language-status" id="status-${code}">⏳ Waiting</div>
            </div>
            <div class="translation-text" id="text-${code}">Waiting for speech...</div>
            <div class="audio-player">
                <audio id="audio-${code}" controls style="width: 100%;">
                    <source id="source-${code}" type="audio/mp3">
                </audio>
            </div>
        `;
        grid.appendChild(card);
    }
}

async function requestMicrophoneAccess() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        console.log('✅ Microphone access granted');
        
        // Setup audio meter
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const analyser = audioContext.createAnalyser();
        const source = audioContext.createMediaStreamSource(stream);
        source.connect(analyser);
        
        analyseAudioLevel(analyser);
        window.audioStream = stream;
    } catch (error) {
        console.error('❌ Microphone access denied:', error);
        addLog('Microphone access required for recording', 'error');
    }
}

function analyseAudioLevel(analyser) {
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    
    function update() {
        analyser.getByteFrequencyData(dataArray);
        const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
        const percent = (average / 256) * 100;
        
        const meter = document.getElementById('audioMeter');
        if (meter) {
            meter.style.width = Math.min(percent, 100) + '%';
        }
        
        requestAnimationFrame(update);
    }
    
    update();
}

// ============================================================
// RECORDING
// ============================================================

function toggleRecording() {
    if (!window.audioStream) {
        addLog('Microphone not available', 'error');
        return;
    }

    if (!isRecording) {
        startRecording();
    } else {
        stopRecording();
    }
}

function startRecording() {
    audioChunks = [];
    currentStreamId = generateStreamId();
    
    mediaRecorder = new MediaRecorder(window.audioStream);
    
    mediaRecorder.ondataavailable = (event) => {
        audioChunks.push(event.data);
    };
    
    mediaRecorder.onstop = async () => {
        await processRecordedAudio();
    };
    
    mediaRecorder.start();
    isRecording = true;
    
    const btn = document.getElementById('recordBtn');
    btn.textContent = '⏹️ Stop Recording';
    btn.classList.add('recording');
    
    // Update display
    document.getElementById('transcriptionOutput').textContent = 'Recording...';
    updateStepStatus('step1', 'processing', 'Recording');
    addLog('🎙️ Recording started...', 'info');
}

function stopRecording() {
    if (mediaRecorder) {
        mediaRecorder.stop();
    }
    
    isRecording = false;
    
    const btn = document.getElementById('recordBtn');
    btn.textContent = '🔴 Press to Record';
    btn.classList.remove('recording');
    
    updateStepStatus('step1', 'done', 'Captured');
}

async function processRecordedAudio() {
    if (audioChunks.length === 0) {
        addLog('No audio recorded', 'error');
        return;
    }

    try {
        addLog('⏳ Processing audio...', 'info');
        updateStepStatus('step2', 'processing', 'Transcribing');
        
        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
        const base64Audio = await blobToBase64(audioBlob);
        
        // Call Sonix STT
        const response = await fetch(`${ASR_API}/api/v1/transcribe`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            mode: 'cors',
            body: JSON.stringify({
                stream_id: currentStreamId,
                audio_bytes: base64Audio,
                language: 'auto'
            })
        });

        if (!response.ok) {
            throw new Error(`ASR error: ${response.status}`);
        }

        const data = await response.json();
        currentTranscription = data.transcription || data.text || '';
        
        document.getElementById('transcriptionOutput').textContent = currentTranscription;
        updateStepStatus('step2', 'done', 'Transcribed');
        addLog(`📝 Text: "${currentTranscription}"`, 'success');
        
        // Start real-time translation
        await startRealTimeTranslation();
        
    } catch (error) {
        console.error('❌ Processing error:', error);
        updateStepStatus('step2', 'error', 'Failed');
        addLog(`Error: ${error.message}`, 'error');
    }
}

// ============================================================
// REAL-TIME TRANSLATION & TTS
// ============================================================

async function startRealTimeTranslation() {
    if (!currentTranscription) {
        addLog('No text to translate', 'error');
        return;
    }

    if (translationInProgress) {
        addLog('Translation already in progress', 'info');
        return;
    }

    translationInProgress = true;
    updateStepStatus('step3', 'processing', 'Translating');
    addLog('🤖 Starting parallel translation to 6 languages...', 'info');

    try {
        // Translate to all 6 languages in parallel
        const translationPromises = [];
        
        for (const [langCode, langInfo] of Object.entries(TARGET_LANGUAGES)) {
            translationPromises.push(
                translateAndSynthesize(langCode, currentTranscription)
            );
        }

        // Wait for all translations & TTS to complete
        await Promise.all(translationPromises);
        
        updateStepStatus('step3', 'done', 'All Translated');
        updateStepStatus('step4', 'done', 'Audio Ready');
        addLog('✅ All translations & audio generation complete!', 'success');
        
    } catch (error) {
        console.error('❌ Translation error:', error);
        updateStepStatus('step3', 'error', 'Failed');
        addLog(`Translation error: ${error.message}`, 'error');
    } finally {
        translationInProgress = false;
    }
}

async function translateAndSynthesize(langCode, text) {
    const langInfo = TARGET_LANGUAGES[langCode];
    
    try {
        // Update UI
        updateLanguageCard(langCode, 'Translating...');
        
        // Call Llama Translation
        const translationResponse = await fetch(`${TRANSLATION_API}/api/v1/translate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            mode: 'cors',
            body: JSON.stringify({
                stream_id: currentStreamId,
                text: text,
                target_language: langCode,
                model: 'llama'  // Use Llama for translation
            })
        });

        if (!translationResponse.ok) {
            throw new Error(`Translation error: ${translationResponse.status}`);
        }

        const translationData = await translationResponse.json();
        const translatedText = translationData.translation || translationData.text || '';
        
        addLog(`✓ ${langInfo.name}: "${translatedText.substring(0, 50)}..."`, 'success');
        
        // Update card with translation
        updateLanguageCard(langCode, `Generating audio...`, translatedText);
        
        // Call ElevenLabs TTS
        const ttsResponse = await fetch(`${TTS_API}/api/v1/synthesize`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            mode: 'cors',
            body: JSON.stringify({
                stream_id: currentStreamId,
                text: translatedText,
                language: langCode,
                speed: 1.0
            })
        });

        if (!ttsResponse.ok) {
            throw new Error(`TTS error: ${ttsResponse.status}`);
        }

        const ttsData = await ttsResponse.json();
        const audioBase64 = ttsData.audio_bytes;

        // Display audio
        const audioSource = document.getElementById(`source-${langCode}`);
        audioSource.src = `data:audio/mp3;base64,${audioBase64}`;
        
        const audio = document.getElementById(`audio-${langCode}`);
        audio.load();
        
        // Mark as complete
        const card = document.getElementById(`lang-${langCode}`);
        card.classList.add('active');
        
        updateLanguageCard(langCode, '✅ Ready', translatedText);
        addLog(`🔊 ${langInfo.name} audio ready`, 'success');
        
    } catch (error) {
        console.error(`Error translating to ${langCode}:`, error);
        updateLanguageCard(langCode, `❌ Error`, `Error: ${error.message}`);
        addLog(`${langInfo.name} error: ${error.message}`, 'error');
    }
}

function updateLanguageCard(langCode, status, translatedText = null) {
    const statusEl = document.getElementById(`status-${langCode}`);
    if (statusEl) {
        statusEl.textContent = status;
        statusEl.classList.toggle('done', status.includes('✅'));
        statusEl.classList.toggle('error', status.includes('❌'));
    }

    if (translatedText) {
        const textEl = document.getElementById(`text-${langCode}`);
        if (textEl) {
            textEl.textContent = translatedText;
        }
    }
}

// ============================================================
// SERVICE STATUS
// ============================================================

async function checkServiceStatus() {
    const services = [
        { port: 5000, name: 'API Gateway' },
        { port: 5002, name: 'Sonix STT' },
        { port: 5003, name: 'Llama Translate' },
        { port: 5005, name: 'ElevenLabs TTS' }
    ];

    let allOnline = true;
    
    for (const service of services) {
        try {
            const response = await fetch(`http://localhost:${service.port}/api/v1/health`, {
                mode: 'cors'
            });
            
            if (!response.ok) {
                allOnline = false;
            }
        } catch (error) {
            allOnline = false;
        }
    }

    const status = document.getElementById('status');
    if (status) {
        status.textContent = allOnline ? '✅ All Systems Online' : '⚠️ Some Services Offline';
        status.classList.toggle('offline', !allOnline);
    }
}

// ============================================================
// UTILITIES
// ============================================================

function updateStepStatus(stepId, status, text) {
    const el = document.getElementById(stepId);
    if (el) {
        el.textContent = text;
        el.classList.remove('processing', 'done', 'error');
        el.classList.add(status);
    }
}

function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
    });
}

function generateStreamId() {
    return `stream-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

function addLog(message, type = 'info') {
    const logs = document.getElementById('activityLogs');
    if (!logs) return;

    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    
    logs.appendChild(entry);
    logs.scrollTop = logs.scrollHeight;

    // Keep only last 50 entries
    const entries = logs.querySelectorAll('.log-entry');
    if (entries.length > 50) {
        entries[0].remove();
    }
}
