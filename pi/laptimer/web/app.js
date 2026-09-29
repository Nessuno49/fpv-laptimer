"use strict";
// Lap timer UI. Polls /api/state every 150 ms, displays it and speaks callouts.
// All texts come from i18n.js: t("key") in the language chosen on this device.

// ============================================================ helpers
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const timeText = (s) => (s == null ? "–" : num(s, 2) + " s");
const clockText = (s) => {                     // running clock: 8.3 or 1:02.5
  if (s == null) return "–";
  s = Math.max(0, s);
  const m = Math.floor(s / 60), r = s - m * 60;
  return m ? `${m}:${num(r, 1).padStart(4, "0")}` : num(r, 1);
};
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const dateText = (iso) => new Date(iso).toLocaleString(locale(),
  { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
const photoUrl = (name) => `/photos/${name}`;
const photoImg = (name, cls = "photo-mini") => name
  ? `<img class="${cls}" src="${photoUrl(esc(name))}" alt="" loading="lazy" onerror="this.outerHTML='<span class=&quot;photo-gone&quot;>${esc(t("photo_expired"))}</span>'">`
  : `<span class="photo-gone">${esc(t("no_photo"))}</span>`;

// Result of a pilot race as text: "17.00 s" or (timed race) "3 laps · 64.00 s"
function resultText(r) {
  if (!r) return t("no_result");
  return r.laps != null ? `${plural("n_laps", r.laps)} · ${timeText(r.time_s)}` : timeText(r.time_s);
}

// Name of a format with its settings, e.g. "10 laps" or "Timed race 2:00"
function categoryName(format, settings) {
  if (format === "practice") return t("format_practice");
  if (format === "laps") return plural("n_laps", settings.laps);
  const duration = mmss(settings.duration_s);
  if (format === "timed") return t("cat_timed", { duration });
  if (format === "consecutive") return t("cat_consecutive", { n: settings.n, duration });
  return t("cat_fastest", { duration });
}
const statsCategoryName = (c) => (c.format ? categoryName(c.format, c.settings) : t("cat_" + (c.key || c.category)));

async function api(path, data) {
  const opt = { headers: { "X-Language": lang } };
  if (data !== undefined) {
    Object.assign(opt, { method: "POST", body: JSON.stringify(data) });
    opt.headers["Content-Type"] = "application/json";
  }
  let r;
  try {
    r = await fetch(path, opt);
  } catch (e) {
    // network error: report with address and time so it can be narrowed down
    throw new Error(`${e.message} – ${opt.method || "GET"} ${path} (${new Date().toLocaleTimeString(locale())})`);
  }
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) showLoginPage();  // not (or no longer) signed in
  if (!r.ok) throw new Error(j.error || t("error_status", { status: r.status }));
  return j;
}

// ---- login page: before anything else (spectators with a button, race director with the PIN)
let signedOut = false;

async function showLoginPage() {
  if (signedOut) return;
  signedOut = true;  // also stops the regular polling
  $("#login-page").hidden = false;
  const info = await fetch("/api/session").then((r) => r.json()).catch(() => ({}));
  $("#login-hint").hidden = info.pin_set !== false;
}

async function signInWith(path, data) {
  $("#login-error").textContent = "";
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Language": lang },
                                body: JSON.stringify(data) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    $("#login-error").textContent = j.error || t("error_status", { status: r.status });
    return;
  }
  location.reload();  // reload signed in
}
$("#login-spectator").addEventListener("click", () => signInWith("/api/spectator", {}));
$("#login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  signInWith("/api/sign_in", { pin: $("#login-pin").value });
});

let messageTimer;
function message(text, info = false) {
  const m = $("#message");
  m.textContent = text;
  m.classList.toggle("info", info);
  m.hidden = false;
  clearTimeout(messageTimer);
  messageTimer = setTimeout(() => (m.hidden = true), info ? 4000 : 15000);  // errors stay longer
}
const attempt = (fn) => async (...args) => { try { await fn(...args); } catch (e) { message(e.message); } };

function options(select, entries, chosen) {
  select.innerHTML = entries.map(([value, text]) =>
    `<option value="${esc(value)}"${String(value) === String(chosen ?? "") ? " selected" : ""}>${esc(text)}</option>`).join("");
}

// ---- tooltips: an ⓘ next to a term. Hover shows the text on the PC, a tap on phones (tap again = close).
const infoButton = (key) => `<button type="button" class="info" data-tip="${key}">ⓘ</button>`;
const tip = document.createElement("div");
tip.id = "tip";
tip.hidden = true;
document.body.append(tip);
let tipButton = null, tipPinned = false;

function showTip(button, pinned) {
  tipButton = button;
  tipPinned = pinned;
  tip.innerHTML = t(button.dataset.tip);
  tip.hidden = false;
  const r = button.getBoundingClientRect(), width = Math.min(340, window.innerWidth - 24);
  tip.style.width = width + "px";
  tip.style.left = Math.max(12, Math.min(r.left + r.width / 2 - width / 2, window.innerWidth - width - 12)) + "px";
  const below = r.bottom + 8, height = tip.offsetHeight;
  tip.style.top = (below + height > window.innerHeight - 8 ? Math.max(8, r.top - height - 8) : below) + "px";
}
function hideTip() { tip.hidden = true; tipButton = null; tipPinned = false; }

// capture phase: the ⓘ must neither submit a form nor toggle a label nor open a tab
document.addEventListener("click", (e) => {
  const button = e.target.closest(".info");
  if (button) {
    e.preventDefault();
    e.stopPropagation();
    if (tipButton === button && tipPinned) hideTip(); else showTip(button, true);
  } else if (!e.target.closest("#tip")) hideTip();
}, true);
const canHover = window.matchMedia("(hover: hover)").matches;
document.addEventListener("mouseover", (e) => {
  const button = e.target.closest(".info");
  if (canHover && button && !tipPinned) showTip(button, false);
});
document.addEventListener("mouseout", (e) => {
  if (canHover && !tipPinned && e.target.closest(".info")) hideTip();
});
window.addEventListener("scroll", hideTip, { passive: true });
document.querySelectorAll(".info").forEach((b) => b.setAttribute("aria-label", "Info"));

// show photos large
document.addEventListener("click", (e) => {
  const img = e.target.closest("img.photo-mini, img.photo-medium, .photo-strip img, .profile-photos img");
  if (!img) return;
  $("#lightbox img").src = img.src;
  $("#lightbox").hidden = false;
});
$("#lightbox").addEventListener("click", () => ($("#lightbox").hidden = true));

// language switch (settings and login page): per device, reloads the page
for (const sel of ["#language", "#login-language"]) {
  options($(sel), Object.entries(LANGUAGES), lang);
  $(sel).addEventListener("change", () => setLanguage($(sel).value));
}

// ============================================================ state
const S = {
  pilots: [], tracks: [], quads: [], formats: [],
  selection: null, race: null, camera: null, settings: null,
  nr: -1, tab: "race", openPilot: null,
  admin: true, pinSet: false,   // comes from the Pi with every /api/state
};

async function loadMasterData() {
  [S.pilots, S.tracks, S.quads] = await Promise.all([api("/api/pilots"), api("/api/tracks"), api("/api/quads")]);
}
const quadsOf = (pilotId) => S.quads.filter((q) => q.pilot_id === Number(pilotId));

// ============================================================ tabs
function showTab(name) {
  if (!document.getElementById(`tab-${name}`)) name = "race";
  if (!S.admin && RACE_DIRECTOR_TABS.has(name)) name = "race";  // spectators
  S.tab = name;
  document.querySelectorAll(".tab").forEach((tab) => (tab.hidden = tab.id !== `tab-${name}`));
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $("#gear").classList.toggle("active", name === "settings");
  if (name === "welcome") store.write("welcome_seen", true);  // shown by itself only on the first visit
  // only load the live image while the camera view is open (saves computing time on the Pi)
  if (name === "camera") { $("#image").src = "/stream.mjpg"; loadCameraPresets().catch((e) => message(e.message)); }
  else $("#image").removeAttribute("src");
  if (name === "stats") loadStats();
  if (name === "history") loadHistory();
  if (name === "settings") { loadSoundSettings(); loadRaceSettings(); }
  if (name === "pilots") loadManagement();
  if (name === "race") fillSetup();
  history.replaceState(null, "", `#${name}`);
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
// the title and the buttons on the welcome page lead to a tab
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.goto)));

// ============================================================ sound & speech
// Every callout is a sequence of steps: {sound: "lap"} or {say: "8.3"}.
// The steps run one after the other through a queue so nothing overlaps.
// Your own files from the sound library (folder sounds/ on the Pi) replace the
// built-in tones – which file plays where is set in the settings.

const SOUNDS = ["countdown", "go", "holeshot", "lap", "best_lap", "last_lap", "30s_left",
                "time_up", "finish", "record", "practice", "aborted", "unassigned"];

// built-in sounds: sequences of tones [frequency Hz, duration s, waveform]
const TONES = {
  countdown: [[880, 0.15, "square"]],
  go: [[1320, 0.7, "square"]],
  holeshot: [[1800, 0.04, "square"]],
  lap: [[1047, 0.07, "sine"], [1319, 0.12, "sine"]],
  best_lap: [[1319, 0.08, "sine"], [1568, 0.08, "sine"], [2093, 0.2, "sine"]],
  last_lap: [[660, 0.25, "triangle"], [0, 0.05], [660, 0.25, "triangle"], [0, 0.05], [990, 0.45, "triangle"]],
  "30s_left": [[440, 0.15, "sawtooth"], [0, 0.08], [440, 0.15, "sawtooth"]],
  time_up: [[440, 0.2, "sawtooth"], [330, 0.2, "sawtooth"], [440, 0.2, "sawtooth"], [330, 0.35, "sawtooth"]],
  finish: [[523, 0.1, "square"], [659, 0.1, "square"], [784, 0.1, "square"], [1047, 0.4, "square"]],
  record: [[523, 0.12, "square"], [523, 0.12, "square"], [523, 0.12, "square"], [659, 0.5, "square"],
           [0, 0.05], [587, 0.12, "square"], [659, 0.12, "square"], [784, 0.7, "square"]],
  practice: [[660, 0.08, "sine"]],
  aborted: [[440, 0.15, "triangle"], [330, 0.15, "triangle"], [220, 0.4, "triangle"]],
  unassigned: [[300, 0.12, "triangle"], [300, 0.12, "triangle"]],
};

