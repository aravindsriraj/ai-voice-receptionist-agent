const logEl = document.getElementById("log");
const orb = document.getElementById("orb");
const talkBtn = document.getElementById("talk");
const statusEl = document.getElementById("status");

function bubble(role, text) {
  const d = document.createElement("div");
  d.className = "bubble " + role;
  d.textContent = text;
  logEl.appendChild(d);
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(state, text) {
  statusEl.className = "status" + (state ? " " + state : "");
  statusEl.textContent = text;
}

// greet by first name
fetch("/api/me").then(r => (r.ok ? r.json() : null)).then(u => {
  if (u && u.name) document.getElementById("greeting").textContent = "Hi, " + u.name.split(" ")[0];
}).catch(() => {});

document.getElementById("callme").onclick = async () => {
  const r = await fetch("/api/call-me", { method: "POST" });
  bubble("system", r.ok ? "Calling your phone now — pick up to talk." : "Couldn't place the call.");
};

talkBtn.onclick = async () => {
  talkBtn.disabled = true;
  let ended = false;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/talk`);
  ws.binaryType = "arraybuffer";

  const recCtx = new AudioContext({ sampleRate: 16000 });
  await recCtx.audioWorklet.addModule("/static/js/pcm-recorder-processor.js");
  const playCtx = new AudioContext({ sampleRate: 24000 });
  await playCtx.audioWorklet.addModule("/static/js/pcm-player-processor.js");
  const player = new AudioWorkletNode(playCtx, "pcm-player-processor");
  player.connect(playCtx.destination);

  function finish(text) {
    if (ended) return;
    ended = true;
    orb.classList.remove("live");
    orb.classList.add("ended");
    setStatus("ended", text);
    talkBtn.disabled = false;
  }

  ws.onopen = () => {
    orb.classList.remove("ended");
    orb.classList.add("live");
    setStatus("live", "Live — listening");
    bubble("system", "Connected — start speaking.");
  };
  ws.onerror = () => bubble("system", "Connection error.");
  ws.onclose = () => finish("Call ended");

  ws.onmessage = (e) => {
    if (typeof e.data === "string") {
      const m = JSON.parse(e.data);
      if (m.type === "interrupt") player.port.postMessage({ command: "endOfAudio" });
      else if (m.type === "transcript") bubble(m.role, m.text);
      else if (m.type === "ended") finish("Call ended");
    } else {
      player.port.postMessage(e.data);   // 24kHz PCM
    }
  };

  const mic = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
  const src = recCtx.createMediaStreamSource(mic);
  const rec = new AudioWorkletNode(recCtx, "pcm-recorder-processor");
  src.connect(rec);
  rec.port.onmessage = (ev) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    const f = ev.data, pcm = new Int16Array(f.length);
    for (let i = 0; i < f.length; i++) pcm[i] = Math.max(-1, Math.min(1, f[i])) * 0x7fff;
    ws.send(pcm.buffer);
  };
};
