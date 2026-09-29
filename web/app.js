// Данные не встроены в страницу: грузятся из data/*.json при открытии (см. init внизу).
const DATA = { days: [], movies: {}, watched: {}, generated: null };
let M = {}, W = {};
const TZ = "Asia/Jerusalem";

// ---------- state ----------
const DEFAULTS = { view: "sessions", prime: false, hidewatched: true, hidepast: false,
                   lang: "any", after: "0", imdb: "0", sort: "imdb" };
let state = { ...DEFAULTS };
try { Object.assign(state, JSON.parse(localStorage.getItem("cinema-state") || "{}")); } catch (e) {}
function save() { try { localStorage.setItem("cinema-state", JSON.stringify(state)); } catch (e) {} }

let allDates = [];
function weekendDates() {
  // «сегодня» по израильскому времени, где бы ни был браузер
  const todayIso = new Date().toLocaleDateString("sv-SE", { timeZone: TZ });
  const today = new Date(todayIso + "T12:00Z");
  const iso = d => d.toISOString().slice(0, 10);
  const wd = today.getUTCDay(); // 0 Sun ... 5 Fri, 6 Sat
  const fri = new Date(today);
  if (wd === 6) fri.setUTCDate(today.getUTCDate() - 1);
  else fri.setUTCDate(today.getUTCDate() + ((5 - wd + 7) % 7));
  const sat = new Date(fri); sat.setUTCDate(fri.getUTCDate() + 1);
  const picked = [iso(fri), iso(sat)].filter(d => allDates.includes(d) && d >= todayIso);
  return picked.length ? picked : allDates.slice(-2);
}
let selected = [];

// ---------- helpers ----------
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const movieOf = s => M[s.movie] || {};
const titleOf = (s) => (M[s.movie] && M[s.movie].title_en) || s.cc_name;
const dayLabel = iso => new Date(iso + "T12:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
const dayShort = iso => new Date(iso + "T12:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
const startOf = s => new Date(s.start);
const isPast = s => startOf(s) < new Date();
const isWatched = slug => !!W[slug];
const minutesOfDay = s => { const [h, m] = s.time.split(":").map(Number); return (s.after_midnight ? 24 * 60 : 0) + h * 60 + m; };
function money(v) {
  if (!v) return null;
  return v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `$${Math.round(v / 1e6)}M` : `$${v.toLocaleString()}`;
}
function ratingsText(m) {
  const p = [];
  if (m.imdb_rating) p.push(`IMDb ${m.imdb_rating.toFixed(1)}`);
  if (m.rt_critics != null) p.push(`RT ${m.rt_critics}%`);
  return p.join(" · ");
}
function metaLine(m) {
  return [m.year, (m.country || []).join(", ")].filter(Boolean).join(" · ");
}

function passes(s) {
  const m = movieOf(s), lang = s.screen_language || "";
  if (state.prime && !s.prime) return false;
  if (state.hidewatched && isWatched(s.movie)) return false;
  if (state.hidepast && isPast(s)) return false;
  if (state.lang === "nodub" && lang.startsWith("dubbed")) return false;
  if (state.lang === "english" && lang !== "English") return false;
  if (state.lang === "hebrew" && !lang.startsWith("Hebrew")) return false;
  if (state.lang === "dubbed" && !lang.startsWith("dubbed")) return false;
  if (+state.after && minutesOfDay(s) < +state.after * 60) return false;
  if (+state.imdb && !(m.imdb_rating >= +state.imdb)) return false;
  return true;
}
const selectedDays = () => DATA.days.filter(d => selected.includes(d.date));
const rowClass = s => [isWatched(s.movie) && "is-watched", isPast(s) && "is-past", s.status === "removed" && "is-removed"].filter(Boolean).join(" ");
function timeLink(s, cls = "") {
  const label = esc(s.time);
  return s.ticket_url && s.status !== "removed" && !isPast(s)
    ? `<a class="${cls}" href="${esc(s.ticket_url)}" target="_blank" rel="noopener" title="Buy tickets">${label}</a>`
    : `<span class="${cls}">${label}</span>`;
}
function sessionNote(s) {
  return [s.after_midnight && "night", s.status === "removed" ? "cancelled" : isPast(s) && "past", s.format]
    .filter(Boolean).join(" · ");
}

// ---------- controls ----------
function renderDates() {
  const wk = weekendDates();
  const isWk = wk.length === selected.length && wk.every(d => selected.includes(d));
  const el = document.getElementById("dates");
  el.innerHTML = `<button class="chip" data-preset="weekend" aria-pressed="${isWk}">This weekend</button>` +
    allDates.map(d => `<button class="chip" data-date="${d}" aria-pressed="${selected.includes(d)}">${dayShort(d)}</button>`).join("");
  el.onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.preset) selected = weekendDates();
    else if (e.metaKey || e.ctrlKey || e.shiftKey) {
      selected = selected.includes(b.dataset.date) ? selected.filter(x => x !== b.dataset.date) : [...selected, b.dataset.date].sort();
      if (!selected.length) selected = [b.dataset.date];
    } else selected = [b.dataset.date];
    render();
  };
}
function bindControls() {
  document.getElementById("views").onclick = e => {
    const b = e.target.closest("[data-view]"); if (!b) return;
    state.view = b.dataset.view; save(); render();
  };
  for (const k of ["prime", "hidewatched", "hidepast"]) {
    document.getElementById("f-" + k).onclick = () => { state[k] = !state[k]; save(); render(); };
  }
  for (const k of ["lang", "after", "imdb", "sort"]) {
    const el = document.getElementById("f-" + k);
    el.value = state[k];
    el.onchange = () => { state[k] = el.value; save(); render(); };
  }
}

