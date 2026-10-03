/*
 * RepoAtlas frontend.
 *
 * The whole flow:
 *   user submits a GitHub URL
 *   -> we POST it to /api/analyze
 *   -> the server answers with nodes + edges already in Cytoscape's format
 *   -> we draw them, and fill in the summary panel.
 */

// ============================================================
// 1. Find the page elements we'll work with
// ============================================================
// document.getElementById returns the element that has id="..." in index.html.
// `const` declares a variable that is never reassigned.
const form = document.getElementById("analyze-form");
const urlInput = document.getElementById("repo-url");
const analyzeButton = document.getElementById("analyze-button");
const statusText = document.getElementById("status");
const emptyState = document.getElementById("empty-state");
const topModulesList = document.getElementById("top-modules");
const exampleChips = document.querySelectorAll(".chip");   // every element with class="chip"

// Community colours from CLAUDE.md. No reds (red = cycle) and no greys
// (grey = isolated / external).
const COMMUNITY_COLORS = [
  "#7c3aed", "#0891b2", "#f59e0b", "#059669", "#2563eb", "#65a30d",
  "#ea580c", "#c026d3", "#0d9488", "#ca8a04", "#4f46e5", "#0284c7",
];
const NO_COMMUNITY_COLOR = "#cbd5e1";
const CYCLE_COLOR = "#e11d48";
const EDGE_COLOR = "#94a3b8";
const MIN_NODE_SIZE = 18;
const MAX_NODE_SIZE = 80;

// The current Cytoscape graph. `let` (not const) because each new analysis replaces it.
let cy = null;


// ============================================================
// 2. React to the user
// ============================================================
// addEventListener("submit", ...) runs our function whenever the form is
// submitted: clicking Analyze, or pressing Enter in the input box.
// `async` marks a function that can `await` slow things like network calls.
form.addEventListener("submit", async (event) => {
  // A form's default behaviour is to reload the page with the answer.
  // We want to stay on this page and fetch the data ourselves.
  event.preventDefault();
  await analyze(urlInput.value.trim());
});

// Clicking an example chip fills in its URL and submits the form.
exampleChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    urlInput.value = chip.dataset.repo;   // dataset.repo reads the data-repo="..." attribute
    form.requestSubmit();                 // like clicking Analyze, including the "required" check
  });
});


// ============================================================
// 3. Talk to the backend
// ============================================================
async function analyze(repoUrl) {
  setBusy(true);
  showStatus("Analysing… a new repo takes a few seconds (clone + parse).");
  try {
    const data = await fetchAnalysis(repoUrl);
    drawGraph(data);
    showSummary(data.summary);
    const source = data.cached ? "from cache" : "freshly analysed";
    // Backtick strings can embed values with ${...}
    showStatus(`${data.repo} @ ${data.commit_sha.slice(0, 7)} · ${source}`);
  } catch (error) {
    // Anything that went wrong above (network, bad URL, server error) lands here.
    showStatus(error.message, true);
  } finally {
    // `finally` runs whether the try block worked or failed.
    setBusy(false);
  }
}

/*
 * fetch() sends an HTTP request and returns a Promise: a placeholder for a value
 * that will arrive later. `await` pauses *this function* until it arrives,
 * while the rest of the page stays responsive. That lets slow network code read
 * top to bottom like normal code.
 */
async function fetchAnalysis(repoUrl) {
  let response;
  try {
    response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // JSON.stringify turns a JS object into the JSON text the API expects.
      body: JSON.stringify({ repo_url: repoUrl, include_external: false }),
    });
  } catch {
    // fetch itself only fails when the server can't be reached at all.
    throw new Error("Can't reach the RepoAtlas server. Is it running?");
  }

  // Read the body as JSON. If it isn't JSON (e.g. a crash page), use an empty object.
  const body = await response.json().catch(() => ({}));

  // response.ok is true for 2xx status codes; anything else is an error.
  if (!response.ok) {
    // Our errors look like {"detail": "message"}. FastAPI's own validation
    // errors put a list in "detail", so fall back to a generic message then.
    const message = typeof body.detail === "string"
      ? body.detail
      : `Something went wrong (HTTP ${response.status}).`;
    throw new Error(message);
  }
  return body;
}


