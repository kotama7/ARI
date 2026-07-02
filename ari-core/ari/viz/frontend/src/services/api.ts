// ARI Dashboard – typed API service (compatibility barrel).
//
// The 79 endpoint wrappers and their 28 inline DTOs were split out of this
// single 863-line god-module into domain-partitioned modules under
// `./api/` over one shared transport core (`./api/client`). This file is now a
// thin barrel that re-exports every wrapper and every DTO by the same name, so
// every existing `import { X } from '.../services/api'` keeps resolving
// unchanged. No endpoint URL, HTTP method, request/response shape, error regime,
// or exported symbol name changes — only the internal file layout.
//
// Both error regimes are unchanged and live in `./api/client`:
//   - get/post THROW on non-2xx.
//   - pbGet/pbPost NEVER throw and return the parsed `{error}` body.
// The three bespoke uploads/deletes keep their exact original fetch bodies in
// their domain modules (`./api/wizard`, `./api/files`, `./api/paperbench`).

export * from './api/state';
export * from './api/checkpoints';
export * from './api/files';
export * from './api/memory';
export * from './api/nodeReport';
export * from './api/ear';
export * from './api/publish';
export * from './api/settings';
export * from './api/catalog';
export * from './api/workflow';
export * from './api/experiment';
export * from './api/subExperiments';
export * from './api/wizard';
export * from './api/ssh';
export * from './api/resources';
export * from './api/paperbench';
