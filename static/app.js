let player = null;
let playerReady = false;
let activeVideoId = null;
let transcript = [];
let chatHistory = [];
let lastBrandVersion = null;

const $ = (id) => document.getElementById(id);

function formatTime(value) {
  const total = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hours ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}

// Keep the embedded YouTube player as the source of truth for playback time.
window.onYouTubeIframeAPIReady = function () {
  player = new YT.Player("player", {
    width: "100%",
    height: "100%",
    videoId: "",
    playerVars: { rel: 0, modestbranding: 1 },
    events: {
      onReady: () => {
        playerReady = true;
        if (activeVideoId) player.cueVideoById(activeVideoId);
      },
    },
  });
};

function seekTo(seconds) {
  if (!playerReady || !player) return;
  player.seekTo(Number(seconds), true);
  player.playVideo();
}

function renderTranscript(query = "") {
  const list = $("transcriptList");
  const needle = query.trim().toLowerCase();
  const visible = needle
    ? transcript.filter((item) => item.text.toLowerCase().includes(needle))
    : transcript;

  if (!visible.length) {
    list.innerHTML = '<div class="empty-panel">No transcript lines match.</div>';
    return;
  }

  list.innerHTML = "";
  visible.forEach((item) => {
    const row = document.createElement("div");
    row.className = "transcript-row";
    row.dataset.start = item.start;

    const time = document.createElement("time");
    time.textContent = item.stamp;

    const text = document.createElement("div");
    text.textContent = item.text;

    row.append(time, text);
    row.addEventListener("click", () => seekTo(item.start));
    list.appendChild(row);
  });
}

function highlightTranscript(current) {
  const rows = document.querySelectorAll(".transcript-row");
  rows.forEach((row) => row.classList.remove("active"));

  let best = null;
  for (const row of rows) {
    if (Number(row.dataset.start) <= current) best = row;
    else break;
  }
  if (best) best.classList.add("active");
}

async function loadVideo() {
  const value = $("videoUrl").value.trim();
  if (!value) return;

  $("loadButton").disabled = true;
  $("loadMessage").textContent = "Loading captions and building the local index...";

  try {
    const data = await api("/api/video/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url_or_id: value }),
    });

    activeVideoId = data.video_id;
    chatHistory = [];
    $("videoTitle").textContent = data.title;
    $("videoChannel").textContent = data.channel || `Video ${data.video_id}`;
    $("ragState").textContent = `${data.chunks} chunks indexed · transcript ${data.language}`;
    $("loadMessage").textContent = "Ready. Transcript and player are synced by timestamp.";

    if (playerReady) player.cueVideoById(data.video_id);

    const transcriptData = await api(`/api/video/${data.video_id}/transcript`);
    transcript = transcriptData.segments;
    renderTranscript();

    $("question").disabled = false;
    $("sendButton").disabled = false;
  } catch (error) {
    $("loadMessage").textContent = error.message;
  } finally {
    $("loadButton").disabled = false;
  }
}

function addMessage(role, text) {
  const wrap = $("chatMessages");
  const node = document.createElement("div");
  node.className = `${role === "user" ? "user" : "assistant"}-message message`;
  node.textContent = text;
  wrap.appendChild(node);
  wrap.scrollTop = wrap.scrollHeight;
  return node;
}

// Source timestamps also act as navigation back into the video.
function addSources(sources) {
  if (!sources || !sources.length) return;
  const row = document.createElement("div");
  row.className = "source-row";

  sources.forEach((source) => {
    const button = document.createElement("button");
    button.className = "source-chip";
    button.type = "button";
    button.textContent = source.stamp;
    button.title = source.preview;
    button.addEventListener("click", () => seekTo(source.start));
    row.appendChild(button);
  });

  $("chatMessages").appendChild(row);
}

async function ask(question, forceCurrent = false) {
  if (!activeVideoId || !question.trim()) return;

  const currentTime = playerReady && player ? player.getCurrentTime() : 0;
  const focusCurrent = forceCurrent || $("focusCurrent").checked;

  addMessage("user", question.trim());
  $("question").value = "";
  $("sendButton").disabled = true;
  const pending = addMessage("assistant", "Thinking from the transcript...");

  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_id: activeVideoId,
        question: question.trim(),
        current_time: currentTime,
        focus_current: focusCurrent,
        history: chatHistory.slice(-4),
      }),
    });

    pending.textContent = data.answer;
    addSources(data.sources);

    chatHistory.push({ role: "user", content: question.trim() });
    chatHistory.push({ role: "assistant", content: data.answer });
  } catch (error) {
    pending.textContent = error.message;
  } finally {
    $("sendButton").disabled = false;
    $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
  }
}

// Only refresh branding when the backend reports a new version.
async function refreshBrand() {
  try {
    const data = await api("/api/brand");
    if (data.version !== lastBrandVersion) {
      lastBrandVersion = data.version;
      $("brandName").textContent = data.name;
      $("brandLogo").src = data.logo_url;
    }
  } catch (_) {}
}

async function uploadLogo(file) {
  const form = new FormData();
  form.append("file", file);
  const data = await api("/api/brand/logo", { method: "POST", body: form });
  lastBrandVersion = data.version;
  $("brandLogo").src = data.logo_url;
}

$("loadButton").addEventListener("click", loadVideo);
$("videoUrl").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadVideo();
});

$("transcriptSearch").addEventListener("input", (event) => renderTranscript(event.target.value));

$("chatForm").addEventListener("submit", (event) => {
  event.preventDefault();
  ask($("question").value);
});

$("question").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("chatForm").requestSubmit();
  }
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => ask(button.dataset.prompt));
});

$("explainHere").addEventListener("click", () => {
  const here = playerReady && player ? formatTime(player.getCurrentTime()) : "the current point";
  ask(`Explain what the speaker is discussing around ${here}. Give enough context to understand it.`, true);
});

$("logoButton").addEventListener("click", () => $("logoInput").click());
$("logoInput").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try { await uploadLogo(file); }
  catch (error) { alert(error.message); }
  event.target.value = "";
});

setInterval(() => {
  if (playerReady && player && typeof player.getCurrentTime === "function") {
    const current = player.getCurrentTime();
    $("playerTime").textContent = formatTime(current);
    highlightTranscript(current);
  }
}, 800);

setInterval(refreshBrand, 4000);

(async function boot() {
  try {
    await api("/api/health");
    $("apiState").textContent = "backend online";
    $("apiState").classList.add("online");
  } catch (_) {
    $("apiState").textContent = "backend offline";
  }
  refreshBrand();
})();
