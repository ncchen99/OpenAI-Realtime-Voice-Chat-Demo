// 全域變數
let realtimeWs = null;
let textWs = null;
let audioContext = null;
let isRecording = false;
let isConnected = false;
let isTextConnected = false;
let currentStream = null;
let hasActiveResponse = false;
let currentTab = 'voice';

// 音頻設定
const AUDIO_CONFIG = {
    sampleRate: 24000,
    channels: 1,
    bitsPerSample: 16
};

// 優化的音頻播放管理
let audioQueue = [];
let isPlayingAudio = false;
let audioSourceNodes = []; // 追蹤音頻源節點

// 初始化頁面
document.addEventListener('DOMContentLoaded', function () {
    initAudioControls();
    initMarkdown();

    // 添加用戶交互監聽器以啟動音頻上下文
    document.addEventListener('click', function () {
        if (audioContext && audioContext.state === 'suspended') {
            audioContext.resume();
        }
    }, { once: true });
});

// 初始化 Markdown
function initMarkdown() {
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
            sanitize: false
        });
    }
}

// 初始化音頻控制
function initAudioControls() {
    const volumeSlider = document.getElementById('volume-slider');
    const volumeValue = document.getElementById('volume-value');

    if (volumeSlider && volumeValue) {
        volumeSlider.oninput = function () {
            const volume = Math.round(this.value * 100);
            volumeValue.textContent = volume + '%';
        };
    }
}

// 分頁切換功能
function switchTab(tabName) {
    // 更新按鈕狀態
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelector(`[onclick="switchTab('${tabName}')"]`).classList.add('active');

    // 更新內容顯示
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(`${tabName}-tab`).classList.add('active');

    currentTab = tabName;

    // 如果切換到語音模式時有文字連接，斷開它
    if (tabName === 'voice' && textWs) {
        textWs.close();
        textWs = null;
        isTextConnected = false;
        updateTextButtonState();
    }
}

// 語音模式 - 通話按鈕切換
async function toggleCall() {
    const callBtn = document.getElementById('call-btn');
    const callIcon = callBtn.querySelector('.call-icon');
    const callText = callBtn.querySelector('.call-text');

    if (!isRecording) {
        await startConversation();
        callBtn.classList.add('active');
        callIcon.textContent = '📞';
        callText.textContent = '通話中';
    } else {
        await endConversation();
        callBtn.classList.remove('active');
        callIcon.textContent = '📞';
        callText.textContent = '開始通話';
    }
}

// 開始語音對話
async function startConversation() {
    if (isConnected && isRecording) return;

    try {
        if (!isConnected) {
            updateStatus('正在連接...', 'connecting');

            realtimeWs = new WebSocket('ws://localhost:8000/realtime-voice');

            realtimeWs.onopen = async function () {
                isConnected = true;
                updateStatus('已連接', 'connected');
                await startRecording();
            };

            realtimeWs.onmessage = async function (event) {
                const data = JSON.parse(event.data);
                await handleRealtimeMessage(data);
            };

            realtimeWs.onclose = function () {
                isConnected = false;
                isRecording = false;
                hasActiveResponse = false;
                updateStatus('連接已斷開', 'disconnected');
                resetCallButton();
            };

            realtimeWs.onerror = function (error) {
                console.error('WebSocket 錯誤:', error);
                updateStatus('連接錯誤', 'disconnected');
                isConnected = false;
                isRecording = false;
                hasActiveResponse = false;
                resetCallButton();
            };
        } else {
            await startRecording();
        }

    } catch (error) {
        console.error('開始對話失敗:', error);
        updateStatus('連接失敗', 'disconnected');
        isConnected = false;
        isRecording = false;
        hasActiveResponse = false;
        resetCallButton();
    }
}