// Audio settings of this device. voices: one voice per UI language
//   "" = browser automatic, "browser:<name>", "piper:<model>[:<speaker>]"
const AUDIO_DEFAULTS = { sounds: true, speech: true, voices: { en: "", de: "" }, rate: 1.1, volume: 0.9,
                         me: "", only_me: false };  // me: the pilot using this device; only_me: callouts only for them
const audio = { ...AUDIO_DEFAULTS, ...store.read("audio", migrateOldAudio()) };
audio.voices = { ...AUDIO_DEFAULTS.voices, ...audio.voices };
if (audio.only_pilot) {  // earlier setting "callouts only for <pilot>"
  Object.assign(audio, { me: audio.only_pilot, only_me: true });
  delete audio.only_pilot;
}
const voiceId = () => audio.voices[lang] || "";

function migrateOldAudio() {
  // settings of the German version (key "sound")
  const old = store.read("sound", null);
  if (!old) return {};
  const voice = /^(browser|piper):/.test(old.stimme || "") ? old.stimme : "";
  return { sounds: old.sounds ?? true, speech: old.sprache ?? true, voices: { en: "", de: voice },
           rate: old.tempo ?? 1.1, volume: old.lautstaerke ?? 0.9, only_pilot: old.nur_pilot || "" };
}

let soundMapping = {};  // {record: "fanfare.mp3", ...} from the server (applies to all devices)
let soundFiles = [];    // all files of the library
let audioCtx = null;
let queue = [], playing = false;

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// One single audio element for the Pi voice: iPhones unlock it for good after the first touch
const piPlayer = new Audio();
const SILENCE = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
let piPlayerUnlocked = false;

function unlockAudio() {
  // browsers only allow sound after a touch/click
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
  if (!piPlayerUnlocked) {
    piPlayer.src = SILENCE;
    piPlayer.play().then(() => (piPlayerUnlocked = true)).catch(() => {});
  }
}
document.addEventListener("pointerdown", unlockAudio);

async function playTones(sequence) {
  unlockAudio();
  let when = audioCtx.currentTime + 0.02;
  for (const [freq, duration, form] of sequence) {
    if (freq > 0) {
      const osc = audioCtx.createOscillator(), gain = audioCtx.createGain();
      osc.type = form;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.25 * audio.volume, when);
      gain.gain.exponentialRampToValueAtTime(0.001, when + duration);  // fade out softly
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(when);
      osc.stop(when + duration);
    }
    when += duration;
  }
  await wait((when - audioCtx.currentTime) * 1000);
}

function playFile(file) {
  const a = new Audio(`/sounds/${encodeURIComponent(file)}`);
  a.volume = audio.volume;
  return new Promise((done, failed) => {
    a.onended = done;
    a.onerror = failed;
    a.play().catch(failed);
  });
}

async function playSound(name) {
  const file = soundMapping[name];
  if (file) {
    try { return await playFile(file); } catch { /* file broken -> built-in tone */ }
  }
  if (TONES[name]) await playTones(TONES[name]);
}

const browserLang = () => (lang === "de" ? "de-DE" : "en-US");

function findBrowserVoice() {
  const voices = speechSynthesis.getVoices();
  const id = voiceId();
  const name = id.startsWith("browser:") ? id.slice(8) : "";
  return voices.find((v) => v.name === name) || voices.find((v) => v.lang.startsWith(lang));
}

// ---- voices on the Pi (Piper): the Pi delivers the callout as ready-made snippets
let piVoices = [];   // list from the server (only needed in the settings)
let piRun = 0;       // increased to cancel a running Pi callout

const isPiVoice = (id) => id.startsWith("piper:");

// whole: the Pi speaks the whole sentence in one go (smoother, but takes a moment – after the race)
async function piParts(text, whole = false) {
  const control = new AbortController();
  const timeout = setTimeout(() => control.abort(), whole ? 20000 : 8000);
  try {
    const r = await fetch(`/api/speech?voice=${encodeURIComponent(voiceId())}&text=${encodeURIComponent(text)}` +
                          (whole ? "&whole=1" : ""), { signal: control.signal, headers: { "X-Language": lang } });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || t("error_status", { status: r.status }));
    return j.parts;
  } finally {
    clearTimeout(timeout);
  }
}

const piPartsSafe = (text, whole) => piParts(text, whole).catch((e) => {
  console.warn("Pi voice not available:", e.message);
  return null;  // -> browser voice
});

async function piSpeak(parts, run) {
  for (const p of parts) fetch(p.url).catch(() => {});  // load them all into the browser cache already
  for (let i = 0; i < parts.length; i++) {
    if (run !== piRun) return;  // cancelled (e.g. countdown)
    const a = piPlayer;
    a.src = parts[i].url;
    a.volume = audio.volume;
    a.defaultPlaybackRate = a.playbackRate = audio.rate;  // the pitch stays the same
    try {
      await new Promise((done, failed) => {
        a.onended = a.onpause = done;  // pause: cancelled
        a.onerror = failed;
        a.play().catch(failed);
      });
    } catch { /* skip the snippet */ }
    if (i < parts.length - 1) await wait((parts[i].pause ? 130 : 25) / audio.rate);  // sentence pause / word gap
  }
}

// early: request to the Pi already started when queuing (see play)
async function speakNow(text, early = null) {
  if (isPiVoice(voiceId())) {
    const run = piRun;
    const parts = await (early || piPartsSafe(text));
    if (parts) return piSpeak(parts, run);
  }
  if ("speechSynthesis" in window) return browserSpeak(text);  // fallback: the browser's voice
}

function browserSpeak(text) {
  return new Promise((done) => {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = browserLang();
    const voice = findBrowserVoice();
    if (voice) u.voice = voice;
    u.rate = audio.rate;
    u.volume = audio.volume;
    u.onend = u.onerror = done;
    speechSynthesis.speak(u);
    setTimeout(done, 1500 + text.length * 150);  // in case onend never comes (some phones)
  });
}

async function runStep(step) {
  if (step.sound) {
    if (audio.sounds) return playSound(step.sound);
    if (step.otherwise && audio.speech) return speakNow(step.otherwise);  // fallback when sounds are off
  } else if (step.say && audio.speech) {
    return speakNow(step.say, step.early);
  }
}

async function play(steps, first = false) {
  if (first) {  // e.g. countdown: drop the old ones, play at once
    queue = [];
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    piRun++;
    piPlayer.pause();
  }
  // Pi voice: ask right away, then the Pi generates while the sound before is still playing
  if (audio.speech && isPiVoice(voiceId())) {
    for (const s of steps) if (s.say) s.early = piPartsSafe(s.say, s.whole);
  }
  queue.push(...steps);
  if (playing) return;
  playing = true;
  while (queue.length) {
    try { await runStep(queue.shift()); } catch { /* go on */ }
  }
  playing = false;
}

// Callouts on/off for this device: one switch in the settings and one in the spectator menu
let calloutsOn = store.read("callouts", store.read("ansage", false));
const calloutToggles = document.querySelectorAll(".callouts-toggle");
calloutToggles.forEach((toggle) => {
  toggle.checked = calloutsOn;
  toggle.addEventListener("change", () => {
    calloutsOn = toggle.checked;
    calloutToggles.forEach((other) => (other.checked = calloutsOn));
    store.write("callouts", calloutsOn);
    unlockAudio();
    if (calloutsOn) play([{ sound: "practice" }, { say: t("say_callouts_on") }]);
  });
});

// Times to call out: under a minute "8.3", otherwise "3 minutes, 40.3" (so all numbers stay below 100)
function spoken(s) {
  const r = Math.round(s * 10) / 10;
  if (r < 60) return num(r, 1);
  const min = Math.floor(r / 60), rest = num(r - min * 60, 1);
  return `${min} ${t(min === 1 ? "say_minute" : "say_minutes")}, ${rest}`;
}
// result for speaking: "45.3 seconds" or (timed race) "5 laps, in 45.3 seconds"
function resultSpoken(r) {
  const time = `${spoken(r.time_s)} ${t("say_seconds")}`;
  return r.laps != null ? `${r.laps} ${t(r.laps === 1 ? "say_lap" : "say_laps")}, ${t("say_in")} ${time}` : time;
}
const pilotFirst = (e) => (e.multiple && e.pilot ? `${e.pilot}. ` : "");

// These callouts concern a single pilot (filter "Callouts for")
const PILOT_CALLOUTS = new Set(["holeshot", "first", "lap", "finish", "unassigned"]);

function callout(e) {
  if (!calloutsOn) return;
  if (audio.only_me && audio.me && PILOT_CALLOUTS.has(e.type) && e.pilot !== audio.me) return;
  switch (e.type) {
    case "staging":  // "30 seconds to start" … "10" … "5"
      return play([{ say: e.value >= 15 ? t("say_staging", { s: e.value }) : String(e.value) }]);
    case "countdown": return play([{ sound: "countdown", otherwise: String(e.value) }], e.value === 3);
    case "go": return play([{ sound: "go", otherwise: t("say_go") }]);
    case "holeshot":
    case "first":
      return play(e.multiple ? [{ sound: "holeshot" }, { say: e.pilot }] : [{ sound: "holeshot" }]);
    case "lap": {
      const steps = [{ sound: e.best_lap ? "best_lap" : "lap" },
                     { say: pilotFirst(e) + spoken(e.time) + (e.best_lap ? ". " + t("say_best_lap") : "") }];
      if (e.last_lap) steps.push({ sound: "last_lap" }, { say: pilotFirst(e) + t("say_last_lap") });
      return play(steps);
    }
    case "finish": return play([{ sound: "finish" }, { say: `${e.pilot}. ${t("say_finished")}` }]);
    case "unassigned": return e.multiple ? play([{ sound: "unassigned" }]) : undefined;
    case "30s_left": return play([{ sound: "30s_left" }, { say: t("say_30s_left") }]);
    case "time_up": return play([{ sound: "time_up" }, { say: t("say_time_up") }]);
    case "race_end": {
      const first = e.results[0] || {};
      const record = e.results.some((x) => x.record === "track");
      let text = t("say_race_over");
      if (e.multiple) {
        if (first.time_s != null) text += " " + t("say_winner", { pilot: first.pilot, result: resultSpoken(first) });
      } else if (first.time_s != null) {
        text += " " + resultSpoken(first) + ".";
        if (first.record === "personal") text += " " + t("say_personal_best");
      }
      if (record) text += " " + t("say_new_record");
      return play([{ sound: record ? "record" : "finish" }, { say: text, whole: true }]);
    }
    case "practice": return play([{ sound: "practice" }, { say: t("say_practice") }]);
    case "practice_end": return play([{ sound: "finish" }, { say: t("say_practice_over"), whole: true }]);
    case "aborted": return play([{ sound: "aborted" }, { say: t("say_race_aborted"), whole: true }]);
  }
}

