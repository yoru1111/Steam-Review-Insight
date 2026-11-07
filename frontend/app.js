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
  [OTHER]: ["분류 안 됨", "other", "💬"],
};

const MODE_KEY = "sri-view-mode";

const ERROR_TITLES = {
  422: "입력값이나 리뷰 데이터를 확인해 주세요",
  500: "분석 중 서버 오류가 났어요",
  501: "아직 지원하지 않는 기능이에요",
  502: "게임 검색에 실패했어요",
  503: "리뷰 수집 모듈이 아직 연결되지 않았어요",
};

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
  for (const child of children.flat()) {
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

function issueChip(type) {
  const [label, key] = ISSUES[type] || [type, "other"];
  return el("span", { class: `chip chip-${key}`, title: type }, label);
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
  constructor(title, detail = "") {
    super(title);
    this.detail = detail;
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
  throw new ApiError(ERROR_TITLES[response.status] || `요청 실패 (${response.status})`, formatDetail(body.detail));
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

// ---------- search ----------

async function searchGames(event) {
  event.preventDefault();
  const query = $("#query").value.trim();
  if (!query) return;
  const list = $("#search-results");
  list.hidden = false;
  list.replaceChildren(el("li", { class: "muted" }, "검색 중…"));
  try {
    const { games } = await request(`/api/games/search?query=${encodeURIComponent(query)}`);
    list.replaceChildren(...(games.length ? games.map(gameOption) : [el("li", { class: "muted" }, "검색 결과가 없어요.")]));
  } catch (error) {
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
  $("#app-id").value = game.app_id;
  $("#search-results").hidden = true;
  $("#selected-game").textContent = `선택됨: ${game.name ?? "이름 없음"} (App ID ${game.app_id})`;
}

// ---------- analyze ----------

let timer;
let lastResult = null;
let mode = loadMode();

async function analyze(event) {
  event.preventDefault();
  const payload = {
    app_id: Number($("#app-id").value),
    limit: Number($("#limit").value),
    k: Number($("#k").value),
    refresh: $("#refresh").checked,
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
    renderResult(result);
  } catch (error) {
    showError(error);
  } finally {
    clearInterval(timer);
    button.disabled = false;
  }
}

function showLoading() {
  lastResult = null;
  const seconds = el("span", {}, "0");
  const started = Date.now();
  clearInterval(timer);
  timer = setInterval(() => { seconds.textContent = Math.floor((Date.now() - started) / 1000); }, 1000);
  $("#output").replaceChildren(
    el("div", { class: "card state" },
      el("div", { class: "spinner", "aria-hidden": "true" }),
      el("p", { class: "state-title" }, "리뷰를 분석하고 있어요"),
      el("p", { class: "muted" }, seconds, "초 경과 · 리뷰가 많으면 몇 분 걸릴 수 있어요")));
}

function showError(error) {
  lastResult = null;
  $("#output").replaceChildren(
    el("div", { class: "card callout danger", role: "alert" },
      el("p", { class: "callout-title" }, error.message),
      error.detail && el("pre", { class: "callout-detail" }, error.detail)));
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
  $("#output").replaceChildren(...(mode === "simple" ? simpleView(result) : detailView(result)));
}

// ---------- simple view: plain-language summary, no clusters/sentiment/scores ----------

function verdict(ratio) {
  if (ratio >= 0.7) return ["대체로 호평", "good"];
  if (ratio >= 0.4) return ["호불호가 갈려요", "mixed"];
  return ["대체로 혹평", "bad"];
}

function simpleView({ game, summary, priorities, clusters }) {
  const total = summary.review_count;
  const complaints = priorities.filter((p) => p.issue_type !== OTHER).slice(0, 3);
  // Clusters are hidden here; only their representative reviews are borrowed when most of the group recommends.
  const praised = clusters.filter((c) => c.positive_ratio >= 0.8).sort((a, b) => b.review_count - a.review_count);
  return [
    verdictCard(game, summary),
    complaintSection(complaints, total),
    praiseSection(praised),
    el("p", { class: "muted small footnote" },
      `리뷰 ${num(total)}건을 자동으로 분석한 결과라 실제 의견과 다를 수 있어요. 숫자와 근거는 ‘자세히’에서 볼 수 있어요.`),
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

function complaintSection(items, total) {
  return el("section", { class: "section" },
    sectionHead("주요 불만 TOP 3", "많이 나오고 평가도 나쁜 문제부터 보여드려요"),
    items.length
      ? el("ol", { class: "complaints" }, items.map((p, i) => complaintCard(p, i + 1, total)))
      : el("p", { class: "card muted" }, "리뷰에서 눈에 띄는 불만을 찾지 못했어요."));
}

function complaintCard(p, rank, total) {
  const [label, , icon] = ISSUES[p.issue_type] || [p.issue_type, "other", "💬"];
  const quote = p.representative_reviews?.[0];
  return el("li", { class: "card complaint" },
    el("span", { class: "complaint-icon", "aria-hidden": "true" }, icon),
    el("h3", {}, el("span", { class: "complaint-rank" }, `${rank}위`), label),
    el("p", {},
      `리뷰 ${num(total)}건 중 `, el("b", {}, `${num(p.review_count)}건`), "에서 이 문제를 이야기했고, ",
      "그중 ", el("b", {}, pct(p.negative_ratio)), "가 게임을 비추천했어요."),
    quote && el("blockquote", {}, el("p", {}, `“${quote.text}”`)));
}

function praiseSection(clusters) {
  const quotes = clusters.map((c) => c.representative_reviews[0]).filter(Boolean).slice(0, 3);
  if (!quotes.length) return null;
  return el("section", { class: "section" },
    sectionHead("좋게 본 점", "추천이 많은 리뷰 묶음에서 고른 리뷰예요"),
    el("div", { class: "praise-grid" }, quotes.map((review) => el("blockquote", { class: "praise" }, el("p", {}, `“${review.text}”`)))));
}

// ---------- detail view ----------

function detailView(result) {
  const top = result.priorities.find((p) => p.issue_type !== OTHER);
  return [
    resultHeader(result),
    kpis(result, top),
    el("div", { class: "grid-2" }, recommendCard(result), sentimentCard(result)),
    prioritySection(result.priorities),
    clusterSection(result.clusters, result.summary.review_count),
    warningsSection(result.warnings),
    configSection(result.metadata.config),
  ].filter(Boolean);
}

function resultHeader({ game, metadata }) {
  const when = new Date(metadata.analyzed_at_utc).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
  const meta = [
    game.app_id != null && `App ID ${game.app_id}`,
    `분석 ${when}`,
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

function kpis({ summary, sentiment, clustering }, top) {
  const silhouette = clustering.silhouette_score;
  return el("div", { class: "kpis" },
    kpi("분석한 리뷰", `${num(summary.review_count)}건`),
    kpi("Steam 추천", pct(summary.positive_ratio, 1), `비추천 ${pct(summary.negative_ratio, 1)}`),
    kpi("글 감성 평균", signed(sentiment.average_compound), "-1 부정 ~ +1 긍정"),
    kpi("1순위 개선 과제", top ? issueLabel(top.issue_type) : "없음", top && `점수 ${top.priority_score.toFixed(2)}`, "accent"),
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

function recommendCard({ summary }) {
  const n = summary.review_count;
  return el("section", { class: "card" },
    el("h3", {}, "Steam 추천 여부"),
    el("p", { class: "muted small" }, "리뷰 작성자가 직접 고른 추천 / 비추천"),
    stackedBar([
      { label: "추천", value: Math.round(summary.positive_ratio * n), tone: "good" },
      { label: "비추천", value: Math.round(summary.negative_ratio * n), tone: "bad" },
    ]));
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

function prioritySection(items) {
  const weights = items[0]?.score_basis.weights;
  // Unclassified reviews are not actionable, so they always go last.
  const ordered = [...items.filter((p) => p.issue_type !== OTHER), ...items.filter((p) => p.issue_type === OTHER)];
  let rank = 0;
  return el("section", { class: "section" },
    sectionHead("개선 우선순위", weights &&
      `점수 = ${weights.frequency} × 언급 빈도 + ${weights.negative_ratio} × 비추천 비율 + ${weights.negative_severity} × 부정 강도`),
    ordered.length
      ? el("ol", { class: "priority-list" }, ordered.map((p) => priorityRow(p, p.issue_type === OTHER ? null : ++rank)))
      : el("p", { class: "muted" }, "우선순위 결과가 없어요."));
}

function priorityRow(p, rank) {
  const basis = p.score_basis;
  const isOther = rank == null;
  return el("li", { class: isOther ? "priority card is-other" : "priority card" },
    el("details", {},
      el("summary", {},
        el("span", { class: "rank" }, isOther ? "–" : rank),
        el("div", { class: "priority-main" },
          el("div", { class: "priority-title" },
            issueChip(p.issue_type),
            isOther && el("span", { class: "muted small" }, "키워드에 걸리지 않은 리뷰 · 참고용")),
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
    reviews.map((review) => el("blockquote", {},
      el("p", {}, review.text),
      review.review_id != null && el("cite", { class: "muted" }, `리뷰 #${review.review_id}`))));
}

function clusterSection(clusters, total) {
  const ordered = [...clusters].sort((a, b) => b.review_count - a.review_count);
  return el("section", { class: "section" },
    sectionHead("리뷰 군집", "비슷한 단어를 쓴 리뷰끼리 자동으로 묶은 결과 · 유형 라벨은 키워드 기준 참고값"),
    el("div", { class: "cluster-grid" }, ordered.map((c) => clusterCard(c, total))));
}

function clusterCard(c, total) {
  return el("article", { class: "card cluster" },
    el("header", { class: "cluster-head" },
      el("h3", {}, `군집 ${c.cluster_id + 1}`),
      issueChip(c.issue_type),
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
      el("div", {}, el("span", { class: "muted small" }, "부정적인 글"), el("b", {}, pct(c.negative_sentiment_ratio)))),
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

$("#search-form").addEventListener("submit", searchGames);
$("#analyze-form").addEventListener("submit", analyze);
$("#app-id").addEventListener("input", () => { $("#selected-game").textContent = ""; });
for (const button of document.querySelectorAll(".mode-switch button")) {
  button.addEventListener("click", () => setMode(button.dataset.mode));
}
setMode(mode);
checkHealth();