// 結束語音對話
async function endConversation() {
    try {
        if (hasActiveResponse && realtimeWs && realtimeWs.readyState === WebSocket.OPEN) {
            realtimeWs.send(JSON.stringify({
                type: 'response.cancel'
            }));
        }

        stopRecording();
        clearAudioQueue();

        if (realtimeWs) {
            realtimeWs.close();
        }

        updateStatus('通話已結束', 'disconnected');

    } catch (error) {
        console.error('結束對話失敗:', error);
    }
}

// 重置通話按鈕
function resetCallButton() {
    const callBtn = document.getElementById('call-btn');
    const callIcon = callBtn.querySelector('.call-icon');
    const callText = callBtn.querySelector('.call-text');

    if (callBtn) {
        callBtn.classList.remove('active');
        callIcon.textContent = '📞';
        callText.textContent = '開始通話';
    }
}

// 處理 Realtime API 訊息
async function handleRealtimeMessage(data) {
    console.log('收到事件:', data.type, data); // 添加調試日誌

    switch (data.type) {
        case 'session.created':
            console.log('會話已建立');
            updateStatus('對話已準備就緒', 'connected');
            break;

        case 'conversation.item.input_audio_transcription.completed':
            console.log('語音轉錄完成:', data.transcript);
            if (data.transcript && data.transcript.trim()) {
                addMessage('user', data.transcript, 'voice');
                updateStatus('🤔 正在思考...', 'connecting');

                // 轉錄完成後手動創建AI回應，確保順序正確
                if (realtimeWs && realtimeWs.readyState === WebSocket.OPEN) {
                    realtimeWs.send(JSON.stringify({
                        type: 'response.create'
                    }));
                    console.log('轉錄完成，手動創建回應');
                }
            }
            break;

        case 'conversation.item.input_audio_transcription.delta':
            console.log('語音轉錄 delta:', data.delta);
            // 根據 OpenAI 社群討論，delta 通常只在語音結束後才發送
            break;

        case 'response.created':
            hasActiveResponse = true;
            break;

        case 'response.audio_transcript.delta':
            updateAssistantMessage(data.delta, 'voice');
            break;

        case 'response.audio.delta':
            if (data.delta) {
                queueAudioChunk(data.delta);
            }
            break;

        case 'response.done':
            hasActiveResponse = false;
            finishAssistantMessage('voice');
            break;

        case 'input_audio_buffer.speech_started':
            console.log('檢測到語音開始');
            updateStatus('🎤 正在聆聽...', 'connecting');
            stopAllAudio(); // 立即停止所有音頻播放
            break;

        case 'input_audio_buffer.speech_stopped':
            console.log('檢測到語音結束，提交音頻緩衝區');
            updateStatus('🤔 正在轉錄...', 'connecting');
            // 提交音頻緩衝區以觸發轉錄
            if (realtimeWs && realtimeWs.readyState === WebSocket.OPEN) {
                realtimeWs.send(JSON.stringify({
                    type: 'input_audio_buffer.commit'
                }));
                console.log('已發送 input_audio_buffer.commit');
            }
            break;

        case 'input_audio_buffer.committed':
            console.log('音頻緩衝區已提交');
            break;

        case 'error':
            console.error('API 錯誤:', data.error);
            if (data.error.code !== 'response_cancel_not_active') {
                updateStatus('發生錯誤', 'disconnected');
            }
            break;

        default:
            console.log('未處理的事件:', data.type);
    }
}

// 開始錄音
async function startRecording() {
    try {
        currentStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: AUDIO_CONFIG.sampleRate,
                channelCount: AUDIO_CONFIG.channels,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        });

        audioContext = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: AUDIO_CONFIG.sampleRate
        });

        const source = audioContext.createMediaStreamSource(currentStream);
        const processor = audioContext.createScriptProcessor(4096, 1, 1);

        processor.onaudioprocess = function (event) {
            if (isRecording && realtimeWs && realtimeWs.readyState === WebSocket.OPEN) {
                const inputBuffer = event.inputBuffer.getChannelData(0);
                const pcmData = convertFloat32ToPCM16(inputBuffer);
                const base64Data = btoa(String.fromCharCode.apply(null, pcmData));

                realtimeWs.send(JSON.stringify({
                    type: 'input_audio_buffer.append',
                    audio: base64Data
                }));
            }
        };

        source.connect(processor);
        processor.connect(audioContext.destination);

        isRecording = true;
        updateStatus('🎤 請開始說話', 'connected');

    } catch (error) {
        console.error('錄音失敗:', error);
        updateStatus('錄音失敗', 'disconnected');
    }
}

