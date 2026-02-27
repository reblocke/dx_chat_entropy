# Contributing

## Ground rules
- Prefer small, reviewable pull requests.
- Keep computational core logic in `src/`; keep orchestration in scripts/notebooks.
- Update/add tests when behavior changes.
- Record design/assumption changes in `docs/DECISIONS.md`.

## Definition of done
A change is generally ready when:
- `make fmt` passes
- `make lint` passes
- `make test` passes
- `make audit` passes
- Any relevant report outputs are updated

## Pull request checklist
- [ ] What is the project/scientific goal of the change?
- [ ] What was verified?
- [ ] Any new dependencies added intentionally?
- [ ] Paths remain repo-relative (no local absolute paths)?
- [ ] No secrets/sensitive data added?
