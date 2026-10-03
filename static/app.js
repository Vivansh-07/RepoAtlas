/*
 * RepoAtlas frontend.
 *
 * The whole flow:
 *   user submits a GitHub URL
 *   -> we POST it to /api/analyze
 *   -> the server answers with nodes + edges already in Cytoscape's format
 *   -> we draw them, fill in the summary, and wire up hover/click/layouts.
 */

// ============================================================
// 1. Page elements and constants
// ============================================================
// document.getElementById returns the element that has id="..." in index.html.
// `const` declares a variable that is never reassigned.
const form = document.getElementById("analyze-form");
const urlInput = document.getElementById("repo-url");
const analyzeButton = document.getElementById("analyze-button");
const statusText = document.getElementById("status");
const emptyState = document.getElementById("empty-state");
const topModulesList = document.getElementById("top-modules");
const detailsCard = document.getElementById("details");
const loadingOverlay = document.getElementById("loading");
const loadingTitle = document.getElementById("loading-title");
const loadingSteps = document.getElementById("loading-steps");
const layoutHint = document.getElementById("layout-hint");
const fitButton = document.getElementById("fit-button");
const exampleChips = document.querySelectorAll(".chip");          // every class="chip"
const layoutButtons = document.querySelectorAll("[data-layout]"); // every data-layout="..."

// Community colours from CLAUDE.md. No reds (red = cycle), no greys (grey = isolated).
const COMMUNITY_COLORS = [
  "#7c3aed", "#0891b2", "#f59e0b", "#059669", "#2563eb", "#65a30d",
  "#ea580c", "#c026d3", "#0d9488", "#ca8a04", "#4f46e5", "#0284c7",
];
const NO_COMMUNITY_COLOR = "#cbd5e1";
const CYCLE_COLOR = "#e11d48";
const ACCENT_COLOR = "#6d28d9";
const EDGE_COLOR = "#94a3b8";
const EDGE_FOCUS_COLOR = "#475569";
const MIN_NODE_SIZE = 18;
const MAX_NODE_SIZE = 80;
// Label culling: a node shows its name when it's at least this many pixels wide
// on screen, and the top few modules ("landmarks") always do.
const LABEL_MIN_SCREEN_SIZE = 30;
const LANDMARK_COUNT = 8;

// ============================================================
// 2. State: what's on screen right now
// ============================================================
// `let` because these change as the user works.
let cy = null;              // the Cytoscape graph
let summary = null;         // summary of the last analysis
let selected = null;        // the clicked node, or null
let currentLayout = "force";
let runningLayout = null;   // so a new layout can stop one still animating


// ============================================================
// 3. React to the user
// ============================================================
// addEventListener("submit", ...) runs our function whenever the form is
// submitted: clicking Analyze, or pressing Enter in the input box.
form.addEventListener("submit", async (event) => {
  event.preventDefault();   // stop the browser from reloading the page
  await analyze(urlInput.value.trim());
});

exampleChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    urlInput.value = chip.dataset.repo;   // dataset.repo reads data-repo="..."
    form.requestSubmit();                 // like clicking Analyze
  });
});

layoutButtons.forEach((button) => {
  button.addEventListener("click", () => runLayout(button.dataset.layout));
});

fitButton.addEventListener("click", () => {
  if (cy) cy.animate({ fit: { eles: cy.elements(), padding: 30 } }, { duration: 400 });
});

// Escape closes the details card.
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && cy) select(null);
});


// ============================================================
// 4. Talk to the backend
// ============================================================
async function analyze(repoUrl) {
  setBusy(true);
  showStatus("");
  const stopLoading = startLoading(repoUrl);
  try {
    const data = await fetchAnalysis(repoUrl);
    summary = data.summary;
    drawGraph(data);
    showSummary(data.summary);
    const source = data.cached ? "from cache" : "freshly analysed";
    showStatus(`${data.repo} @ ${data.commit_sha.slice(0, 7)} · ${source}`);
  } catch (error) {
    showStatus(error.message, true);   // network, bad URL, server error: all land here
  } finally {
    stopLoading();                     // runs whether it worked or failed
    setBusy(false);
  }
}

/*
 * fetch() sends an HTTP request and returns a Promise: a placeholder for a value
 * that arrives later. `await` pauses *this function* until it arrives, while the
 * page stays responsive.
 */