// ---- settings "Sound & voice"
function saveAudio() { store.write("audio", audio); }

// find the Pi voice of an ID (with several speakers the number is appended)
const piEntry = (id) => piVoices.find((v) => id === v.id || id.startsWith(v.id + ":"));
const speakerName = (s) => (s.name ? t("emotion_" + s.name, {}, s.name) : t("speaker_n", { n: s.nr }));

function fillVoices() {
  const opt = (value, text) => `<option value="${esc(value)}">${esc(text)}</option>`;
  const groups = {};
  for (const v of piVoices.filter((v) => v.language === lang)) (groups[v.locale] ||= []).push(v);
  const browser = "speechSynthesis" in window
    ? speechSynthesis.getVoices().filter((v) => v.lang.startsWith(lang)) : [];
  $("#snd-voice").innerHTML =
    Object.entries(groups).map(([locale, list]) =>
      `<optgroup label="${esc(t("voices_pi", { locale }))}">${list.map((v) => opt(v.id, v.name)).join("")}</optgroup>`).join("") +
    `<optgroup label="${esc(t("voices_browser"))}">${opt("", t("voice_automatic"))}` +
    browser.map((v) => opt("browser:" + v.name, v.name)).join("") + "</optgroup>";
  const entry = piEntry(voiceId());
  $("#snd-voice").value = entry ? entry.id : voiceId();
  fillSpeakers(entry);
}

function fillSpeakers(entry) {
  $("#snd-speaker-row").hidden = !entry?.speakers;
  if (!entry?.speakers) return;
  $("#snd-speaker").innerHTML = entry.speakers.map((s) => `<option value="${s.nr}">${esc(speakerName(s))}</option>`).join("");
  $("#snd-speaker").value = voiceId().startsWith(entry.id + ":") ? voiceId().slice(entry.id.length + 1) : "0";
}

let voiceTimer = null;

async function voiceStatus() {
  clearTimeout(voiceTimer);
  const field = $("#snd-voice-status");
  const voice = voiceId();
  if (!isPiVoice(voice)) {
    field.textContent = t("voice_from_browser");
    return;
  }
  let s;
  try {
    s = await api(`/api/voices/status?voice=${encodeURIComponent(voice)}`);
  } catch (e) {
    field.textContent = t("voice_error_fallback", { error: e.message });
    return;
  }
  if (voice !== voiceId()) return;  // another voice chosen in the meantime
  if (s.done < s.total) {
    field.textContent = t("voice_preparing", { done: s.done, total: s.total }) + (s.error ? ` – ⚠ ${s.error}` : "");
    if (field.offsetParent !== null) voiceTimer = setTimeout(voiceStatus, 1000);  // only while visible
  } else {
    field.textContent = s.error ? t("voice_partly", { error: s.error }) : t("voice_ready");
  }
}

async function prepareVoice() {
  if (isPiVoice(voiceId())) {
    await api("/api/voices/prepare", { voice: voiceId() }).catch(() => {});
  }
  voiceStatus();
}

function voiceChosen() {
  saveAudio();
  prepareVoice();
}
if ("speechSynthesis" in window) speechSynthesis.addEventListener("voiceschanged", fillVoices);

async function loadSoundLibrary() {
  const s = await api("/api/sounds").catch(() => ({ files: [], mapping: {} }));
  soundFiles = s.files;
  soundMapping = s.mapping;
}

function fillSoundTiles() {
  $("#snd-tests").innerHTML = SOUNDS.map((n) => `
    <div class="sound-tile" data-choose="${n}" title="${esc(t("sound_tile_title"))}">
      <button class="play" data-play="${n}" title="${esc(t("listen"))}">▶</button>
      <div><b>${esc(t("sound_" + n))}</b><small>${soundMapping[n] ? "🎵 " + esc(soundMapping[n]) : esc(t("built_in"))}</small></div>
    </div>`).join("");
}

async function loadSoundSettings() {
  fillCalloutPilots();
  piVoices = (await api("/api/voices").catch(() => ({ voices: [] }))).voices;
  await loadSoundLibrary();
  fillSoundTiles();
  $("#snd-sounds").checked = audio.sounds;
  $("#snd-speech").checked = audio.speech;
  $("#snd-rate").value = audio.rate;
  $("#snd-rate-v").textContent = num(audio.rate, 2) + "×";
  $("#snd-volume").value = audio.volume;
  $("#snd-volume-v").textContent = Math.round(audio.volume * 100) + " %";
  fillVoices();
  prepareVoice();  // generate missing snippets (e.g. new pilots)
}
loadSoundLibrary();

$("#snd-sounds").addEventListener("change", () => { audio.sounds = $("#snd-sounds").checked; saveAudio(); });
$("#snd-speech").addEventListener("change", () => { audio.speech = $("#snd-speech").checked; saveAudio(); });
// ---- callouts for: "All pilots" or "Only me". Who "me" is, the device asks once and remembers.
function fillCalloutPilots() {
  const meLabel = audio.me ? t("callouts_me_named", { name: audio.me }) : t("callouts_me");
  document.querySelectorAll(".callout-filter").forEach((box) => {  // settings and spectator menu
    box.innerHTML = `<div class="segmented">
        <button data-filter="all" class="${audio.only_me ? "" : "on"}">${esc(t("callouts_all"))}</button>
        <button data-filter="me" class="${audio.only_me ? "on" : ""}">${esc(meLabel)}</button></div>
      ${audio.me ? `<button class="link" data-filter="change">${esc(t("change"))}</button>` : ""}`;
  });
  $("#welcome-me").textContent = audio.me ? t("i_am_name", { name: audio.me }) : t("i_am");
}

function setMe(name) {
  Object.assign(audio, { me: name, only_me: true });
  saveAudio();
  if (!calloutsOn) {  // whoever says who they are wants to hear their times
    calloutsOn = true;
    calloutToggles.forEach((toggle) => (toggle.checked = true));
    store.write("callouts", true);
  }
  fillCalloutPilots();
}

document.querySelectorAll(".callout-filter").forEach((box) => box.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-filter]");
  if (!b) return;
  unlockAudio();
  if (b.dataset.filter === "all") {
    audio.only_me = false;
    saveAudio();
    fillCalloutPilots();
  } else if (b.dataset.filter === "me" && audio.me) {
    audio.only_me = true;
    saveAudio();
    fillCalloutPilots();
  } else {
    const name = await askWhoAmI();
    if (name) setMe(name);
  }
}));
$("#welcome-me").addEventListener("click", async () => {
  unlockAudio();
  const name = await askWhoAmI();
  if (name) setMe(name);
});

// "Who are you?": the pilots of the current or next race as buttons, below a search over all pilots
function askWhoAmI() {
  const names = (list) => [...new Set(list.filter(Boolean))];
  const current = S.race && S.race.status !== "ready"
    ? names(S.race.participants.map((p) => p.pilot))
    : names((S.selection?.participants || []).map((p) => S.pilots.find((x) => x.id === p.pilot_id)?.name));
  const buttons = (list) => list.map((n) => `<button data-me="${esc(n)}">${esc(n)}</button>`).join("");
  $("#me-current").innerHTML = current.length
    ? `<div class="muted small">${esc(t("in_this_race"))}</div><div class="me-buttons">${buttons(current)}</div>` : "";
  const search = () => {
    const q = $("#me-search").value.trim().toLocaleLowerCase();
    const all = S.pilots.map((p) => p.name);
    let found = q ? all.filter((n) => n.toLocaleLowerCase().includes(q)) : (all.length <= 12 ? all : []);
    found.sort((a, b) => b.toLocaleLowerCase().startsWith(q) - a.toLocaleLowerCase().startsWith(q) || a.localeCompare(b));
    found = found.slice(0, 12);
    $("#me-results").innerHTML = found.length ? buttons(found)
      : q ? `<span class="muted small">${esc(t("no_match"))}</span>` : "";
  };
  $("#me-search").value = "";
  search();
  $("#me-dialog").hidden = false;
  $("#me-search").focus();
  return new Promise((done) => {
    const end = (name) => {
      $("#me-dialog").hidden = true;
      $("#me-dialog").onclick = $("#me-search").oninput = null;
      done(name);
    };
    $("#me-search").oninput = search;
    $("#me-dialog").onclick = (e) => {
      const b = e.target.closest("[data-me]");
      if (b) end(b.dataset.me);
      else if (e.target.id === "me-cancel" || e.target.id === "me-dialog") end(null);
    };
  });
}

// gear top right: the settings tab for the race director, a small menu for spectators
// (callouts, callout filter, language, signing out)
$("#gear").addEventListener("click", (e) => {
  if (S.admin) return showTab("settings");
  e.stopPropagation();
  fillCalloutPilots();
  $("#sm-menu").hidden = !$("#sm-menu").hidden;
});
$("#sm-menu").addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", () => ($("#sm-menu").hidden = true));
$("#sm-sign-out").addEventListener("click", attempt(async () => {
  await api("/api/sign_out", {});
  location.reload();  // back to the login page
}));
options($("#sm-language"), Object.entries(LANGUAGES), lang);
$("#sm-language").addEventListener("change", () => setLanguage($("#sm-language").value));

$("#snd-voice").addEventListener("change", () => {
  const entry = piVoices.find((v) => v.id === $("#snd-voice").value);
  audio.voices[lang] = entry?.speakers ? `${entry.id}:${entry.speakers[0].nr}` : $("#snd-voice").value;
  fillSpeakers(entry);
  voiceChosen();
});
$("#snd-speaker").addEventListener("change", () => {
  audio.voices[lang] = `${piEntry(voiceId()).id}:${$("#snd-speaker").value}`;
  voiceChosen();
});
$("#snd-rate").addEventListener("input", () => {
  audio.rate = Number($("#snd-rate").value);
  $("#snd-rate-v").textContent = num(audio.rate, 2) + "×";
  saveAudio();
});
$("#snd-volume").addEventListener("input", () => {
  audio.volume = Number($("#snd-volume").value);
  $("#snd-volume-v").textContent = Math.round(audio.volume * 100) + " %";
  saveAudio();
});
$("#snd-voice-test").addEventListener("click", () => { unlockAudio(); speakNow(t("say_voice_test")); });
// tile: ▶ plays the current sound, a click on the rest opens the selection
$("#snd-tests").addEventListener("click", (e) => {
  unlockAudio();
  const p = e.target.closest("[data-play]");
  if (p) return playSound(p.dataset.play);
  const tile = e.target.closest("[data-choose]");
  if (tile) openSoundDialog(tile.dataset.choose);
});

