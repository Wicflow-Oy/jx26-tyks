// Fetch wrapper for the backend. Every request carries the demo session header, the UI language (?lang=) and the
// global as-of Sunday (?as_of=); GET responses are shared and cached per URL (one week's data does not change);
// a write clears that cache and tells onWrite() listeners (the sidebar, the brief). Failures become ApiError
// subclasses whose message is a friendly sentence.

import { getLang, t } from "./i18n.js";
import { getState } from "./state.js";

const BASE = new URL("./", document.baseURI);
const SESSION_HEADER = "X-Demo-Session";
const SESSION_KEY = "demo-session";
const TIMEOUT_MS = 30_000;
const CACHE_LIMIT = 80;

export class ApiError extends Error {
  /** kind: network | timeout | rate_limited | write_limit | not_found | bad_request | unavailable | server */
  constructor(kind, { status = 0, detail = "" } = {}) {
    super(t(`shell.error.${kind}`));
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

export class NetworkError extends ApiError {}

export class RateLimitError extends ApiError {
  constructor(retryAfterSeconds, options) {
    super("rate_limited", options);
    this.retryAfter = retryAfterSeconds;
  }
}

export const isAbort = (error) => error?.name === "AbortError";

const cache = new Map();
const writeListeners = new Set();
let pausedUntil = 0; // after a 429, requests wait out Retry-After instead of hitting the server again
let memorySession = "";

/**
 * GET JSON: get("/api/brief", {}, { signal }) → /api/brief?as_of=<global as-of>&lang=<ui language>.
 * params: query values (null and "" are dropped; an explicit as_of wins). Options: signal (AbortSignal; aborting
 * stops waiting, the shared request still completes), asOf / lang (false for endpoints without a week or text,
 * like /api/meta), fresh (true skips the cache).
 */
export function get(path, params = {}, { signal, asOf = true, lang = true, fresh = false } = {}) {
  const url = urlFor(path, {
    ...(asOf && { as_of: getState().asOf }),
    ...params,
    ...(lang && { lang: getLang() }),
  });
  if (fresh || !cache.has(url)) {
    const request = send(url, { method: "GET" });
    request.catch(() => cache.get(url) === request && cache.delete(url));
    cache.set(url, request);
    if (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value);
  }
  return untilAborted(cache.get(url), signal);
}

/**
 * POST JSON. A write (approve, draft) clears the GET cache, because it changes what the brief, the case file and
 * the sidebar show, then runs the onWrite() listeners. keepCache: true for a POST that changes nothing a GET
 * returns (the order context, a feedback log).
 */
export async function post(path, body, { signal, keepCache = false } = {}) {
  const result = await untilAborted(
    send(urlFor(path, { lang: getLang() }), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    }),
    signal,
  );
  if (!keepCache) {
    cache.clear();
    for (const fn of writeListeners) fn();
  }
  return result;
}

/** fn() runs after every successful write. Returns an unsubscribe function. */
export function onWrite(fn) {
  writeListeners.add(fn);
  return () => writeListeners.delete(fn);
}

function urlFor(path, params) {
  const url = new URL(path.replace(/^\//, ""), BASE);
  for (const [key, value] of Object.entries(params)) {
    if (value != null && value !== "") url.searchParams.set(key, value);
  }
  return url.href;
}

async function send(url, init) {
  if (Date.now() < pausedUntil) throw new RateLimitError(Math.ceil((pausedUntil - Date.now()) / 1000));
  let response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { ...init.headers, Accept: "application/json", [SESSION_HEADER]: sessionId() },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    throw new NetworkError(error?.name === "TimeoutError" ? "timeout" : "network");
  }
  if (response.ok) return response.json();

  const body = await response.json().catch(() => ({}));
  const detail = typeof body.message === "string" ? body.message : "";
  const retryAfter = Number(response.headers.get("Retry-After"));
  if (response.status === 429 && body.error !== "write_limit") {
    pausedUntil = Date.now() + (retryAfter || 60) * 1000;
    throw new RateLimitError(retryAfter || 60, { status: 429, detail });
  }
  throw new ApiError(kindOf(response.status, body.error), { status: response.status, detail });
}

function kindOf(status, code) {
  if (code === "write_limit") return "write_limit";
  if (status === 404) return "not_found";
  if (status === 503) return "unavailable";
  if (status >= 400 && status < 500) return "bad_request";
  return "server";
}

function untilAborted(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(signal.reason);
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

/** A random id per browser tab, so approvals and drafts stay in this demo session (CONTRACTS §10). */
function sessionId() {
  try {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = randomId();
      sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    memorySession ||= randomId();
    return memorySession;
  }
}

function randomId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