async function fetchAnalysis(repoUrl) {
  let response;
  try {
    response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: repoUrl, include_external: false }),
    });
  } catch {
    throw new Error("Can't reach the RepoAtlas server. Is it running?");
  }

  const body = await response.json().catch(() => ({}));   // not JSON? use {}
  if (!response.ok) {
    // Our errors look like {"detail": "message"}; FastAPI's validation errors
    // put a list in "detail", so fall back to a generic message for those.
    const message = typeof body.detail === "string"
      ? body.detail
      : `Something went wrong (HTTP ${response.status}).`;
    throw new Error(message);
  }
  return body;
}


// ============================================================
// 5. Loading overlay
// ============================================================
// [text, milliseconds after the start when this step lights up]
const LOADING_STEPS = [
  ["Checking the latest commit", 0],
  ["Cloning the repository", 900],
  ["Parsing imports with ast", 2400],
  ["Ranking, clustering, finding cycles", 3800],
];

/*
 * Shows the overlay and returns a function that hides it again.
 * The server answers in one go, so we can't see its real progress: these timers
 * just move the highlight along at the speed a new repo typically takes.
 * A cached repo answers before most of them fire.
 */
function startLoading(repoUrl) {
  loadingTitle.textContent = `Analysing ${repoUrl.replace("https://github.com/", "").replace(/\/$/, "")}`;
  loadingSteps.replaceChildren(...LOADING_STEPS.map(([text]) => el("li", "", text)));
  loadingOverlay.hidden = false;

  // setTimeout(fn, ms) runs fn once, ms milliseconds from now, and returns an id
  // that clearTimeout(id) can use to cancel it.
  const timers = LOADING_STEPS.map(([, delay], index) => setTimeout(() => markStep(index), delay));

  // The returned arrow function still "remembers" `timers` (a closure),
  // so whoever calls it later can cancel exactly these timers.
  return () => {
    timers.forEach(clearTimeout);
    loadingOverlay.hidden = true;
  };
}

function markStep(active) {
  [...loadingSteps.children].forEach((item, index) => {
    item.classList.toggle("is-done", index < active);
    item.classList.toggle("is-active", index === active);
  });
}


// ============================================================
// 6. Graph styles
// ============================================================
// Cytoscape styles work like CSS: a selector picks elements, then properties
// style them. "data(size)" means "use this element's own `size` field".
// When two rules set the same property, the LATER rule wins, so the order of
// this list matters (e.g. .faded comes last so it beats everything).
const GRAPH_STYLE = [
  {
    selector: "node",
    style: {
      width: "data(size)",
      height: "data(size)",
      "background-color": "data(color)",
      "border-width": 2,
      "border-color": "#ffffff",
      label: "",                           // names are switched on by the next rule
      "font-family": "Inter, system-ui, sans-serif",
      "font-size": 12,
      "font-weight": 500,
      color: "#0f172a",
      "text-valign": "bottom",
      "text-margin-y": 5,
      "text-outline-color": "#ffffff",     // white halo keeps names readable over edges
      "text-outline-width": 2.5,
      "transition-property": "opacity",    // fade smoothly on hover
      "transition-duration": "0.15s",
    },
  },
  {
    // Label culling: only big-enough nodes (.labelled, see updateLabels),
    // plus whatever the user is focusing on, show their names.
    selector: "node.labelled, node.highlighted, node.selected",
    style: { label: "data(label)" },
  },
  {
    // [?in_cycle] matches elements whose in_cycle field is true.
    // The "underlay" is a soft red halo drawn behind the node.
    selector: "node[?in_cycle]",
    style: {
      "border-color": CYCLE_COLOR,
      "border-width": 3,
      "underlay-color": CYCLE_COLOR,
      "underlay-opacity": 0.18,
      "underlay-padding": 7,
      "underlay-shape": "ellipse",
    },
  },
  {
    selector: "edge",
    style: {
      width: "mapData(weight, 1, 6, 1, 3.5)",   // weight 1 -> 1px ... 6 or more -> 3.5px
      "line-color": EDGE_COLOR,
      "target-arrow-color": EDGE_COLOR,
      "target-arrow-shape": "triangle",         // the arrow points at the imported module
      "arrow-scale": 0.8,
      "curve-style": "bezier",
      opacity: 0.5,
      "transition-property": "opacity",
      "transition-duration": "0.15s",
    },
  },
  { selector: "edge[?type_only]", style: { "line-style": "dashed" } },
  {
    selector: "edge.highlighted",
    style: { "line-color": EDGE_FOCUS_COLOR, "target-arrow-color": EDGE_FOCUS_COLOR, opacity: 0.9 },
  },
  {
    selector: "edge[?in_cycle]",
    style: {
      "line-color": CYCLE_COLOR,
      "target-arrow-color": CYCLE_COLOR,
      width: 2.5,
      opacity: 0.9,
      "underlay-color": CYCLE_COLOR,
      "underlay-opacity": 0.12,
      "underlay-padding": 3,
    },
  },
  { selector: "node.selected", style: { "border-color": ACCENT_COLOR, "border-width": 4 } },
  { selector: "node.faded", style: { opacity: 0.12 } },
  { selector: "edge.faded", style: { opacity: 0.05 } },
];


