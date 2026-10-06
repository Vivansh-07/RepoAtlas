/*
 * Repo Explorer tab.
 *
 * The whole flow:
 *   user submits a GitHub URL
 *   -> we POST it to /api/analyze
 *   -> the server answers with nodes + edges already in Cytoscape's format
 *   -> we draw them, fill in the summary, and wire up hover/click/layouts.
 *
 * An ES module: app.js imports it, and only what's marked `export` (at the
 * bottom) can be used from outside.
 */

import {
  ACCENT_COLOR, EDGE_COLOR, EDGE_FOCUS_COLOR, NODE_LABEL_STYLE,
  downloadPng, el, fetchJson, focusNeighbourhood, sizeAndColor,
} from "./common.js";

// ============================================================
// 1. Page elements and constants
// ============================================================
// document.getElementById returns the element that has id="..." in index.html.
// `const` declares a variable that is never reassigned.
const view = document.getElementById("explorer-view");
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
const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("module-search");
const searchOptions = document.getElementById("module-names");
const searchHint = document.getElementById("search-hint");
const showTypeOnly = document.getElementById("show-type-only");
const showExternal = document.getElementById("show-external");
const cyclesOnly = document.getElementById("cycles-only");
const filterNote = document.getElementById("filter-note");
const levelHint = document.getElementById("level-hint");
// querySelectorAll inside `view` only, so we never grab the Graph Lab's controls.
const exampleChips = view.querySelectorAll(".chip");
const layoutButtons = view.querySelectorAll("[data-layout]");
const levelButtons = view.querySelectorAll("[data-level]");

/*
 * The two levels of detail. Every analysis returns both graphs: the module
 * graph, and the same graph collapsed into packages (app/packages.py). They
 * have the same shape, so drawing, filters, layouts and the details card work
 * on either; these are just the words that change.
 */
const LEVELS = {
  modules: {
    plural: "modules", title: "Modules", edgesTitle: "Imports",
    noCycles: "This repository has no circular dependencies.",
    hint: "Each node is one Python file.",
  },
  packages: {
    plural: "packages", title: "Packages", edgesTitle: "Dependencies",
    noCycles: "No packages depend on each other in a loop.",
    hint: "Each node is a whole package. Imports inside a package disappear, leaving the architecture.",
  },
};

const CYCLE_COLOR = "#e11d48";
const EXTERNAL_COLOR = "#94a3b8";
const EXTERNAL_SIZE = 14;
const MIN_NODE_SIZE = 18;
const MAX_NODE_SIZE = 80;
// Label culling: a node shows its name when it's at least this many pixels wide
// on screen, and the top few modules ("landmarks") always do. A small graph
// (like most package views) has room to name every node.
const LABEL_MIN_SCREEN_SIZE = 30;
const LANDMARK_COUNT = 8;
const LABEL_ALL_UP_TO = 25;

// ============================================================
// 2. State: what's on screen right now
// ============================================================
// `let` because these change as the user works.
let cy = null;              // the Cytoscape graph
let lastData = null;        // the full answer of the last analysis, external libraries included
let moduleById = new Map(); // module id -> its data, to list a package's modules
let summary = null;         // summary of the graph on screen (module or package level)
let currentRepo = null;     // "owner/name" of the graph on screen
let selected = null;        // the clicked node, or null
let currentLevel = "modules";
let currentLayout = "force";
let runningLayout = null;   // so a new layout can stop one still animating


// ============================================================
// 3. React to the user
// ============================================================
// addEventListener("submit", ...) runs our function whenever the form is
// submitted: clicking Analyze, or pressing Enter in the input box.
form.addEventListener("submit", async (event) => {
  event.preventDefault();   // stop the browser from reloading the page
  await analyze(normalizeRepoInput(urlInput.value));
});

// The "Show" checkboxes: "change" fires when one is ticked or unticked.
[showTypeOnly, showExternal, cyclesOnly].forEach((box) => {
  box.addEventListener("change", () => {
    if (!lastData) return;
    redraw();
    updateAddressBar();
  });
});

// Search: Enter jumps to the best match; picking a suggestion jumps straight away.
searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  findModule(searchInput.value);
});
searchInput.addEventListener("input", () => {
  searchHint.textContent = "";
  // A suggestion picked from the list fills in an exact module name.
  if (cy && cy.getElementById(searchInput.value).nonempty()) findModule(searchInput.value);
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

levelButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const level = button.dataset.level;
    if (level === currentLevel) return;
    // A selected module stays in view: going up selects the package that holds it.
    const holder = selected && level === "packages" ? selected.data("package_node") : null;
    if (holder) drillTo("packages", holder);
    else setLevel(level);
  });
});

