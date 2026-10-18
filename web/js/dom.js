// DOM building. Every text value becomes a text node, so API text can never be parsed as HTML.

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * h("button", { class: "btn", onclick: fn, "aria-label": "Close" }, "text", node, [nodes], null)
 * Attributes: null/undefined/false are skipped (aria-* keep "false"); on* functions become listeners;
 * class takes a string or an array (falsy entries dropped); style takes an object of CSS properties
 * ("left", "--w"); dataset takes an object.
 */
export function h(tag, attrs, ...children) {
  return build(document.createElement(tag), attrs, children);
}

/** The same as h() for SVG elements. */
export function s(tag, attrs, ...children) {
  return build(document.createElementNS(SVG_NS, tag), attrs, children);
}

function build(el, attrs, children) {
  for (const [key, value] of Object.entries(attrs ?? {})) setAttr(el, key, value);
  append(el, children);
  return el;
}

function setAttr(el, key, value) {
  if (value == null || (value === false && !key.startsWith("aria-"))) return;
  if (key.startsWith("on") && typeof value === "function") {
    el.addEventListener(key.slice(2), value);
  } else if (key === "class") {
    el.setAttribute("class", Array.isArray(value) ? value.filter(Boolean).join(" ") : value);
  } else if (key === "style" && typeof value === "object") {
    for (const [prop, v] of Object.entries(value)) el.style.setProperty(prop, String(v));
  } else if (key === "dataset") {
    Object.assign(el.dataset, value);
  } else {
    el.setAttribute(key, value === true ? "" : String(value));
  }
}

/** Appends children (nested arrays allowed); strings and numbers become text nodes. */
export function append(el, children) {
  for (const child of [children].flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

/** Replaces all children of el. */
export function mount(el, ...children) {
  el.replaceChildren();
  return append(el, children);
}

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