// ---- selection dialog: choose, listen to, upload, delete a file
let dialogEvent = null;

function openSoundDialog(event) {
  dialogEvent = event;
  $("#sd-title").textContent = t("sound_for", { name: t("sound_" + event) });
  fillSoundDialog();
  $("#sound-dialog").hidden = false;
}

function fillSoundDialog() {
  const current = soundMapping[dialogEvent] || "";
  const row = (file, text, deletable) => `
    <li class="${file === current ? "chosen" : ""}">
      <button class="mini" data-listen="${esc(file)}">▶</button>
      <span class="sd-name">${esc(text)}</span>
      ${file === current ? `<span class="muted small">${esc(t("chosen"))}</span>`
                         : `<button class="mini primary" data-take="${esc(file)}">${esc(t("choose"))}</button>`}
      ${deletable ? `<button class="mini danger" data-remove="${esc(file)}" title="${esc(t("delete_file"))}">🗑</button>` : ""}
    </li>`;
  $("#sd-list").innerHTML = row("", t("built_in_default"), false) +
    (soundFiles.map((f) => row(f, f, true)).join("") ||
     `<li class="muted small">${esc(t("no_own_sounds"))}</li>`);
}

const mapSound = attempt(async (file) => {
  await api("/api/sounds/map", { event: dialogEvent, file: file || null });
  await loadSoundLibrary();
  fillSoundDialog();
  fillSoundTiles();
});

$("#sd-list").addEventListener("click", attempt(async (e) => {
  unlockAudio();
  const listen = e.target.closest("[data-listen]"), take = e.target.closest("[data-take]");
  const remove = e.target.closest("[data-remove]");
  if (listen) {
    if (listen.dataset.listen) await playFile(listen.dataset.listen);
    else if (TONES[dialogEvent]) await playTones(TONES[dialogEvent]);
  } else if (take) {
    await mapSound(take.dataset.take);
  } else if (remove) {
    if (!confirm(t("confirm_delete_sound", { file: remove.dataset.remove }))) return;
    await api("/api/sounds/delete", { file: remove.dataset.remove });
    await loadSoundLibrary();
    fillSoundDialog();
    fillSoundTiles();
  }
}));

$("#sd-upload").addEventListener("click", () => $("#sd-file").click());
$("#sd-file").addEventListener("change", attempt(async () => {
  const file = $("#sd-file").files[0];
  $("#sd-file").value = "";
  if (!file) return;
  $("#sd-status").textContent = t("uploading", { file: file.name });
  try {
    const r = await fetch(`/api/sounds/upload?name=${encodeURIComponent(file.name)}`,
                          { method: "POST", body: file, headers: { "X-Language": lang } });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || t("error_status", { status: r.status }));
    await loadSoundLibrary();
    await mapSound(j.file);           // use the uploaded file for this event right away
    $("#sd-status").textContent = t("uploaded", { file: j.file });
  } catch (e) {
    $("#sd-status").textContent = "";
    throw e;
  }
}));

function closeSoundDialog() { $("#sound-dialog").hidden = true; $("#sd-status").textContent = ""; }
$("#sd-close").addEventListener("click", closeSoundDialog);
$("#sound-dialog").addEventListener("click", (e) => { if (e.target.id === "sound-dialog") closeSoundDialog(); });

// ============================================================ race: selection
const PARAMETERS = {
  laps: { text: "param_laps", toInput: (v) => v, fromInput: (v) => Math.round(v), step: 1 },
  duration_s: { text: "param_duration", toInput: (v) => v / 60, fromInput: (v) => Math.round(v * 60), step: 0.5 },
  n: { text: "param_n", toInput: (v) => v, fromInput: (v) => Math.round(v), step: 1 },
};
const MAX_PARTICIPANTS = 8;

function settingsFor(format) {
  const f = S.formats.find((x) => x.format === format);
  return { ...f.defaults, ...((S.selection?.settings || {})[format] || {}) };
}

function fillSetup() {
  if (!S.selection || !S.formats.length) return;
  options($("#s-format"), S.formats.map((f) => [f.format, t("format_" + f.format)]), S.selection.format);
  options($("#s-track"), [["", t("popup_course_long")], ...S.tracks.map((tr) => [tr.id, tr.name])],
    S.selection.track_id);
  options($("#s-staging"), [[0, t("staging_none")], [15, "15 s"], [30, "30 s"], [45, "45 s"], [60, "60 s"]],
    S.selection.staging_s ?? 0);
  fillParameters();
  let list = (S.selection.participants || []).filter((p) => S.pilots.some((x) => x.id === p.pilot_id));
  if (!list.length) list = [{ pilot_id: null, quad_id: null }];
  fillParticipants(list);
}

function fillParameters() {
  const format = $("#s-format").value;
  const f = S.formats.find((x) => x.format === format);
  const settings = settingsFor(format);
  $("#s-staging-row").hidden = format === "practice";  // practice starts without a countdown
  $("#s-parameters").className = "parameters";
  $("#s-parameters").innerHTML = Object.keys(f.defaults).map((k) => {
    const p = PARAMETERS[k], [low, high] = f.limits[k];
    return `<label>${esc(t(p.text))}<input type="number" data-param="${k}" step="${p.step}"
      min="${p.toInput(low)}" max="${p.toInput(high)}" value="${p.toInput(settings[k])}"></label>`;
  }).join("");
}

function fillParticipants(list) {
  $("#s-participants").innerHTML = list.map(() => `<div class="participant-row">
      <select data-field="pilot"></select><select data-field="quad"></select>
      <button class="mini" data-remove title="${esc(t("remove"))}">✕</button></div>`).join("");
  const rows = document.querySelectorAll("#s-participants .participant-row");
  list.forEach((p, i) => {
    const row = rows[i];
    options(row.querySelector("[data-field=pilot]"), [["", t("choose_pilot")], ...S.pilots.map((x) => [x.id, x.name])], p.pilot_id);
    fillQuads(row, p.quad_id);
  });
  $("#s-add").hidden = list.length >= MAX_PARTICIPANTS;
}

function fillQuads(row, chosen) {
  const pilot = row.querySelector("[data-field=pilot]").value;
  const list = pilot ? quadsOf(pilot) : [];
  options(row.querySelector("[data-field=quad]"), list.map((q) => [q.id, q.name]), chosen ?? list[0]?.id);
}

function readParticipants() {
  return [...document.querySelectorAll("#s-participants .participant-row")].map((row) => ({
    pilot_id: Number(row.querySelector("[data-field=pilot]").value) || null,
    quad_id: Number(row.querySelector("[data-field=quad]").value) || null,
  }));
}

function readSelection() {
  const settings = {};
  document.querySelectorAll("#s-parameters input").forEach((i) => {
    settings[i.dataset.param] = PARAMETERS[i.dataset.param].fromInput(Number(i.value));
  });
  return { format: $("#s-format").value, settings, track_id: Number($("#s-track").value) || null,
           participants: readParticipants(), staging_s: Number($("#s-staging").value) || 0 };
}

const saveSelection = attempt(async () => {
  const s = readSelection();
  S.selection.format = s.format;
  S.selection.track_id = s.track_id;
  S.selection.participants = s.participants;
  S.selection.staging_s = s.staging_s;
  (S.selection.settings ||= {})[s.format] = s.settings;
  await api("/api/selection", s);
});
$("#s-format").addEventListener("change", () => { fillParameters(); saveSelection(); });
$("#s-track").addEventListener("change", saveSelection);
$("#s-staging").addEventListener("change", saveSelection);
$("#s-parameters").addEventListener("change", saveSelection);
$("#s-participants").addEventListener("change", (e) => {
  if (e.target.dataset.field === "pilot") fillQuads(e.target.closest(".participant-row"));
  saveSelection();
});
$("#s-participants").addEventListener("click", (e) => {
  if (!e.target.closest("[data-remove]")) return;
  const list = readParticipants();
  list.splice([...document.querySelectorAll("#s-participants [data-remove]")].indexOf(e.target.closest("[data-remove]")), 1);
  fillParticipants(list.length ? list : [{ pilot_id: null, quad_id: null }]);
  saveSelection();
});
$("#s-add").addEventListener("click", () => {
  fillParticipants([...readParticipants(), { pilot_id: null, quad_id: null }]);
});

const startRace = attempt(async () => {
  const s = readSelection();
  s.participants = s.participants.filter((p) => p.pilot_id && p.quad_id);
  if (!s.participants.length) throw new Error(t("choose_a_pilot"));
  await api("/api/race/start", s);
  S.openPilot = null;
});
$("#start").addEventListener("click", startRace);
$("#again").addEventListener("click", startRace);
$("#finish").addEventListener("click", attempt(() => api("/api/race/finish", {})));
$("#abort").addEventListener("click", attempt(async () => {
  if (confirm(t("confirm_abort"))) await api("/api/race/abort", {});
}));
$("#end-practice").addEventListener("click", attempt(() => api("/api/race/end_practice", {})));
$("#ok").addEventListener("click", attempt(() => api("/api/race/dismiss", {})));
$("#skip-staging").addEventListener("click", attempt(() => api("/api/race/skip_staging", {})));

// ============================================================ race: display
let lastStatus = null;

function statusText(r) {
  if (r.status === "ready") return [t("status_ready"), "ready"];
  if (r.status === "staging") return [t("status_staging"), "countdown"];
  if (r.status === "countdown") return [t("status_countdown"), "countdown"];
  if (r.status === "finished") return [t("status_finished"), "finished"];
  return r.format === "practice" ? [t("status_practice"), "practice"] : [t("status_running"), "running"];
}