fitButton.addEventListener("click", () => {
  if (cy) cy.animate({ fit: { eles: cy.elements(), padding: 30 } }, { duration: 400 });
});

// e.g. repoatlas-pallets-flask-hierarchy.png, repoatlas-pallets-flask-packages-force.png
document.getElementById("png-button").addEventListener("click", () => {
  if (!cy || cy.nodes().empty()) {
    showStatus("Analyse a repository first, then save the picture.", true);
    return;
  }
  const level = currentLevel === "packages" ? "packages-" : "";
  downloadPng(cy, `repoatlas-${currentRepo.replace("/", "-")}-${level}${currentLayout}.png`);
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
    lastData = data;
    currentRepo = data.repo;
    // Sizes and colours are worked out once, from the whole repo, so the Show
    // options can hide nodes without ever resizing the ones that stay.
    prepareNodes(data.nodes);
    prepareNodes(data.packages.nodes);
    linkLevels(data);
    setLevel(currentLevel);            // draw the graph, summary and link at the current level
    const source = data.cached ? "from cache" : "freshly analysed";
    showStatus(`${data.repo} @ ${data.commit_sha.slice(0, 7)} · ${source}`);
  } catch (error) {
    showStatus(error.message, true);   // network, bad URL, server error: all land here
  } finally {
    stopLoading();                     // runs whether it worked or failed
    setBusy(false);
  }
}

// POST the URL; fetchJson (common.js) turns any failure into a readable Error.
// We always ask for external libraries too and hide them in the browser, so the
// "External libraries" checkbox works instantly, without a second request.
function fetchAnalysis(repoUrl) {
  return fetchJson("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // JSON.stringify turns a JS object into the JSON text the API expects.
    body: JSON.stringify({ repo_url: repoUrl, include_external: true }),
  });
}

/*
 * Be forgiving about what people paste: "pallets/flask", "github.com/pallets/flask",
 * "http://...", a trailing ".git" or "/" all become https://github.com/pallets/flask.
 * The server still checks the result strictly, so this is convenience, not security.
 */
