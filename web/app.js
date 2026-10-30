'use strict';

/* All question text and transcripts are rendered as text nodes, never as HTML. */
const $ = (id) => document.getElementById(id);
const state = {
  page: 'practice', mode: '1', config: null, questions: [], sequence: [],
  question: null, questionIndex: 0, chosenIds: new Set(), sessionId: '',
  phase: 'idle', prepDone: false, recording: null, audioBlob: null, audioUrl: null,
  answerSeconds: 0, timer: null, deadline: 0, stats: null, history: [],
  requestNumber: 0, busy: false, lastAttempt: null, micTester: null, audioQuality: null,
};

const labels = {fluency_coherence: 'Fluency & coherence', lexical_resource: 'Lexical resource',
  grammar: 'Grammar range & accuracy', pronunciation: 'Pronunciation'};

function node(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined && content !== null) element.textContent = String(content);
  return element;
}

function errorMessage(data) {
  if (typeof data?.detail === 'string') return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map((x) => x.msg).filter(Boolean).join('; ');
  return 'Something went wrong. Check your connection and try again.';
}

async function api(path, options = {}) {
  let response;
  try { response = await fetch('/api' + path, {cache: 'no-store', ...options}); }
  catch (_err) { throw new Error('Cannot connect to the local server.'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(data));
  return data;
}

let toastTimeout;
function showToast(message, isError = false) {
  const toast = $('toast');
  toast.textContent = message;
  toast.className = 'toast' + (isError ? ' error' : '');
  toast.hidden = false;
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => {toast.hidden = true;}, 6000);
}

function secondsToClock(seconds) {
  const num = Math.max(0, Math.ceil(seconds));
  return String(Math.floor(num / 60)).padStart(2, '0') + ':' + String(num % 60).padStart(2, '0');
}

function shortDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Unknown date' : date.toLocaleString(undefined,
    {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
}

function newSessionId() {
  return (globalThis.crypto && crypto.randomUUID) ? crypto.randomUUID() :
    String(Date.now()) + '-' + Math.floor(Math.random() * 100000);
}