// ============================================================
// 7. Layouts
// ============================================================
// One entry per layout button. `options` is a function so values like the
// ring width can be computed from the graph currently on screen.
const LAYOUTS = {
  force: {
    hint: "Connected modules pull together, so clusters emerge.",
    // fcose: edges act like springs, every node pushes the others away.
    options: () => ({
      name: "fcose",
      randomize: true,
      nodeRepulsion: () => 9000,
      idealEdgeLength: () => 90,
      nodeSeparation: 90,
    }),
  },
  hierarchy: {
    hint: "Bottom: foundations that import nothing else in the repo. Each module sits one level above its deepest dependency.",
    // "preset" = place nodes exactly where we say; we compute the spots ourselves.
    options: () => ({ name: "preset", positions: layeredPositions() }),
  },
  rings: {
    hint: "The most important modules sit in the centre, the least important on the outside.",
    options: () => ({
      name: "concentric",
      concentric: (node) => node.data("pagerank"),   // higher value = closer to the centre
      // About six rings: each ring spans 1/6 of the highest PageRank.
      levelWidth: (nodes) => nodes.max((node) => node.data("pagerank")).value / 6,
      minNodeSpacing: 12,
    }),
  },
  circle: {
    hint: "One circle, ordered by community, to compare the size of each cluster.",
    // `??` means "use the right side if the left is null": isolated modules go last.
    options: () => ({
      name: "circle",
      sort: (a, b) => (a.data("community") ?? 999) - (b.data("community") ?? 999),
    }),
  },
};

/*
 * Our layered ("hierarchy") layout: a simplified take on the Sugiyama method
 * for drawing directed graphs. (Cytoscape's built-in breadthfirst put all ~60
 * modules nothing imports, mostly tests, on one huge top row.)
 *  1. Treat each cycle group as one unit (the backend's scc_id). What's left
 *     has no cycles: it's the condensation DAG from analytics.py.
 *  2. Layer by longest chain: a unit that imports nothing internal is level 0
 *     (the bottom); any other unit sits one level above its deepest dependency.
 *  3. Order each level by community, so related modules sit side by side (a
 *     cheap stand-in for Sugiyama's crossing-reduction step).
 *  4. Wrap long levels onto several rows, so the drawing stays roughly square.
 * Returns {nodeId: {x, y}} for the "preset" layout.
 */
function layeredPositions() {
  const unitOf = (node) => (node.data("scc_id") !== null ? `cycle-${node.data("scc_id")}` : node.id());

  // unit -> the set of units it imports. Runtime edges only, like the analytics.
  const imports = new Map();
  cy.nodes().forEach((node) => imports.set(unitOf(node), new Set()));
  cy.edges().forEach((edge) => {
    const from = unitOf(edge.source());
    const to = unitOf(edge.target());
    if (!edge.data("type_only") && from !== to) imports.get(from).add(to);
  });

  // Longest chain below each unit, remembered in `level` so each is computed once.
  const level = new Map();
  function levelOf(unit) {
    if (!level.has(unit)) {
      level.set(unit, 0);                       // guard against loops, just in case
      let deepest = -1;
      for (const dependency of imports.get(unit)) deepest = Math.max(deepest, levelOf(dependency));
      level.set(unit, deepest + 1);
    }
    return level.get(unit);
  }

  // Group the nodes by level.
  const nodesByLevel = new Map();
  cy.nodes().forEach((node) => {
    const l = levelOf(unitOf(node));
    if (!nodesByLevel.has(l)) nodesByLevel.set(l, []);
    nodesByLevel.get(l).push(node);
  });

  const perRow = Math.max(8, Math.ceil(Math.sqrt(cy.nodes().length) * 1.6));
  const positions = {};
  let y = 0;
  // Highest level first, so it's drawn at the top and arrows point downwards.
  const levels = [...nodesByLevel.keys()].sort((a, b) => b - a);
  for (const l of levels) {
    const nodes = nodesByLevel.get(l).sort((a, b) =>
      (a.data("community") ?? 999) - (b.data("community") ?? 999)   // same community together...
      || b.data("pagerank") - a.data("pagerank"));                  // ...most important first

    for (let start = 0; start < nodes.length; start += perRow) {
      const row = nodes.slice(start, start + perRow);
      const widths = row.map((node) => node.data("size") + 14);     // each node + a gap
      let x = -widths.reduce((sum, w) => sum + w, 0) / 2;           // centre the row on x = 0
      row.forEach((node, i) => {
        positions[node.id()] = { x: x + widths[i] / 2, y };
        x += widths[i];
      });
      y += Math.max(...row.map((node) => node.data("size"))) + 18;  // next row below the tallest node
    }
    y += 36;                                                        // extra gap between levels
  }
  return positions;
}

