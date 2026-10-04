/*
 * Entry point: loads both tabs and switches between them.
 *
 * index.html loads this with <script type="module">. Module scripts run after
 * the page is parsed (like `defer`), and `import` pulls in the other files:
 * importing a module runs its top-level code once, which wires up that tab.
 */

import { getExplorerGraph, showExplorer } from "./explorer.js";
import { getLabGraph, showLab } from "./lab.js";

const views = {
  explorer: { element: document.getElementById("explorer-view"), show: showExplorer },
  lab: { element: document.getElementById("lab-view"), show: showLab },
};
const tabs = document.querySelectorAll("[data-tab]");

function switchTab(name) {
  // Object.entries turns {explorer: ..., lab: ...} into [["explorer", ...], ["lab", ...]].
  for (const [key, view] of Object.entries(views)) {
    view.element.hidden = key !== name;
  }
  tabs.forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));   // tells screen readers which tab is open
  });
  views[name].show();
}

tabs.forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));

// A Graph Lab link (/?lab=ba&...) opens straight on the Graph Lab tab.
if (new URLSearchParams(window.location.search).has("lab")) switchTab("lab");

// Handy in the browser console: repoatlas.explorer() and repoatlas.lab() return
// the Cytoscape graph of each tab, to inspect nodes, zoom, positions...
window.repoatlas = { explorer: getExplorerGraph, lab: getLabGraph };
