/*
 * Things both tabs (Repo Explorer and Graph Lab) share.
 *
 * This file is an ES module: anything marked `export` can be pulled into
 * another module with `import { name } from "./common.js"`. Nothing else in
 * here is visible outside the file, so modules can't trip over each other's
 * variables by accident.
 */

// Community colours from CLAUDE.md. No reds (red = cycle), no greys (grey = isolated).
export const COMMUNITY_COLORS = [
  "#7c3aed", "#0891b2", "#f59e0b", "#059669", "#2563eb", "#65a30d",
  "#ea580c", "#c026d3", "#0d9488", "#ca8a04", "#4f46e5", "#0284c7",
];
export const NO_COMMUNITY_COLOR = "#cbd5e1";
export const ACCENT_COLOR = "#6d28d9";
export const EDGE_COLOR = "#94a3b8";
export const EDGE_FOCUS_COLOR = "#475569";

// How node names look in both graphs: dark text with a white halo.
export const NODE_LABEL_STYLE = {
  "font-family": "Inter, system-ui, sans-serif",
  "font-size": 12,
  "font-weight": 500,
  color: "#0f172a",
  "text-valign": "bottom",
  "text-margin-y": 5,
  "text-outline-color": "#ffffff",
  "text-outline-width": 2.5,
};

/*
 * Give every node two display-only fields:
 *  - size: from `valueOf(node data)`, scaled between minSize and maxSize. We
 *    use the square root because people judge a circle by its AREA, and area
 *    grows with the square of the width: linear widths exaggerate the biggest.
 *  - color: from the Louvain community.
 */
export function sizeAndColor(nodes, valueOf, minSize, maxSize) {
  const values = nodes.map((node) => valueOf(node.data));
  const min = Math.min(...values);
  const max = Math.max(...values);
  for (const node of nodes) {
    const d = node.data;
    const t = max > min ? (valueOf(d) - min) / (max - min) : 0.5;   // 0 .. 1
    d.size = minSize + Math.sqrt(t) * (maxSize - minSize);
    d.color = d.community === null
      ? NO_COMMUNITY_COLOR
      : COMMUNITY_COLORS[d.community % COMMUNITY_COLORS.length];   // % wraps past 12
  }
}

/*
 * Focus + context: keep one node and its direct neighbours fully visible and
 * fade everything else. Passing node = null clears the focus.
 */
export function focusNeighbourhood(cy, node) {
  cy.batch(() => {               // batch = apply all class changes in a single redraw
    cy.elements().removeClass("faded highlighted");
    if (!node) return;
    // closedNeighborhood = the node + its edges + the nodes at their other ends
    const neighbourhood = node.closedNeighborhood();
    cy.elements().not(neighbourhood).addClass("faded");
    neighbourhood.addClass("highlighted");
  });
}

/*
 * Save what a Cytoscape graph currently shows as a PNG file.
 * cy.png() draws the graph into an image and returns it as a "data URL" (the
 * file's bytes written out as text). full: false = exactly the current view,
 * as on screen; scale: 2 = double resolution, so it stays sharp in a report.
 * A temporary <a download> link then makes the browser save it as a file.
 */
export function downloadPng(cy, filename) {
  const link = document.createElement("a");
  link.href = cy.png({ full: false, scale: 2, bg: "#ffffff" });
  link.download = filename;
  link.click();
}

/*
 * fetch() + JSON + friendly errors, used by both tabs.
 *
 * fetch() sends an HTTP request and returns a Promise: a placeholder for a value
 * that arrives later. `await` pauses *this function* until it arrives, while the
 * page stays responsive. Throws an Error whose message is safe to show the user.
 */
export async function fetchJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    // fetch itself only fails when the server can't be reached at all.
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

/*
 * Create an element with an optional class and text.
 * Text always goes in through textContent, never innerHTML: module names come
 * from someone else's repository, and innerHTML would run any HTML hidden in
 * them (an XSS attack). textContent always shows them as plain text.
 */
export function el(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}
