/*
 * Graph Lab tab: generate random graphs from three classic models and compare them.
 *
 * Flow: pick a model and parameters -> GET /api/generate?... -> draw the graph
 * with Cytoscape, the statistics in the side panel, and the degree distribution
 * with Chart.js.
 */

import {
  ACCENT_COLOR, EDGE_COLOR, EDGE_FOCUS_COLOR, NODE_LABEL_STYLE,
  fetchJson, focusNeighbourhood, sizeAndColor,
} from "./common.js";

// ============================================================
// 1. Page elements
// ============================================================
const view = document.getElementById("lab-view");
const modelButtons = view.querySelectorAll("[data-model]");
const paramRows = view.querySelectorAll("[data-for]");        // slider rows, per model
const sliders = view.querySelectorAll("input[type=range]");
const seedInput = document.getElementById("lab-seed");
const generateButton = document.getElementById("lab-generate");
const statusText = document.getElementById("lab-status");
const budgetHint = document.getElementById("lab-budget");
const layoutButtons = view.querySelectorAll("[data-lab-layout]");
const lookForBlocks = view.querySelectorAll("[data-look-for]");
const loadingOverlay = document.getElementById("lab-loading");
const fitButton = document.getElementById("lab-fit");
const nodeInfo = document.getElementById("lab-node-info");
const logToggle = document.getElementById("lab-log");
const chartCanvas = document.getElementById("degree-chart");

const MAX_EDGES = 5000;          // same budget as the server (config.MAX_GENERATED_EDGES)
const GRID_COLOR = "#e2e8f0";

// Chart.js defaults, set once: our font and muted text colour.
Chart.defaults.font.family = "Inter, system-ui, sans-serif";
Chart.defaults.color = "#64748b";

// ============================================================
// 2. State
// ============================================================
let model = "ba";
let layout = "force";
let cy = null;
let chart = null;
let lastData = null;
let started = false;             // has the tab been opened yet?
let latestRequest = 0;           // numbers each generate() call; see below


// ============================================================
// 3. Reading the controls
// ============================================================
const sliderValue = (name) => Number(document.getElementById(`lab-${name}`).value);

// The query parameters for /api/generate, from the current controls.
function currentParams() {
  const params = { model, n: sliderValue("n") };
  if (model === "er") params.p = sliderValue("p");
  if (model === "ba") params.m = sliderValue("m");
  if (model === "ws") {
    params.k = sliderValue("k");
    params.p = sliderValue("rewire");      // the API calls the rewiring probability p too
  }
  if (seedInput.value.trim() !== "") params.seed = seedInput.value.trim();
  return params;
}

// Live hint under the sliders: expected size, and the model's key threshold.
function updateBudgetHint() {
  const n = sliderValue("n");
  let edges;
  let extra = "";
  if (model === "er") {
    const p = sliderValue("p");
    edges = (p * n * (n - 1)) / 2;
    extra = ` Giant component appears around p = 1/n ≈ ${(1 / n).toFixed(3)}.`;
  } else if (model === "ba") {
    const m = sliderValue("m");
    edges = m * (n - m);
  } else {
    edges = (n * sliderValue("k")) / 2;
  }
  const avgDegree = (2 * edges) / n;
  const over = edges > MAX_EDGES;
  budgetHint.textContent = over
    ? `About ${Math.round(edges).toLocaleString()} edges: over the ${MAX_EDGES.toLocaleString()} limit. Lower n or the other slider.`
    : `About ${Math.round(edges).toLocaleString()} edges, average degree ${avgDegree.toFixed(1)}.${extra}`;
  budgetHint.classList.toggle("is-error", over);
}

// Each slider has an <output data-value-for="its id"> showing its value.
function showSliderValue(slider) {
  const output = view.querySelector(`[data-value-for="${slider.id}"]`);
  output.textContent = slider.step.includes(".") ? Number(slider.value).toFixed(slider.step.split(".")[1].length) : slider.value;
}


// ============================================================
// 4. Reacting to the user
// ============================================================
modelButtons.forEach((button) => button.addEventListener("click", () => {
  selectModel(button.dataset.model);
  generate();
}));

sliders.forEach((slider) => slider.addEventListener("input", () => {   // "input" fires while dragging
  showSliderValue(slider);
  updateBudgetHint();
}));

generateButton.addEventListener("click", () => generate());

layoutButtons.forEach((button) => button.addEventListener("click", () => runLayout(button.dataset.labLayout)));

fitButton.addEventListener("click", () => {
  if (cy) cy.animate({ fit: { eles: cy.elements(), padding: 30 } }, { duration: 400 });
});

logToggle.addEventListener("change", () => {
  if (lastData) drawChart(lastData.degree_distribution);
});