// ---------- views ----------
function renderSessions(days) {
  let shown = 0;
  const html = days.map(d => {
    const list = d.sessions.filter(passes);
    shown += list.length;
    const rows = list.map(s => {
      const m = movieOf(s), note = sessionNote(s);
      return `<div class="session ${rowClass(s)}">
        <div class="time">${timeLink(s)}${note ? `<small>${esc(note)}</small>` : ""}</div>
        <div>
          <button class="title-btn" data-movie="${esc(s.movie)}">${esc(titleOf(s))}</button>${s.prime ? '<span class="badge">PRIME</span>' : ""}${isWatched(s.movie) ? '<span class="badge plain">✓ watched</span>' : ""}
          <div class="meta">${esc(metaLine(m))}</div>
          <div class="lang">${esc(s.screen_language || "")}</div>
        </div>
        <div class="ratings">${esc(ratingsText(m))}</div>
      </div>`;
    }).join("");
    return `<section class="day"><h2>${dayLabel(d.date)} <small>${list.length} sessions</small></h2>${rows || '<div class="empty">Nothing matches the filters.</div>'}</section>`;
  }).join("");
  return { html: `<div class="days">${html}</div>`, shown };
}

function renderMovies(days) {
  const by = {};
  for (const d of days) for (const s of d.sessions.filter(passes)) {
    const key = s.movie || s.cc_name;
    (by[key] ||= { slug: s.movie, name: titleOf(s), days: {} });
    (by[key].days[d.date] ||= []).push(s);
  }
  const items = Object.values(by);
  const count = it => Object.values(it.days).reduce((n, l) => n + l.length, 0);
  const sorters = {
    imdb: (a, b) => (M[b.slug]?.imdb_rating ?? -1) - (M[a.slug]?.imdb_rating ?? -1),
    rt: (a, b) => (M[b.slug]?.rt_critics ?? -1) - (M[a.slug]?.rt_critics ?? -1),
    sessions: (a, b) => count(b) - count(a),
    title: (a, b) => a.name.localeCompare(b.name),
  };
  items.sort((a, b) => sorters[state.sort](a, b) || a.name.localeCompare(b.name));
  const html = items.map(it => {
    const m = M[it.slug] || {};
    const langs = [...new Set(Object.values(it.days).flat().map(s => s.screen_language))].join(" / ");
    const times = Object.entries(it.days).map(([d, list]) =>
      `<span><b>${dayShort(d)}</b> ${list.map(s => `<span class="t ${rowClass(s)}">${timeLink(s)}${s.prime ? '<span class="badge">P</span>' : ""}</span>`).join("")}</span>`).join("");
    return `<article class="movie ${isWatched(it.slug) ? "is-watched" : ""}">
      <div>
        <button class="title-btn" data-movie="${esc(it.slug)}">${esc(it.name)}</button>${isWatched(it.slug) ? '<span class="badge plain">✓ watched</span>' : ""}
        <div class="meta">${esc([metaLine(m), (m.genre || []).join(", "), m.runtime_min && m.runtime_min + " min"].filter(Boolean).join(" · "))}</div>
        <div class="lang">${esc(langs)}</div>
      </div>
      <div class="big-rating">${esc(ratingsText(m))}</div>
      <div class="times">${times}</div>
    </article>`;
  }).join("");
  return { html: `<div class="movies">${html || '<div class="empty">Nothing matches the filters.</div>'}</div>`, shown: items.length, unit: "movies" };
}