function setPage(page) {
  if (state.phase === 'recording' || state.phase === 'preparing' || state.micTester) {
    showToast('Finish the current recording or preparation first.', true);
    return;
  }
  state.page = page;
  for (const name of ['practice','history','insights']) {
    $(name + 'Page').hidden = name !== page;
    const button = document.querySelector(`.nav-item[data-page="${name}"]`);
    button.classList.toggle('active', name === page);
    if (name === page) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  $('breadcrumbCurrent').textContent = ({practice:'Practice studio', history:'Practice history', insights:'My progress'})[page];
  if (page === 'history') void loadHistory();
  if (page === 'insights') void loadStats();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

async function changeMode(mode) {
  if (state.phase === 'recording' || state.phase === 'preparing' || state.micTester || state.busy) {
    showToast('Finish this response before switching modes.', true); return;
  }
  state.mode = mode;
  state.questionIndex = 0;
  state.sessionId = newSessionId();
  state.chosenIds = new Set();
  $('topicSelect').disabled = mode === 'mock';
  for (const button of document.querySelectorAll('.mode-card')) {
    const active = button.dataset.mode === mode;
    button.classList.toggle('selected', active);
    button.setAttribute('aria-pressed', String(active));
  }
  const token = ++state.requestNumber;
  try {
    if (mode === 'mock') {
      const data = await api('/mock');
      if (token !== state.requestNumber) return;
      state.sequence = data.questions;
      state.questions = data.questions;
      fillTopics([]);
      showQuestion(state.sequence[0]);
    } else {
      const data = await api(`/questions?part=${mode}`);
      if (token !== state.requestNumber) return;
      state.questions = data.questions;
      state.sequence = [];
      fillTopics(data.topics);
      pickQuestion();
    }
  } catch (err) { showToast(err.message, true); }
}

function fillTopics(topics) {
  const select = $('topicSelect');
  select.replaceChildren(new Option('All topics', ''));
  for (const topic of topics) select.add(new Option(topic, topic));
}

function pickQuestion() {
  const topic = $('topicSelect').value;
  let choices = state.questions.filter((q) => !topic || q.topic === topic);
  if (!choices.length) {showToast('No questions for this topic.', true); return;}
  let unseen = choices.filter((q) => !state.chosenIds.has(q.id));
  if (!unseen.length) {state.chosenIds.clear(); unseen = choices;}
  const pick = unseen[Math.floor(Math.random() * unseen.length)];
  state.chosenIds.add(pick.id);
  showQuestion(pick);
}

function stopTimer() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

function countdown(seconds, status, onExpire) {
  stopTimer();
  state.deadline = performance.now() + seconds * 1000;
  $('timerStatus').textContent = status;
  const update = () => {
    const remaining = Math.max(0, (state.deadline - performance.now()) / 1000);
    $('clock').textContent = secondsToClock(remaining);
    if (remaining <= 0) {stopTimer(); onExpire();}
  };
  update();
  state.timer = setInterval(update, 180);
}

function resetRecording() {
  stopTimer();
  if (state.audioUrl) {URL.revokeObjectURL(state.audioUrl); state.audioUrl = null;}
  state.audioBlob = null;
  state.audioQuality = null;
  state.recording = null;
  $('audioWarning').hidden = true;
  state.answerSeconds = 0;
  $('playback').hidden = true;
  $('playback').removeAttribute('src');
  $('transcriptInput').value = '';
  $('reviewPanel').hidden = true;
  $('resultPanel').hidden = true;
  state.lastAttempt = null;
  $('notesCard').hidden = true;
  $('prepNotes').value = '';
}

function showQuestion(question) {
  if (!question) return;
  resetRecording();
  state.question = question;
  state.phase = 'idle';
  state.prepDone = false;
  state.questionIndex += 1;
  $('questionPart').textContent = 'PART 0' + question.part;
  $('questionTitle').textContent = question.prompt;
  $('questionCount').textContent = question.topic.toUpperCase();
  $('sessionCounter').textContent = state.mode === 'mock' ?
    `Mock · ${state.questionIndex} of ${state.sequence.length}` :
    `Part ${question.part} · Question ${state.questionIndex}`;
  $('questionTip').textContent = question.part === 2 ?
    'You have 1 minute to prepare, then up to 2 minutes to speak.' :
    question.part === 3 ? 'Support your view with a reason, comparison or consequence.' :
      'Aim for a natural answer with a reason and a specific example.';
  const cues = $('questionCues');
  cues.replaceChildren();
  cues.hidden = !question.cues?.length;
  for (const item of question.cues || []) cues.append(node('li', '', item));
  $('notesCard').hidden = question.part !== 2;
  $('timerStatus').textContent = 'RESPONSE TIME';
  $('clock').textContent = secondsToClock(question.part === 2 ? 120 : question.part === 1 ? 45 : 60);
  $('timerSub').textContent = question.part === 2 ? 'One minute to prepare first' : 'Press start when ready';
  $('recorderState').textContent = 'READY';
  $('recorderState').classList.remove('recording');
  document.querySelector('.timer-ring').classList.remove('counting', 'recording');
  $('recorderTitle').textContent = question.part === 2 ? 'Gather your thoughts.' : "You're up!";
  $('recorderDescription').textContent = question.part === 2 ? 'You can take notes before you speak.' : 'Take a moment, then speak naturally.';
  $('recordButton').classList.remove('is-recording');
  $('recordButtonText').textContent = question.part === 2 ? 'Start 1-min prep' : 'Start speaking';
  $('recordButton').disabled = false;
  $('typeButton').hidden = false;
  $('recordHint').textContent = 'Microphone access is requested only when you record.';
  drawIdleWave();
}

async function nextQuestion() {
  if (state.busy) return;
  if (state.mode === 'mock') {
    if (state.questionIndex >= state.sequence.length) {
      showToast('Mock practice complete! Review your progress or start a new mock.');
      await changeMode('mock');
    } else showQuestion(state.sequence[state.questionIndex]);
  } else pickQuestion();
  $('studioAnchor').scrollIntoView({behavior: 'smooth', block: 'start'});
}

function startPreparation() {
  state.phase = 'preparing';
  $('recordButtonText').textContent = 'Skip preparation';
  $('recorderState').textContent = 'PREPARING';
  $('recorderTitle').textContent = 'Organise your ideas.';
  $('recorderDescription').textContent = 'Write a few quick notes while your timer runs.';
  $('timerSub').textContent = 'Preparing your long turn';
  document.querySelector('.timer-ring').classList.add('counting');
  countdown(60, 'PREPARATION', finishPreparation);
  $('prepNotes').focus();
}

function finishPreparation() {
  stopTimer();
  state.prepDone = true;
  state.phase = 'ready';
  $('clock').textContent = '02:00';
  $('timerStatus').textContent = 'RESPONSE TIME';
  $('timerSub').textContent = 'Ready for your long turn';
  $('recordButtonText').textContent = 'Start speaking';
  $('recorderState').textContent = 'READY';
  $('recorderTitle').textContent = 'Now tell your story.';
  document.querySelector('.timer-ring').classList.remove('counting');
  showToast('Preparation complete. Start speaking when ready!');
}

function drawIdleWave() {
  const canvas = $('waveform');
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = '#b5cdb8';
  for (let i = 0; i < 35; i++) {
    const height = 5 + 17 * Math.pow(Math.abs(Math.sin((i + 3) * 1.23)), 2);
    context.fillRect(3 + i * 8.35, (40 - height) / 2, 3.5, height);
  }
}

function selectedMicrophoneConstraints() {
  const id = $('microphoneSelect').value;
  return {audio: {
    ...(id ? {deviceId: {exact: id}} : {}),
    echoCancellation: true, noiseSuppression: false, autoGainControl: true
  }};
}

async function refreshMicrophones() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  try {
    const select = $('microphoneSelect');
    const current = select.value;
    const devices = (await navigator.mediaDevices.enumerateDevices())
      .filter(device => device.kind === 'audioinput' && device.deviceId && device.deviceId !== 'default');
    select.replaceChildren(new Option('System default microphone', ''));
    devices.forEach((device, index) => select.add(new Option(device.label || `Microphone ${index+1}`, device.deviceId)));
    if (current && [...select.options].some(option => option.value === current)) select.value = current;
  } catch (_) { /* Device labels may be unavailable until permission is granted. */ }
}

function updateMicMeter(rms) {
  const percent = Math.min(100, Math.round(Math.sqrt(Math.max(0, rms)) * 250));
  $('micLevelFill').style.width = percent + '%';
  $('micLevelText').textContent = percent + '%';
  $('micLevelFill').classList.toggle('quiet', rms < .0008);
}

function summarizeSignal(chunks) {
  let sumSquares = 0, count = 0, peak = 0;
  for (const chunk of chunks) {
    // A downsampled energy estimate is sufficient to flag silent input quickly.
    for (let i = 0; i < chunk.length; i += 8) {
      const magnitude = Math.abs(chunk[i]);
      sumSquares += magnitude * magnitude;
      peak = Math.max(peak, magnitude);
      count++;
    }
  }
  const rms = count ? Math.sqrt(sumSquares / count) : 0;
  return {rms, peak, silent: rms < .00035 && peak < .006};
}

function micStatus(message) {
  $('micStatus').textContent = message;
}

let lastMicStatusAt = 0;
function onMicLevel(rms) {
  updateMicMeter(rms);
  // Status text is throttled; the progress bar stays live.
  const now = Date.now();
  if (now - lastMicStatusAt < 900) return;
  lastMicStatusAt = now;
  if (rms >= .0015) micStatus('Microphone signal detected ✓');
  else micStatus('Input is very quiet — speak closer or select another mic.');
}

async function toggleMicTest() {
  const button = $('testMicButton');
  if (state.micTester) {
    const tester = state.micTester;
    state.micTester = null;
    button.disabled = true;
    try {
      const {quality} = await tester.stop();
      if (quality.silent) {
        micStatus('No microphone sound detected. Check Windows Input.');
        showToast('Mic test is silent. Choose the correct microphone or adjust Windows Input volume.', true);
      } else micStatus('Microphone works! You can start speaking.');
    } catch (err) { showToast('Microphone test failed: ' + err.message, true); }
    finally {
      button.textContent = 'Test mic';
      button.disabled = false;
      $('microphoneSelect').disabled = false;
      $('recordButton').disabled = false;
      updateMicMeter(0);
      drawIdleWave();
    }
    return;
  }
  if (state.busy || state.phase === 'recording' || state.phase === 'preparing') {
    showToast('Finish your current recording or preparation first.', true);
    return;
  }
  const recorder = new PCMRecorder($('waveform'), onMicLevel);
  button.disabled = true;
  try {
    await recorder.start(selectedMicrophoneConstraints());
    state.micTester = recorder;
    button.textContent = 'Stop test';
    $('recordButton').disabled = true;
    $('microphoneSelect').disabled = true;
    micStatus('Speak now: watch the green microphone level.');
    void refreshMicrophones();
  } catch (err) {
    micStatus('Microphone access failed. Check permission and device.');
    showToast(err.message || 'Microphone test failed.', true);
  } finally {button.disabled = false;}
}

class PCMRecorder {
  constructor(canvas, onLevel = null) {
    this.canvas = canvas;
    this.onLevel = onLevel;
    this.chunks = [];
    this.live = false;
    this.raf = null;
  }

  async start(constraints = selectedMicrophoneConstraints()) {
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
      throw new Error('Microphone recording requires a modern browser on localhost or HTTPS.');
    }
    this.stream = await navigator.mediaDevices.getUserMedia(constraints);
    try {
      this.context = new AudioContext();
      await this.context.resume();
      this.source = this.context.createMediaStreamSource(this.stream);
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 1024;
      this.source.connect(this.analyser);
      this.chunks = [];
      if (this.context.audioWorklet && window.AudioWorkletNode) {
        const workletSource = `class PcmCollector extends AudioWorkletProcessor {
          process(inputs){const input=inputs[0];if(input && input[0]) this.port.postMessage(input[0].slice());return true;}
        }registerProcessor('speakly-pcm-collector',PcmCollector);`;
        const url = URL.createObjectURL(new Blob([workletSource], {type: 'text/javascript'}));
        try {
          await this.context.audioWorklet.addModule(url);
          this.processor = new AudioWorkletNode(this.context, 'speakly-pcm-collector');
          this.processor.port.onmessage = ({data}) => this.chunks.push(data);
        } catch (err) {
          // AudioWorklet can be blocked by browser security settings. Use the PCM fallback.
          this.processor = null;
        } finally {URL.revokeObjectURL(url);}
      }
      if (!this.processor) {
        this.processor = this.context.createScriptProcessor(4096, 1, 1);
        this.processor.onaudioprocess = (event) =>
          this.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      }
      this.muted = this.context.createGain();
      this.muted.gain.value = 0;
      this.analyser.connect(this.processor);
      this.processor.connect(this.muted);
      this.muted.connect(this.context.destination);
      this.sampleRate = this.context.sampleRate;
      this.live = true;
      this.drawWave();
    } catch (err) {
      this.stream.getTracks().forEach((track) => track.stop());
      if (this.context) await this.context.close().catch(() => {});
      throw err;
    }
  }

  drawWave() {
    if (!this.live) return;
    const canvas = this.canvas;
    const ctx = canvas.getContext('2d');
    const buffer = new Float32Array(this.analyser.fftSize);
    this.analyser.getFloatTimeDomainData(buffer);
    let squareSum = 0;
    for (let i = 0; i < buffer.length; i++) squareSum += buffer[i] * buffer[i];
    const rms = Math.sqrt(squareSum / buffer.length);
    this.onLevel?.(rms);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#6fa78c';
    for (let i = 0; i < 35; i++) {
      let max = 0;
      for (let j = 0; j < 20; j++) max = Math.max(max, Math.abs(buffer[i * 20 + j]));
      const height = Math.max(3, Math.min(34, max * 100));
      ctx.fillRect(3 + i * 8.35, 20 - height/2, 4, height);
    }
    this.raf = requestAnimationFrame(() => this.drawWave());
  }

  async stop() {
    this.live = false;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.source?.disconnect();
    this.analyser?.disconnect();
    this.processor?.disconnect();
    this.muted?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    // Allow final posted PCM buffers to arrive before closing the AudioContext.
    await new Promise((resolve) => setTimeout(resolve, 90));
    const quality = summarizeSignal(this.chunks);
    const result = {...pcmToWav(this.chunks, this.sampleRate), quality};
    await this.context?.close().catch(() => {});
    this.chunks = [];
    return result;
  }
}