function runLayout(name) {
  currentLayout = name;
  layoutButtons.forEach((button) => button.classList.toggle("is-active", button.dataset.layout === name));
  layoutHint.textContent = LAYOUTS[name].hint;
  if (!cy) return;

  if (runningLayout) runningLayout.stop();   // don't let two layouts fight over positions
  // {...a, b: 1} copies every field of a, then adds/overrides b.
  runningLayout = cy.layout({ ...LAYOUTS[name].options(), animate: true, animationDuration: 600, padding: 30 });
  runningLayout.run();
}


// ============================================================
// 8. Draw the graph and wire up interactions
// ============================================================
function drawGraph(data) {
  prepareNodes(data.nodes);

  if (cy) cy.destroy();          // throw away the previous graph, if any
  selected = null;
  hideDetails();
  emptyState.hidden = true;

  cy = cytoscape({
    container: document.getElementById("graph"),
    elements: { nodes: data.nodes, edges: data.edges },   // already Cytoscape's format
    style: GRAPH_STYLE,
    minZoom: 0.1,
    maxZoom: 3,
    autounselectify: true,       // we track the clicked node ourselves (`selected`)
    boxSelectionEnabled: false,
  });

  // Hover: focus on a module and its direct neighbours.
  cy.on("mouseover", "node", (event) => {
    focusOn(event.target);
    cy.container().style.cursor = "pointer";
  });
  cy.on("mouseout", "node", () => {
    focusOn(selected);           // back to the clicked module (or to nothing)
    cy.container().style.cursor = "";
  });

  // Click ("tap" also covers touch screens). Tapping empty space clears the selection.
  cy.on("tap", "node", (event) => select(event.target));
  cy.on("tap", (event) => {
    if (event.target === cy) select(null);
  });

  // Zooming changes how big nodes look on screen, so re-decide which get names.
  cy.on("zoom", scheduleLabelUpdate);
  cy.on("layoutstop", updateLabels);

  runLayout(currentLayout);
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

/*
 * Focus + context: keep one module and its direct neighbours fully visible and
 * fade everything else, so you can follow its connections without losing the
 * big picture. Passing null clears the focus.
 */
function focusOn(node) {
  cy.batch(() => {               // batch = apply all class changes in a single redraw
    cy.elements().removeClass("faded highlighted");
    if (!node) return;
    // closedNeighborhood = the node + its edges + the nodes at their other ends
    const neighbourhood = node.closedNeighborhood();
    cy.elements().not(neighbourhood).addClass("faded");
    neighbourhood.addClass("highlighted");
  });
}

function select(node) {
  if (selected) selected.removeClass("selected");
  selected = node;
  if (node) {
    node.addClass("selected");
    showDetails(node);
  } else {
    hideDetails();
  }
  focusOn(node);
}

// Select a module by name and glide the camera to it (used by the side lists).
function selectAndCenter(id) {
  const node = cy.getElementById(id);
  if (node.empty()) return;
  select(node);
  cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1.1) }, { duration: 500 });
}

/*
 * Label culling, one of our fixes for the "hairball". Like a paper map, which
 * always names the capitals but only names villages when you zoom in:
 *  - the LANDMARK_COUNT most important modules are always named;
 *  - any other node is named once it's LABEL_MIN_SCREEN_SIZE pixels wide on screen.
 */
function updateLabels() {
  const zoom = cy.zoom();
  cy.batch(() => {
    cy.nodes().forEach((node) => {
      const rank = node.data("pagerank_rank");          // null for external libraries
      const isLandmark = rank !== null && rank <= LANDMARK_COUNT;
      const bigOnScreen = node.data("size") * zoom >= LABEL_MIN_SCREEN_SIZE;
      node.toggleClass("labelled", isLandmark || bigOnScreen);
    });
  });
}