function selectModel(name) {
  model = name;
  modelButtons.forEach((b) => b.classList.toggle("is-active", b.dataset.model === name));
  // data-for="er ws" means "show this slider for ER and WS".
  paramRows.forEach((row) => { row.hidden = !row.dataset.for.split(" ").includes(name); });
  lookForBlocks.forEach((block) => { block.hidden = block.dataset.lookFor !== name; });
  // Watts–Strogatz is easiest to understand as a ring; the others as clusters.
  setLayout(name === "ws" ? "circle" : "force");
  updateBudgetHint();
}


// ============================================================
// 5. Generating
// ============================================================
async function generate() {
  // Clicking two models quickly starts two requests; if the first answers last
  // it must not overwrite the second. Only the latest request may draw.
  const requestId = ++latestRequest;
  setBusy(true);
  try {
    // URLSearchParams turns {model: "ba", n: 200} into "model=ba&n=200".
    const query = new URLSearchParams(currentParams()).toString();
    const data = await fetchJson(`/api/generate?${query}`);
    if (requestId !== latestRequest) return;
    lastData = data;
    drawGraph(data);
    showStats(data.summary);
    drawChart(data.degree_distribution);
    showStatus(`Seed ${data.summary.seed}. Type it in the seed box to get this exact graph again.`);
    updateAddressBar();
  } catch (error) {
    if (requestId === latestRequest) showStatus(error.message, true);
  } finally {
    if (requestId === latestRequest) setBusy(false);
  }
}

function setBusy(busy) {
  generateButton.disabled = busy;
  generateButton.textContent = busy ? "Generating…" : "Generate";
  loadingOverlay.hidden = !busy;
}

function showStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.classList.toggle("is-error", isError);
}


// ============================================================
// 6. Drawing the graph
// ============================================================
const LAB_STYLE = [
  {
    selector: "node",
    style: {
      width: "data(size)",
      height: "data(size)",
      "background-color": "data(color)",
      "border-width": 1,
      "border-color": "#ffffff",
      label: "",
      ...NODE_LABEL_STYLE,
      "font-size": 10,
    },
  },
  { selector: "node.highlighted", style: { label: "data(label)" } },
  {
    // "haystack" edges are straight lines drawn in bulk: much faster than curves
    // when there are thousands of them. No arrows: these graphs are undirected.
    selector: "edge",
    style: { width: 1, "line-color": EDGE_COLOR, opacity: 0.45, "curve-style": "haystack" },
  },
  { selector: "edge.highlighted", style: { "line-color": EDGE_FOCUS_COLOR, opacity: 0.9, width: 1.5 } },
  { selector: "node.faded", style: { opacity: 0.12 } },
  { selector: "edge.faded", style: { opacity: 0.04 } },
];

const LAB_LAYOUTS = {
  force: () => ({
    name: "fcose",
    randomize: true,
    nodeRepulsion: () => 4500,
    idealEdgeLength: () => 45,
    nodeSeparation: 40,
  }),
  // Nodes in creation order around the circle (0, 1, 2, ...). Sorted collection
  // passed in, because Cytoscape 3.34's circle layout ignores its sort option.
  circle: () => ({
    name: "circle",
    eles: cy.nodes().sort((a, b) => Number(a.id()) - Number(b.id())),
  }),
};

function drawGraph(data) {
  // Size = degree (how many connections), square-root scaled; colour = community.
  sizeAndColor(data.nodes, (d) => d.degree, 6, 34);

  if (cy) cy.destroy();
  cy = cytoscape({
    container: document.getElementById("lab-graph"),
    elements: { nodes: data.nodes, edges: data.edges },
    style: LAB_STYLE,
    minZoom: 0.05,
    maxZoom: 4,
    autounselectify: true,
    boxSelectionEnabled: false,
  });

  cy.on("mouseover", "node", (event) => {
    focusNeighbourhood(cy, event.target);
    showNodeInfo(event.target);
    cy.container().style.cursor = "pointer";
  });
  cy.on("mouseout", "node", () => {
    focusNeighbourhood(cy, null);
    cy.container().style.cursor = "";
  });

  // First placement without animation: sliding up to 500 nodes out of one
  // pile at (0, 0) adds nothing. Switching layouts later does animate.
  runLayout(layout, false);
}

function setLayout(name) {
  layout = name;
  layoutButtons.forEach((b) => b.classList.toggle("is-active", b.dataset.labLayout === name));
}

function runLayout(name, animate = true) {
  setLayout(name);
  if (!cy) return;
  cy.layout({ ...LAB_LAYOUTS[name](), animate, animationDuration: 600, padding: 30 }).run();
  updateAddressBar();
}

function showNodeInfo(node) {
  const d = node.data();
  const community = d.community === null ? "no community" : `community #${d.community + 1}`;
  nodeInfo.textContent = `Node ${d.id}: ${d.degree} connections · clustering ${d.clustering.toFixed(2)} · ${community}`;
  nodeInfo.hidden = false;
}


