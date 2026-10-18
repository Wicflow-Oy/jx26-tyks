// The changed-number marker for numbers a view updates in place across a replay step (DESIGN §7): a yellow
// underline that fades over 1.2 s (.mk.marked in components.css; static under reduced motion). Numbers that are
// re-rendered with mk() are compared by main.js instead.

/**
 * markChanged(el, oldValue, newValue): underlines el when the value differs from last week's. The first render
 * (oldValue null or undefined) never marks. Returns true when it marked.
 */
export function markChanged(el, oldValue, newValue) {
  if (!el || oldValue == null || String(oldValue) === String(newValue)) return false;
  el.classList.add("mk");
  el.classList.remove("marked");
  void el.offsetWidth; // restarts the fade when the same element changes again within 1.2 s
  el.classList.add("marked");
  return true;
}