function pcmToWav(chunks, sampleRate) {
  const count = chunks.reduce((sum, item) => sum + item.length, 0);
  const output = new ArrayBuffer(44 + count * 2);
  const view = new DataView(output);
  const string = (offset, val) => {for (let i = 0; i < val.length; i++) view.setUint8(offset+i,val.charCodeAt(i));};
  string(0,'RIFF'); view.setUint32(4,36+count*2,true); string(8,'WAVE');
  string(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);
  view.setUint16(22,1,true);view.setUint32(24,sampleRate,true);
  view.setUint32(28,sampleRate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);
  string(36,'data');view.setUint32(40,count*2,true);
  let pos=44;
  for (const chunk of chunks) for (const val of chunk) {
    const n=Math.max(-1,Math.min(1,val));
    view.setInt16(pos, n<0 ? Math.round(n*32768) : Math.round(n*32767),true);
    pos += 2;
  }
  return {blob: new Blob([output],{type:'audio/wav'}), duration: count/sampleRate};
}

async function startRecording() {
  if (state.busy) return;
  if (state.micTester) return showToast('Stop the microphone test first.', true);
  const recorder = new PCMRecorder($('waveform'), onMicLevel);
  $('recordButton').disabled = true;
  $('recordHint').textContent = 'Checking microphone permission…';
  try {
    await recorder.start(selectedMicrophoneConstraints());
    void refreshMicrophones();
    $('microphoneSelect').disabled = true;
    $('testMicButton').disabled = true;
    micStatus('Speak now: watch the input level.');
    state.recording = recorder;
    state.phase = 'recording';
    $('recorderState').textContent = 'RECORDING';
    $('recorderState').classList.add('recording');
    $('recorderTitle').textContent = 'Keep going!';
    $('recorderDescription').textContent = 'Speak clearly, without rushing.';
    $('recordButton').classList.add('is-recording');
    $('recordButtonText').textContent = 'Finish recording';
    $('recordHint').textContent = 'Live microphone • nothing is saved until you submit your answer';
    document.querySelector('.timer-ring').classList.add('recording');
    $('timerSub').textContent = 'Recording your response';
    $('typeButton').hidden = true;
    countdown(state.question.part === 2 ? 120 : state.question.part === 1 ? 45 : 60,
      'TIME REMAINING', () => {void finishRecording();});
  } catch (err) {showToast(err.message || 'Cannot start microphone.', true); $('recordHint').textContent = 'You can enter your transcript manually instead.'; micStatus('Microphone could not start — check permission.');}
  finally {$('recordButton').disabled = false; if(state.phase !== 'recording') { $('microphoneSelect').disabled = false; $('testMicButton').disabled = false; }}
}