function showRace(r) {
  const [text, cls] = statusText(r);
  const ps = r.participants;
  const single = ps.length === 1 ? ps[0] : null;
  $("#status").className = `status ${cls}`;
  $("#status").textContent = text + (single ? ` · ${single.pilot}` : ps.length ? ` · ${t("n_pilots", { n: ps.length })}` : "");

  const ready = r.status === "ready";
  $("#setup").hidden = !ready;
  $("#live").hidden = ready;
  if (r.status !== lastStatus && ready) fillSetup();
  lastStatus = r.status;
  if (ready) {
    ["#unassigned-card", "#monitor-card", "#laps-card"].forEach((s) => ($(s).hidden = true));
    return;
  }

  // controls / result
  const practice = r.format === "practice";
  const category = categoryName(r.format, r.settings);
  $("#controls").hidden = r.status === "finished";
  $("#result").hidden = r.status !== "finished";
  $("#finish").hidden = practice || r.status === "countdown" || r.status === "staging";
  $("#skip-staging").hidden = r.status !== "staging";
  $("#abort").hidden = practice;
  $("#end-practice").hidden = !practice;
  $("#ctl-category").textContent = category;
  const track = S.tracks.find((tr) => tr.id === r.track_id)?.name;
  $("#ctl-info").textContent = `${ps.map((p) => p.pilot).join(", ")} · ${track ?? t("popup_course")}`;
  if (r.status === "finished") showResult(r, category);

  showBig(r, single);
  showLast(r);
  showUnassigned(r);

  // several: lap monitor + expanded pilot; one: only their laps
  $("#monitor-card").hidden = !!single;
  if (!single) showMonitor(r);
  const shown = single || ps.find((p) => p.quad_id === S.openPilot);
  $("#laps-card").hidden = !shown;
  if (shown) {
    $("#laps-title").textContent = single ? t("laps") : `${t("laps")} · ${shown.pilot}`;
    lapTable(r, shown);
  }
}

function showBig(r, single) {
  const big = $("#big");
  big.classList.toggle("countdown", r.status === "countdown");
  $("#figures").hidden = !single;
  if (r.status === "staging") {
    $("#big-label").textContent = t("until_start");
    big.textContent = mmss(Math.ceil(r.staging_s));
    return;
  }
  if (r.status === "countdown") {
    $("#big-label").textContent = t("about_to_start");
    big.textContent = r.countdown;
    return;
  }
  if (r.status === "finished") {
    $("#big-label").textContent = t("race_over");
    big.textContent = "🏁";
  } else if (!single) {
    // several pilots: remaining time or race time
    $("#big-label").textContent = r.remaining_s != null ? t("remaining_time")
      : (r.format === "practice" ? t("practice_time") : t("race_time"));
    big.textContent = r.remaining_s != null
      ? (r.remaining_s > 0 ? mmss(Math.ceil(r.remaining_s)) : t("last_lap_excl")) : clockText(r.race_time_s);
  } else if (!single.started) {
    $("#big-label").textContent = r.format === "practice" ? t("waiting_first") : t("go_waiting_first");
    big.textContent = clockText(r.race_time_s);
  } else {
    $("#big-label").textContent = single.finished ? t("finished") : t("current_lap");
    big.textContent = single.finished ? "🏁" : clockText(single.since_last_s);
  }
  if (!single) return;
  $("#f-last").textContent = timeText(single.laps.at(-1));
  $("#f-best").textContent = timeText(single.best);
  if (r.status === "running" && r.remaining_s != null) {
    $("#f-progress-label").textContent = t("remaining_time");
    $("#f-progress").textContent = r.remaining_s > 0 ? mmss(Math.ceil(r.remaining_s)) : t("last_lap_excl");
  } else if (r.format === "laps" && r.status !== "finished") {
    $("#f-progress-label").textContent = t("lap");
    $("#f-progress").textContent = `${Math.min(single.laps.length + 1, r.settings.laps)}/${r.settings.laps}`;
  } else {
    $("#f-progress-label").textContent = t("laps");
    $("#f-progress").textContent = single.laps.length;
  }
}

function showResult(r, category) {
  $("#r-category").textContent = category;
  const html = r.participants.map((p) => {
    const rating = p.rating || {};
    let extra = "";
    if (rating.record === "track") extra = t("track_record");
    else if (rating.record === "personal") extra = t("personal_best");
    else if (rating.rank) extra = t("rank_on_track", { rank: rating.rank });
    const holeshot = p.holeshot_s != null && p.result
      ? `<br><span class="muted small">${esc(t("incl_holeshot", { time: timeText(p.holeshot_s) }))}</span>` : "";
    return `<tr><td>${p.rank === 1 && r.participants.length > 1 ? "🥇" : p.rank}</td>
      <td><b>${esc(p.pilot)}</b> <span class="muted small">${esc(p.quad)}</span></td>
      <td><b>${esc(resultText(p.result))}</b>${holeshot}</td>
      <td class="small">${esc(extra)}</td></tr>`;
  }).join("");
  if ($("#r-list").innerHTML !== html) $("#r-list").innerHTML = html;
}

function showLast(r) {
  const l = r.last;
  $("#last-card").hidden = !l;
  if (!l) return;
  const url = l.photo ? photoUrl(l.photo) : "";
  if ($("#last-photo").dataset.url !== url) {
    $("#last-photo").dataset.url = url;
    if (url) $("#last-photo").src = url; else $("#last-photo").removeAttribute("src");
  }
  $("#last-pilot").textContent = l.pilot ?? t("unassigned_q");
  $("#last-info").textContent = t("after_start", { time: timeText(l.t) }) +
    (l.ignored ? t("ignored_note") : l.pilot && l.uncertain ? t("uncertain_note") : "");
}

function showUnassigned(r) {
  $("#unassigned-card").hidden = !r.unassigned.length;
  $("#unassigned-count").textContent = r.unassigned.length;
  const buttons = r.participants.filter((p) => !p.finished);
  const html = r.unassigned.map((u) => `<div class="unassigned-entry">${photoImg(u.photo, "photo-medium")}
      <span class="muted">${esc(t("after_start", { time: timeText(u.t) }))}</span>
      ${r.status === "running" ? buttons.map((p) => `<button data-unassigned="${u.nr}" data-quad="${p.quad_id}">→ ${esc(p.pilot)}</button>`).join("")
                               : `<span class="muted small">${esc(t("assign_in_history"))}</span>`}</div>`).join("");
  if ($("#unassigned-list").innerHTML !== html) $("#unassigned-list").innerHTML = html;
}
$("#unassigned-list").addEventListener("click", attempt(async (e) => {
  const b = e.target.closest("[data-unassigned]");
  if (b) await api("/api/race/assign", { nr: Number(b.dataset.unassigned), quad_id: Number(b.dataset.quad) });
}));

function gapText(gap) {
  if (!gap) return "";
  return gap.laps != null ? plural("gap_laps", gap.laps) : "+" + timeText(gap.time_s);
}

function showMonitor(r) {
  const html = r.participants.map((p) => {
    const target = r.format === "laps" ? `/${r.settings.laps}` : "";
    return `<tr data-quad="${p.quad_id}" class="${p.quad_id === S.openPilot ? "open" : ""} ${p.finished ? "done" : ""}">
      <td>${p.rank}</td><td>${esc(p.pilot)}</td><td>${p.laps.length}${target}</td>
      <td>${timeText(p.laps.at(-1))}</td><td>${timeText(p.best)}</td><td>${esc(gapText(p.gap))}</td></tr>`;
  }).join("");
  if ($("#monitor").innerHTML !== html) $("#monitor").innerHTML = html;
}
$("#monitor").addEventListener("click", (e) => {
  const row = e.target.closest("[data-quad]");
  if (!row) return;
  const id = Number(row.dataset.quad);
  S.openPilot = S.openPilot === id ? null : id;
});

// Lap table of a participant: top to bottom in time order.
// Holeshot + laps = total time. With "X laps" all rows are there from the start.
let lastCurrentRow = null;

function lapTable(r, p) {
  const practice = r.format === "practice";
  const running = r.status === "running";
  const rows = [];
  const current = (s) => `▶ ${clockText(s)}`;

  if (practice) {
    p.laps.forEach((l, i) => rows.push({ lap: i + 1, time: timeText(l), cls: l === p.best ? "best" : "" }));
    if (running && p.since_last_s != null) rows.push({ lap: p.laps.length + 1, time: current(p.since_last_s), cls: "current" });
  } else {
    if (p.holeshot_s != null) {
      rows.push({ lap: "Holeshot", time: timeText(p.holeshot_s), total: timeText(p.holeshot_s), cls: "holeshot" });
    } else {
      rows.push({ lap: "Holeshot", time: running ? current(r.race_time_s) : "–", total: "",
                  cls: running ? "holeshot current" : "holeshot empty" });
    }
    let total = p.holeshot_s ?? 0;
    p.laps.forEach((l, i) => {
      total += l;
      rows.push({ lap: i + 1, time: timeText(l), total: timeText(total), cls: l === p.best ? "best" : "" });
    });
    const target = r.format === "laps" ? r.settings.laps : null;
    if (running && p.holeshot_s != null && !p.finished) {
      rows.push({ lap: p.laps.length + 1, time: current(p.since_last_s), total: "", cls: "current" });
    }
    if (target != null && r.status !== "finished" && !p.finished) {
      for (let nr = rows.length; nr <= target; nr++) rows.push({ lap: nr, time: "–", total: "", cls: "empty" });
    }
  }

  $(".lap-table").classList.toggle("no-total", practice);
  const html = rows.map((row) => `<tr class="${row.cls}"><td>${row.lap}</td><td>${row.time}</td>
    <td class="col-total">${row.total ?? ""}</td></tr>`).join("");
  if ($("#laps").innerHTML !== html) $("#laps").innerHTML = html;

  // scroll to the current row, but only when a new lap has begun
  const currentRow = rows.findIndex((row) => row.cls.includes("current"));
  if (currentRow !== lastCurrentRow) {
    lastCurrentRow = currentRow;
    $("#laps").children[currentRow]?.scrollIntoView({ block: "nearest" });
  }
}

// ---- shut down / restart the Pi
async function systemCommand(action) {
  const off = action === "shutdown";
  if (!confirm(t(off ? "confirm_shutdown" : "confirm_reboot"))) return;
  await api(`/api/system/${action}`, {});
  $("#sys-title").textContent = t(off ? "shutting_down" : "rebooting");
  $("#sys-text").textContent = t(off ? "shutting_down_text" : "rebooting_text");
  $("#system-notice").hidden = false;
  if (off) return;
  await wait(15000);  // let it shut down properly first
  for (;;) {
    try {
      if ((await fetch("/api/formats", { cache: "no-store" })).ok) break;
    } catch { /* not back yet */ }
    await wait(2000);
  }
  location.reload();
}
// ---- hotspot password
$("#hotspot-form").addEventListener("submit", attempt(async (e) => {
  e.preventDefault();
  const password = $("#hotspot-password").value;
  if (!confirm(t("confirm_hotspot_password", { password }))) return;
  await api("/api/hotspot/password", { password });
  $("#hotspot-password").value = "";
  message(t("hotspot_password_changed"), true);
}));

