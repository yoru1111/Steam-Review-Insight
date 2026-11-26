// Steam Review Insight UI. Talks to the FastAPI backend on the same origin (see docs/API_CONTRACT.md).
// All server/review text is inserted as text nodes, never as HTML.

const $ = (selector) => document.querySelector(selector);

const OTHER = "Other / Unclassified";
const ISSUES = {
  "Bugs / Crashes": ["버그·크래시", "bug", "🐞"],
  "Performance / Optimization": ["성능·최적화", "perf", "🐢"],
  "Game Balance": ["밸런스", "balance", "⚖️"],
  "Gameplay": ["게임플레이", "gameplay", "🎮"],
  "UI / Usability": ["UI·사용성", "ui", "🧭"],
  "Monetization": ["과금", "money", "💰"],
  "Story / Narrative": ["스토리", "story", "📖"],
  "Story / Dialogue Length": ["대사 길이", "dialogue", "💬"],
  "Content / Open World": ["콘텐츠·오픈월드", "content", "🗺️"],
  "Customization": ["커스터마이징", "custom", "🎨"],
  "Developer Support": ["개발사 지원", "devsupport", "🛠️"],
  "Quest / Progression Design": ["퀘스트·진행", "quest", "🎯"],
  [OTHER]: ["기타 불만", "other", "📝"],
};

const POSITIVES = {
  "Gameplay": ["게임플레이", "🎮"],
  "Graphics / Visuals": ["그래픽·비주얼", "🖼️"],
  "Sound / Music": ["사운드·음악", "🎵"],
  "Story / Narrative": ["스토리", "📖"],
  "Content / Exploration": ["콘텐츠·탐험", "🗺️"],
};

const MODE_KEY = "sri-view-mode";

const ERROR_TITLES = {
  422: "입력값이나 리뷰 데이터를 확인해 주세요",
  500: "분석 중 서버 오류가 났어요",
  501: "아직 지원하지 않는 기능이에요",
  502: "게임 검색에 실패했어요",
  503: "리뷰 데이터를 가져올 수 없어요",
};

// Shown under the sample-mode select so the user knows how each option picks reviews and what it is for.
const SAMPLE_MODE_HELP = {
  recent: "최신 리뷰: Steam에 최근 올라온 리뷰를 순서대로 가져와요. 추천 비율이 실제와 같아서 전체 반응을 볼 때 좋아요. 호평이 많은 게임은 불만 리뷰가 적게 모일 수 있어요.",
  balanced: "추천·비추천 반반: 최근 추천 리뷰와 최근 비추천 리뷰를 같은 수만큼 따로 가져와요. 호평이 많은 게임에서도 불만 리뷰가 충분히 모여 개선점을 찾을 때 좋아요. 표본의 추천 비율은 일부러 50%로 맞춘 값이라, 전체 평가는 Steam 집계로 따로 보여드려요.",
};

const BALANCED_NOTE ="추천·비추천 리뷰를 반반씩 골라 분석했어요. 표본의 추천 비율은 일부러 맞춘 값이라 Steam 전체 비율이 아니에요.";

const WARNINGS = [
  [/^Silhouette score is very low/, () => "군집 분리도가 매우 낮아요. 묶음 사이 경계가 약할 수 있어요."],
  [/^Silhouette score is unavailable/, () => "군집이 제대로 나뉘지 않아 분리도를 계산하지 못했어요."],
  [/^Requested (\d+) clusters, but only (\d+)/, (m) => `군집 ${m[1]}개를 요청했지만 ${m[2]}개만 만들어졌어요. 거의 같은 리뷰가 많을 수 있어요.`],
  [/^VADER may misread/, () => "글 감성(VADER)은 반어법, 게임 용어, 맥락을 잘못 읽을 수 있어요."],
  [/^Issue labels and priority scores/, () => "이슈 유형과 우선순위 점수는 키워드 규칙으로 낸 참고값이에요. 실제 결함의 심각도와는 달라요."],
];

// ---------- helpers ----------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "style") node.style.cssText = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false || child === "") continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