async function finishRecording() {
  if (state.phase !== 'recording' || !state.recording) return;
  state.phase = 'processing';
  stopTimer();
  $('recordButton').disabled = true;
  $('recordButtonText').textContent = 'Preparing audio…';
  document.querySelector('.timer-ring').classList.remove('recording');
  try {
    const {blob, duration, quality} = await state.recording.stop();
    state.recording = null;
    if (duration < .3) throw new Error('The recording is too short. Please try again.');
    state.audioBlob = blob;
    state.audioQuality = quality;
    $('audioWarning').hidden = !quality.silent;
    $('audioWarning').textContent = quality.silent ? 'No clear microphone signal detected in this recording. Please choose the correct microphone, test it, and record again before sending audio to Groq.' : '';
    if (quality.silent) { micStatus('Recording is nearly silent — choose another microphone.'); showToast('Recording contains almost no sound. Check your microphone before using Groq.', true); }
    else micStatus('Sound detected. Play back the recording to confirm.');
    state.answerSeconds = duration;
    state.audioUrl = URL.createObjectURL(blob);
    $('playback').src = state.audioUrl;
    $('playback').muted = false;
    $('playback').volume = 1;
    $('playback').hidden = false;
    openReview();
  } catch (err) {state.phase='ready'; showToast(err.message, true); $('recordButtonText').textContent='Try recording again';}
  finally {$('recordButton').disabled = false; $('microphoneSelect').disabled = false; $('testMicButton').disabled = false; updateMicMeter(0);}
}