$("#sys-off").addEventListener("click", attempt(() => systemCommand("shutdown")));
$("#sys-reboot").addEventListener("click", attempt(() => systemCommand("reboot")));

// ---- race director / spectator
const RACE_DIRECTOR_TABS = new Set(["history", "pilots", "settings", "camera"]);

function applyRole(role) {
  if (!role) return;
  const changed = role.admin !== S.admin || role.pin_set !== S.pinSet;
  S.admin = role.admin;
  S.pinSet = role.pin_set;
  document.body.classList.toggle("spectator", !S.admin);
  $("#role-spectator").hidden = S.admin;
  $("#role-admin").hidden = !S.admin;
  if (!S.admin && RACE_DIRECTOR_TABS.has(S.tab)) showTab("race");
  if (changed && S.tab === "history" && historyChosen) showRaceDetail(historyChosen);  // buttons on/off
}

$("#role-sign-in").addEventListener("submit", attempt(async (e) => {
  e.preventDefault();
  await api("/api/sign_in", { pin: $("#role-pin").value });
  location.reload();  // reload as race director
}));
$("#role-pin-form").addEventListener("submit", attempt(async (e) => {
  e.preventDefault();
  const pin = $("#role-new-pin").value;
  if (!confirm(t("confirm_pin_change", { pin }))) return;
  await api("/api/pin", { pin });
  $("#role-new-pin").value = "";
  message(t("pin_changed"), true);
}));
$("#role-sign-out").addEventListener("click", attempt(async () => {
  await api("/api/sign_out", {});
  location.reload();  // back to the login page
}));

// ============================================================ polling loop
async function poll() {
  if (signedOut) return;  // the login page is open
  try {
    const d = await api(`/api/state?since=${S.nr}`);
    S.nr = d.event_nr;
    S.race = d.race;
    S.camera = d.camera;
    S.settings = d.settings;
    applyRole(d.role);
    if (!S.selection) { S.selection = d.selection; fillSetup(); }
    d.events.forEach(callout);
    if (d.events.some((e) => e.type === "race_end") && S.tab === "history") loadHistory();
    showRace(d.race);
    if (S.tab === "camera") showCamera(d.camera, d.recent_crossings);
  } catch (e) { /* Pi briefly not reachable – next try soon */ }
  setTimeout(poll, 150);
}

// ============================================================ statistics
async function loadStats() {
  // pop-up course = all races without a fixed track (no records there, the course changes every time)
  options($("#st-track"), [["none", t("popup_course")], ...S.tracks.map((tr) => [tr.id, tr.name])],
    store.read("st-track", S.tracks[0]?.id ?? "none"));
  options($("#st-quad"), [["", t("all_quads")], ...S.quads.map((q) => [q.id, `${q.pilot} – ${q.name}`])],
    store.read("st-quad", ""));
  options($("#st-pilot"), S.pilots.map((p) => [p.id, p.name]), store.read("st-pilot", S.pilots[0]?.id));
  await statsTrackChosen();
}
const statsFilter = () => `track=${$("#st-track").value}&quad=${$("#st-quad").value}`;

const statsTrackChosen = attempt(async () => {
  const track = $("#st-track").value;
  if (!track) { ["#st-leaderboard", "#st-records"].forEach((s) => ($(s).innerHTML = "")); $("#st-chart").innerHTML = ""; return; }
  store.write("st-track", track);
  store.write("st-quad", $("#st-quad").value);
  const categories = await api(`/api/stats/categories?${statsFilter()}`);
  const list = categories.map((c) => [c.key, statsCategoryName(c)]);
  options($("#st-cat"), list, store.read("st-cat", list[0]?.[0]));
  options($("#st-pcat"), list, store.read("st-pcat", list[0]?.[0]));
  await Promise.all([loadLeaderboard(), loadPilotStats()]);
});

const loadLeaderboard = attempt(async () => {
  const cat = $("#st-cat").value;
  if (!$("#st-track").value || !cat) return;
  store.write("st-cat", cat);
  const list = await api(`/api/stats/leaderboard?${statsFilter()}&category=${encodeURIComponent(cat)}`);
  $("#st-leaderboard").innerHTML = list.length ? list.map((e) =>
    `<tr class="clickable" data-race="${e.race_id}"><td>${e.rank === 1 ? "🏆" : e.rank}</td><td>${esc(e.pilot)}</td>
     <td>${esc(resultText(e))}</td><td class="muted">${dateText(e.date)}</td></tr>`).join("")
    : `<tr><td colspan="4" class="muted">${esc(t("no_results_category"))}</td></tr>`;
});

const loadPilotStats = attempt(async () => {
  const pilot = $("#st-pilot").value;
  if (!$("#st-track").value || !pilot) return;
  store.write("st-pilot", Number(pilot));
  const records = await api(`/api/stats/pilot?${statsFilter()}&pilot=${pilot}`);
  $("#st-records").innerHTML = records.length ? records.map((r) =>
    `<tr class="clickable" data-race="${r.race_id}"><td>${esc(statsCategoryName(r))}</td><td>${esc(resultText(r))}</td>
     <td>${r.rank === 1 ? "🏆 1" : r.rank}</td></tr>`).join("")
    : `<tr><td colspan="3" class="muted">${esc(t("no_races_on_track"))}</td></tr>`;
  await loadProgress();
});

const loadProgress = attempt(async () => {
  const pilot = $("#st-pilot").value, cat = $("#st-pcat").value;
  if (!$("#st-track").value || !pilot || !cat) return;
  store.write("st-pcat", cat);
  const p = await api(`/api/stats/progress?${statsFilter()}&pilot=${pilot}&category=${encodeURIComponent(cat)}`);
  $("#st-chart").innerHTML = chart(p);
});

