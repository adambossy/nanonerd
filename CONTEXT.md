# Nanonerd

A tool for recursively generating learning curricula from a seed concept and visualizing mastery of them as a nested grid.

## Language

### Curriculum structure

**Subject**:
The seed concept an atlas is built from (e.g., "Large Language Models"). The root of the curriculum tree.
_Avoid_: Concept, seed, root topic

**Area**:
A top-level division of a Subject (~16–20 per subject). Level 1 of the tree.
_Avoid_: Category, domain, section

**Topic**:
A division of an Area. Level 2 of the tree.
_Avoid_: Subtopic, sub-area

**Leaf**:
A node with no generated children yet — the current frontier of the curriculum. Leaf status is relative: fragmenting a leaf turns it into an interior node.
_Avoid_: Leaf skill, skill, item

**Fragmentation**:
Generating a child curriculum for a node — the recursive step that adds a level of depth beneath it.
_Avoid_: Expansion, drilling down (that's zooming, a view action)

### Mastery

**Quiz**:
The set of Questions generated for a frontier node, graded against its Rubric.

**Question**:
The atomic unit of mastery — one prompt answered against the rubric, scored and colorized like any other node. Every color above a question is a rollup of questions.
_Avoid_: Item, exercise

**Rubric**:
The grading criteria generated alongside a node's quiz that define what mastery of it means.

**Score**:
The 0–100 result of a leaf's most recent quiz. Absent until first attempt.
_Avoid_: Grade, mastery level

**Band**:
The discrete classification of a score that determines a cell's color: Mastered (90–100), Solid (75–89), Partial (60–74), Failed (40–59), Failed badly (0–39), Not attempted.
_Avoid_: Status, state, color

**Rollup**:
A node's aggregate mastery, computed over all descendant leaves with unattempted leaves counting as zero — so it can only reach 100% by covering everything.
_Avoid_: Average, progress, completion

### Atlas (the visualization)

**Atlas**:
The whole mastery visualization for one Subject. The goal is to color it green.
_Avoid_: Grid (ambiguous), dashboard, map

**Tile**:
The rendered card for one node at the current zoom level — titled, showing its rollup, clickable to zoom.
_Avoid_: Card, square, box

**Mosaic**:
The nested grid inside an Area tile that shows its entire subtree at once — Blocks of Cells.
_Avoid_: Heatmap, minimap

**Block**:
One Topic's rectangular region inside a Mosaic, containing that topic's cells.
_Avoid_: Sub-grid, group, cluster

**Cell**:
The smallest square — one Leaf, filled with its Band's color. At the top level a deep cell may be only a few pixels.
_Avoid_: Pixel, square, dot

**Layout**:
A node's grid geometry — columns, rows, and spans for its children — owned by the node itself and reused at every zoom level, so a tile keeps its exact shape when blown up.
_Avoid_: Arrangement, view config

**Lattice**:
The shared unit grid a mosaic's cells sit on when quantized: every Leaf is exactly one lattice cell, so all seams align and a region's cell count is its size.
_Avoid_: Unit grid, quantum grid

**Level**:
A zoom stop the view snaps to — Subject fitted, one Topic fitted, or one Leaf fitted. Smooth zooming settles onto the nearest Level.
_Avoid_: Depth (that's tree distance, not a view stop)

**Zoom**:
Changing the focus node to view one level in more detail (in) or less (out). Purely a view action; it never changes the tree.
_Avoid_: Drill-down, navigate

**Focus**:
The node whose children the Atlas is currently displaying, identified by the breadcrumb path from the Subject.
_Avoid_: Current level, selection