// 停止錄音
function stopRecording() {
    isRecording = false;

    if (currentStream) {
        currentStream.getTracks().forEach(track => track.stop());
        currentStream = null;
    }

    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
}

// 文字模式連接
async function connectTextMode() {
    if (isTextConnected) return;

    try {
        updateStatus('正在連接文字模式...', 'connecting');

        textWs = new WebSocket('ws://localhost:8000/text-chat');

        textWs.onopen = function () {
            isTextConnected = true;
            updateStatus('文字模式已連接', 'connected');
            updateTextButtonState();
        };

        textWs.onmessage = async function (event) {
            const data = JSON.parse(event.data);
            await handleTextMessage(data);
        };

        textWs.onclose = function () {
            isTextConnected = false;
            updateStatus('文字模式已斷開', 'disconnected');
            updateTextButtonState();
        };

        textWs.onerror = function (error) {
            console.error('文字模式 WebSocket 錯誤:', error);
            updateStatus('文字模式連接錯誤', 'disconnected');
            isTextConnected = false;
            updateTextButtonState();
        };

    } catch (error) {
        console.error('文字模式連接失敗:', error);
        updateStatus('文字模式連接失敗', 'disconnected');
        isTextConnected = false;
        updateTextButtonState();
    }
}

// 處理文字模式訊息
async function handleTextMessage(data) {
    switch (data.type) {
        case 'session.created':
            console.log('文字模式會話已建立');
            updateStatus('文字模式準備就緒', 'connected');
            break;

        case 'response.text.delta':
        case 'response.audio_transcript.delta':  // 也處理這個事件類型
            updateAssistantMessage(data.delta, 'text');
            break;

        case 'response.done':
            finishAssistantMessage('text');
            break;

        case 'error':
            console.error('文字模式 API 錯誤:', data.error);
            updateStatus('文字模式發生錯誤', 'disconnected');
            break;

        default:
            console.log('文字模式未處理的事件:', data.type);
    }
}

// 發送文字訊息
function sendTextMessage() {
    const input = document.getElementById('text-input');
    const message = input.value.trim();

    if (currentTab === 'voice') {
        // 語音模式下的文字訊息
        if (!message || !isConnected) return;

        addMessage('user', message, 'voice');

        if (realtimeWs && realtimeWs.readyState === WebSocket.OPEN) {
            realtimeWs.send(JSON.stringify({
                type: 'conversation.item.create',
                item: {
                    type: 'message',
                    role: 'user',
                    content: [{
                        type: 'input_text',
                        text: message
                    }]
                }
            }));

            realtimeWs.send(JSON.stringify({
                type: 'response.create'
            }));

            hasActiveResponse = true;
        }
    } else {
        // 文字模式
        if (!message) return;

        // 如果尚未連接文字模式，自動連接
        if (!isTextConnected) {
            addMessage('user', message, 'text');
            // 暫存訊息，等連接完成後發送
            const pendingMessage = message;

            connectTextMode().then(() => {
                // 連接成功後發送訊息
                if (textWs && textWs.readyState === WebSocket.OPEN) {
                    textWs.send(JSON.stringify({
                        type: 'conversation.item.create',
                        item: {
                            type: 'message',
                            role: 'user',
                            content: [{
                                type: 'input_text',
                                text: pendingMessage
                            }]
                        }
                    }));

                    textWs.send(JSON.stringify({
                        type: 'response.create',
                        response: {
                            modalities: ["text"],
                            instructions: "請用繁體中文回應，並可以使用 Markdown 格式來美化回應內容。"
                        }
                    }));
                }
            }).catch(error => {
                console.error('自動連接文字模式失敗:', error);
                updateStatus('文字模式連接失敗', 'disconnected');
            });

            return;
        }

        addMessage('user', message, 'text');

        if (textWs && textWs.readyState === WebSocket.OPEN) {
            textWs.send(JSON.stringify({
                type: 'conversation.item.create',
                item: {
                    type: 'message',
                    role: 'user',
                    content: [{
                        type: 'input_text',
                        text: message
                    }]
                }
            }));

            textWs.send(JSON.stringify({
                type: 'response.create',
                response: {
                    modalities: ["text"],
                    instructions: "請用繁體中文回應，並可以使用 Markdown 格式來美化回應內容。"
                }
            }));
        }
    }

    input.value = '';
}