function renderTimeline(days) {
  let shown = 0;
  const html = days.map(d => {
    const list = d.sessions.filter(passes);
    shown += list.length;
    if (!list.length) return `<section class="tl-day"><h2>${dayLabel(d.date)}</h2><div class="empty">Nothing matches the filters.</div></section>`;
    const runtime = s => movieOf(s).runtime_min || 120;
    const start = Math.floor(Math.min(...list.map(minutesOfDay)) / 60) * 60;
    const end = Math.ceil(Math.max(...list.map(s => minutesOfDay(s) + runtime(s))) / 60) * 60;
    const span = end - start, pct = v => ((v - start) / span * 100).toFixed(3) + "%";
    const hours = []; for (let t = start; t <= end; t += 60) hours.push(t);
    const axis = hours.map(t => `<span style="left:${pct(t)}">${String((t / 60) % 24).padStart(2, "0")}:00</span>`).join("");
    const grid = hours.map(t => `<div class="tl-grid" style="left:${pct(t)}"></div>`).join("");
    const now = new Date(), dayStart = new Date(d.date + "T00:00" + (d.utc_offset || ""));
    const nowMin = (now - dayStart) / 60000;
    const nowLine = nowMin > start && nowMin < end ? `<div class="tl-now" style="left:${pct(nowMin)}" title="now"></div>` : "";
    // одна строка на фильм, в порядке первого сеанса
    const rows = {};
    for (const s of list) (rows[s.movie || s.cc_name] ||= []).push(s);
    const body = Object.values(rows).map(ss => {
      const slug = ss[0].movie;
      // пересекающиеся сеансы одного фильма раскладываем по дорожкам
      const lanes = [];
      const laneOf = new Map();
      for (const s of [...ss].sort((x, y) => minutesOfDay(x) - minutesOfDay(y))) {
        let i = lanes.findIndex(endAt => endAt <= minutesOfDay(s));
        if (i < 0) { i = lanes.length; lanes.push(0); }
        lanes[i] = minutesOfDay(s) + runtime(s) + 2;
        laneOf.set(s, i);
      }
      const bars = ss.map(s => {
        const a = minutesOfDay(s), b = a + runtime(s);
        const fin = new Date(startOf(s).getTime() + runtime(s) * 60000);
        const tip = `${titleOf(s)}\n${s.time}–${fin.toTimeString().slice(0, 5)} (${runtime(s)} min, ads before not counted)\n` +
          `${s.prime ? "Prime · " : ""}${s.screen_language || ""}`;
        return `<button class="tl-bar ${s.prime ? "prime" : ""} ${rowClass(s)}" data-movie="${esc(slug)}" data-tip="${esc(tip)}"
          style="left:${pct(a)};width:calc(${pct(b)} - ${pct(a)});top:${5 + laneOf.get(s) * 26}px">${esc(s.time)}${s.prime ? " · Prime" : ""}</button>`;
      }).join("");
      return `<div class="tl-row ${isWatched(slug) ? "is-watched" : ""}" style="height:${4 + lanes.length * 26}px"><div class="tl-label"><button class="title-btn" data-movie="${esc(slug)}" title="${esc(titleOf(ss[0]))}">${esc(titleOf(ss[0]))}</button></div>
        <div class="tl-track">${grid}${nowLine}${bars}</div></div>`;
    }).join("");
    return `<section class="tl-day"><h2>${dayLabel(d.date)}</h2><div class="tl">
      <div class="tl-axis">${axis}</div>${body}
      <div class="tl-legend"><span><i style="background:var(--accent-bar)"></i>Prime</span><span><i style="background:var(--bar)"></i>Regular hall</span><span>Bar length = film runtime</span></div>
    </div></section>`;
  }).join("");
  return { html, shown };
}

