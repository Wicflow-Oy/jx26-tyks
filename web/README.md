# web/

The UI: plain HTML, CSS and ES modules, served as static files by the FastAPI app at `/`. No build step, no
framework, no third-party requests. Design spec: `design/DESIGN.md`; API: `CONTRACTS.md`.

## How it fits together

- `index.html` loads the stylesheets and `js/main.js`.
- `js/main.js` boots (`GET /api/meta`), reads the URL into the one app state (`js/state.js`) and renders the page
  view for the route plus the pane view beside it. Every view is `render(root, ctx)`; the contract is at the top of
  `main.js`.
- Data: `js/api.js` (fetch, session header, cache), `js/signals.js` (the brief and signal titles), `js/alerts.js`
  (approved alerts, strict as-of), `js/names.js` (code → label).
- Text: `js/i18n.js` is the one hook, `t(key)`; the words live in `js/strings/<area>.js` as `{ en, fi }`.
  `js/text.js` adds sentences with bold numbers and plurals; `js/format.js` formats dates and shares.
- DOM: `js/dom.js` builds every node with `h()`, so API text is always a text node, never HTML.

## Files

| Folder               | What is in it                                                                                            |
| -------------------- | -------------------------------------------------------------------------------------------------------- |
| `js/`                | boot, state, API, shell (`shell.js`: toolbar, phone bar, tab bar) and sidebar (`sidebar.js`, `sidebar/`) |
| `js/components/`     | shared UI: buttons, badges, pane, sheet, menu, overlay stack (`layers.js`), states, charts               |
| `js/replay/`         | the week rail, its ticks, the phone replay sheet and Play                                                |
| `js/views/`          | one file per screen: `brief.js`, `case.js`, `ward.js`, `trend.js`, `order.js`, and the `tour.js`         |
| `js/views/<screen>/` | that screen's named parts                                                                                |
| `js/strings/`        | the words of each area                                                                                   |
| `css/`               | `tokens.css` (the only place colours, type, space and motion are defined), then one file per area        |

## Checks

```sh
npx --yes prettier@3 --config .prettierrc --check . && npx --yes eslint@9 --config eslint.config.js .
cd .. && .venv/bin/python -m pytest -q tests/test_ui.py   # Playwright click-through against the app
```