function chart({ points, higher_is_better }) {
  if (points.length === 0) return `<p class="muted">${esc(t("no_values"))}</p>`;
  const W = 600, H = 240, L = 60, R = 16, T = 16, B = 34;
  const values = points.flatMap((p) => [p.value, p.best]);
  let min = Math.min(...values), max = Math.max(...values);
  if (min === max) { min -= 1; max += 1; }
  const pad = (max - min) * 0.1; min -= pad; max += pad;
  const x = (i) => L + (points.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (points.length - 1));
  // top = better: for times (smaller is better) the axis is turned around
  const y = (v) => { const a = (v - min) / (max - min); return T + (higher_is_better ? 1 - a : a) * (H - T - B); };
  const fmt = (v) => (higher_is_better ? String(Math.round(v)) : num(v, 1));
  const top = higher_is_better ? max : min, bottom = higher_is_better ? min : max;
  const bestLine = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.best).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("progress"))}">
    <line class="axis" x1="${L}" y1="${T}" x2="${L}" y2="${H - B}"/>
    <line class="axis" x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}"/>
    <text class="label" x="${L - 6}" y="${T + 4}" text-anchor="end">${fmt(top)}</text>
    <text class="label" x="${L - 6}" y="${H - B}" text-anchor="end">${fmt(bottom)}</text>
    <text class="label" x="${L}" y="${H - 12}">${dateText(points[0].date)}</text>
    <text class="label" x="${W - R}" y="${H - 12}" text-anchor="end">${dateText(points.at(-1).date)}</text>
    <path class="best-line" d="${bestLine}"/>
    ${points.map((p, i) => `<circle class="point" cx="${x(i).toFixed(1)}" cy="${y(p.value).toFixed(1)}" r="4">
      <title>${dateText(p.date)}: ${esc(resultText(p))}</title></circle>`).join("")}
  </svg>`;
}

$("#st-track").addEventListener("change", statsTrackChosen);
$("#st-quad").addEventListener("change", statsTrackChosen);
$("#st-cat").addEventListener("change", loadLeaderboard);
$("#st-pilot").addEventListener("change", loadPilotStats);
$("#st-pcat").addEventListener("change", loadProgress);
// a click on a row opens the race in the race history
["#st-leaderboard", "#st-records"].forEach((s) => $(s).addEventListener("click", (e) => {
  const row = e.target.closest("[data-race]");
  if (!row || !S.admin) return;  // race history only for the race director
  showTab("history");
  showRaceDetail(Number(row.dataset.race));
}));

// ============================================================ race history
let historyChosen = null;
let historyShowDeleted = false;  // crossings deleted with ✕ are hidden otherwise
const historyRowVisible = (c) => historyShowDeleted || !c.deleted;

const loadHistory = attempt(async () => {
  const allP = await api("/api/pilots?all=1"), allT = await api("/api/tracks?all=1");
  if (!$("#h-pilot").options.length) {
    options($("#h-pilot"), [["", t("all")], ...allP.map((p) => [p.id, p.name])], "");
    options($("#h-track"), [["", t("all")], ["none", t("popup_course")], ...allT.map((tr) => [tr.id, tr.name])], "");
  }
  const list = await api(`/api/races?pilot=${$("#h-pilot").value}&track=${$("#h-track").value}`);
  $("#h-list").innerHTML = list.length ? list.map((r) =>
    `<li class="clickable${r.id === historyChosen ? " chosen" : ""}" data-id="${r.id}">
      <div><b>${esc(r.pilots.join(", "))}</b> · ${esc(categoryName(r.format, r.settings))}${r.unassigned ? ` · <span title="${esc(t("unassigned"))}">❓ ${r.unassigned}</span>` : ""}<br>
      <span class="muted small">${dateText(r.started)} · ${esc(r.track ?? t("popup_course"))}</span></div></li>`).join("")
    : `<li class="muted">${esc(t("no_saved_races"))}</li>`;
});
["#h-pilot", "#h-track"].forEach((s) => $(s).addEventListener("change", loadHistory));
$("#h-list").addEventListener("click", (e) => {
  const li = e.target.closest("[data-id]");
  if (li) showRaceDetail(Number(li.dataset.id));
});

const showRaceDetail = attempt(async (id) => {
  historyChosen = id;
  document.querySelectorAll("#h-list li").forEach((li) => li.classList.toggle("chosen", Number(li.dataset.id) === id));
  const [race, allP, allT] = await Promise.all([api(`/api/races/${id}`), api("/api/pilots?all=1"), api("/api/tracks?all=1")]);
  const participants = race.pilot_races.map((r) => [r.pilot_id, r.pilot]);
  const assignSelect = (c, current) => `<select data-assign="${c.id}">
      <option value="">${esc(t(current ? "move_to" : "assign_to"))}</option>
      ${participants.filter(([pid]) => pid !== current).map(([pid, n]) => `<option value="${pid}">→ ${esc(n)}</option>`).join("")}</select>`;
  const deleteButton = (c) => `<button class="mini" data-crossing="${c.id}" data-action="${c.deleted ? "restore" : "delete"}">${c.deleted ? "↺" : "✕"}</button>`;

  const deletedCount = [...race.pilot_races.flatMap((r) => r.crossings), ...race.unassigned]
    .filter((c) => c.deleted).length;
  const pilotRacesHtml = race.pilot_races.map((r) => {
    let nr = 0;
    const rows = r.crossings.filter(historyRowVisible).map((c) => {
      const kind = c.deleted ? t("deleted") : c.lap == null ? "Holeshot" : `${t("lap")} ${++nr}`;
      const time = c.lap != null ? timeText(c.lap) : !c.deleted ? timeText(c.t) : "";
      const actions = S.admin ? `${deleteButton(c)} ${participants.length > 1 && !c.deleted ? assignSelect(c, r.pilot_id) : ""}` : "";
      return `<tr class="${c.deleted ? "deleted" : ""}"><td>${photoImg(c.photo)}</td><td>${kind}${c.uncertain ? " ⚠" : ""}</td>
        <td>${time}</td><td class="muted">${timeText(c.t)}</td><td>${actions}</td></tr>`;
    }).join("");
    return `<div class="pilot-race-block">
      <h4>${S.admin ? `<select data-pilot-race="${r.id}">${allP.map((p) => `<option value="${p.id}"${p.id === r.pilot_id ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select>` : esc(r.pilot)}
        <span class="muted small">${esc(r.quad ?? "")}</span>
        <b>${esc(resultText(r.result))}</b></h4>
      <table class="table"><thead><tr><th>${esc(t("photo"))}</th><th></th><th>${esc(t("lap_time"))}</th><th>${esc(t("since_go"))}</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="5" class="muted">${esc(t("no_crossings"))}</td></tr>`}</tbody></table></div>`;
  }).join("");

  const open = race.unassigned.filter(historyRowVisible);
  const openHtml = open.length ? `<div class="pilot-race-block"><h4>${esc(t("unassigned_q"))}</h4>
    <table class="table"><tbody>${open.map((c) => `<tr class="${c.deleted ? "deleted" : ""}">
      <td>${photoImg(c.photo)}</td><td class="muted">${esc(t("after_start", { time: timeText(c.t) }))}</td>
      <td class="admin-only">${assignSelect(c, null)} ${deleteButton(c)}</td></tr>`).join("")}
    </tbody></table></div>` : "";

  // ranking of the race, recalculated with every correction (deleted / reassigned crossings)
  const ranked = [...race.pilot_races].sort((a, b) => a.rank - b.rank);
  const rankingHtml = `<table class="table result-table"><thead><tr><th>#</th><th>${esc(t("pilot"))}</th>
      <th>${esc(t("result"))}</th><th>${esc(t("best_lap"))}</th><th>Holeshot</th></tr></thead><tbody>
    ${ranked.map((r) => `<tr><td>${r.rank === 1 && ranked.length > 1 && r.result ? "🥇" : r.rank}</td>
      <td><b>${esc(r.pilot)}</b> <span class="muted small">${esc(r.quad ?? "")}</span></td>
      <td><b>${esc(resultText(r.result))}</b></td><td>${timeText(r.best_lap)}</td>
      <td class="muted">${timeText(r.holeshot_s)}</td></tr>`).join("")}</tbody></table>`;

  $("#h-detail").innerHTML = `
    <h3>${esc(categoryName(race.format, race.settings))} · ${dateText(race.started)} ${infoButton("tip_history")}</h3>
    <label>${esc(t("track"))} <select id="hd-track"${S.admin ? "" : " disabled"}></select></label>
    <h4>${esc(t("ranking"))}</h4>${rankingHtml}
    ${pilotRacesHtml}${openHtml}
    ${deletedCount ? `<button class="mini" id="hd-deleted">${esc(historyShowDeleted
      ? t("hide_deleted") : t("show_deleted", { n: deletedCount }))}</button>` : ""}
    <button class="danger admin-only" id="hd-delete">${esc(t("delete_race"))}</button>`;
  options($("#hd-track"), [["", t("popup_course")], ...allT.map((tr) => [tr.id, tr.name])], race.track_id);
  $("#hd-track").addEventListener("change", attempt(async () => {
    await api(`/api/races/${id}`, { track_id: $("#hd-track").value || null });
    loadHistory(); message(t("track_changed"), true);
  }));
  $("#hd-delete").addEventListener("click", attempt(async () => {
    if (!confirm(t("confirm_delete_race"))) return;
    await api(`/api/races/${id}/delete`, {});
    historyChosen = null;
    $("#h-detail").innerHTML = `<p class="muted">${esc(t("race_deleted"))}</p>`;
    loadHistory();
  }));
});

$("#h-detail").addEventListener("click", attempt(async (e) => {
  if (e.target.closest("#hd-deleted")) {
    historyShowDeleted = !historyShowDeleted;
    return showRaceDetail(historyChosen);
  }
  const b = e.target.closest("[data-crossing]");
  if (!b) return;
  await api(`/api/crossings/${b.dataset.crossing}/${b.dataset.action}`, {});
  showRaceDetail(historyChosen);
}));
$("#h-detail").addEventListener("change", attempt(async (e) => {
  const assign = e.target.closest("[data-assign]");
  const pilot = e.target.closest("[data-pilot-race]");
  if (assign && assign.value) {
    await api(`/api/crossings/${assign.dataset.assign}/assign`, { pilot_id: Number(assign.value) });
  } else if (pilot) {
    await api(`/api/pilot_races/${pilot.dataset.pilotRace}`, { pilot_id: Number(pilot.value) });
    loadHistory();
  } else return;
  showRaceDetail(historyChosen);
}));

// ============================================================ settings
function loadRaceSettings() {
  if (!S.settings) return setTimeout(loadRaceSettings, 200);  // state not there yet
  $("#set-min-lap").value = S.settings.min_lap_s;
  $("#set-min-lap-v").textContent = minLapText(S.settings.min_lap_s);
  $("#set-photos").value = S.settings.photo_months;
  $("#set-photos-v").textContent = monthsText(S.settings.photo_months);
}
const minLapText = (v) => num(Number(v), 1) + " s";
const monthsText = (v) => plural("n_months", Math.round(v));
$("#set-min-lap").addEventListener("input", () => ($("#set-min-lap-v").textContent = minLapText($("#set-min-lap").value)));
$("#set-min-lap").addEventListener("change", attempt(async () => {
  await api("/api/settings", { min_lap_s: Number($("#set-min-lap").value) });
  message(`${t("min_lap")}: ${minLapText($("#set-min-lap").value)}`, true);
}));
$("#set-photos").addEventListener("input", () => ($("#set-photos-v").textContent = monthsText($("#set-photos").value)));
$("#set-photos").addEventListener("change", attempt(async () => {
  await api("/api/settings", { photo_months: Number($("#set-photos").value) });
  message(`${t("keep_photos")}: ${monthsText($("#set-photos").value)}`, true);
}));

$("#m-archived").addEventListener("change", () => loadManagement());

const loadManagement = attempt(async () => {
  const all = $("#m-archived").checked ? "?all=1" : "";
  const [pilots, quads, tracks] = await Promise.all([api(`/api/pilots${all}`), api(`/api/quads${all}`), api(`/api/tracks${all}`)]);
  const profiles = Object.fromEntries(await Promise.all(quads.map(async (q) => [q.id, await api(`/api/quads/${q.id}/profile`)])));
  const button = (kind, x, action, text) => `<button class="mini" data-kind="${kind}" data-id="${x.id}" data-action="${action}">${esc(text)}</button>`;

  $("#m-pilots").innerHTML = pilots.map((p) => {
    const qs = quads.filter((q) => q.pilot_id === p.id);
    return `<li class="pilot-block ${p.archived ? "archived" : ""}">
      <div class="pilot-head"><b>${esc(p.name)}</b><div class="button-row" style="margin:0">
        ${button("pilots", p, "new_quad", t("add_quad"))}${button("pilots", p, "rename", t("rename"))}
        ${button("pilots", p, "archive", t(p.archived ? "reactivate" : "archive"))}
        <button class="mini danger" data-kind="pilots" data-id="${p.id}" data-action="delete"
                title="${esc(t("delete_for_good"))}">🗑</button></div></div>
      <ul class="quad-list">${qs.map((q) => `<li class="${q.archived ? "archived" : ""}">
        <div>🚁 ${esc(q.name)} <span class="muted small">· ${esc(plural("n_samples", profiles[q.id].count))}</span>
          <div class="profile-photos">${profiles[q.id].photos.map((f) => `<img src="${photoUrl(esc(f))}" alt="" onerror="this.remove()">`).join("")}</div></div>
        <div class="button-row" style="margin:0">${button("quads", q, "rename", t("rename"))}
          ${button("quads", q, "profile", t("reset_profile"))}${button("quads", q, "archive", t(q.archived ? "reactivate" : "archive"))}</div>
      </li>`).join("")}</ul></li>`;
  }).join("") || `<li class="muted">${esc(t("no_pilots"))}</li>`;

  $("#m-tracks").innerHTML = tracks.map((tr) => `<li class="${tr.archived ? "archived" : ""}">
    <div><b>${esc(tr.name)}</b>${tr.description ? `<br><span class="muted small">${esc(tr.description)}</span>` : ""}</div>
    <div class="button-row" style="margin:0">${button("tracks", tr, "rename", t("rename"))}${button("tracks", tr, "description", t("description"))}
      ${button("tracks", tr, "archive", t(tr.archived ? "reactivate" : "archive"))}</div></li>`).join("") ||
    `<li class="muted">${esc(t("no_tracks"))}</li>`;
  S.m = { pilots, quads, tracks };
});

async function afterChange() {
  await loadMasterData();
  await loadManagement();
  $("#h-pilot").innerHTML = "";  // rebuild the history filter the next time it opens
}

$("#m-pilot-form").addEventListener("submit", attempt(async (e) => {
  e.preventDefault();
  await api("/api/pilots", { name: $("#m-pilot-name").value });
  $("#m-pilot-name").value = "";
  await afterChange();
}));
$("#m-track-form").addEventListener("submit", attempt(async (e) => {
  e.preventDefault();
  await api("/api/tracks", { name: $("#m-track-name").value, description: $("#m-track-description").value });
  $("#m-track-name").value = $("#m-track-description").value = "";
  await afterChange();
}));
document.querySelectorAll("#m-pilots, #m-tracks").forEach((list) => list.addEventListener("click", attempt(async (e) => {
  const b = e.target.closest("[data-action]");
  if (!b) return;
  const x = S.m[b.dataset.kind].find((v) => v.id === Number(b.dataset.id));
  const path = `/api/${b.dataset.kind}/${x.id}`;
  const action = b.dataset.action;
  if (action === "rename") {
    const name = prompt(t("new_name"), x.name);
    if (name === null) return;
    await api(path, { name });
  } else if (action === "description") {
    const description = prompt(t("description_prompt"), x.description);
    if (description === null) return;
    await api(path, { description });
  } else if (action === "new_quad") {
    const name = prompt(t("new_quad_prompt", { name: x.name }));
    if (!name) return;
    await api("/api/quads", { pilot_id: x.id, name });
  } else if (action === "profile") {
    if (!confirm(t("confirm_reset_profile", { name: x.name }))) return;
    await api(`/api/quads/${x.id}/clear_profile`, {});
  } else if (action === "delete") {
    if (!confirm(t("confirm_delete_pilot", { name: x.name }))) return;
    const pin = await askPin(t("pin_to_delete", { name: x.name }));
    if (pin === null) return;
    await api(`${path}/delete`, { pin });
    message(t("pilot_deleted", { name: x.name }), true);
    await loadMasterData();
  } else {
    await api(path, { archived: !x.archived });
  }
  await afterChange();
})));

// PIN prompt (own window instead of prompt(), so the PIN is not readable on the screen)
function askPin(text) {
  return new Promise((done) => {
    $("#pin-text").textContent = text;
    $("#pin-input").value = "";
    $("#pin-dialog").hidden = false;
    $("#pin-input").focus();
    const end = (value) => {
      $("#pin-dialog").hidden = true;
      $("#pin-form").onsubmit = $("#pin-cancel").onclick = null;
      done(value);
    };
    $("#pin-form").onsubmit = (e) => { e.preventDefault(); end($("#pin-input").value); };
    $("#pin-cancel").onclick = () => end(null);
  });
}

// ============================================================ camera
const SLIDERS = [
  ["min_size", "min_size", 10, 800, 10, (v) => Math.round(v) + " px"],
  ["pixel_threshold", "pixel_threshold", 5, 80, 1, (v) => Math.round(v)],
  ["exposure_ms", "exposure", 1, 30, 0.5, (v) => num(Number(v), 1) + " ms"],
  ["gain", "gain", 0, 255, 1, (v) => (Number(v) < 20 ? num(Number(v), 1) : String(Math.round(v)))],
  ["focus_m", "distance_to_gate", 0.3, 5, 0.1, (v) => num(Number(v), 1) + " m"],
];
$("#sliders").innerHTML = SLIDERS.map(([n, text, min, max, step]) =>
  `<label class="slider"><span>${esc(t(text))} ${infoButton("tip_s_" + n)}</span><input type="range" id="c-${n}" min="${min}" max="${max}" step="${step}">
   <span id="c-${n}-v"></span></label>`).join("");
let slidersLoaded = false;
SLIDERS.forEach(([n, , , , , format]) => {
  const s = $(`#c-${n}`);
  s.addEventListener("input", () => ($(`#c-${n}-v`).textContent = format(s.value)));
  s.addEventListener("change", attempt(() => api("/api/settings", { [n]: Number(s.value) })));
});