// ---------- movie card ----------
function openCard(slug) {
  const m = M[slug]; if (!m) return;
  const w = W[slug];
  const sessions = DATA.days.filter(d => selected.includes(d.date))
    .map(d => [d.date, d.sessions.filter(s => s.movie === slug)]).filter(([, l]) => l.length);
  const fact = (k, v) => v ? `<dt>${k}</dt><dd>${v}</dd>` : "";
  const score = (v, label, href) => v != null ? `<div class="score"><b>${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(v)}</a>` : esc(v)}</b><span>${label}</span></div>` : "";
  const dlg = document.getElementById("card");
  dlg.innerHTML = `<div class="card">
    <button class="close" aria-label="Close">×</button>
    <h2>${esc(m.title_en || m.title_he)}${m.year ? ` <span style="color:var(--ink-3);font-weight:400">(${m.year})</span>` : ""}</h2>
    ${m.title_original && m.title_original !== m.title_en ? `<div class="orig">${esc(m.title_original)}</div>` : ""}
    <div class="orig" dir="rtl" style="text-align:left">${esc(m.title_he)}</div>
    ${w ? `<div class="note"><b>✓ Watched</b>${w.watched ? " · " + esc(w.watched) : ""}${w.rating ? " · " + esc(w.rating) + "/10" : ""}${w.note ? `<div>${esc(w.note)}</div>` : ""}</div>` : ""}
    <div class="scores">
      ${score(m.imdb_rating != null ? m.imdb_rating.toFixed(1) : null, `IMDb${m.imdb_votes ? " · " + m.imdb_votes.toLocaleString() + " votes" : ""}`, m.imdb_id && `https://www.imdb.com/title/${m.imdb_id}/`)}
      ${score(m.rt_critics != null ? m.rt_critics + "%" : null, "RT critics", m.rt_url)}
      ${score(m.rt_audience != null ? m.rt_audience + "%" : null, "RT audience", m.rt_url)}
    </div>
    <dl class="facts">
      ${fact("Country", esc((m.country || []).join(", ")))}
      ${fact("Language", esc((m.spoken_languages && m.spoken_languages.length ? m.spoken_languages : [m.original_language]).filter(Boolean).join(", ")))}
      ${fact("Genre", esc((m.genre || []).join(", ")))}
      ${fact("Runtime", m.runtime_min && m.runtime_min + " min")}
      ${fact("Age", esc(m.age_rating))}
      ${fact("Premiere (IL)", m.premiere_il && new Date(m.premiere_il + "T12:00").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }))}
      ${fact("Budget", money(m.budget_usd))}
      ${fact("Box office", money(m.revenue_usd) && money(m.revenue_usd) + " worldwide")}
      ${fact("Dubbed version", m.dubbed_available ? "available" : "")}
    </dl>
    ${m.overview ? m.overview.split(/\n\n+/).map(p => `<p>${esc(p)}</p>`).join("") : ""}
    ${sessions.length ? `<h3>Sessions</h3>` + sessions.map(([d, l]) =>
      `<div class="sess"><b style="min-width:110px">${dayShort(d)}</b>${l.map(s => `<span class="t ${rowClass(s)}">${timeLink(s)}${s.prime ? '<span class="badge">P</span>' : ""} <span class="meta">${esc(s.screen_language || "")}</span></span>`).join("")}</div>`).join("") : ""}
    <h3>Links</h3>
    <p>${[m.tmdb_id && `<a href="https://www.themoviedb.org/movie/${m.tmdb_id}" target="_blank" rel="noopener">TMDB</a>`,
          m.imdb_id && `<a href="https://www.imdb.com/title/${m.imdb_id}/" target="_blank" rel="noopener">IMDb</a>`,
          m.rt_url && `<a href="${esc(m.rt_url)}" target="_blank" rel="noopener">Rotten Tomatoes</a>`,
          (m.cc_movie_id || [])[0] && `<a href="https://www.cinema-city.co.il/movie/${m.cc_movie_id[0]}" target="_blank" rel="noopener">Cinema City</a>`]
          .filter(Boolean).join(" · ")}</p>
  </div>`;
  dlg.querySelector(".close").onclick = () => dlg.close();
  dlg.onclick = e => { if (e.target === dlg) dlg.close(); };
  dlg.showModal();
}

// ---------- render ----------
function render() {
  renderDates();
  document.querySelectorAll("#views .tab").forEach(b => b.setAttribute("aria-selected", b.dataset.view === state.view));
  for (const k of ["prime", "hidewatched", "hidepast"]) document.getElementById("f-" + k).setAttribute("aria-pressed", state[k]);
  document.getElementById("sort-wrap").style.display = state.view === "movies" ? "" : "none";
  const days = selectedDays();
  const r = state.view === "movies" ? renderMovies(days) : state.view === "timeline" ? renderTimeline(days) : renderSessions(days);
  document.getElementById("main").innerHTML = r.html;
  document.getElementById("count").textContent = `${r.shown} ${r.unit || "sessions"}`;
}

document.getElementById("main").addEventListener("click", e => {
  const b = e.target.closest("[data-movie]");
  if (b && b.dataset.movie) openCard(b.dataset.movie);
});
const tip = document.getElementById("tip");
document.getElementById("main").addEventListener("mouseover", e => {
  const b = e.target.closest("[data-tip]");
  if (!b) { tip.style.display = "none"; return; }
  tip.textContent = ""; b.dataset.tip.split("\n").forEach((l, i) => { if (i) tip.appendChild(document.createElement("br")); tip.appendChild(document.createTextNode(l)); });
  tip.style.display = "block";
});
document.getElementById("main").addEventListener("mousemove", e => {
  if (tip.style.display === "block") {
    tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8) + "px";
    tip.style.top = (e.clientY + 16) + "px";
  }
});
document.getElementById("main").addEventListener("mouseleave", () => tip.style.display = "none");

async function loadJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

async function init() {
  try {
    const [index, movies, watched] = await Promise.all(
      ["data/index.json", "data/movies.json", "data/watched.json"].map(loadJSON));
    DATA.generated = index.generated;
    DATA.movies = M = movies;
    DATA.watched = W = watched;
    DATA.days = await Promise.all(index.dates.map(d => loadJSON(`data/days/${d}.json`)));
  } catch (e) {
    document.getElementById("main").innerHTML =
      `<div class="empty">Could not load schedule data (${esc(e.message)}).` +
      (location.protocol === "file:" ? " Open the page through a local server: python3 scripts/serve.py" : "") + "</div>";
    return;
  }
  allDates = DATA.days.map(d => d.date);
  selected = weekendDates();
  const gen = new Date(DATA.generated);
  document.getElementById("sub").textContent =
    `Schedule, ratings and notes · updated ${gen.toLocaleString("en-GB", { timeZone: TZ, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`;
  bindControls();
  render();
}

init();
