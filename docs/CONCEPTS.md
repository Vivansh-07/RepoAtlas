# Graph visualization concepts in RepoAtlas

This document maps the graph-visualization ideas behind RepoAtlas to where they appear in the tool, why each design choice was made, and what it revealed on real repositories. It doubles as notes for a course report (Graph Visualization, DSE3151).

Measured numbers come from RepoAtlas runs on pallets/flask (`d73fa1c`), psf/requests (`611c616`), pallets/click (`2247b35`) and encode/httpx (`b5addb6`).

---

## 1. The data as a graph

A repository becomes a **directed, weighted, attributed graph** G = (V, E):

- **V**: one node per Python module (one `.py` file; a package's `__init__.py` is the package node).
- **E**: an edge **A → B** means *module A imports module B*. The edge weight is the number of import statements behind it.
- **Node attributes:** path, lines of code, PageRank, community, cycle group (SCC id), parse error, internal/stdlib/third-party.
- **Edge attributes:** weight, kind (internal/external), `type_only` (inside `if TYPE_CHECKING:`), `in_cycle`.

**Why this edge direction.** Arrows point from the dependent module to its dependency, so importance flows *towards* the modules everything relies on. PageRank then ranks foundations highly without any extra work.

**Three derived graphs** do the analytical work:
- the **analysis view**: repo modules only, runtime imports only (no type-only edges, no external libraries)
- the **condensation**: every strongly connected component collapsed into one node, which makes the graph acyclic (section 7)
- the **package graph**: every package collapsed into one node, which can still contain cycles: cycles *between packages* (section 7.1)

---

## 2. Visual encoding: marks and channels

Each data attribute gets exactly one visual channel, chosen by the type of data (categorical or quantitative) and by how accurately people perceive that channel (Mackinlay 1986).

| Attribute | Type | Channel | Reasoning |
|---|---|---|---|
| Importance (PageRank) | Quantitative | **Node size** | Circle **area** ∝ value (diameter ∝ √value), because viewers judge circles by area (Stevens' power law). Linear diameter would exaggerate the top module. |
| Community | Categorical | **Hue** | 12 distinct mid-tone hues that are readable on white. Hue is the strongest channel for categories. |
| In a circular dependency | Categorical (flag) | **Red border + red halo + red edges** | Red is *reserved* for cycles and used nowhere else, so cycles pop out pre-attentively. |
| Isolated / external | Categorical | **Grey** (dashed outline for external) | Grey is reserved for "not part of the repo's connected structure". |
| Import statements (weight) | Quantitative | **Edge width** | Thicker = more statements = harder to remove. |
| Type-only import | Categorical | **Dashed line** | Visible but visually weaker: it never runs. |
| Graph Lab: degree | Quantitative | Node size | Degree is the quantity the random-graph models are about. |
| Graph Lab: Watts–Strogatz shortcut | Categorical | **Accent (violet) edge colour** | The rewired shortcuts are the point of the model, so they must stand out. |

**Expressiveness.** Every encoding shows exactly the data and nothing more. Colour never carries both meaning and decoration: the palette contains no reds (red means cycle) and no greys (grey means isolated or external).

---

## 3. Layout algorithms

The same graph can be drawn four ways. Each layout makes a different question easy to answer.

### 3.1 Force-directed (fCoSE): "what belongs together?"
A spring-electrical model: edges act as springs, nodes repel each other, and the system relaxes towards low energy (Fruchterman & Reingold 1991; fCoSE: Balci & Dogrusoz 2022). Densely connected modules settle into visible clusters, which match the Louvain colours because both reflect the same edge density.
*Strengths:* reveals clusters, hubs and outliers. *Weaknesses:* it ignores edge direction and isn't deterministic, so read neighbourhoods, not exact positions.

### 3.2 Layered (simplified Sugiyama): "what builds on what?"
Dependency graphs have a meaningful direction, so a layered drawing in which arrows point one way is the natural choice. RepoAtlas implements its own simplified version of the Sugiyama framework (Sugiyama, Tagawa & Toda 1981):

| Sugiyama step | Classic approach | RepoAtlas |
|---|---|---|
| 1. Make the graph acyclic | Reverse a feedback set of edges | **Collapse each SCC** into one unit (the condensation). Nothing is reversed, and each cycle group shares one row. |
| 2. Layer assignment | Longest path / network simplex | **Longest path**: foundations (no internal imports) on layer 0 at the bottom; each module one layer above its deepest dependency |
| 3. Crossing reduction | Barycenter / median heuristics | **Order each layer by community** (a cheap heuristic: related modules sit together) |
| 4. Coordinate assignment | Priority / brick layout | **Wrap long layers** into rows of about 1.6√n, so the drawing stays roughly square |

*Why not Cytoscape's built-in breadth-first layout?* It put all ~60 modules that nothing imports (mostly tests) on one row, an unreadable strip. Longest-path layering spreads them over the levels where they belong.

### 3.3 Concentric by PageRank: "where is the core?"
A radial layout with the most important modules at the centre. It turns the ranking into geometry, so the core is the middle of the picture.

### 3.4 Circular, ordered by community: "how big is each cluster?"
Each community becomes one arc, so arc length shows cluster size and chords across the middle show imports between communities. In the Graph Lab, a circle in node-creation order shows the Watts–Strogatz ring lattice directly, with its shortcuts as chords.

**Aesthetic criteria considered:** fewer edge crossings (community ordering), aspect ratio (row wrapping), consistent edge direction (layered), symmetry (circle and rings).

---

## 4. The hairball problem and how RepoAtlas fights it

Real repositories give 35–150 nodes and 100–450 edges, enough to produce a "hairball". RepoAtlas combines several mitigations:

| Technique | Implementation |
|---|---|
| **Filtering** | External libraries hidden by default (Flask: 146 → 82 nodes); type-only imports toggle; "only circular dependencies" (Flask: 82 → 13 nodes) |
| **Focus + context** | Hovering keeps a module's closed neighbourhood sharp and fades everything else to 12% opacity |
| **Label culling** | The 8 highest-PageRank modules ("landmarks") are always named; any other node only once it is ≥ 30 px on screen, recomputed on zoom. Graphs of at most 25 nodes name everything. |
| **Aggregation** | **Package view**: modules collapsed into packages (Flask: 82 → 20 nodes, 162 → 24 edges; section 7.1). Cycle groups are also collapsed into one layer unit in the layered layout. |
| **Semantic layouts** | Layered and concentric layouts give positions a meaning, so the eye knows where to look |
| **Search** | Type part of a name and the camera flies to the best match |

### Shneiderman's Visual Information-Seeking Mantra
"Overview first, zoom and filter, then details on demand" (Shneiderman 1996), and his seven tasks:

| Task | RepoAtlas |
|---|---|
| **Overview** | Fit-to-screen graph, summary panel, top-10 list; the package view as an overview of the architecture |
| **Zoom** | Mouse-wheel zoom with progressive labels; search flies to a module; drill down from a package to its modules |
| **Filter** | Show options (external, type-only, cycles only) |
| **Details on demand** | Click a module: path, lines, rank, community |
| **Relate** | Details card lists *imports* and *imported by*; click to follow |
| **History** | Shareable links reproduce repository, layout and filters |
| **Extract** | PNG export of the current view |

---

## 5. Centrality: PageRank

PageRank (Page et al. 1999) models a random walker who follows edges and occasionally jumps to a random node (damping 0.85). A node's score is the share of time the walker spends there, so a module is important when **important modules import it**. That is more informative than raw in-degree, which treats an import from a throwaway test the same as one from the core.

**Observed:** requests' #1 module is `requests.compat` (PageRank 0.187, 14 importers), a legacy Python 2/3 shim that became load-bearing. Flask's top modules after the package itself are the tiny `globals` (56 lines) and `signals` (13 lines): foundations, not big files.

**Critical observations** (useful for evaluating the visualization):
- **Cycles inflate PageRank.** `click._winconsole` ranks #2 with a single importer, because rank keeps circulating inside its 2-module cycle with #1 (`click._compat`).
- **Tests skew the ranking** towards the package `__init__` they import.
- **Type-only imports are excluded.** `flask.app` (1,238 lines, the largest file) ranks only #27, because five of its six importers use it only for type hints.

---

## 6. Community detection: Louvain and modularity

**Modularity** compares the share of edges inside communities with the share expected in a random graph with the same degrees (Newman 2006):

Q = (1 / 2m) Σᵢⱼ [Aᵢⱼ − kᵢkⱼ / 2m] δ(cᵢ, cⱼ)

**Louvain** (Blondel et al. 2008) maximises Q greedily. It moves single nodes between communities while Q improves, then collapses each community into a single node and repeats. It runs on the undirected version of the graph (clustering doesn't depend on who imports whom) with a fixed seed, so the colours are reproducible. Modules with no internal edges are left out, so they don't each become a one-member community.

**Observed:** Q = 0.37 for Flask and httpx (clearly separated subsystems), 0.30 for click, and 0.21 for requests: a small library whose modules all share the same helpers. Values above about 0.3 usually indicate real modular structure.

---

## 7. Strongly connected components and condensation

A **strongly connected component** (SCC) is a maximal set of nodes that can all reach each other along directed edges. Every SCC with two or more modules is a **circular dependency group**. SCCs are found in linear time, O(V + E) (Tarjan 1972). Listing every individual cycle can take exponential time, and answers a less useful question.

Collapsing each SCC into one node gives the **condensation**, which is always a DAG. RepoAtlas uses it three times:
1. **Cycle highlighting**: red nodes and red edges are those inside an SCC.
2. **Dependency depth** = longest path in the condensation (Flask 9, requests 10, click 6, httpx 11).
3. **Layer assignment** in the layered layout (section 3.2).

**Observed:**
- Flask's core is one 11-module SCC, kept working at runtime by imports deferred into functions.
- click has a 7-module core SCC.
- requests has none.

**A key finding.** Counting `if TYPE_CHECKING:` imports as normal edges inflated the cycles dramatically: Flask [20, 2] → [11, 2], requests [8] → none, httpx [11, 6] → [2]. Type-only imports never run, so they can't create a circular-import problem. They are therefore drawn dashed and excluded from all analytics.

### 7.1 Quotient graphs: the package view

Given a partition of the nodes into blocks, the **quotient graph** has one node per block and an edge from block P to block Q whenever some edge goes from a node in P to a node in Q. The condensation is the quotient under the "same SCC" partition. The package view is the quotient under the **"same package"** partition: a package is a folder, so modules are grouped by folder. Edge weights add up, and an edge is type-only only if every import behind it is.

The same analytics then run on the smaller graph: PageRank, Louvain, SCCs and depth. Two properties make package cycles worth computing separately:
- **A cycle inside one package disappears.** Its modules become one node. In the test fixture, the `orders ↔ payments` cycle lives inside `shop`, so the package graph has no cycle.
- **A cycle between packages can appear without any cycle between modules.** For example, `a.x → b.y` and `b.z → a.w`: no module reaches itself, but packages `a` and `b` depend on each other. (A module cycle that crosses packages always shows up as a package cycle.)

**Why it matters.** Packages are the units people own, test and release. The *Acyclic Dependencies Principle* (Martin 2002) says the package graph should be a DAG: packages in a loop can only be understood, changed or released together.

**Observed:**
- Flask: 82 modules → 20 packages. One package cycle remains: `flask` ↔ `flask.json` ↔ `flask.sansio`.
- httpx: 60 → 5 packages, with `httpx` ↔ `httpx._transports`.
- requests (35 → 4) and click (90 → 17) have no package cycles.

**Why a separate graph rather than compound nodes.** Cytoscape can draw modules inside package boxes ("compound nodes"). That shows the same grouping, but it has three drawbacks:
- it gives no package-level analytics
- it stays as crowded as the module graph
- the layered, concentric and circle layouts don't support parent boxes

The quotient graph is computed once on the server, cached with the module graph, and drawn with the same code.

---

## 8. Random graph models (Graph Lab)

The Graph Lab generates the three classic models and measures them, so their defining properties can be *seen* and compared.

| Model | Construction | Degree distribution | Signature property |
|---|---|---|---|
| **Erdős–Rényi** G(n, p) (1959) | Each pair linked independently with probability p | Binomial ≈ Poisson(λ = (n−1)p): a hump, no hubs | **Phase transition:** a giant component appears when λ > 1 (p > 1/n); clustering ≈ p |
| **Barabási–Albert** (n, m) (1999) | Growth + preferential attachment: each new node links to m nodes, preferring high degree | Power law P(k) ∝ k⁻³: heavy tail, hubs | **Scale-free:** a straight line on a log–log plot |
| **Watts–Strogatz** (n, k, p) (1998) | Ring lattice (k nearest neighbours) with each edge rewired with probability p | Narrow, centred on k | **Small world:** high clustering and short paths at small p |

**Measured in RepoAtlas** (n = 500, seed 1):
- ER with p = 0.008 (average degree ≈ 4.2): max degree **12**, clustering **0.010**, average path 4.46, 8 components.
- BA with m = 2 (average degree ≈ 4.0): max degree **58**, a single component, average path 3.79. These are hubs: 15× the average.
- WS with k = 6, p = 0.05: clustering **0.51** (≈ 50× ER), average path 6.61. That is a small world. With n = 120, the 19 rewired edges (expected 0.05 × 360 = 18) are drawn as violet chords.

**Theory checked by automated tests:**
- a ring lattice (p = 0) has clustering exactly 3(k−2)/(4(k−1)) = 0.5 for k = 4
- rewiring 10% of edges more than halves the average path length while keeping over half the clustering
- BA max degree > 5× average while ER < 4×
- exact edge counts m(n−m) and nk/2

**Link to real software:** the repositories above also have heavy-tailed degree distributions: a few foundation modules are imported by dozens, while most modules are imported by few. Scale-free structure is a known property of software dependency networks.

---

## 9. Interaction techniques summary

| Technique | Where |
|---|---|
| Animated layout transitions (600 ms) | Switching layouts, so the viewer can track nodes between arrangements |
| Brushing / highlighting | Hover: neighbourhood highlighted, rest faded |
| Selection + linked views | Click a module: the details card and the graph stay in sync; click a neighbour in the card to move there |
| Dynamic queries | Show options re-filter instantly in the browser |
| Semantic zoom (labels) | Labels appear as nodes grow on screen |
| Drill-down between levels | Package view ↔ module view: a package's card lists its modules (click to drill down); a module's card links up to its package |
| Camera animation | Search and the top-modules list fly to the module |

---

## 10. Limitations of the visual analysis

- **Static analysis:** dynamic imports aren't seen, and conditional imports count even if they only run on one platform (click's `_compat ↔ _winconsole` cycle exists only on Windows).
- **Force layouts aren't deterministic.** Positions shouldn't be read as data.
- **Colours are labels.** Community 0 in two repositories are unrelated groups.
- **Scale.** Beyond a few hundred modules the module view gets crowded. The package view is the overview at that scale, but a very large package can still be a crowded drill-down.

---

## References

- Barabási, A.-L. & Albert, R. (1999). Emergence of scaling in random networks. *Science* 286.
- Balci, H. & Dogrusoz, U. (2022). fCoSE: A fast compound graph layout algorithm with constraint support. *IEEE TVCG* 28(12).
- Blondel, V. D., Guillaume, J.-L., Lambiotte, R. & Lefebvre, E. (2008). Fast unfolding of communities in large networks. *J. Stat. Mech.*
- Erdős, P. & Rényi, A. (1959). On random graphs I. *Publicationes Mathematicae*.
- Fruchterman, T. M. J. & Reingold, E. M. (1991). Graph drawing by force-directed placement. *Software: Practice and Experience* 21(11).
- Mackinlay, J. (1986). Automating the design of graphical presentations of relational information. *ACM Transactions on Graphics* 5(2).
- Martin, R. C. (2002). *Agile Software Development: Principles, Patterns, and Practices*. Prentice Hall. (Acyclic Dependencies Principle.)
- Newman, M. E. J. (2006). Modularity and community structure in networks. *PNAS* 103(23).
- Page, L., Brin, S., Motwani, R. & Winograd, T. (1999). The PageRank citation ranking: Bringing order to the web. Stanford InfoLab.
- Shneiderman, B. (1996). The eyes have it: A task by data type taxonomy for information visualizations. *IEEE Symposium on Visual Languages*.
- Sugiyama, K., Tagawa, S. & Toda, M. (1981). Methods for visual understanding of hierarchical system structures. *IEEE Trans. SMC* 11(2).
- Tarjan, R. (1972). Depth-first search and linear graph algorithms. *SIAM Journal on Computing* 1(2).
- Watts, D. J. & Strogatz, S. H. (1998). Collective dynamics of 'small-world' networks. *Nature* 393.