// 處理按鍵事件
function handleTextKeyPress(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendTextMessage();
    }
}

// 優化的音頻播放管理
function queueAudioChunk(base64Audio) {
    audioQueue.push(base64Audio);

    if (!isPlayingAudio) {
        processAudioQueue();
    }
}

async function processAudioQueue() {
    if (audioQueue.length === 0 || isPlayingAudio) {
        return;
    }

    isPlayingAudio = true;

    while (audioQueue.length > 0) {
        const base64Audio = audioQueue.shift();
        try {
            await playAudioChunk(base64Audio);
            // 小延遲確保音頻順序播放
            await new Promise(resolve => setTimeout(resolve, 10));
        } catch (error) {
            console.error('音頻播放錯誤:', error);
        }
    }

    isPlayingAudio = false;
}

// 停止所有音頻播放
function stopAllAudio() {
    // 停止所有正在播放的音頻源
    audioSourceNodes.forEach(source => {
        try {
            source.stop();
        } catch (e) {
            // 忽略已經停止的源
        }
    });
    audioSourceNodes = [];

    // 清空佇列
    clearAudioQueue();
}

function clearAudioQueue() {
    audioQueue = [];
    isPlayingAudio = false;
}

// 優化的音頻播放函數
async function playAudioChunk(base64Audio) {
    return new Promise((resolve, reject) => {
        try {
            const binaryString = atob(base64Audio);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }

            if (!audioContext || audioContext.state === 'closed') {
                audioContext = new (window.AudioContext || window.webkitAudioContext)({
                    sampleRate: AUDIO_CONFIG.sampleRate
                });
            }

            if (audioContext.state === 'suspended') {
                audioContext.resume().then(() => {
                    playAudioData(bytes, resolve, reject);
                });
            } else {
                playAudioData(bytes, resolve, reject);
            }

        } catch (error) {
            reject(error);
        }
    });
}

function playAudioData(bytes, resolve, reject) {
    try {
        const pcm16Data = new Int16Array(bytes.buffer);
        const audioBuffer = audioContext.createBuffer(1, pcm16Data.length, AUDIO_CONFIG.sampleRate);
        const channelData = audioBuffer.getChannelData(0);

        for (let i = 0; i < pcm16Data.length; i++) {
            channelData[i] = pcm16Data[i] / 32768.0;
        }

        const audioBufferSource = audioContext.createBufferSource();
        const gainNode = audioContext.createGain();
        const volumeSlider = document.getElementById('volume-slider');
        const volume = volumeSlider ? parseFloat(volumeSlider.value) : 0.8;
        gainNode.gain.value = volume;

        // 追蹤音頻源以便停止
        audioSourceNodes.push(audioBufferSource);

        audioBufferSource.onended = () => {
            // 從追蹤列表中移除
            const index = audioSourceNodes.indexOf(audioBufferSource);
            if (index > -1) {
                audioSourceNodes.splice(index, 1);
            }
            resolve();
        };

        audioBufferSource.buffer = audioBuffer;
        audioBufferSource.connect(gainNode);
        gainNode.connect(audioContext.destination);

        audioBufferSource.start();

    } catch (error) {
        reject(error);
    }
}