function openReview(typeOnly = false) {
  if (typeOnly) {
    if (state.phase === 'preparing') stopTimer();
    state.phase = 'review';
    $('playback').hidden = true;
  } else state.phase = 'review';
  $('reviewPanel').hidden = false;
  $('resultPanel').hidden = true;
  $('recordButtonText').textContent = 'Record again';
  $('recorderState').textContent = 'RECORDED';
  $('recorderState').classList.remove('recording');
  $('recorderTitle').textContent = 'Nice work!';
  $('recorderDescription').textContent = 'Review and get your feedback below.';
  $('timerSub').textContent = 'Response captured';
  $('typeButton').hidden = true;
  $('recordHint').textContent = 'Your audio is held in memory, and is not stored by the server.';
  $('transcriptHint').textContent = state.audioBlob ?
    'Leave this box blank: pressing Analyze automatically uses speech recognition. Or enter text to skip transcription.' :
    'Text-only evaluation cannot assess pronunciation or produce a complete overall band estimate.';
  $('cloudAudioNotice').hidden = !state.audioBlob || !state.config?.cloud_stt_available;
  $('reviewPanel').scrollIntoView({behavior: 'smooth', block: 'start'});
  if (typeOnly) $('transcriptInput').focus();
}

async function onRecordClick() {
  if (state.phase === 'recording') {await finishRecording(); return;}
  if (state.phase === 'preparing') {finishPreparation(); return;}
  if (state.phase === 'review') {discardAnswer(); await startRecording(); return;}
  if (state.phase === 'done') discardAnswer();
  if (state.question?.part === 2 && !state.prepDone) {startPreparation(); return;}
  await startRecording();
}

function discardAnswer() {
  if (state.phase === 'recording' || state.busy) return;
  if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
  state.audioUrl = null;
  state.audioBlob = null;
  state.audioQuality = null;
  $('audioWarning').hidden = true;
  state.answerSeconds = 0;
  state.phase = 'ready';
  $('playback').hidden = true;
  $('playback').removeAttribute('src');
  $('transcriptInput').value = '';
  $('reviewPanel').hidden = true;
  $('resultPanel').hidden = true;
  $('recordButtonText').textContent = 'Start speaking';
  $('recorderTitle').textContent = 'Give it another try.';
  $('recorderDescription').textContent = 'A fresh attempt is always a good idea.';
  $('recorderState').textContent = 'READY';
  $('typeButton').hidden = false;
  $('timerStatus').textContent = 'RESPONSE TIME';
  $('timerSub').textContent = 'Press start when ready';
  $('clock').textContent = secondsToClock(state.question.part === 2 ? 120 : state.question.part === 1 ? 45 : 60);
  drawIdleWave();
}

