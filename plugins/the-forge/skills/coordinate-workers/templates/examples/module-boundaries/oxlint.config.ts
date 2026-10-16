// OPTIONAL EXAMPLE: module boundaries with oxlint's `no-restricted-imports`.
// Merge the constants, `moduleBoundaries` and the override entries into your own oxlint.config.ts, and set
// the module lists to your repo's. README.md next to this file says why and how.
//
// For the files in MODULES_DIR:
//
//   - Another module only through its index: '@/modules/content', never '@/modules/content/api' or a
//     relative path into it. A module imports its own files by relative path.
//   - No module imports a page-level module. Pages import only the base modules, so what two pages share
//     belongs in a base module.
//
// Files outside MODULES_DIR (routes, tests) may import any module. A new module goes into BASE_MODULES or
// PAGE_MODULES.
import { defineConfig, type DummyRuleMap } from 'oxlint'

const MODULES_DIR = 'modules' // imported as '@/modules/<name>'
const BASE_MODULES = ['auth', 'content', 'profile'] // shared: any module may import them
const PAGE_MODULES = ['home', 'search', 'settings'] // page-level: no other module imports them

const moduleBoundaries = (pageModules: string[]): DummyRuleMap['no-restricted-imports'] => [
  'error',
  {
    patterns: [
      {
        group: [`@/${MODULES_DIR}/*/**`],
        message: `Import another module through its index ('@/${MODULES_DIR}/<name>'), and your own module's files by relative path.`
      },
      {
        regex: `^(\\.\\./)+(${[...BASE_MODULES, ...PAGE_MODULES].join('|')})(/|$)`,
        message: `Import another module through its index ('@/${MODULES_DIR}/<name>'), not by a relative path.`
      },
      {
        regex: `^@/${MODULES_DIR}/(${pageModules.join('|')})$`,
        message:
          'No module imports a page-level module; pages import only the base modules. Move what two of them share into a base module.'
      }
    ]
  }
]

export default defineConfig({
  overrides: [
    {
      files: [`${MODULES_DIR}/**`],
      rules: {
        'no-restricted-imports': moduleBoundaries(PAGE_MODULES)
      }
    },
    // A later override replaces the rule's options instead of adding to them, so each page module gets
    // the whole list again, minus itself (a page imports its own index without a warning).
    ...PAGE_MODULES.map((page) => ({
      files: [`${MODULES_DIR}/${page}/**`],
      rules: {
        'no-restricted-imports': moduleBoundaries(PAGE_MODULES.filter((other) => other !== page))
      }
    }))
  ]
})