function showCamera(c, recent) {
  const lost = c.lost > 0.005 ? ` · ${t("lost_percent", { n: Math.round(c.lost * 100) })}` : "";
  $("#cam-info").textContent = `· ${num(c.fps, 1)} fps${lost} · ${t("timestamps")}: ${t("time_source_" + c.time_source, {}, c.time_source)}`;
  $("#bar-value").style.width = Math.min(c.share / 0.3, 1) * 100 + "%";
  const a = c.actual;
  $("#cam-calibrate-box").hidden = c.kind !== "csi";
  $("#cam-rotation").textContent = c.rotation ? t("rotation_now", { degrees: c.rotation }) : "";
  $("#cam-actual").textContent = a && a.exposure_ms != null
    ? t("camera_reports", { exposure: num(a.exposure_ms, 2), gain: num(a.gain, 2) }) +
      (a.focus_m ? ` · ${t("focus")} ${num(a.focus_m, 2)} m` : "") +
      (a.white_balance ? ` · ${t("white_balance")} ${a.white_balance.map((v) => num(v, 2)).join(" / ")}` : "")
    : "";
  if (!slidersLoaded) {
    // hide sliders this camera doesn't have (focus with the webcam)
    SLIDERS.forEach(([n]) => ($(`#c-${n}`).closest("label").hidden = c[n] == null));
    // value ranges depend on the camera (webcam / Camera Module 3)
    for (const [n, [min, max, step]] of Object.entries(c.limits || {})) {
      Object.assign($(`#c-${n}`), { min, max, step });
    }
    SLIDERS.forEach(([n, , , , , format]) => {
      $(`#c-${n}`).value = c[n];
      $(`#c-${n}-v`).textContent = format(c[n]);
    });
    slidersLoaded = true;
  }
  const html = recent.map((r) => `<figure>${r.photo ? `<img src="${photoUrl(esc(r.photo))}" alt="">` : `<span class="photo-gone">${esc(t("no_photo"))}</span>`}
    <figcaption>${esc(r.time)}<br>${r.ignored ? `${esc(r.pilot)} <span class="muted">(${esc(t("ignored"))})</span>`
      : r.counted ? (r.pilot ? esc(r.pilot) + (r.uncertain ? " ⚠" : "") : "❓") : `<span class="muted">${esc(t("not_counted"))}</span>`}</figcaption></figure>`).join("")
    || `<p class="muted">${esc(t("no_crossing_yet"))}</p>`;
  if ($("#cam-recent").innerHTML !== html) $("#cam-recent").innerHTML = html;
}

// ---- camera presets (settings per location)
let cameraPresets = [];

async function loadCameraPresets() {
  cameraPresets = await api("/api/camera/presets");
  const date = (iso) => new Date(iso).toLocaleDateString(locale(), { day: "2-digit", month: "2-digit", year: "2-digit" });
  $("#cp-list").innerHTML = cameraPresets.length
    ? cameraPresets.map((p) => `<option value="${esc(p.name)}">${esc(p.name)} (${date(p.saved)})</option>`).join("")
    : `<option value="">${esc(t("no_presets"))}</option>`;
  $("#cp-load").disabled = $("#cp-delete").disabled = !cameraPresets.length;
}

$("#cp-form").addEventListener("submit", attempt(async (e) => {
  e.preventDefault();
  const name = $("#cp-name").value.trim();
  if (cameraPresets.some((p) => p.name === name) && !confirm(t("confirm_overwrite_preset", { name }))) return;
  await api("/api/camera/presets", { name });
  $("#cp-name").value = "";
  await loadCameraPresets();
  $("#cp-list").value = name;
  message(t("preset_saved", { name }), true);
}));

$("#cp-load").addEventListener("click", attempt(async () => {
  const name = $("#cp-list").value;
  await api("/api/camera/presets/load", { name });
  slidersLoaded = false;  // fill the sliders with the preset's values
  message(t("preset_loaded", { name }), true);
}));

$("#cp-delete").addEventListener("click", attempt(async () => {
  const name = $("#cp-list").value;
  if (!confirm(t("confirm_delete_preset", { name }))) return;
  await api("/api/camera/presets/delete", { name });
  await loadCameraPresets();
}));

$("#cam-calibrate").addEventListener("click", attempt(async () => {
  const b = $("#cam-calibrate");
  b.disabled = true;
  b.textContent = t("calibrating");
  try {
    const v = await api("/api/camera/calibrate", {});
    slidersLoaded = false;  // fill the sliders with the new values
    message(t("calibrated", { exposure: num(v.exposure_ms, 2), gain: num(v.gain, 2) }), true);
  } finally {
    b.disabled = false;
    b.textContent = t("calibrate_camera");
  }
}));

$("#cam-rotate").addEventListener("click", attempt(async () => {
  const v = await api("/api/camera/rotate", {});
  message(v.rotation ? t("rotated", { degrees: v.rotation }) : t("rotated_back"), true);
}));

// drag the detection zone with mouse/finger
const box = $("#image-box"), image = $("#image"), band = $("#rubber-band");
let startPoint = null;
function point(e) {
  const r = image.getBoundingClientRect();
  return { x: Math.min(Math.max(e.clientX - r.left, 0), r.width), y: Math.min(Math.max(e.clientY - r.top, 0), r.height) };
}
// The live image is an <img>: otherwise the browser would "drag it out" by drag & drop
// and cancel our mouse events (stop sign, no new zone).
image.addEventListener("dragstart", (e) => e.preventDefault());
box.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  startPoint = point(e);
  box.setPointerCapture(e.pointerId);
  Object.assign(band.style, { display: "block", left: startPoint.x + "px", top: startPoint.y + "px", width: "0px", height: "0px" });
});
box.addEventListener("pointermove", (e) => {
  if (!startPoint) return;
  const p = point(e);
  Object.assign(band.style, {
    left: Math.min(p.x, startPoint.x) + "px", top: Math.min(p.y, startPoint.y) + "px",
    width: Math.abs(p.x - startPoint.x) + "px", height: Math.abs(p.y - startPoint.y) + "px" });
});
box.addEventListener("pointercancel", () => {  // the browser cancelled the dragging
  startPoint = null;
  band.style.display = "none";
});
box.addEventListener("pointerup", attempt(async (e) => {
  if (!startPoint) return;
  const p = point(e), r = image.getBoundingClientRect();
  const factor = image.naturalWidth / r.width;  // screen pixels -> camera pixels
  const zone = [Math.min(p.x, startPoint.x), Math.min(p.y, startPoint.y),
                Math.abs(p.x - startPoint.x), Math.abs(p.y - startPoint.y)].map((v) => Math.round(v * factor));
  startPoint = null;
  band.style.display = "none";
  if (zone[2] > 10 && zone[3] > 10) await api("/api/settings", { zone });
}));

// ============================================================ start
(async () => {
  const session = await fetch("/api/session").then((r) => r.json()).catch(() => null);
  if (session && !session.role) return showLoginPage();  // sign in first
  try {
    [S.formats] = await Promise.all([api("/api/formats"), loadMasterData()]);
  } catch (e) { if (!signedOut) message(t("not_reachable", { error: e.message })); }
  fillCalloutPilots();
  showTab(location.hash.slice(1) || (store.read("welcome_seen", false) ? "race" : "welcome"));
  poll();
})();
