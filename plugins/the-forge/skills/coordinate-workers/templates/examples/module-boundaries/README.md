# Module boundaries in lint (optional example)

Optional: for a repo split into modules (domains, features). Parallel workers change different modules at the same time. When modules import each other's internals, or when one page imports another page, a change in one task breaks another task. Reviewers then have to catch that by eye, and review is already the slow step. A lint rule catches it for free, in CI and on every agent's lint run.

[`oxlint.config.ts`](oxlint.config.ts) sets oxlint's `no-restricted-imports` for the files in the modules folder:

- **Another module only through its index:** `@/modules/content` is allowed. `@/modules/content/api` and `../../content/api` are not. A module imports its own files by relative path.
- **No module imports a page-level module.** Pages (`home`, `search`, `settings` in the example) import only base modules (`auth`, `content`, `profile`). What two pages share moves into a base module.
- **Routes and tests are outside the modules folder,** so they may import any module.

## Adopt it

1. Merge the constants, `moduleBoundaries` and the override entries into your `oxlint.config.ts`. Set `MODULES_DIR`, `BASE_MODULES` and `PAGE_MODULES` to your repo's.
2. Prove it works: add one bad import of each kind, run the linter, and see each one fail. Then remove them. Run it on the default branch too, and fix what it finds first, or the rule lands red.
3. Name the rule in the repo's `CLAUDE.md`, so workers know why the linter fails, and keep the module lists in step with the folders. A new module goes into one of the lists.
4. The MR is a small config change with no new app logic, so it fits `no-review-needed` (Risk 0).

## Notes

- A later override replaces the rule's options instead of adding to them. That's why each page module gets the whole list again, minus itself.
- The rule matches the import text and doesn't resolve paths. The relative-path pattern lists the module names, and the `@/` alias is spelled out.
- ESLint has a rule with the same name and a similar `patterns` option. Check your ESLint version's docs for `regex` support before you copy the patterns.
- Checked with oxlint 1.78 on a throwaway tree. A deep import, a relative path into another module, a page importing a page, and a base module importing a page all fail. An index import, a page importing its own index, and a route importing anything all pass.
