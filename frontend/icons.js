/* The studio's icons: drawn on a 24-unit grid in one 1.5px stroke, never typed glyphs. */

const PATHS = {
  close: "M6 6l12 12M18 6L6 18",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  check: "M5 12.5l4.5 4.5L19 7.5",
  prev: "M14.5 6l-6 6 6 6",
  next: "M9.5 6l6 6-6 6",
  collapse: "M12 6l-6 6 6 6M18.5 6l-6 6 6 6",
  dash: "M7 12h10",
  download: "M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14",
};

export function icon(name, cls = "ico") {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", cls);
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", PATHS[name]);
  svg.append(p);
  return svg;
}

// The same, as markup, for the few places that build HTML strings.
export const iconHTML = (name, cls = "ico") =>
  `<svg viewBox="0 0 24 24" aria-hidden="true" class="${cls}"><path d="${PATHS[name]}"/></svg>`;