function normalizeRepoInput(text) {
  const t = text.trim().replace(/\.git$/, "").replace(/\/+$/, "").replace(/^http:\/\//i, "https://");
  if (/^[\w.-]+\/[\w.-]+$/.test(t)) return `https://github.com/${t}`;     // owner/repo
  if (/^(www\.)?github\.com\//i.test(t)) return `https://${t.replace(/^www\./i, "")}`;
  return t.replace(/^https:\/\/www\.github\.com\//i, "https://github.com/");
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
      ...NODE_LABEL_STYLE,                 // shared font + white halo (common.js)
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
    // Imports of external libraries: fainter, so the repo's own structure stays in front.
    selector: "edge[kind != 'internal']",
    style: { "line-color": "#cbd5e1", "target-arrow-color": "#cbd5e1", opacity: 0.6 },
  },
  {
    // External library nodes: small, grey, dashed outline (see the legend).
    selector: "node[?is_external]",
    style: { "border-style": "dashed", "border-color": "#64748b", "border-width": 1.5 },
  },
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
    // We hand the layout the nodes already sorted by community instead of using
    // its `sort` option: in Cytoscape 3.34.3 the circle layout sorts, but then
    // assigns positions in the original order, so `sort` has no effect.
    // `??` means "use the right side if the left is null": isolated modules go last.
    options: () => ({
      name: "circle",
      eles: cy.nodes().sort((a, b) => (a.data("community") ?? 999) - (b.data("community") ?? 999)),
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
  updateAddressBar();
  if (cy.nodes().empty()) return;            // e.g. "only circular dependencies" on a cycle-free repo

  if (runningLayout) runningLayout.stop();   // don't let two layouts fight over positions
  // {...a, b: 1} copies every field of a, then adds/overrides b.
  runningLayout = cy.layout({ ...LAYOUTS[name].options(), animate: true, animationDuration: 600, padding: 30 });
  runningLayout.run();
}


// ============================================================
// 8. Levels of detail: modules or packages
// ============================================================
// The graph of the current level: the answer itself, or its `packages` part.
// Both look like {summary, nodes, edges}.
function graphData() {
  return currentLevel === "packages" ? lastData.packages : lastData;
}

function setLevel(name) {
  currentLevel = name;
  levelButtons.forEach((button) => button.classList.toggle("is-active", button.dataset.level === name));
  levelHint.textContent = LEVELS[name].hint;
  if (!lastData) return;               // e.g. set from a share link before the analysis arrives
  summary = graphData().summary;
  redraw();
  showSummary(summary);
  updateAddressBar();
}

/*
 * Tie the two levels together: each module remembers the package node it was
 * collapsed into (`package_node`), so the details card can link up a level,
 * and `moduleById` lets a package list its modules, most important first.
 */
function linkLevels(data) {
  // new Map([[key, value], ...]) builds a lookup table from a list of pairs.
  moduleById = new Map(data.nodes.map((n) => [n.data.id, n.data]));
  for (const pkg of data.packages.nodes) {
    for (const id of pkg.data.modules) moduleById.get(id).package_node = pkg.data.id;
  }
}

/*
 * Switch level and select a node there: down from a package to one of its
 * modules, or up from a module to its package. The new level's layout is still
 * animating, so the camera glides over once it has finished ("layoutstop").
 */
function drillTo(level, id) {
  setLevel(level);
  const node = cy.getElementById(id);
  if (node.empty()) {                  // hidden by "Only circular dependencies"
    searchHint.textContent = `${id} is hidden by the Show options below.`;
    return;
  }
  searchHint.textContent = "";
  select(node);
  cy.one("layoutstop", () => selectAndCenter(id));   // .one = run once, then forget
}


// ============================================================
// 9. Draw the graph and wire up interactions
// ============================================================
// The elements the "Show" options let through, as fresh copies for Cytoscape.
function visibleElements() {
  const all = graphData();
  let nodes = all.nodes;
  if (!showExternal.checked) nodes = nodes.filter((n) => !n.data.is_external);
  if (cyclesOnly.checked) nodes = nodes.filter((n) => n.data.in_cycle);
  // A Set answers "is this id in here?" instantly, however many nodes there are.
  const kept = new Set(nodes.map((n) => n.data.id));
  const edges = all.edges.filter((e) =>
    kept.has(e.data.source) && kept.has(e.data.target) && (showTypeOnly.checked || !e.data.type_only));
  // {...x} makes a shallow copy, so Cytoscape never holds on to our master data.
  return {
    nodes: nodes.map((n) => ({ data: { ...n.data } })),
    edges: edges.map((e) => ({ data: { ...e.data } })),
  };
}

function redraw() {
  const elements = visibleElements();
  drawGraph(elements);
  updateSearchOptions();
  updateFilterNote(elements);
}

// A note on the canvas: "Showing 13 of 82 modules" whenever a Show option hides
// something, and in the package view how many modules the packages hold.
function updateFilterNote(elements) {
  const { plural, noCycles } = LEVELS[currentLevel];   // pulls two fields out of the object
  const total = graphData().nodes.filter((n) => !n.data.is_external).length;
  const shown = elements.nodes.filter((n) => !n.data.is_external).length;
  const externals = elements.nodes.length - shown;
  const notes = [];
  if (currentLevel === "packages") notes.push(`${lastData.summary.num_nodes} modules in ${total} packages`);
  if (cyclesOnly.checked && shown === 0) notes.push(noCycles);
  else if (shown < total) notes.push(`Showing ${shown} of ${total} ${plural} (only circular dependencies)`);
  if (externals > 0) notes.push(`${externals} external libraries`);
  filterNote.textContent = notes.join(" · ");
  filterNote.hidden = notes.length === 0;
}

function drawGraph(elements) {
  if (cy) cy.destroy();          // throw away the previous graph, if any
  selected = null;
  hideDetails();
  emptyState.hidden = true;

  cy = cytoscape({
    container: document.getElementById("graph"),
    elements,                    // already Cytoscape's {data: ...} format
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

// Size from PageRank (square-root scaled, see common.js), colour from community.
// Repo modules: size from PageRank, colour from community (common.js).
// External libraries have no PageRank of their own: small and grey.
function prepareNodes(nodes) {
  sizeAndColor(nodes.filter((n) => !n.data.is_external), (d) => d.pagerank, MIN_NODE_SIZE, MAX_NODE_SIZE);
  for (const node of nodes) {
    if (node.data.is_external) Object.assign(node.data, { size: EXTERNAL_SIZE, color: EXTERNAL_COLOR });
  }
}

// Fill the search box's suggestion list with the visible modules, most important first.
function updateSearchOptions() {
  const ids = cy.nodes().sort((a, b) => b.data("pagerank") - a.data("pagerank")).map((n) => n.id());
  searchOptions.replaceChildren(...ids.map((id) => {
    const option = el("option");
    option.value = id;
    return option;
  }));
}

/*
 * Jump to a node by name. In the package view, a module's name finds the
 * package that holds it ("flask.app is in the package flask").
 */
function findModule(query) {
  const q = query.trim().toLowerCase();
  if (!q || !cy) return;
  searchHint.textContent = "";
  const match = bestMatch(cy.nodes().map((n) => n.data()), q);
  if (match) {
    selectAndCenter(match.id);
    return;
  }
  const module = bestMatch(lastData.nodes.map((n) => n.data), q);
  const holder = module?.package_node;   // ?. = "undefined if module is undefined", instead of an error
  if (currentLevel === "packages" && holder && cy.getElementById(holder).nonempty()) {
    searchHint.textContent = `${module.id} is in the package ${holder}.`;
    selectAndCenter(holder);
    return;
  }
  // Not on screen: is it hidden by a Show option, or not in the repo at all?
  const hidden = module || graphData().nodes.some((n) => n.data.id.toLowerCase().includes(q));
  searchHint.textContent = hidden
    ? `"${query.trim()}" is hidden by the Show options below.`
    : `Nothing matches "${query.trim()}".`;
}

// Of a list of node data, the one named exactly q, otherwise the most
// important one whose name contains q ("app" finds flask.app). undefined if none.
function bestMatch(items, q) {
  return items.find((d) => d.id.toLowerCase() === q)
    ?? items.filter((d) => d.id.toLowerCase().includes(q)).sort((a, b) => b.pagerank - a.pagerank)[0];
}

// Focus + context on one module (or none), shared with the Graph Lab.
function focusOn(node) {
  focusNeighbourhood(cy, node);
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
 *  - any other node is named once it's LABEL_MIN_SCREEN_SIZE pixels wide on screen;
 *  - in a graph of at most LABEL_ALL_UP_TO nodes, every node is named.
 */
function updateLabels() {
  const zoom = cy.zoom();
  const labelAll = cy.nodes().length <= LABEL_ALL_UP_TO;
  cy.batch(() => {
    cy.nodes().forEach((node) => {
      const rank = node.data("pagerank_rank");          // null for external libraries
      const isLandmark = rank !== null && rank <= LANDMARK_COUNT;
      const bigOnScreen = node.data("size") * zoom >= LABEL_MIN_SCREEN_SIZE;
      node.toggleClass("labelled", labelAll || isLandmark || bigOnScreen);
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
// 10. Details card (a module, a package or a library)
// ============================================================
function showDetails(node) {
  const d = node.data();
  const isPackage = currentLevel === "packages" && !d.is_external;

  const dot = el("span", "dot");
  dot.style.background = d.color;
  const title = el("div", "details-title");
  title.append(el("h2", "", d.label), el("p", "", d.id));     // short name, then the full one
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
    addFact(facts, isPackage ? "Folder" : "Path", d.path);
    if (isPackage) {
      addFact(facts, "Modules", d.module_count);
    } else {
      // Up a level: a link to the package this module was collapsed into.
      const up = el("button", "link-button", d.package_node);
      up.type = "button";
      up.title = "Show it in the package view";
      up.addEventListener("click", () => drillTo("packages", d.package_node));
      addFact(facts, "Package", up);
    }
    addFact(facts, "Lines", d.loc.toLocaleString());          // 1234 -> "1,234"
    addFact(facts, "Importance", `#${d.pagerank_rank} of ${summary.num_nodes} · ${d.pagerank.toFixed(3)}`);
    addFact(facts, "Community", d.community === null ? "None (isolated)" : `#${d.community + 1}`);
  }
  parts.push(facts);

  // Down a level: the package's modules, most important first.
  if (isPackage) {
    const members = d.modules.map((id) => moduleById.get(id)).sort((a, b) => b.pagerank - a.pagerank);
    parts.push(...nodeList("Modules", members.map((m) => ({
      id: m.id,
      tag: m.in_cycle ? "cycle" : "",
      open: () => drillTo("modules", m.id),
    }))));
  }

  // Edge A -> B means "A imports B", so outgoing edges are what this node
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

// `value` can be text or an element (like the package link): append() takes both.
function addFact(list, term, value) {
  const dd = el("dd");
  dd.append(value);
  list.append(el("dt", "", term), dd);
}

// The neighbours at the other end of `edges`, most important first.
// `otherEnd` is a function that picks the neighbour out of an edge.
function neighbourSection(title, edges, otherEnd) {
  const sorted = edges.toArray().sort((a, b) => otherEnd(b).data("pagerank") - otherEnd(a).data("pagerank"));
  return nodeList(title, sorted.map((edge) => ({
    id: otherEnd(edge).id(),
    tag: edgeTag(edge),
    open: () => selectAndCenter(otherEnd(edge).id()),
  })));
}

// "cycle", "type-only", and for a package link how many imports it stands for.
function edgeTag(edge) {
  const tags = [];
  if (edge.data("in_cycle")) tags.push("cycle");
  else if (edge.data("type_only")) tags.push("type-only");
  if (currentLevel === "packages") tags.push(count(edge.data("weight"), "import"));
  return tags.join(" · ");
}

// A heading plus a list of clickable names. items: [{id, tag, open}], where
// `open` is the function to run when the name is clicked.
function nodeList(title, items) {
  const heading = el("p", "neighbors-title", `${title} (${items.length})`);
  const list = el("ul", "neighbor-list");
  if (items.length === 0) list.append(el("li", "empty", "None"));
  for (const item of items) {
    const button = el("button");
    button.type = "button";
    button.append(el("span", "", item.id));
    if (item.tag) button.append(el("span", "tag", item.tag));
    button.addEventListener("click", item.open);
    const li = el("li");
    li.append(button);
    list.append(li);
  }
  return [heading, list];
}


// ============================================================
// 11. Summary panel
// ============================================================
function showSummary(summary) {
  // Every <dd data-stat="..."> gets the summary field it names.
  document.querySelectorAll("[data-stat]").forEach((dd) => {
    const value = summary[dd.dataset.stat];
    dd.textContent = Number.isInteger(value) ? value : value.toFixed(2);
  });
  document.getElementById("cycles-stat").classList.toggle("is-alert", summary.num_cycles > 0);
  const level = LEVELS[currentLevel];
  document.getElementById("nodes-label").textContent = level.title;
  document.getElementById("edges-label").textContent = level.edgesTitle;
  document.getElementById("top-title").textContent = `Most important ${level.plural}`;
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
// 12. Small helpers (el() lives in common.js)
// ============================================================
function setBusy(busy) {
  analyzeButton.disabled = busy;
  analyzeButton.textContent = busy ? "Analysing…" : "Analyze";
  exampleChips.forEach((chip) => { chip.disabled = busy; });
}

function showStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.classList.toggle("is-error", isError);
}

// count(1, "module") -> "1 module", count(5, "module") -> "5 modules"
function count(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}


// ============================================================
// 13. Shareable links: /?repo=pallets/flask&layout=hierarchy&level=packages
// ============================================================
// Keep the address bar in sync with what's on screen, so it can be copied and
// shared. replaceState changes the URL without reloading the page. Only while
// this tab is visible: an analysis finishing in the background mustn't
// overwrite the Graph Lab's link.
// (currentRepo comes from the server, which only accepts [A-Za-z0-9_.-] names.)
function updateAddressBar() {
  if (view.hidden) return;
  if (!currentRepo) {
    history.replaceState(null, "", "/");
    return;
  }
  // The level and Show options are only added when they differ from the defaults.
  let link = `?repo=${currentRepo}&layout=${currentLayout}`;
  if (currentLevel === "packages") link += "&level=packages";
  if (showExternal.checked) link += "&external=1";
  if (!showTypeOnly.checked) link += "&typeonly=0";
  if (cyclesOnly.checked) link += "&cycles=1";
  history.replaceState(null, "", link);
}

// On page load, open whatever the link asks for. URLSearchParams reads the
// "?key=value&..." part of the address. This runs last in the file because it
// uses LAYOUTS and the functions defined above.
const linkParams = new URLSearchParams(window.location.search);
if (linkParams.get("repo")) {
  // Object.hasOwn, not `in`: `"constructor" in LAYOUTS` is true for every object.
  if (Object.hasOwn(LAYOUTS, linkParams.get("layout"))) runLayout(linkParams.get("layout"));
  if (Object.hasOwn(LEVELS, linkParams.get("level"))) setLevel(linkParams.get("level"));
  showExternal.checked = linkParams.get("external") === "1";
  showTypeOnly.checked = linkParams.get("typeonly") !== "0";
  cyclesOnly.checked = linkParams.get("cycles") === "1";
  const repo = linkParams.get("repo");
  urlInput.value = repo.startsWith("https://") ? repo : `https://github.com/${repo}`;
  form.requestSubmit();
}


// ============================================================
// 14. What app.js (the tab switcher) can use
// ============================================================
// Called when this tab becomes visible. A Cytoscape graph that was hidden
// doesn't notice size changes, so tell it to re-measure its container.
export function showExplorer() {
  if (cy) cy.resize();
  updateAddressBar();
}

// For poking around in the browser console (see app.js).
export function getExplorerGraph() {
  return cy;
}