const num = (x) => Number(x).toLocaleString("ko-KR");
const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`;
const width = (x) => `width:${Math.min(100, Math.max(0, x * 100))}%`;
const signed = (x) => `${x > 0 ? "+" : ""}${x.toFixed(2)}`;
const issueLabel = (type) => (ISSUES[type] || [type])[0];
const isBalanced = (metadata) => metadata?.sample_mode === "balanced" || metadata?.sampling?.mode === "balanced";

// Steam's own recommendation split for reviews matching the collection filters (balanced mode only).
function steamPopulation(metadata) {
  const population = metadata?.sampling?.matching_population;
  return population?.positive_ratio != null && population.total ? population : null;
}

// Real Steam reviews can run to thousands of characters; show 4 lines and expand on click/Enter.
function quoteBlock(text, extra = null) {
  const toggle = (event) => event.currentTarget.classList.toggle("expanded");
  return el("blockquote", {
    class: "quote",
    tabindex: "0",
    title: "눌러서 전체 보기 / 접기",
    onclick: toggle,
    onkeydown: (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(event); } },
  }, el("p", {}, text), extra);
}

function issueChip(type) {
  const [label, key] = ISSUES[type] || [type, "other"];
  return el("span", { class: `chip chip-${key}`, title: type }, label);
}

function clusterChip(cluster) {
  if (cluster.label_kind === "general") {
    return el("span", { class: "chip", style: "--chip:var(--neutral)" }, "일반 리뷰 중심");
  }
  if (cluster.label_kind === "mixed") {
    return el("span", { class: "chip chip-other" }, "혼합·유형 미분류");
  }
  if (cluster.label_kind === "other") {
    return el("span", { class: "chip chip-other" }, "기타 불만 중심");
  }
  if (cluster.label_kind === "issue" && cluster.dominant_issue_type) {
    const [label, key] = ISSUES[cluster.dominant_issue_type] || [cluster.dominant_issue_type, "other"];
    return el("span", { class: `chip chip-${key}`, title: cluster.dominant_issue_type }, `${label} 중심`);
  }
  // Backward compatibility for responses produced before cluster profiles existed.
  return issueChip(cluster.issue_type);
}

function separation(score) {
  if (score == null) return "계산 불가";
  if (score < 0.05) return "약함";
  if (score < 0.2) return "보통";
  return "좋음";
}

function translateWarning(text) {
  for (const [pattern, toKorean] of WARNINGS) {
    const match = text.match(pattern);
    if (match) return toKorean(match);
  }
  return text;
}

// ---------- API ----------

class ApiError extends Error {
  constructor(title, detail = "", status = 0) {
    super(title);
    this.detail = detail;
    this.status = status;
  }
}

function formatDetail(detail) {
  if (Array.isArray(detail)) return detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("\n");
  return detail ? String(detail) : "";
}

async function request(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError("서버에 연결할 수 없어요", "분석 서버(uvicorn)가 실행 중인지 확인해 주세요.");
  }
  const body = await response.json().catch(() => ({}));
  if (response.ok) return body;
  throw new ApiError(ERROR_TITLES[response.status] || `요청 실패 (${response.status})`, formatDetail(body.detail), response.status);
}

async function checkHealth() {
  const pill = $("#server-status");
  const setStatus = (state, text) => {
    pill.className = `status ${state}`;
    pill.title = text;
    pill.querySelector(".status-text").textContent = text;
  };
  try {
    await request("/api/health");
    setStatus("ok", "서버 연결됨");
  } catch {
    setStatus("down", "서버 응답 없음");
  }
}

// ---------- screens and catalog ----------

let catalog = [];
const knownGames = new Map();
let catalogTab = "popular";
let genre = "전체";
let activeAppId = null;
let requestVersion = 0;
let searchVersion = 0;

function gameImage(game) {
  const name = game.name || `App ID ${game.app_id}`;
  const placeholder = el("span", { class: "game-image-placeholder", "aria-hidden": "true" }, name);
  return el("div", { class: "game-image" }, placeholder,
    el("img", {
      src: `https://cdn.akamai.steamstatic.com/steam/apps/${game.app_id}/header.jpg`,
      loading: "lazy", alt: `${name} 게임 이미지`,
      onerror: (event) => { event.currentTarget.hidden = true; },
    }));
}

function buildScreens() {
  $("#app").append(
    el("div", { id: "selection-screen", class: "screen" },
      el("div", { class: "selection-intro" },
        el("h2", {}, "어떤 게임의 리뷰가 궁금하세요?"),
        el("p", { class: "muted" }, "게임을 고르면 리뷰 속 개선할 문제와 유지할 강점을 살펴볼 수 있어요.")),
      el("section", { class: "card panel", "aria-label": "게임 검색과 App ID 입력" },
        el("form", { id: "search-form", class: "search", role: "search", onsubmit: searchGames },
          el("input", { id: "query", type: "search", placeholder: "게임 이름으로 검색 (예: Cyberpunk)",
            maxlength: "100", autocomplete: "off", "aria-label": "게임 이름" }),
          el("button", { type: "submit", class: "btn" }, "검색")),
        el("ul", { id: "search-results", class: "search-results", hidden: true, "aria-live": "polite" }),
        el("form", { id: "app-id-form", class: "direct-entry", onsubmit: (event) => {
          event.preventDefault();
          const appId = Number($("#app-id").value);
          if (Number.isSafeInteger(appId) && appId > 0) location.hash = `/game/${appId}`;
        } },
          el("label", { class: "field", for: "app-id" }, "App ID로 바로 열어요",
            el("input", { id: "app-id", type: "number", min: "1", max: String(Number.MAX_SAFE_INTEGER),
              required: true, placeholder: "1091500" })),
          el("button", { type: "submit", class: "btn" }, "분석하러 가기"))),
      el("section", { class: "section", "aria-label": "편집한 게임 목록" },
        el("nav", { class: "catalog-tabs", "aria-label": "게임 목록 분류" },
          [["popular", "최근 인기"], ["recent", "최근 출시"], ["genre", "장르별"]].map(([key, label]) =>
            el("button", { type: "button", class: "btn", "data-tab": key,
              "aria-pressed": String(key === catalogTab), onclick: () => {
                catalogTab = key;
                renderCatalog();
              } }, label))),
        el("p", { id: "catalog-note", class: "muted small", hidden: true }),
        el("div", { id: "genre-filters", class: "genre-filters", hidden: true, "aria-label": "장르 선택" }),
        el("div", { id: "game-grid", class: "game-grid" }))),
    el("div", { id: "analysis-screen", class: "screen", hidden: true },
      el("div", { id: "game-header" }),
      el("section", { class: "card panel", "aria-labelledby": "settings-title" },
        el("h2", { id: "settings-title", class: "panel-title" }, "분석 설정"),
        el("form", { id: "analyze-form", class: "analyze", onsubmit: analyze },
          el("label", { class: "field" }, "리뷰 수",
            el("input", { id: "limit", type: "number", min: "2", max: "10000", value: "1000", required: true })),
          el("label", { class: "field detail-only" }, "군집 수 (k)",
            el("input", { id: "k", type: "number", min: "2", max: "50", value: "5", required: true })),
          el("label", { class: "field field-wide" }, "리뷰 고르는 방식",
            el("select", { id: "sample-mode", "aria-describedby": "sample-mode-help", onchange: showSampleModeHelp },
              el("option", { value: "recent" }, "최신 리뷰 — 전체 반응 보기"),
              el("option", { value: "balanced" }, "추천·비추천 반반 — 불만 찾기"))),
          el("label", { class: "check" }, el("input", { id: "refresh", type: "checkbox" }), " 새로 수집"),
          el("button", { id: "analyze-btn", type: "submit", class: "btn btn-primary" }, "다시 분석")),
        el("p", { id: "sample-mode-help", class: "muted small" })),
      el("div", { id: "output", "aria-live": "polite" })));
  showSampleModeHelp();
}