// 工具函數
function convertFloat32ToPCM16(float32Array) {
    const pcm16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]));
        pcm16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return new Uint8Array(pcm16Array.buffer);
}

// UI 更新函數
function updateStatus(message, className) {
    const status = document.getElementById('status');
    if (status) {
        status.textContent = message;
        status.className = 'status ' + className;
    }
}

function updateTextButtonState() {
    const connectBtn = document.getElementById('connect-text-btn');
    if (connectBtn) {
        if (isTextConnected) {
            connectBtn.textContent = '🔗 已連接文字模式';
            connectBtn.disabled = true;
        } else {
            connectBtn.textContent = '🔗 連接文字模式';
            connectBtn.disabled = false;
        }
    }
}

// 助手訊息管理
let currentAssistantMessage = {
    voice: '',
    text: ''
};
let assistantMessageDiv = {
    voice: null,
    text: null
};

function updateAssistantMessage(delta, mode) {
    if (!assistantMessageDiv[mode]) {
        const messagesContainer = document.getElementById(`${mode}-messages`);
        const messageElement = document.createElement('div');
        messageElement.className = 'message assistant';

        const avatar = document.createElement('div');
        avatar.className = 'bot-avatar';
        avatar.textContent = '🤖';

        const content = document.createElement('div');
        content.className = 'message-content';

        messageElement.appendChild(avatar);
        messageElement.appendChild(content);
        messagesContainer.appendChild(messageElement);

        assistantMessageDiv[mode] = content;
        currentAssistantMessage[mode] = '';

        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    currentAssistantMessage[mode] += delta;

    if (mode === 'text' && typeof marked !== 'undefined') {
        // 文字模式使用 Markdown 渲染
        assistantMessageDiv[mode].innerHTML = marked.parse(currentAssistantMessage[mode]);
    } else {
        // 語音模式使用純文字
        assistantMessageDiv[mode].textContent = currentAssistantMessage[mode];
    }

    const messagesContainer = document.getElementById(`${mode}-messages`);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function addMessage(sender, content, mode) {
    if (sender === 'system') {
        return null;
    }

    const messagesContainer = document.getElementById(`${mode}-messages`);
    const messageElement = document.createElement('div');
    messageElement.className = `message ${sender}`;

    const avatar = document.createElement('div');
    if (sender === 'user') {
        avatar.className = 'user-avatar';
        avatar.textContent = '👤';
    } else {
        avatar.className = 'bot-avatar';
        avatar.textContent = '🤖';
    }

    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';

    if (sender === 'assistant' && mode === 'text' && typeof marked !== 'undefined') {
        messageContent.innerHTML = marked.parse(content);
    } else {
        messageContent.textContent = content;
    }

    messageElement.appendChild(avatar);
    messageElement.appendChild(messageContent);
    messagesContainer.appendChild(messageElement);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return messageElement;
}

function finishAssistantMessage(mode) {
    if (assistantMessageDiv[mode]) {
        assistantMessageDiv[mode] = null;
        currentAssistantMessage[mode] = '';
        updateStatus('對話中', 'connected');
    }
}

function clearChat(mode) {
    const messagesContainer = document.getElementById(`${mode}-messages`);
    const welcomeMessage = messagesContainer.querySelector('.welcome-message');
    messagesContainer.innerHTML = '';

    if (welcomeMessage) {
        messagesContainer.appendChild(welcomeMessage);
    }

    currentAssistantMessage[mode] = '';
    assistantMessageDiv[mode] = null;

    if (mode === 'voice') {
        clearAudioQueue();
        stopAllAudio();
    }
}

// 清理資源
window.addEventListener('beforeunload', function () {
    if (realtimeWs) realtimeWs.close();
    if (textWs) textWs.close();
    if (currentStream) {
        currentStream.getTracks().forEach(track => track.stop());
    }
    if (audioContext) {
        audioContext.close();
    }
    clearAudioQueue();
    stopAllAudio();
}); 