// "zoom" fires many times per second while scrolling. requestAnimationFrame
// runs our update just before the next screen repaint, so it happens at most
// once per frame however many zoom events arrive.
let labelFrame = 0;
function scheduleLabelUpdate() {
  if (labelFrame) return;
  labelFrame = requestAnimationFrame(() => {
    labelFrame = 0;
    updateLabels();
  });
}


// ============================================================
// 9. Module details card
// ============================================================
function showDetails(node) {
  const d = node.data();

  const dot = el("span", "dot");
  dot.style.background = d.color;
  const title = el("div", "details-title");
  title.append(el("h2", "", d.label), el("p", "", d.id));
  const close = el("button", "icon-button", "×");
  close.type = "button";
  close.setAttribute("aria-label", "Close details");
  close.addEventListener("click", () => select(null));
  const header = el("div", "details-header");
  header.append(dot, title, close);

  const parts = [header];
  if (d.in_cycle) parts.push(el("span", "badge badge-cycle", "In a circular dependency"));
  if (d.parse_error) parts.push(el("span", "badge badge-warn", `Couldn't parse: ${d.parse_error}`));

  const facts = el("dl", "facts");
  if (d.is_external) {
    addFact(facts, "Kind", d.kind === "stdlib" ? "Standard library" : "Third-party library");
  } else {
    addFact(facts, "Path", d.path);
    addFact(facts, "Lines", d.loc.toLocaleString());          // 1234 -> "1,234"
    addFact(facts, "Importance", `#${d.pagerank_rank} of ${summary.num_nodes} · ${d.pagerank.toFixed(3)}`);
    addFact(facts, "Community", d.community === null ? "None (isolated)" : `#${d.community + 1}`);
  }
  parts.push(facts);

  // Edge A -> B means "A imports B", so outgoing edges are what this module
  // imports and incoming edges are who imports it.
  parts.push(...neighbourSection("Imports", node.outgoers("edge"), (edge) => edge.target()));
  parts.push(...neighbourSection("Imported by", node.incomers("edge"), (edge) => edge.source()));

  detailsCard.replaceChildren(...parts);
  detailsCard.hidden = false;
}

function hideDetails() {
  detailsCard.hidden = true;
  detailsCard.replaceChildren();
}

function addFact(list, term, value) {
  list.append(el("dt", "", term), el("dd", "", value));
}

// A heading plus a clickable list of neighbouring modules, most important first.
// `otherEnd` is a function that picks the neighbour out of an edge.
function neighbourSection(title, edges, otherEnd) {
  const heading = el("p", "neighbors-title", `${title} (${edges.length})`);
  const list = el("ul", "neighbor-list");
  if (edges.empty()) list.append(el("li", "empty", "None"));

  const sorted = edges.toArray().sort((a, b) => otherEnd(b).data("pagerank") - otherEnd(a).data("pagerank"));
  for (const edge of sorted) {
    const other = otherEnd(edge);
    const button = el("button");
    button.type = "button";
    button.append(el("span", "", other.id()));
    if (edge.data("in_cycle")) button.append(el("span", "tag", "cycle"));
    else if (edge.data("type_only")) button.append(el("span", "tag", "type-only"));
    button.addEventListener("click", () => selectAndCenter(other.id()));
    const item = el("li");
    item.append(button);
    list.append(item);
  }
  return [heading, list];
}


// ============================================================
// 10. Summary panel
// ============================================================
function showSummary(summary) {
  // Every <dd data-stat="..."> gets the summary field it names.
  document.querySelectorAll("[data-stat]").forEach((dd) => {
    const value = summary[dd.dataset.stat];
    dd.textContent = Number.isInteger(value) ? value : value.toFixed(2);
  });
  document.getElementById("cycles-stat").classList.toggle("is-alert", summary.num_cycles > 0);
  showTopModules(summary.top_modules);
}

function showTopModules(topModules) {
  topModulesList.replaceChildren();
  const best = topModules.length ? topModules[0].pagerank : 1;

  for (const module of topModules) {
    const row = el("div", "top-row");
    row.append(el("span", "top-name", module.id), el("span", "top-score", module.pagerank.toFixed(3)));

    const fill = el("span");
    fill.style.width = `${(module.pagerank / best) * 100}%`;   // bar length relative to #1
    const bar = el("div", "top-bar");
    bar.append(fill);

    const item = el("li");
    item.title = `${module.id}: click to find it in the graph`;
    item.append(row, bar);
    item.addEventListener("click", () => selectAndCenter(module.id));
    topModulesList.append(item);
  }
}


// ============================================================
// 11. Small helpers
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
