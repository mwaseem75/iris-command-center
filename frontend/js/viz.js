// Shared, dependency-free visualization primitives for the design system:
// a CSS-only donut ring (conic-gradient) and a compact horizontal stacked
// bar. Both are used across Dashboard/Processes/Databases/Web Apps/Tasks/
// Operations/Observability/Investigation/API Explorer to visualize real
// distributions computed from data those views ALREADY fetch from existing
// `/api/iris/*` routes — this module fetches nothing itself.
//
// Nothing here invents, estimates, or randomizes a value: countBy() only
// ever counts real field values already present in an already-fetched
// response array, topCategories() only ever folds real counts into a real
// "Other" aggregate (never a guess), and an empty/zero input renders an
// explicit empty ring/bar, never a fabricated placeholder shape. There is
// no CPU/memory/trend/alert concept anywhere in this module — only counts,
// distributions, and durations of data the backend actually returned.

const PALETTE = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
  "var(--color-chart-6)",
];
const NEUTRAL_COLOR = "var(--color-chart-neutral)";

/**
 * Counts occurrences of `keyFn(item)` across `items`. Returns
 * `[{ key, count }]` sorted by count descending — every `key` is a real
 * value read directly from `items`, never invented.
 */
export function countBy(items, keyFn) {
  const counts = new Map();
  for (const item of items) {
    const key = keyFn(item);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count);
}

/**
 * Caps a countBy() result at `max` entries, folding the remainder into one
 * "Other" entry whose count is the real sum of the folded entries' real
 * counts (never an estimate) — keeps a high-cardinality real field (e.g.
 * free-text event types) from producing an unreadable legend.
 */
export function topCategories(counts, max = 6) {
  if (counts.length <= max) return counts;
  const head = counts.slice(0, max - 1);
  const tailTotal = counts.slice(max - 1).reduce((sum, c) => sum + c.count, 0);
  return [...head, { key: "Other", count: tailTotal }];
}

export function assignColors(entries) {
  return entries.map((entry, i) => ({
    ...entry,
    color: entry.key === "Other" ? NEUTRAL_COLOR : PALETTE[i % PALETTE.length],
  }));
}

function buildLegend(entries, formatLabel, formatValue) {
  const legend = document.createElement("div");
  legend.className = "viz-legend";
  for (const entry of entries) {
    const item = document.createElement("span");
    item.className = "viz-legend-item";
    const dot = document.createElement("span");
    dot.className = "viz-legend-dot";
    dot.style.background = entry.color;
    item.append(dot, document.createTextNode(`${formatLabel(entry)} · ${formatValue(entry)}`));
    legend.append(item);
  }
  return legend;
}

const defaultLabel = (entry) => String(entry.key);
const defaultValue = (entry) => String(entry.count);

/**
 * Renders a compact horizontal stacked bar into `container` (cleared
 * first, so this is safe to call again on refresh/refilter). `entries` is
 * countBy()/topCategories() output. `compact` omits the legend row (for
 * inline use inside a KPI stat card) — the real label/value are still
 * available via each segment's `title` tooltip. Returns nothing; renders
 * nothing (leaves `container` empty) when `entries` is empty, rather than
 * drawing a placeholder bar for data that doesn't exist.
 */
export function renderStackedBar(
  container,
  entries,
  { compact = false, formatLabel = defaultLabel, formatValue = defaultValue } = {},
) {
  container.replaceChildren();
  if (!Array.isArray(entries) || entries.length === 0) return;

  const colored = assignColors(entries);
  const total = colored.reduce((sum, e) => sum + e.count, 0);

  const wrapper = document.createElement("div");
  wrapper.className = "viz-bar";

  const track = document.createElement("div");
  track.className = compact ? "viz-bar-track viz-bar-track--compact" : "viz-bar-track";
  for (const entry of colored) {
    const segment = document.createElement("div");
    segment.className = "viz-bar-segment";
    segment.style.background = entry.color;
    // A tiny flex-grow floor keeps a real zero-count-adjacent sliver
    // visible; the tooltip/legend text always shows the true count.
    segment.style.flexGrow = String(Math.max(entry.count, total === 0 ? 1 : total * 0.01));
    segment.title = `${formatLabel(entry)} — ${formatValue(entry)}`;
    track.append(segment);
  }
  wrapper.append(track);

  if (!compact) {
    wrapper.append(buildLegend(colored, formatLabel, formatValue));
  }

  container.append(wrapper);
}

/**
 * Renders a CSS-only donut ring (a `conic-gradient` circle with a punched
 * hole, no SVG/canvas/charting library) plus a legend into `container`
 * (cleared first). `centerLabel`/`centerValue` are plain text placed in
 * the ring's hole — callers pass a real total (e.g. the real item count),
 * never a computed/derived metric IRIS doesn't provide. Renders nothing
 * when `entries` is empty.
 */
export function renderDonut(
  container,
  entries,
  { size = 96, centerLabel, centerValue, formatLabel = defaultLabel, formatValue = defaultValue } = {},
) {
  container.replaceChildren();
  if (!Array.isArray(entries) || entries.length === 0) return;

  const colored = assignColors(entries);
  const total = colored.reduce((sum, e) => sum + e.count, 0);

  const row = document.createElement("div");
  row.className = "viz-row";

  const donut = document.createElement("div");
  donut.className = "viz-donut";
  donut.style.width = `${size}px`;
  donut.style.height = `${size}px`;

  if (total === 0) {
    donut.style.background = "var(--color-border)";
  } else {
    let cursor = 0;
    const stops = colored.map((entry) => {
      const start = (cursor / total) * 360;
      cursor += entry.count;
      const end = (cursor / total) * 360;
      return `${entry.color} ${start}deg ${end}deg`;
    });
    donut.style.background = `conic-gradient(${stops.join(", ")})`;
  }

  const hole = document.createElement("div");
  hole.className = "viz-donut__hole";
  if (centerValue !== undefined && centerValue !== null) {
    const value = document.createElement("div");
    value.className = "viz-donut__center-value";
    value.textContent = String(centerValue);
    hole.append(value);
  }
  if (centerLabel) {
    const label = document.createElement("div");
    label.className = "viz-donut__center-label";
    label.textContent = centerLabel;
    hole.append(label);
  }
  donut.append(hole);

  row.append(donut, buildLegend(colored, formatLabel, formatValue));
  container.append(row);
}
