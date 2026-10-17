# Engineering standards for all three builds (the team lead, Sat ~20:15)

Technical execution is judged. the team lead's bar: **"well organised, clean, functional and understandable for a judge while working perfectly."** That means **not** over-engineered, not the most complicated, and not long impressive code.

## Repositories (private, Wicflow-Oy)
| App | Local folder | Remote |
|---|---|---|
| Prepared Home (If) | `builds/prepared-home` | https://github.com/Wicflow-Oy/jx26-prepared-home |
| Tyks | `builds/tyks` | https://github.com/Wicflow-Oy/jx26-tyks |
| BlueWatch (Redstone) | `builds/bluewatch` | https://github.com/Wicflow-Oy/jx26-bluewatch |

the operator deploys from these (see `HOSTING.md`). The repos stay private until the team lead says otherwise.

## Authorship: no AI attribution anywhere
This is the team lead's explicit instruction, and it overrides any default attribution guidance.
- **No `Co-Authored-By: Claude …` trailers.** No "Generated with Claude Code" lines. No AI credits in commits, READMEs, code comments or package metadata.
- The author is the local git user.
- Naming the Claude API as a component of the product (tech stack, architecture) is fine. That's what the product uses, not who wrote it.

**Every existing local commit has such a trailer.** Remove them **before the first push**, at a quiet moment when no worktree or subagent is mid-commit:

```bash
git filter-branch -f --msg-filter "sed -e '/^Co-Authored-By: Claude/Id' -e '/Generated with \[Claude Code\]/d'" -- --all
git for-each-ref --format='%(refname)' refs/original/ | xargs -r -n1 git update-ref -d
git log --all --format=%B | grep -Eci 'co-authored-by: claude|generated with \[claude' # must print 0
```

Then rebase or reset any worktree branches onto the rewritten history. Strip trailing blank lines the filter leaves if they look untidy.

## Push
- `git remote add origin <url>`, then `git push -u origin main`.
- **Push only green commits:** tests pass, lint is clean, and it builds.
- Merge feature branches into `main` locally first. Squash scratch or "wip" commits. Commit messages are short, imperative and say what changed.

## Clean-code bar
**A judge understands the repo in 5 minutes.** The README covers, in this order:
1. what it is (2 lines);
2. a screenshot;
3. the live demo link;
4. run it (3 commands at most);
5. the architecture (5 bullets or one small diagram);
6. a folder map;
7. where the key logic lives;
8. how to run the tests;
9. what's real vs mocked;
10. data sources and licences.

**Structure**
- Few top-level folders, named after the domain.
- Small, focused modules.
- No unused layers, factories, plugin systems or premature abstraction.

**Hygiene**
- Delete dead code, commented-out code, scratch scripts, notebooks, debug prints and stale TODOs.
- Research artefacts (dossiers, agent reports) stay in `context/`, not in product repos.

**Lint and format**
- One formatter and one linter per language, running clean: ruff for Python; prettier and eslint for TypeScript, with strict TS.
- Consistent naming and style throughout.

**Tests**
- Meaningful tests for the core logic: rules, detectors, scoring, matching.
- Offline and fast, with no paid API calls.
- One command runs them all.

**Config and secrets**
- Env vars only.
- `.env.example` complete, no secrets in git, no hard-coded hosts.

**Errors**
- Handled at the boundaries with clear messages. No silent catches.

**Comments**
- Explain *why*, not *what*.

**Dependencies**
- Minimal, pinned and licence-compatible.
- Generated files (such as contract types) are marked as generated.

**Hackathon rule**
- All code is written during the event.