async function submitAttempt() {
  if (state.busy || !state.question) return;
  const transcript = $('transcriptInput').value.trim();
  if (!transcript && !state.audioBlob) {
    showToast('Please record your answer or enter a transcript.', true);
    $('transcriptInput').focus();
    return;
  }
  const canUseOffline = state.config?.local_stt_available &&
    ['auto','whisper'].includes(state.config.stt_provider);
  const canUseGroq = state.config?.cloud_stt_available;
  if (!transcript && state.audioQuality?.silent) {
    showToast('This recording is nearly silent. Choose another mic and record again, or type your answer.', true);
    return;
  }
  if (!transcript && state.audioBlob && !(canUseOffline || canUseGroq)) {
    showToast('Speech transcription is unavailable. Configure Groq STT, or enter a transcript.', true);
    $('transcriptInput').focus();
    return;
  }
  state.busy = true;
  $('evaluateButton').disabled = true;
  $('evaluateButton').textContent = 'Analysing your answer…';
  const form = new FormData();
  form.set('question_id', state.question.id);
  form.set('transcript', transcript);
  form.set('session_id', state.sessionId);
  // Clicking Analyze explicitly authorizes the described cloud upload, if needed.
  form.set('allow_cloud_audio', String(Boolean(!transcript && state.audioBlob && canUseGroq)));
  form.set('duration_seconds', String(state.answerSeconds));
  if (state.audioBlob) form.append('audio', state.audioBlob, 'practice.wav');
  try {
    const attempt = await api('/attempts', {method: 'POST', body: form});
    state.lastAttempt = attempt;
    $('transcriptInput').value = attempt.transcript;
    renderAttempt(attempt);
    state.phase = 'done';
    $('reviewPanel').hidden = true;
    $('resultPanel').hidden = false;
    $('recorderState').textContent = 'FINISHED';
    $('resultPanel').scrollIntoView({behavior: 'smooth', block:'start'});
    await loadStats();
  } catch (err) {showToast(err.message, true);}
  finally {
    state.busy = false;
    $('evaluateButton').disabled = false;
    $('evaluateButton').textContent = 'Analyze my answer ↗';
  }
}

function fillList(parent, values) {
  parent.replaceChildren();
  for (const value of values) parent.append(node('li', '', value));
}

function renderAttempt(attempt) {
  const evaluation = attempt.evaluation;
  $('overallBand').textContent = evaluation?.language_estimate_band ?? '—';
  $('resultSubtitle').textContent = evaluation ?
    (attempt.cloud_audio_used ? 'Groq transcribed your audio. AI reviewed only the transcript; pronunciation is unscored.' :
      'AI reviewed your transcript for language feedback. Pronunciation is unscored.') :
    'Your practice signals are ready. AI feedback is unavailable.';
  $('criteriaGrid').replaceChildren();
  for (const [key, label] of Object.entries(labels)) {
    const score = evaluation?.criteria?.[key];
    const card = node('article', 'criterion');
    card.append(node('div', 'criterion-title', label));
    card.append(node('div', 'criterion-score', score?.band ?? '—'));
    const band = node('div', 'criterion-band');
    const progress = node('div');
    progress.style.width = `${Math.min(100, ((score?.band || 0) / 9) * 100)}%`;
    band.append(progress);
    card.append(band);
    const detail = node('p', 'criterion-details', score?.improve || score?.evidence ||
      (key === 'pronunciation' ? 'Pronunciation is not measured by Whisper transcription.' :
        'Enable the AI coach to get a practice estimate.'));
    card.append(detail);
    $('criteriaGrid').append(card);
  }
  const metrics = attempt.metrics;
  const displayed = [
    ['WORDS SPOKEN', metrics.word_count],
    ['EST. WORDS / MIN', metrics.estimated_wpm ?? '—'],
    ['LONG PAUSES', metrics.audio?.pause_count ?? '—'],
    ['FILLERS', metrics.filler_count],
  ];
  $('metricStrip').replaceChildren();
  for (const [name, value] of displayed) {
    const pill = node('div', 'metric-pill');
    pill.append(node('strong', '', value));
    pill.append(node('span', '', name));
    $('metricStrip').append(pill);
  }
  fillList($('strengthsList'), evaluation?.strengths?.length ? evaluation.strengths :
    ['You completed a practice answer and can reflect on your message.']);
  fillList($('prioritiesList'), evaluation?.priorities?.length ? evaluation.priorities :
    metrics.practice_tips);
  $('sampleBox').hidden = !evaluation?.improved_answer;
  $('improvedAnswer').textContent = evaluation?.improved_answer || '';
  $('drillBox').hidden = !evaluation?.practice_drill;
  $('practiceDrill').textContent = evaluation?.practice_drill || '';
  $('retryFeedback').hidden = Boolean(evaluation) || !attempt.ai_error || !state.config?.ai_enabled;
  $('resultDisclaimer').textContent = evaluation?.disclaimer ||
    `${attempt.ai_error || 'AI feedback unavailable.'} These metrics are not an IELTS score.`;
}

async function retryFeedback() {
  if (state.busy || !state.lastAttempt?.id) return;
  state.busy = true;
  $('retryFeedback').disabled = true;
  $('retryFeedback').textContent = 'Retrying AI feedback…';
  try {
    const updated = await api('/attempts/' + encodeURIComponent(state.lastAttempt.id) + '/retry-feedback',
      {method: 'POST'});
    state.lastAttempt = updated;
    renderAttempt(updated);
    await loadStats();
    showToast('AI feedback updated from the saved transcript. No new transcription was used.');
  } catch (err) {
    showToast(err.message, true);
  } finally {
    state.busy = false;
    $('retryFeedback').disabled = false;
    $('retryFeedback').textContent = 'Retry AI feedback';
  }
}