// ============================================================
// 4. Draw the graph
// ============================================================
// Cytoscape styles work like CSS: a selector picks elements, then properties
// style them. "data(size)" means "use this element's own `size` field".
const GRAPH_STYLE = [
  {
    selector: "node",
    style: {
      width: "data(size)",
      height: "data(size)",
      "background-color": "data(color)",
      "border-width": 2,
      "border-color": "#ffffff",
      label: "data(label)",
      "font-family": "Inter, system-ui, sans-serif",
      "font-size": 11,
      color: "#0f172a",
      "text-valign": "bottom",
      "text-margin-y": 4,
      "text-outline-color": "#ffffff",   // white halo keeps labels readable over edges
      "text-outline-width": 2,
      "min-zoomed-font-size": 7,          // hide labels when zoomed out too far to read
    },
  },
  {
    // [?in_cycle] matches elements whose in_cycle field is true
    selector: "node[?in_cycle]",
    style: { "border-color": CYCLE_COLOR, "border-width": 3 },
  },
  {
    selector: "edge",
    style: {
      // mapData: weight 1 -> 1px wide, weight 6 or more -> 3.5px
      width: "mapData(weight, 1, 6, 1, 3.5)",
      "line-color": EDGE_COLOR,
      "target-arrow-color": EDGE_COLOR,
      "target-arrow-shape": "triangle",   // arrow points at the imported module
      "arrow-scale": 0.8,
      "curve-style": "bezier",
      opacity: 0.5,
    },
  },
  {
    selector: "edge[?type_only]",          // `if TYPE_CHECKING:` imports
    style: { "line-style": "dashed" },
  },
  {
    selector: "edge[?in_cycle]",
    style: { "line-color": CYCLE_COLOR, "target-arrow-color": CYCLE_COLOR, opacity: 0.9, width: 2.5 },
  },
];

// fcose = a fast force-directed layout: edges pull connected modules together,
// all nodes push each other apart, and the result settles into clusters.
const LAYOUT = {
  name: "fcose",
  animate: true,
  animationDuration: 600,
  randomize: true,
  nodeRepulsion: () => 9000,
  idealEdgeLength: () => 90,
  nodeSeparation: 90,
  padding: 30,
};

function drawGraph(data) {
  prepareNodes(data.nodes);

  if (cy) cy.destroy();        // throw away the previous graph, if any
  emptyState.hidden = true;

  cy = cytoscape({
    container: document.getElementById("graph"),
    // The API already returns {data: {...}} objects: Cytoscape's own format.
    elements: { nodes: data.nodes, edges: data.edges },
    style: GRAPH_STYLE,
    layout: LAYOUT,
    minZoom: 0.1,
    maxZoom: 3,
  });
}

/*
 * Add two display-only fields to every node:
 *  - size, from PageRank. We use the square root because people judge a circle
 *    by its AREA, and area grows with the square of the width. Scaling the
 *    width linearly would make the top module look far more dominant than it is.
 *  - color, from the Louvain community.
 */
function prepareNodes(nodes) {
  const ranks = nodes.map((node) => node.data.pagerank);
  const min = Math.min(...ranks);           // ...ranks spreads the array into arguments
  const max = Math.max(...ranks);

  for (const node of nodes) {
    const d = node.data;
    const t = max > min ? (d.pagerank - min) / (max - min) : 0.5;   // 0 (least) .. 1 (most)
    d.size = MIN_NODE_SIZE + Math.sqrt(t) * (MAX_NODE_SIZE - MIN_NODE_SIZE);
    d.color = d.community === null
      ? NO_COMMUNITY_COLOR
      : COMMUNITY_COLORS[d.community % COMMUNITY_COLORS.length];   // % wraps past 12
  }
}


// ============================================================
// 5. Summary panel
// ============================================================
function showSummary(summary) {
  // Every <dd data-stat="..."> gets the summary field it names.
  document.querySelectorAll("[data-stat]").forEach((dd) => {
    const value = summary[dd.dataset.stat];
    dd.textContent = Number.isInteger(value) ? value : value.toFixed(2);
  });
  // Turn the "Cycle groups" number red when there's at least one cycle.
  document.getElementById("cycles-stat").classList.toggle("is-alert", summary.num_cycles > 0);
  showTopModules(summary.top_modules);
}

function showTopModules(topModules) {
  topModulesList.replaceChildren();               // remove the old rows
  const best = topModules.length ? topModules[0].pagerank : 1;

  for (const module of topModules) {
    const row = el("div", "top-row");
    row.append(el("span", "top-name", module.id), el("span", "top-score", module.pagerank.toFixed(3)));

    const fill = el("span");
    fill.style.width = `${(module.pagerank / best) * 100}%`;   // bar length relative to #1
    const bar = el("div", "top-bar");
    bar.append(fill);

    const item = el("li");
    item.title = module.id;                       // full name on hover if it's cut off
    item.append(row, bar);
    topModulesList.append(item);
  }
}


// ============================================================
// 6. Small helpers
// ============================================================
/*
 * Create an element with an optional class and text.
 * Text always goes in through textContent, never innerHTML: module names come
 * from someone else's repository, and innerHTML would run any HTML hidden in
 * them (an XSS attack). textContent always shows them as plain text.
 */
function el(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}

function setBusy(busy) {
  analyzeButton.disabled = busy;
  analyzeButton.textContent = busy ? "Analysing…" : "Analyze";
  exampleChips.forEach((chip) => { chip.disabled = busy; });
}

function showStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.classList.toggle("is-error", isError);
}