async function loadCatalog() {
  try {
    const data = await request("games.json");
    catalog = data.games;
    for (const game of catalog) {
      if (!knownGames.has(game.app_id)) knownGames.set(game.app_id, game);
    }
    $("#catalog-note").hidden = true;
    renderCatalog();
    if (activeAppId != null) renderGameHeader();
  } catch {
    $("#catalog-note").textContent = "게임 목록을 불러오지 못했어요. 이름 검색이나 App ID로 게임을 열 수 있어요.";
    $("#catalog-note").hidden = false;
    $("#game-grid").replaceChildren(el("button", { type: "button", class: "btn", onclick: loadCatalog }, "목록 다시 불러오기"));
  }
}

function renderCatalog() {
  for (const button of document.querySelectorAll(".catalog-tabs button")) {
    button.setAttribute("aria-pressed", String(button.dataset.tab === catalogTab));
  }
  const filters = $("#genre-filters");
  filters.hidden = catalogTab !== "genre";
  const genres = ["전체", ...new Set(catalog.flatMap((game) => game.genres))];
  filters.replaceChildren(...genres.map((label) => el("button", {
    type: "button", class: "btn genre-chip", "aria-pressed": String(label === genre),
    onclick: () => { genre = label; renderCatalog(); },
  }, label)));
  const games = catalogTab === "popular" ? catalog.filter((game) => game.popular)
    : catalogTab === "recent" ? [...catalog].sort((a, b) => b.release_date.localeCompare(a.release_date))
      : catalog.filter((game) => genre === "전체" || game.genres.includes(genre));
  $("#game-grid").replaceChildren(...games.map((game) =>
    el("a", { class: "card game-card", href: `#/game/${game.app_id}` },
      gameImage(game),
      el("div", { class: "game-card-body" }, el("h3", {}, game.name),
        el("p", { class: "muted small" }, `${game.genres.join(" · ")} · ${game.release_date.slice(0, 4)}년`)))));
}

function currentGame() {
  return knownGames.get(activeAppId) || { app_id: activeAppId, name: `App ID ${activeAppId}` };
}

function renderGameHeader() {
  const game = currentGame();
  $("#game-header").replaceChildren(
    el("a", { class: "back-link", href: "#/" }, "← 게임 목록으로"),
    el("div", { class: "game-heading" }, gameImage(game),
      el("div", {}, el("h2", {}, game.name), el("p", { class: "muted small" }, `App ID ${game.app_id}`))));
  if ($("#loading-game")) $("#loading-game").textContent = game.name;
  document.title = `${game.name} · Steam Review Insight`;
}