async function loadStats() {
  try {
    const stats = await api('/stats');
    state.stats = stats;
    $('heroAttempts').textContent = String(stats.total_attempts);
    $('heroMinutes').textContent = stats.total_minutes + ' min';
    $('heroAverage').textContent = stats.average_language_estimate ?? '—';
    $('insightAttempts').textContent = String(stats.total_attempts);
    $('insightMinutes').replaceChildren(document.createTextNode(String(stats.total_minutes)), node('span','', ' min'));
    $('insightBand').textContent = stats.average_language_estimate ?? '—';
    renderActivity(stats.last7);
    renderParts(stats.by_part);
    renderTrend(stats.band_trend);
  } catch (err) {showToast(err.message, true);}
}

function renderActivity(days) {
  $('activityBars').replaceChildren();
  const max = Math.max(1,...days.map((day) => day.count));
  for (const day of days) {
    const group = node('div','bar-group');
    group.append(node('span','bar-value',day.count || ''));
    const bar=node('div','bar');
    bar.style.height = `${Math.max(3,(day.count/max)*140)}px`;
    bar.title=`${day.day}: ${day.count} answers`;
    group.append(bar);
    group.append(node('small','',new Date(day.day + 'T12:00:00').toLocaleDateString(undefined,{weekday:'short'})));
    $('activityBars').append(group);
  }
}

function renderParts(byPart) {
  $('partsBars').replaceChildren();
  const max=Math.max(1,...Object.values(byPart).map(Number));
  for(let p=1;p<=3;p++) {
    const count=Number(byPart[String(p)]||0);
    const row=node('div','part-row');
    const heading=node('div','part-row-head');
    heading.append(node('span','',`Part ${p}`),node('strong','',`${count} answers`));
    row.append(heading);
    const progress=node('div','part-progress');
    const fill=node('div');fill.style.width=`${count/max*100}%`;
    progress.append(fill);row.append(progress);
    $('partsBars').append(row);
  }
}

function renderTrend(trend) {
  $('bandTrend').replaceChildren();
  if (!trend.length) {
    $('bandTrend').append(node('div','trend-empty',
      'A language estimate trend appears after Groq reviews at least one complete transcript.'));
    return;
  }
  for (const value of trend) {
    const row=node('div','trend-line');
    row.append(node('time','',shortDate(value.created_at)));
    const bg=node('div','trend-fill');
    const bar=node('span');bar.style.width=`${value.estimated_band/9*100}%`;
    bg.append(bar);row.append(bg);
    row.append(node('strong','',value.estimated_band));
    $('bandTrend').append(row);
  }
}

async function loadHistory() {
  try {
    const result = await api('/attempts?limit=100');
    state.history = result.attempts;
    renderHistory();
  } catch (err) {showToast(err.message, true);}
}

function renderHistory() {
  const list = $('historyList');
  list.replaceChildren();
  if (!state.history.length) {
    const empty=node('div','empty');
    empty.append(node('span','empty-mark','✦'),node('h3','','Your practice story starts here.'),
      node('p','','Try your first question and your learning history will appear here.'));
    list.append(empty);
    return;
  }
  for (const item of state.history) {
    const row=node('article','history-item');
    const content=node('div');
    const tags=node('div','history-tags');
    tags.append(node('span','history-part',`PART ${item.part}`),
      node('span','',item.topic),node('span','',shortDate(item.created_at)));
    content.append(tags,node('h3','',item.prompt),node('p','',
      `${item.metrics.word_count} words · ${Math.round(item.duration_seconds)} seconds · ${item.language_estimate_band==null?'Practice signals':`Language estimate ${item.language_estimate_band}`}`));
    row.append(content);
    const button=node('button','','View details');
    button.type='button';
    button.addEventListener('click', () => {
      const existing=row.querySelector('.history-expanded');
      if (existing) {existing.remove();button.textContent='View details';return;}
      const detail=node('div','history-expanded');
      detail.append(node('strong','','Your answer\n'),document.createTextNode(item.transcript));
      if(item.evaluation) {
        detail.append(node('strong','','\n\nCoaching priorities\n'));
        detail.append(document.createTextNode(item.evaluation.priorities.join('\n• ')));
      } else detail.append(node('p','',item.ai_error || 'No AI assessment.'));
      row.append(detail);button.textContent='Hide details';
    });
    row.append(button);
    if (!item.evaluation && item.ai_error && state.config?.ai_enabled) {
      const retry = node('button', 'outline-button', 'Retry AI feedback');
      retry.type = 'button';
      retry.addEventListener('click', async () => {
        if (state.busy) return;
        state.busy = true;
        retry.disabled = true;
        retry.textContent = 'Retrying…';
        try {
          const updated = await api('/attempts/' + encodeURIComponent(item.id) + '/retry-feedback',
            {method: 'POST'});
          const index = state.history.findIndex((entry) => entry.id === item.id);
          if (index !== -1) state.history[index] = updated;
          renderHistory();
          await loadStats();
          showToast('Feedback updated from saved transcript. Whisper was not called again.');
        } catch (err) {
          showToast(err.message, true);
          retry.disabled = false;
          retry.textContent = 'Retry AI feedback';
        } finally {state.busy = false;}
      });
      row.append(retry);
    }
    list.append(row);
  }
}

