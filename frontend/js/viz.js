// Small chart helpers with no dependencies: a CSS donut (conic-gradient)
// and a horizontal stacked bar.
//
// They only draw data the pages already fetched; nothing is fetched here.
// Empty input draws an empty ring/bar.

const PALETTE = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
  "var(--color-chart-6)",
];
const NEUTRAL_COLOR = "var(--color-chart-neutral)";

/** Count `keyFn(item)` over `items`. Returns [{ key, count }], biggest first. */
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
 * Keep the top `max` entries and add the rest up into one "Other" entry,
 * so fields with lots of values still get a readable legend.
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
 * Draw a stacked bar into `container` (cleared first, so it's fine to call
 * again). `entries` comes from countBy()/topCategories(). `compact` hides
 * the legend (for use inside a KPI card); each segment still has a title
 * tooltip. Draws nothing if `entries` is empty.
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
    // A small minimum grow keeps tiny segments visible; the label still
    // shows the real count.
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
 * Draw a CSS donut plus legend into `container` (cleared first).
 * `centerLabel`/`centerValue` go in the hole, usually the total count.
 * Draws nothing if `entries` is empty.
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