function route() {
  ++requestVersion;
  ++searchVersion;
  clearInterval(timer);
  lastResult = null;
  const dialog = $(".evidence-dialog");
  if (dialog) dialog.close();
  const match = location.hash.match(/^#\/game\/([1-9]\d*)$/);
  activeAppId = match && Number.isSafeInteger(Number(match[1])) ? Number(match[1]) : null;
  $("#selection-screen").hidden = activeAppId != null;
  $("#analysis-screen").hidden = activeAppId == null;
  $("#analyze-btn").disabled = false;
  $("#output").replaceChildren();
  if (activeAppId != null) {
    renderGameHeader();
    analyze();
  } else {
    document.title = "Steam Review Insight";
    if (location.hash !== "#/") history.replaceState(null, "", "#/");
  }
}

function showSampleModeHelp() {
  $("#sample-mode-help").textContent = SAMPLE_MODE_HELP[$("#sample-mode").value];
}

// ---------- search ----------

async function searchGames(event) {
  event.preventDefault();
  const query = $("#query").value.trim();
  if (!query) return;
  const version = ++searchVersion;
  const list = $("#search-results");
  list.hidden = false;
  list.replaceChildren(el("li", { class: "muted" }, "검색 중…"));
  try {
    const { games } = await request(`/api/games/search?query=${encodeURIComponent(query)}`);
    if (version !== searchVersion) return;
    list.replaceChildren(...(games.length ? games.map(gameOption)
      : [el("li", { class: "muted" }, "등록된 게임 중에 없어요. Steam 상점 주소의 App ID를 아래에 직접 넣어도 돼요.")]));
  } catch (error) {
    if (version !== searchVersion) return;
    list.replaceChildren(el("li", { class: "error-text" }, error.message, error.detail && ` — ${error.detail}`));
  }
}

function gameOption(game) {
  return el("li", {},
    el("button", { type: "button", class: "game-option", onclick: () => selectGame(game) },
      el("span", {}, game.name ?? "이름 없음"),
      el("span", { class: "muted" }, `App ID ${game.app_id}`)));
}

function selectGame(game) {
  knownGames.set(Number(game.app_id), { ...game, app_id: Number(game.app_id) });
  $("#search-results").hidden = true;
  location.hash = `/game/${game.app_id}`;
}

// ---------- analyze ----------

let timer;
let lastResult = null;
let mode = loadMode();

async function analyze(event) {
  event?.preventDefault();
  if (activeAppId == null || !$("#analyze-form").reportValidity()) return;
  const version = ++requestVersion;
  const hash = location.hash;
  const isCurrent = () => version === requestVersion && hash === location.hash;
  const payload = {
    app_id: activeAppId,
    limit: Number($("#limit").value),
    k: Number($("#k").value),
    refresh: $("#refresh").checked,
    sample_mode: $("#sample-mode").value,
  };
  const button = $("#analyze-btn");
  button.disabled = true;
  showLoading();
  try {
    const result = await request("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (isCurrent()) renderResult(result);
  } catch (error) {
    if (isCurrent()) showError(error);
  } finally {
    if (isCurrent()) {
      clearInterval(timer);
      button.disabled = false;
    }
  }
}

function showLoading() {
  lastResult = null;
  const seconds = el("span", { "aria-live": "off" }, "0");
  const started = Date.now();
  clearInterval(timer);
  timer = setInterval(() => { seconds.textContent = Math.floor((Date.now() - started) / 1000); }, 1000);
  $("#output").replaceChildren(
    el("div", { class: "card state" },
      el("div", { class: "spinner", "aria-hidden": "true" }),
      el("h2", { class: "state-title" }, "분석 대기"),
      el("p", { id: "loading-game" }, currentGame().name),
      el("p", {}, "Steam 리뷰를 모아서 분석하고 있어요."),
      el("p", { class: "muted" }, seconds, "초 경과 · 처음 받는 게임은 리뷰 1,000건에 20초쯤, 많으면 몇 분 걸려요")));
}

function showError(error) {
  lastResult = null;
  const shortage = error.status === 422 && /Input DataFrame is empty|Review count \(\d+\) is smaller than k \(\d+\)|No reviews to vectorize|vocabulary|no usable terms|terms remain|zero features/i.test(error.detail);
  $("#output").replaceChildren(
    shortage ? shortageNotice(error.detail) : el("div", { class: "card state callout danger", role: "alert" },
      el("h2", { class: "state-title" }, "분석 실패"),
      el("p", { class: "callout-title" }, error.message),
      error.detail && el("pre", { class: "callout-detail" }, error.detail),
      el("div", { class: "state-actions" },
        el("button", { type: "button", class: "btn btn-primary", onclick: () => analyze() }, "다시 시도"),
        el("a", { class: "btn", href: "#/" }, "게임 목록으로"))));
}

function shortageNotice(detail = "") {
  return el("section", { class: "card callout warn shortage", role: "status" },
    el("h2", { class: "state-title" }, "데이터 부족"),
    el("p", {}, "문제나 강점을 판단할 만큼 분석에 쓸 리뷰가 모이지 않았어요. 리뷰가 적거나 분석할 수 있는 단어가 부족할 수 있어요."),
    el("p", { class: "muted small" }, "리뷰 수를 늘리거나 추천·비추천 반반 모드로 다시 분석해 보세요. 다른 게임을 골라도 좋아요."),
    detail && el("pre", { class: "callout-detail" }, detail),
    el("div", { class: "state-actions" },
      el("button", { type: "button", class: "btn", disabled: Number($("#limit").value) >= 10000,
        onclick: () => {
          $("#limit").value = Math.min(10000, Math.max(1000, Number($("#limit").value) * 2));
          analyze();
        } }, "리뷰 수 늘려서 분석"),
      el("button", { type: "button", class: "btn", onclick: () => {
        $("#sample-mode").value = "balanced";
        showSampleModeHelp();
        analyze();
      } }, "추천·비추천 반반으로 분석"),
      el("a", { class: "btn", href: "#/" }, "다른 게임 고르기")));
}

// ---------- view mode ----------

function loadMode() {
  try {
    return localStorage.getItem(MODE_KEY) === "detail" ? "detail" : "simple";
  } catch {
    return "simple";
  }
}

function setMode(next) {
  mode = next;
  try { localStorage.setItem(MODE_KEY, next); } catch { /* storage unavailable: keep in memory only */ }
  document.body.dataset.mode = next;
  for (const button of document.querySelectorAll(".mode-switch button")) {
    button.setAttribute("aria-checked", String(button.dataset.mode === next));
  }
  if (lastResult) renderResult(lastResult);
}

function renderResult(result) {
  lastResult = result;
  if (result.game.name) knownGames.set(activeAppId, { ...currentGame(), name: result.game.name });
  renderGameHeader();
  const insufficient = !result.priorities.some((p) => p.issue_type !== OTHER && p.sufficient_evidence)
    && !result.positive_aspects.some((a) => a.sufficient_evidence);
  $("#output").replaceChildren(...[
    insufficient && shortageNotice(),
    ...(mode === "simple" ? simpleView(result) : detailView(result)),
  ].filter(Boolean));
}

// ---------- simple view: top issues and strengths with evidence ----------

function verdict(ratio) {
  if (ratio >= 0.7) return ["대체로 호평", "good"];
  if (ratio >= 0.4) return ["호불호가 갈려요", "mixed"];
  return ["대체로 혹평", "bad"];
}

function simpleView({ game, summary, priorities, positive_aspects, metadata }) {
  const total = summary.review_count;
  const minReviews = metadata.config.min_priority_reviews;
  // Both rankings use the backend's evidence threshold and ordering.
  const named = priorities.filter((p) => p.issue_type !== OTHER);
  const complaints = named.filter((p) => p.sufficient_evidence).slice(0, 3);
  const praised = positive_aspects.filter((a) => a.sufficient_evidence).slice(0, 3);
  return [
    isBalanced(metadata) ? balancedVerdictCard(game, summary, metadata) : verdictCard(game, summary),
    complaintSection(complaints, summary.negative_ratio, named.filter((p) => p.sufficient_evidence)),
    praiseSection(praised),
    simpleThinEvidenceSection(named.filter((p) => !p.sufficient_evidence),
      positive_aspects.filter((a) => !a.sufficient_evidence), minReviews),
    el("p", { class: "muted small footnote" },
      `리뷰 ${num(total)}건을 자동으로 분석한 결과라 실제 의견과 다를 수 있어요. 더 자세한 분석은 ‘자세히’에서 볼 수 있어요.`),
  ].filter(Boolean);
}

function verdictCard(game, summary) {
  const total = summary.review_count;
  const up = Math.round(summary.positive_ratio * total);
  const [label, tone] = verdict(summary.positive_ratio);
  return el("section", { class: "card verdict" },
    el("div", { class: "verdict-head" },
      el("h2", {}, game.name ?? "이 게임"),
      el("span", { class: `badge badge-${tone}` }, label)),
    el("p", { class: "verdict-line" },
      `리뷰 ${num(total)}건 중 `, el("b", {}, `${num(up)}건(${pct(summary.positive_ratio)})`), "이 이 게임을 추천했어요."),
    stackedBar([
      { label: "추천", value: up, tone: "good" },
      { label: "비추천", value: total - up, tone: "bad" },
    ]));
}

// In balanced mode the sample is 50:50 by design, so the verdict must come from Steam's own totals.
function balancedVerdictCard(game, summary, metadata) {
  const population = steamPopulation(metadata);
  const [label, tone] = population ? verdict(population.positive_ratio) : [];
  return el("section", { class: "card verdict" },
    el("div", { class: "verdict-head" },
      el("h2", {}, game.name ?? "이 게임"),
      label && el("span", { class: `badge badge-${tone}` }, label)),
    population
      ? [
        el("p", { class: "verdict-line", title: "Steam API 조건(언어 등)에 맞는 리뷰 기준" },
          `Steam 리뷰 ${num(population.total)}건 중 `, el("b", {}, pct(population.positive_ratio)), "가 이 게임을 추천했어요."),
        stackedBar([
          { label: "추천", value: population.positive, tone: "good" },
          { label: "비추천", value: population.negative, tone: "bad" },
        ]),
      ]
      : el("p", { class: "verdict-line" }, "이번에는 Steam 전체 추천 비율을 확인하지 못했어요."),
    el("p", { class: "sample-note" },
      `불만을 잘 찾으려고 추천·비추천 리뷰를 반반씩(${num(summary.review_count)}건) 골라 분석했어요. 아래 내용은 이 리뷰들 기준이에요.`));
}

function complaintSection(items, sampleNegative, ranked) {
  return el("section", { class: "section" },
    sectionHead(items.length === 3 ? "개선할 문제 TOP 3" : "개선할 문제", "많이 나오고 평가도 나쁜 문제부터 보여드려요"),
    items.length
      ? el("ol", { class: "complaints" }, items.map((p, i) => complaintCard(p, i + 1, sampleNegative, ranked)))
      : el("p", { class: "card muted" }, "순위를 매길 만큼 리뷰가 모인 문제가 없어요."));
}

function complaintReason(item, sampleNegative, ranked) {
  const lift = (item.negative_ratio - sampleNegative) * 100;
  const comparison = `언급 리뷰의 비추천 ${pct(item.negative_ratio, 1)} · 전체 분석 표본 ${pct(sampleNegative, 1)}`;
  if (lift > 0) {
    return `${comparison}보다 ${lift < 0.1 ? "0.1%p 미만" : `${lift.toFixed(1)}%p`} 높아요.`;
  }
  const frequencyRank = 1 + ranked.filter((p) => p.review_count > item.review_count).length;
  return `${comparison} · 순위에 오른 불만 중 언급 수 ${frequencyRank}위예요.`;
}

function topReviewFacts(item) {
  return el("p", { class: "top-facts" },
    "관련 리뷰 수 ", el("b", {}, `${num(item.review_count)}건`),
    " · 비율 ", el("b", {}, pct(item.review_ratio)), " (분석 리뷰 기준)");
}

function complaintCard(p, rank, sampleNegative, ranked) {
  const [label, , icon] = ISSUES[p.issue_type] || [p.issue_type, "other", "📝"];
  return el("li", { class: "card complaint" },
    el("span", { class: "complaint-icon", "aria-hidden": "true" }, icon),
    el("h3", {}, el("span", { class: "complaint-rank" }, `${rank}위`), label),
    topReviewFacts(p),
    el("p", { class: "selection-reason" }, "선정 이유 · ", complaintReason(p, sampleNegative, ranked)),
    evidenceButton(label, p.representative_reviews));
}

function praiseSection(items) {
  return el("section", { class: "section" },
    sectionHead(items.length === 3 ? "유지할 강점 TOP 3" : "유지할 강점", "리뷰에서 구체적으로 칭찬한 요소를 많이 나온 순서로 보여드려요"),
    items.length
      ? el("ol", { class: "complaints praises" }, items.map((a, i) => praiseCard(a, i + 1)))
      : el("p", { class: "card muted" }, "순위를 매길 만큼 리뷰가 모인 강점이 없어요."));
}

function praiseCard(a, rank) {
  const [label, icon] = POSITIVES[a.aspect_type] || [a.aspect_type, "👍"];
  return el("li", { class: "card complaint" },
    el("span", { class: "complaint-icon", "aria-hidden": "true" }, icon),
    el("h3", {}, el("span", { class: "complaint-rank" }, `${rank}위`), label),
    topReviewFacts(a),
    el("p", { class: "selection-reason" },
      `선정 이유 · 칭찬 언급 수 ${rank}위이고, 이 강점을 언급한 리뷰의 ${pct(a.positive_ratio)}가 추천했어요.`),
    evidenceButton(label, a.representative_reviews));
}

function simpleThinEvidenceSection(complaints, strengths, minReviews) {
  if (!complaints.length && !strengths.length) return null;
  const row = (item, type, label) => el("li", { class: "card thin-evidence-item" },
    el("span", { class: "muted small" }, type),
    el("b", {}, label),
    el("span", { class: "muted" }, `관련 리뷰 ${num(item.review_count)}건`),
    evidenceButton(label, item.representative_reviews));
  return el("section", { class: "section" },
    sectionHead("근거 리뷰 부족", `최소 리뷰 수(${num(minReviews)}건)에 못 미치는 항목은 TOP 3에서 제외했어요.`),
    el("ul", { class: "thin-evidence-list" },
      complaints.map((p) => row(p, "문제", issueLabel(p.issue_type))),
      strengths.map((a) => row(a, "강점", (POSITIVES[a.aspect_type] || [a.aspect_type])[0]))));
}

function evidenceButton(label, reviews) {
  return el("button", {
    type: "button", class: "btn evidence-button", "aria-haspopup": "dialog", "aria-label": `${label} 근거 보기`,
    onclick: (event) => openEvidenceDialog(label, reviews, event.currentTarget),
  }, "근거 보기");
}

function openEvidenceDialog(label, reviews, trigger) {
  const dialog = el("dialog", {
    class: "card evidence-dialog", "aria-labelledby": "evidence-dialog-title",
    onclose: () => { dialog.remove(); trigger.focus(); },
  },
  el("div", { class: "evidence-dialog-head" },
    el("h2", { id: "evidence-dialog-title" }, label),
    el("button", { type: "button", class: "btn", autofocus: true, onclick: () => dialog.close() }, "닫기")),
  reviews?.length
    ? el("div", { class: "quotes" }, reviews.map((review) =>
      el("blockquote", {}, el("p", {}, review.text),
        review.review_id != null && el("cite", { class: "muted" }, `리뷰 #${review.review_id}`))))
    : el("p", { class: "muted" }, "표시할 대표 리뷰가 없어요."));
  document.body.append(dialog);
  dialog.showModal();
}

// ---------- detail view ----------

function detailView(result) {
  const top = result.priorities.find((p) => p.issue_type !== OTHER && p.sufficient_evidence);
  const minReviews = result.metadata.config.min_priority_reviews;
  return [
    resultHeader(result),
    kpis(result, top),
    el("div", { class: "grid-2" }, recommendCard(result), sentimentCard(result)),
    prioritySection(result.priorities.filter((p) => p.sufficient_evidence), minReviews),
    thinEvidenceSection(result.priorities.filter((p) => !p.sufficient_evidence), minReviews),
    positiveSection(result.positive_aspects, minReviews),
    clusterSection(result.clusters, result.summary.review_count),
    warningsSection(isBalanced(result.metadata) ? [BALANCED_NOTE, ...result.warnings] : result.warnings),
    configSection(result.metadata.config),
  ].filter(Boolean);
}

function resultHeader({ game, metadata }) {
  const when = new Date(metadata.analyzed_at_utc).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
  const meta = [
    game.app_id != null && `App ID ${game.app_id}`,
    `분석 ${when}`,
    isBalanced(metadata) ? "표본 추천·비추천 반반" : "표본 최신 리뷰",
    `데이터 ${metadata.data_source}`,
    metadata.cache_used ? "캐시 사용" : "새로 수집",
  ].filter(Boolean).join(" · ");
  return el("div", { class: "result-head" }, el("h2", {}, game.name ?? "이름 없는 게임"), el("p", { class: "muted" }, meta));
}

function kpi(label, value, sub, tone) {
  return el("div", { class: tone ? `kpi kpi-${tone}` : "kpi" },
    el("span", { class: "kpi-label" }, label),
    el("b", {}, value),
    sub && el("span", { class: "kpi-sub" }, sub));
}

function kpis({ summary, sentiment, clustering, metadata }, top) {
  const silhouette = clustering.silhouette_score;
  const population = steamPopulation(metadata);
  return el("div", { class: "kpis" },
    kpi("분석한 리뷰", `${num(summary.review_count)}건`),
    isBalanced(metadata)
      ? kpi("Steam 전체 추천", population ? pct(population.positive_ratio, 1) : "-",
        `표본은 반반으로 맞춤 (${pct(summary.positive_ratio, 1)})`)
      : kpi("Steam 추천", pct(summary.positive_ratio, 1), `비추천 ${pct(summary.negative_ratio, 1)}`),
    kpi("글 감성 평균", signed(sentiment.average_compound), "-1 부정 ~ +1 긍정"),
    kpi("1순위 개선 과제", top ? issueLabel(top.issue_type) : "없음",
      top && `점수 ${top.priority_score.toFixed(2)} · 리뷰 ${num(top.review_count)}건`, "accent"),
    kpi("군집", `${clustering.formed_clusters}개`,
      `분리도 ${silhouette == null ? "-" : silhouette.toFixed(2)} · ${separation(silhouette)}`),
  );
}

function stackedBar(parts) {
  const total = parts.reduce((sum, part) => sum + part.value, 0) || 1;
  const share = (part) => pct(part.value / total);
  return [
    el("div", { class: "stack", role: "img", "aria-label": parts.map((p) => `${p.label} ${share(p)}`).join(", ") },
      parts.filter((p) => p.value > 0).map((p) =>
        el("span", { class: `seg seg-${p.tone}`, style: `flex-grow:${p.value}`, title: `${p.label} ${num(p.value)}건 (${share(p)})` }))),
    el("ul", { class: "legend" },
      parts.map((p) => el("li", {},
        el("i", { class: `dot seg-${p.tone}` }), `${p.label} `, el("b", {}, share(p)),
        el("span", { class: "muted" }, ` ${num(p.value)}건`)))),
  ];
}

function recommendCard({ summary, metadata }) {
  const n = summary.review_count;
  const sampleBar = stackedBar([
    { label: "추천", value: Math.round(summary.positive_ratio * n), tone: "good" },
    { label: "비추천", value: Math.round(summary.negative_ratio * n), tone: "bad" },
  ]);
  if (!isBalanced(metadata)) {
    return el("section", { class: "card" },
      el("h3", {}, "Steam 추천 여부"),
      el("p", { class: "muted small" }, "리뷰 작성자가 직접 고른 추천 / 비추천"),
      sampleBar);
  }
  const population = steamPopulation(metadata);
  return el("section", { class: "card" },
    el("h3", {}, "Steam 추천 여부"),
    el("p", { class: "muted small" }, "분석 표본은 추천·비추천을 반반 골라 만든 값이에요"),
    population && [
      el("p", { class: "bar-label" }, `Steam 전체 (${num(population.total)}건)`),
      stackedBar([
        { label: "추천", value: population.positive, tone: "good" },
        { label: "비추천", value: population.negative, tone: "bad" },
      ]),
    ],
    el("p", { class: "bar-label" }, `분석 표본 (${num(n)}건)`),
    sampleBar);
}

function sentimentCard({ sentiment }) {
  return el("section", { class: "card" },
    el("h3", {}, "리뷰 글의 감성"),
    el("p", { class: "muted small" }, "VADER가 글만 읽고 판단 · 추천 여부와 다를 수 있어요"),
    stackedBar([
      { label: "긍정", value: sentiment.positive, tone: "good" },
      { label: "중립", value: sentiment.neutral, tone: "neutral" },
      { label: "부정", value: sentiment.negative, tone: "bad" },
    ]));
}

function sectionHead(title, note) {
  return el("div", { class: "section-head" }, el("h2", {}, title), note && el("p", { class: "muted small" }, note));
}

function prioritySection(items, minReviews) {
  const weights = items[0]?.score_basis.weights;
  // Unclassified reviews are not actionable, so they always go last.
  const ordered = [...items.filter((p) => p.issue_type !== OTHER), ...items.filter((p) => p.issue_type === OTHER)];
  let rank = 0;
  return el("section", { class: "section" },
    sectionHead("개선 우선순위", [
      weights && `점수 = ${weights.frequency} × 언급 빈도 + ${weights.negative_ratio} × 비추천 비율 + ${weights.negative_severity} × 부정 강도`,
      `리뷰 ${minReviews}건 이상에서 나온 문제만 순위를 매겨요`,
    ].filter(Boolean).join(" · ")),
    ordered.length
      ? el("ol", { class: "priority-list" }, ordered.map((p) => priorityRow(p, p.issue_type === OTHER ? null : ++rank)))
      : el("p", { class: "muted" }, "순위를 매길 만큼 리뷰가 모인 문제가 없어요."));
}

// Issues with too few reviews keep their score for reference but stay out of the ranking above.
function thinEvidenceSection(items, minReviews) {
  if (!items.length) return null;
  return el("section", { class: "section" },
    sectionHead("근거 리뷰 부족", `리뷰 ${minReviews}건 미만에서만 나온 문제라 점수가 높아도 순위에서 뺐어요 · 참고용`),
    el("ol", { class: "priority-list" }, items.map((p) => priorityRow(p, null))));
}

function priorityRow(p, rank) {
  const basis = p.score_basis;
  const unranked = rank == null;
  return el("li", { class: unranked ? "priority card is-other" : "priority card" },
    el("details", {},
      el("summary", {},
        el("span", { class: "rank" }, unranked ? "–" : rank),
        el("div", { class: "priority-main" },
          el("div", { class: "priority-title" },
            issueChip(p.issue_type),
            p.issue_type === OTHER && el("span", { class: "muted small" }, "불만이지만 정해진 유형에 맞지 않는 리뷰 · 참고용")),
          el("div", { class: "meter" }, el("span", { class: "meter-fill", style: width(p.priority_score) }))),
        el("b", { class: "score" }, p.priority_score.toFixed(2)),
        el("ul", { class: "facts" },
          el("li", {}, "리뷰 ", el("b", {}, `${num(p.review_count)}건`), ` (${pct(p.review_ratio)})`),
          el("li", {}, "비추천 ", el("b", {}, pct(p.negative_ratio))),
          el("li", {}, "부정 강도 ", el("b", {}, p.negative_sentiment_severity.toFixed(2))),
          el("li", { class: "more" }, "점수 구성·리뷰"))),
      el("div", { class: "details-body" },
        el("div", {},
          el("h4", {}, "점수 구성"),
          el("div", { class: "breakdown" },
            scorePart("언급 빈도", basis.frequency_score, basis.weights.frequency),
            scorePart("비추천 비율", basis.negative_review_ratio, basis.weights.negative_ratio),
            scorePart("부정 강도", basis.negative_sentiment_severity, basis.weights.negative_severity))),
        reviewQuotes("가장 부정적인 리뷰", p.representative_reviews))));
}

// Ranked by review count (backend order); aspects below the complaint evidence bar stay listed but unranked.
function positiveSection(items, minReviews) {
  const ordered = [...items.filter((a) => a.sufficient_evidence), ...items.filter((a) => !a.sufficient_evidence)];
  let rank = 0;
  return el("section", { class: "section" },
    sectionHead("좋게 본 점", [
      "리뷰 문장에 구체적인 대상과 칭찬 표현이 함께 나온 경우만 세요",
      "한 리뷰가 여러 요소에 들어갈 수 있어요",
      `리뷰 ${minReviews}건 이상에서 나온 요소만 순위를 매겨요`,
    ].join(" · ")),
    ordered.length
      ? el("ol", { class: "priority-list positive-list" },
        ordered.map((a) => positiveRow(a, a.sufficient_evidence ? ++rank : null)))
      : el("p", { class: "muted" }, "리뷰에서 구체적으로 칭찬한 요소를 찾지 못했어요."));
}

function positiveRow(a, rank) {
  const [label] = POSITIVES[a.aspect_type] || [a.aspect_type];
  const unranked = rank == null;
  return el("li", { class: unranked ? "priority card is-other" : "priority card" },
    el("details", {},
      el("summary", {},
        el("span", { class: "rank" }, unranked ? "–" : rank),
        el("div", { class: "priority-main" },
          el("div", { class: "priority-title" },
            el("span", { class: "chip", style: "--chip:var(--good)", title: a.aspect_type }, label),
            unranked && el("span", { class: "muted small" }, "근거 리뷰 부족 · 참고용"))),
        el("b", { class: "score", title: "전체 리뷰 중 이 요소를 칭찬한 비율" }, pct(a.review_ratio, 1)),
        el("ul", { class: "facts" },
          el("li", {}, "리뷰 ", el("b", {}, `${num(a.review_count)}건`)),
          el("li", {}, "그중 추천 ", el("b", {}, pct(a.positive_ratio))),
          el("li", { class: "more" }, "리뷰 보기"))),
      el("div", { class: "details-body" }, reviewQuotes("글 감성이 가장 긍정적인 리뷰", a.representative_reviews))));
}

function scorePart(label, value, weight) {
  return el("div", { class: "part" },
    el("span", {}, label),
    el("div", { class: "meter thin" }, el("span", { class: "meter-fill", style: width(value) })),
    el("span", { class: "part-calc" }, `${value.toFixed(2)} × ${weight} = ${(value * weight).toFixed(2)}`));
}

function reviewQuotes(title, reviews) {
  if (!reviews?.length) return null;
  return el("div", { class: "quotes" },
    title && el("h4", {}, title),
    reviews.map((review) => quoteBlock(review.text,
      review.review_id != null && el("cite", { class: "muted" }, `리뷰 #${review.review_id}`))));
}

function clusterSection(clusters, total) {
  const ordered = [...clusters].sort((a, b) => b.review_count - a.review_count);
  return el("section", { class: "section" },
    sectionHead("리뷰 군집", "군집 라벨은 군집 전체의 대표 성격이에요. 개별 리뷰의 불만 유형은 별도이며, 한 리뷰에 여러 유형이 붙을 수 있어요."),
    clusterChart(ordered, total),
    el("div", { class: "cluster-grid" }, ordered.map((c) => clusterCard(c, total))));
}

function clusterChart(clusters, total) {
  return el("div", { class: "card cluster-chart" },
    el("p", { class: "muted small" }, "막대 길이는 분석 리뷰에서 차지하는 비중이에요 · 초록: 추천 · 빨강: 비추천"),
    clusters.map((c) => {
      const description = `군집 ${c.cluster_id + 1} · ${clusterChip(c).textContent} · 리뷰 ${num(c.review_count)}건, 전체의 ${pct(c.review_count / total, 1)}, 추천 ${pct(c.positive_ratio, 1)}, 비추천 ${pct(c.negative_ratio, 1)}`;
      return el("div", { class: "cluster-chart-row", role: "img", "aria-label": description },
        el("div", { class: "cluster-chart-label", "aria-hidden": "true" },
          el("b", {}, `군집 ${c.cluster_id + 1}`), clusterChip(c),
          el("span", { class: "muted small" }, `${num(c.review_count)}건 · ${pct(c.review_count / total, 1)}`)),
        el("div", { class: "cluster-chart-track", "aria-hidden": "true" },
          el("div", { class: "cluster-chart-bar", style: width(c.review_count / total) },
            el("span", { class: "seg-good", style: width(c.positive_ratio) }),
            el("span", { class: "seg-bad", style: width(c.negative_ratio) }))),
        el("p", { class: "muted small", "aria-hidden": "true" }, `추천 ${pct(c.positive_ratio, 1)} · 비추천 ${pct(c.negative_ratio, 1)}`));
    }));
}

function clusterCard(c, total) {
  return el("article", { class: "card cluster" },
    el("header", { class: "cluster-head" },
      el("h3", {}, `군집 ${c.cluster_id + 1}`),
      clusterChip(c),
      el("span", { class: "muted small push" }, `${num(c.review_count)}건 · ${pct(c.review_count / total)}`)),
    el("div", { class: "tags" }, c.keywords.map((keyword) => el("span", { class: "tag" }, keyword))),
    el("div", { class: "cluster-stats" },
      el("div", {},
        el("span", { class: "muted small" }, "Steam 추천"),
        el("b", {}, pct(c.positive_ratio)),
        el("div", { class: "split" },
          el("span", { class: "seg-good", style: `flex-grow:${c.positive_ratio}` }),
          el("span", { class: "seg-bad", style: `flex-grow:${c.negative_ratio}` }))),
      el("div", {}, el("span", { class: "muted small" }, "글 감성 평균"), el("b", {}, signed(c.average_sentiment_score))),
      el("div", {}, el("span", { class: "muted small" }, "부정적인 글"), el("b", {}, pct(c.negative_sentiment_ratio))),
      c.complaint_ratio != null && el("div", {},
        el("span", { class: "muted small" }, "불만 탐지 리뷰"),
        el("b", {}, `${num(c.complaint_review_count)}건 · ${pct(c.complaint_ratio)}`))),
    el("details", { class: "cluster-reviews" },
      el("summary", {}, `대표 리뷰 ${c.representative_reviews.length}개`),
      reviewQuotes(null, c.representative_reviews)));
}

function warningsSection(warnings) {
  if (!warnings?.length) return null;
  return el("section", { class: "card callout warn" },
    el("p", { class: "callout-title" }, "결과를 볼 때 주의할 점"),
    el("ul", {}, warnings.map((warning) => el("li", { title: warning }, translateWarning(warning)))));
}

function configSection(config) {
  return el("details", { class: "config" },
    el("summary", { class: "muted" }, "분석 설정 원본 보기"),
    el("pre", {}, JSON.stringify(config, null, 2)));
}

// ---------- wiring ----------

buildScreens();
for (const button of document.querySelectorAll(".mode-switch button")) {
  button.addEventListener("click", () => setMode(button.dataset.mode));
}
setMode(mode);
checkHealth();
window.addEventListener("hashchange", route);
route();
loadCatalog();