async function exportHistory() {
  try {
    const records=[];
    for (let offset=0;offset<10000;offset+=100) {
      const data=await api(`/attempts?limit=100&offset=${offset}`);
      records.push(...data.attempts);
      if(data.attempts.length<100) break;
    }
    if (!records.length) {showToast('No attempts to export yet.');return;}
    const blob=new Blob([JSON.stringify({exported_at:new Date().toISOString(),attempts:records},null,2)],
      {type:'application/json'});
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download='speakly-practice-history.json';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    showToast(`Exported ${records.length} attempts.`);
  } catch (err) {showToast(err.message,true);}
}

async function clearHistory() {
  if (!window.confirm('Permanently erase every saved transcript, score and practice metric from this local database?')) return;
  try {
    const result=await api('/attempts',{method:'DELETE'});
    state.history=[];
    renderHistory();
    await loadStats();
    showToast(`Deleted ${result.deleted} local practice attempts.`);
  } catch (err) {showToast(err.message,true);}
}

function speakQuestion() {
  if (!('speechSynthesis' in window)) {
    showToast('Your browser does not support text-to-speech.',true);return;
  }
  speechSynthesis.cancel();
  const text=state.question?.prompt;
  if (!text) return;
  const utterance=new SpeechSynthesisUtterance(text);
  utterance.lang='en-GB';utterance.rate=.91;utterance.pitch=1;
  speechSynthesis.speak(utterance);
}

async function initialize() {
  state.sessionId=newSessionId();
  for (const button of document.querySelectorAll('.nav-item')) {
    button.addEventListener('click',()=>setPage(button.dataset.page));
  }
  for (const button of document.querySelectorAll('.mode-card')) {
    button.addEventListener('click',()=>{void changeMode(button.dataset.mode);});
  }
  for (const id of ['heroStart','sidebarStart']) $(id).addEventListener('click',()=>{
    if(state.page!=='practice')setPage('practice');
    $('studioAnchor').scrollIntoView({behavior:'smooth',block:'start'});
  });
  $('topicSelect').addEventListener('change',()=>{
    state.chosenIds.clear();state.questionIndex=0;pickQuestion();
  });
  $('shuffleQuestion').addEventListener('click',()=>{
    if(state.phase==='recording'||state.phase==='preparing'||state.busy)
      return showToast('Finish this response first.',true);
    if(state.mode==='mock') return showToast('Mock questions advance in sequence.',true);
    pickQuestion();
  });
  $('recordButton').addEventListener('click',()=>{void onRecordClick();});
  $('testMicButton').addEventListener('click',()=>{void toggleMicTest();});
  $('microphoneSelect').addEventListener('change',()=>{micStatus('Microphone selected. Use Test mic to confirm.');});
  navigator.mediaDevices?.addEventListener?.('devicechange',()=>{void refreshMicrophones();});
  void refreshMicrophones();
  $('typeButton').addEventListener('click',()=>openReview(true));
  $('discardButton').addEventListener('click',discardAnswer);
  $('evaluateButton').addEventListener('click',()=>{void submitAttempt();});
  $('retryFeedback').addEventListener('click',()=>{void retryFeedback();});
  $('nextQuestion').addEventListener('click',()=>{void nextQuestion();});
  $('reviewAgain').addEventListener('click',()=>{
    $('reviewPanel').hidden=false;
    $('reviewPanel').scrollIntoView({behavior:'smooth',block:'start'});
  });
  $('speakQuestion').addEventListener('click',speakQuestion);
  $('exportHistory').addEventListener('click',()=>{void exportHistory();});
  $('clearHistory').addEventListener('click',()=>{void clearHistory();});
  drawIdleWave();
  try {
    state.config=await api('/config');
    const enabled=state.config.ai_enabled;
    $('aiStatus').classList.toggle('offline',!enabled);
    $('aiStatus').replaceChildren(node('span','status-indicator'),
      document.createTextNode(enabled ? 'Groq AI configured' : 'Practice mode · AI off'));
    if(!state.config.stt_available) {
      $('transcriptHint').textContent='Enter your transcript manually to get practice metrics.';
    }
  } catch (err) {showToast(err.message,true);}
  await Promise.all([changeMode('1'),loadStats()]);
}

document.addEventListener('DOMContentLoaded',()=>{void initialize();});