// ============================================================
// 7. Statistics and the degree-distribution chart
// ============================================================
function showStats(summary) {
  const format = {
    num_nodes: (s) => s.num_nodes,
    num_edges: (s) => s.num_edges.toLocaleString(),
    avg_degree: (s) => s.avg_degree.toFixed(2),
    max_degree: (s) => s.max_degree,
    avg_clustering: (s) => s.avg_clustering.toFixed(3),
    avg_path_length: (s) => (s.avg_path_length === null ? "–" : s.avg_path_length.toFixed(2)),
    num_components: (s) => `${s.num_components} (giant ${s.giant_component_size})`,
    num_communities: (s) => `${s.num_communities} (Q ${s.modularity.toFixed(2)})`,
  };
  view.querySelectorAll("[data-lab-stat]").forEach((dd) => {
    dd.textContent = format[dd.dataset.labStat](summary);
  });
}

/*
 * Two views of the same numbers:
 *  - bars (default): how many nodes have 0, 1, 2, ... connections;
 *  - log–log points: both axes on a log scale. A power law (count ∝ degree^-γ)
 *    becomes a straight line, which is how scale-free networks are spotted.
 */
function drawChart(dist) {
  if (chart) chart.destroy();      // Chart.js needs the old chart removed first

  const axis = (title, type) => ({
    type,
    title: { display: true, text: title },
    grid: { color: GRID_COLOR },
  });
  const options = (xType, yType) => ({
    responsive: true,
    maintainAspectRatio: false,    // fill the fixed-height box in the card
    animation: { duration: 300 },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => `Degree ${items[0].raw.x ?? items[0].label}`,
          label: (item) => `${item.raw.y ?? item.raw} nodes`,
        },
      },
    },
    scales: { x: axis("Degree (connections)", xType), y: axis("Number of nodes", yType) },
  });

  if (logToggle.checked) {
    // log(0) is undefined, so leave out degree 0 and empty bars.
    const points = dist.degree
      .map((degree, i) => ({ x: degree, y: dist.count[i] }))
      .filter((p) => p.x > 0 && p.y > 0);
    chart = new Chart(chartCanvas, {
      type: "scatter",
      data: { datasets: [{ data: points, backgroundColor: ACCENT_COLOR, pointRadius: 3.5 }] },
      options: options("logarithmic", "logarithmic"),
    });
  } else {
    const barOptions = options("category", "linear");
    barOptions.scales.x.grid.display = false;   // vertical grid lines just clutter bars
    chart = new Chart(chartCanvas, {
      type: "bar",
      data: {
        labels: dist.degree,
        datasets: [{ data: dist.count, backgroundColor: ACCENT_COLOR, borderRadius: 2,
                     barPercentage: 1, categoryPercentage: 0.9 }],
      },
      options: barOptions,
    });
  }
}


// ============================================================
// 8. Shareable links: /?lab=ba&n=200&m=2&seed=123&layout=force
// ============================================================
function updateAddressBar() {
  if (view.hidden || !lastData) return;
  const s = lastData.summary;
  const params = new URLSearchParams({ lab: s.model, n: s.n });
  if (s.p !== null) params.set("p", s.p);
  if (s.m !== null) params.set("m", s.m);
  if (s.k !== null) params.set("k", s.k);
  params.set("seed", s.seed);
  params.set("layout", layout);
  history.replaceState(null, "", `?${params}`);
}

// Copy a link's parameters into the controls (used once, when the tab opens).
function applyLinkParams() {
  const link = new URLSearchParams(window.location.search);
  const linkModel = link.get("lab");
  if (!["er", "ba", "ws"].includes(linkModel)) return;
  selectModel(linkModel);
  const set = (name, value) => {
    if (value === null) return;
    const slider = document.getElementById(`lab-${name}`);
    slider.value = value;
    showSliderValue(slider);
  };
  set("n", link.get("n"));
  if (linkModel === "er") set("p", link.get("p"));
  if (linkModel === "ba") set("m", link.get("m"));
  if (linkModel === "ws") { set("k", link.get("k")); set("rewire", link.get("p")); }
  if (link.get("seed")) seedInput.value = link.get("seed");
  if (link.get("layout") in LAB_LAYOUTS) setLayout(link.get("layout"));
  updateBudgetHint();
}


// ============================================================
// 9. What app.js (the tab switcher) can use
// ============================================================
export function showLab() {
  if (!started) {
    // First visit: set up the controls and draw a graph straight away, so the
    // tab never opens on an empty canvas.
    started = true;
    sliders.forEach(showSliderValue);
    selectModel(model);
    applyLinkParams();
    generate();
    return;
  }
  if (cy) cy.resize();   // a hidden graph doesn't notice size changes
  updateAddressBar();
}

export function getLabGraph() {
  return cy;
}
